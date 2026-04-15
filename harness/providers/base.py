from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from harness.engine.cost_tracker import UsageSnapshot
from harness.engine.messages import ConversationMessage, ToolCall


@dataclass(frozen=True)
class ProviderMessageRequest:
    model: str
    messages: list[ConversationMessage]
    system_prompt: str | None = None
    max_tokens: int = 4096
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderTextDeltaEvent:
    text: str


@dataclass(frozen=True)
class ProviderRetryEvent:
    message: str
    attempt: int
    max_attempts: int
    delay_seconds: float


@dataclass(frozen=True)
class ProviderCompleteEvent:
    message: ConversationMessage
    usage: UsageSnapshot
    stop_reason: str | None = None


ProviderEvent = ProviderTextDeltaEvent | ProviderRetryEvent | ProviderCompleteEvent


@dataclass(frozen=True)
class ProviderResponse:
    message: ConversationMessage
    usage: UsageSnapshot
    stop_reason: str | None = None


class StreamingProvider(Protocol):
    async def stream_message(self, request: ProviderMessageRequest) -> AsyncIterator[ProviderEvent]:
        ...


def provider_message_from_openai_payload(payload: dict[str, Any]) -> ConversationMessage:
    tool_calls: list[ToolCall] = []
    for row in payload.get("tool_calls", []) or []:
        function = row.get("function", {}) or {}
        arguments = function.get("arguments", {}) or {}
        if isinstance(arguments, str):
            try:
                import json

                arguments = json.loads(arguments)
            except Exception:
                arguments = {"raw_arguments": arguments}
        tool_calls.append(
            ToolCall(
                id=str(row.get("id", "")),
                name=str(function.get("name", "")),
                arguments=arguments,
            )
        )
    content = payload.get("content")
    if isinstance(content, list):
        content = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
        )
    return ConversationMessage(
        role="assistant",
        content=str(content or ""),
        tool_calls=tool_calls,
    )
