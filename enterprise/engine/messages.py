from __future__ import annotations

import json
from typing import Any, Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str = Field(default_factory=lambda: f"toolu_{uuid4().hex}")
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = Annotated[TextBlock | ToolUseBlock | ToolResultBlock, Field(discriminator="type")]


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock] = Field(default_factory=list)

    @classmethod
    def from_user_text(cls, text: str) -> "ConversationMessage":
        return cls(role="user", content=[TextBlock(text=text)])

    @property
    def text(self) -> str:
        return "".join(block.text for block in self.content if isinstance(block, TextBlock))

    @property
    def tool_uses(self) -> list[ToolUseBlock]:
        return [block for block in self.content if isinstance(block, ToolUseBlock)]

    def to_openai_messages(self) -> list[dict[str, Any]]:
        text = self.text
        if self.role == "user":
            tool_results = [block for block in self.content if isinstance(block, ToolResultBlock)]
            if tool_results:
                return [
                    {
                        "role": "tool",
                        "tool_call_id": block.tool_use_id,
                        "content": block.content,
                    }
                    for block in tool_results
                ]
            return [{"role": "user", "content": text}]

        payload: dict[str, Any] = {"role": "assistant", "content": text or ""}
        tool_calls = []
        for block in self.tool_uses:
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    },
                }
            )
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return [payload]

    def to_storage(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_storage(cls, payload: dict[str, Any]) -> "ConversationMessage":
        return cls.model_validate(payload)


def serialize_for_openai(messages: list[ConversationMessage]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        payload.extend(message.to_openai_messages())
    return payload


def assistant_message_from_openai(raw_message: dict[str, Any]) -> ConversationMessage:
    content: list[ContentBlock] = []
    text = raw_message.get("content") or ""
    if text:
        content.append(TextBlock(text=str(text)))

    for call in raw_message.get("tool_calls", []) or []:
        function = call.get("function", {}) if isinstance(call, dict) else {}
        arguments = function.get("arguments") or "{}"
        try:
            parsed_args = json.loads(arguments)
        except json.JSONDecodeError:
            parsed_args = {"raw_arguments": arguments}
        content.append(
            ToolUseBlock(
                id=str(call.get("id") or f"toolu_{uuid4().hex}"),
                name=str(function.get("name") or ""),
                input=parsed_args if isinstance(parsed_args, dict) else {"value": parsed_args},
            )
        )
    return ConversationMessage(role="assistant", content=content)
