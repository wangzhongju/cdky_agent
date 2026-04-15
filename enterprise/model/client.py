from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

import httpx

from enterprise.engine.messages import ConversationMessage, assistant_message_from_openai, serialize_for_openai
from enterprise.model.usage import UsageSnapshot
from utils.config_handler import enterprise_conf


@dataclass(frozen=True)
class ApiMessageRequest:
    model: str
    messages: list[ConversationMessage]
    system_prompt: str | None = None
    max_tokens: int = 4096
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ApiTextDeltaEvent:
    text: str


@dataclass(frozen=True)
class ApiMessageCompleteEvent:
    message: ConversationMessage
    usage: UsageSnapshot
    stop_reason: str | None = None


@dataclass(frozen=True)
class ApiRetryEvent:
    message: str
    attempt: int
    max_attempts: int
    delay_seconds: float


ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent


class SupportsStreamingMessages(Protocol):
    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        ...

    async def complete_text(self, *, model: str, system_prompt: str, prompt: str, max_tokens: int = 1024) -> str:
        ...


def create_model_client() -> SupportsStreamingMessages:
    model_conf = enterprise_conf.get("model", {})
    provider = str(model_conf.get("provider") or "").strip().lower()
    api_key = str(model_conf.get("api_key", "")).strip()
    if provider == "mock" or not api_key:
        return MockModelClient()
    return DashScopeOpenAIClient(
        base_url=str(model_conf.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")).rstrip("/"),
        api_key=api_key,
    )


class DashScopeOpenAIClient:
    def __init__(self, *, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        retry_conf = enterprise_conf.get("model", {}).get("retry", {})
        self.max_retries = int(retry_conf.get("max_retries", 3))
        self.base_delay = float(retry_conf.get("base_delay_seconds", 1))
        self.max_delay = float(retry_conf.get("max_delay_seconds", 30))
        self.timeout = float(enterprise_conf.get("model", {}).get("request_timeout_seconds", 90))

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async for event in self._stream_once(request):
                    yield event
                return
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise
                delay = _get_retry_delay(attempt, exc, self.base_delay, self.max_delay)
                yield ApiRetryEvent(
                    message=str(exc),
                    attempt=attempt + 1,
                    max_attempts=self.max_retries + 1,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
        if last_error is not None:
            raise last_error

    async def complete_text(self, *, model: str, system_prompt: str, prompt: str, max_tokens: int = 1024) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=_headers(self.api_key),
            )
            response.raise_for_status()
            data = response.json()
        return str(data["choices"][0]["message"].get("content", "")).strip()

    async def _stream_once(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        payload = {
            "model": request.model,
            "messages": _wire_messages(request),
            "max_tokens": request.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.2,
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"

        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage = UsageSnapshot()
        stop_reason: str | None = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=_headers(self.api_key),
            ) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        text = str(delta["content"])
                        content_parts.append(text)
                        yield ApiTextDeltaEvent(text=text)

                    for call in delta.get("tool_calls") or []:
                        index = int(call.get("index", 0))
                        state = tool_calls.setdefault(
                            index,
                            {
                                "id": call.get("id"),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if call.get("id"):
                            state["id"] = call["id"]
                        function = call.get("function") or {}
                        if function.get("name"):
                            state["function"]["name"] += str(function["name"])
                        if function.get("arguments"):
                            state["function"]["arguments"] += str(function["arguments"])

                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        stop_reason = str(finish_reason)
                    if chunk.get("usage"):
                        usage = UsageSnapshot(
                            input_tokens=int(chunk["usage"].get("prompt_tokens", 0) or 0),
                            output_tokens=int(chunk["usage"].get("completion_tokens", 0) or 0),
                        )

        final_message = assistant_message_from_openai(
            {
                "content": "".join(content_parts),
                "tool_calls": [tool_calls[idx] for idx in sorted(tool_calls)],
            }
        )
        yield ApiMessageCompleteEvent(
            message=final_message,
            usage=usage,
            stop_reason=stop_reason,
        )


class MockModelClient:
    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        report_kw = "\u62a5\u544a"
        weather_kw = "\u5929\u6c14"
        last_user = next((msg for msg in reversed(request.messages) if msg.role == "user"), None)
        prompt = last_user.text if last_user else ""
        lower = prompt.lower()

        if any(tool["function"]["name"] == "get_usage_report_data" for tool in request.tools) and (report_kw in prompt or "report" in lower):
            message = assistant_message_from_openai(
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "toolu_mock_report_months",
                            "type": "function",
                            "function": {"name": "get_available_report_months", "arguments": json.dumps({"user_id": "1001"})},
                        },
                        {
                            "id": "toolu_mock_report",
                            "type": "function",
                            "function": {"name": "get_usage_report_data", "arguments": json.dumps({"user_id": "1001", "month": "2025-03"})},
                        },
                    ],
                }
            )
            yield ApiMessageCompleteEvent(message=message, usage=UsageSnapshot(input_tokens=20, output_tokens=5), stop_reason="tool_calls")
            return

        tool_names = {tool["function"]["name"] for tool in request.tools}
        if "mcp__gaode__get_user_location" in tool_names and (weather_kw in prompt or "weather" in lower):
            message = assistant_message_from_openai(
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "toolu_mock_location",
                            "type": "function",
                            "function": {"name": "mcp__gaode__get_user_location", "arguments": "{}"},
                        },
                        {
                            "id": "toolu_mock_weather",
                            "type": "function",
                            "function": {"name": "mcp__gaode__get_weather", "arguments": json.dumps({"city": "\u5317\u4eac"})},
                        },
                    ],
                }
            )
            yield ApiMessageCompleteEvent(message=message, usage=UsageSnapshot(input_tokens=20, output_tokens=5), stop_reason="tool_calls")
            return

        has_tool_results = any(
            any(block.get("type") == "tool_result" for block in message.model_dump(mode="json")["content"])
            for message in request.messages
        )
        text = "Completed after reviewing tool results." if has_tool_results else "This is a mock assistant response."
        for chunk in _chunk_text(text, 12):
            yield ApiTextDeltaEvent(text=chunk)
        yield ApiMessageCompleteEvent(
            message=assistant_message_from_openai({"content": text, "tool_calls": []}),
            usage=UsageSnapshot(input_tokens=10, output_tokens=8),
            stop_reason="stop",
        )

    async def complete_text(self, *, model: str, system_prompt: str, prompt: str, max_tokens: int = 1024) -> str:
        del model, system_prompt, max_tokens
        lower = prompt.lower()
        if "choose the most relevant skills" in lower:
            if "\u62a5\u544a" in prompt or "report" in lower:
                return '["report"]'
            return '["product_knowledge"]'
        if "summarize the conversation" in lower:
            return "The user is discussing robot usage and the assistant used tools."
        return "[]"


def _wire_messages(request: ApiMessageRequest) -> list[dict[str, Any]]:
    payload = []
    if request.system_prompt:
        payload.append({"role": "system", "content": request.system_prompt})
    payload.extend(serialize_for_openai(request.messages))
    return payload


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504, 529}
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError))


def _get_retry_delay(attempt: int, exc: Exception, base_delay: float, max_delay: float) -> float:
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), max_delay)
            except ValueError:
                pass
    delay = min(base_delay * (2 ** attempt), max_delay)
    return delay + random.uniform(0, delay * 0.25)


def _chunk_text(text: str, chunk_size: int) -> list[str]:
    return [text[idx:idx + chunk_size] for idx in range(0, len(text), chunk_size)] or [""]
