from __future__ import annotations

import asyncio
import json
import random
from typing import Any, AsyncIterator

import requests

from harness.engine.cost_tracker import UsageSnapshot
from harness.engine.messages import ConversationMessage, ToolCall
from harness.providers.base import (
    ProviderCompleteEvent,
    ProviderEvent,
    ProviderMessageRequest,
    ProviderRetryEvent,
    ProviderTextDeltaEvent,
    provider_message_from_openai_payload,
)


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class DashScopeProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        timeout_seconds: int = 60,
        max_retries: int = 3,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    async def stream_message(self, request: ProviderMessageRequest) -> AsyncIterator[ProviderEvent]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async for event in self._stream_once(request):
                    yield event
                return
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not self._is_retryable(exc):
                    raise
                delay = self._retry_delay(attempt)
                yield ProviderRetryEvent(
                    message=str(exc),
                    attempt=attempt + 1,
                    max_attempts=self.max_retries + 1,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
        if last_error:
            raise last_error

    async def _stream_once(self, request: ProviderMessageRequest) -> AsyncIterator[ProviderEvent]:
        payload = self._build_payload(request)
        response = await asyncio.to_thread(self._post_once, payload)
        message = provider_message_from_openai_payload(response["choices"][0]["message"])
        if message.content:
            chunk_size = 32
            for index in range(0, len(message.content), chunk_size):
                yield ProviderTextDeltaEvent(text=message.content[index:index + chunk_size])
        usage_payload = response.get("usage", {}) or {}
        yield ProviderCompleteEvent(
            message=message,
            usage=UsageSnapshot(
                input_tokens=int(usage_payload.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage_payload.get("completion_tokens", 0) or 0),
            ),
            stop_reason=response["choices"][0].get("finish_reason"),
        )

    def _post_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=self.timeout_seconds,
        )
        if resp.status_code in RETRYABLE_STATUS_CODES:
            raise RuntimeError(f"provider retryable error: status={resp.status_code} body={resp.text}")
        resp.raise_for_status()
        body = resp.json()
        if "choices" not in body:
            raise RuntimeError(f"invalid provider response: {body}")
        return body

    def _build_payload(self, request: ProviderMessageRequest) -> dict[str, Any]:
        messages = [message.to_provider_message() for message in request.messages]
        if request.system_prompt:
            messages = [{"role": "system", "content": request.system_prompt}] + messages
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"
        return payload

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(token in message for token in ("retryable", "timeout", "connection", "temporarily", "429", "500", "502", "503", "504"))

    def _retry_delay(self, attempt: int) -> float:
        delay = min(self.base_delay_seconds * (2 ** attempt), self.max_delay_seconds)
        jitter = random.uniform(0, delay * 0.25)
        return delay + jitter
