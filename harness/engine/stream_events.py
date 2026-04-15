from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from harness.engine.messages import ConversationMessage


class StreamEvent(BaseModel):
    type: str
    session_id: str
    trace_id: str


class AssistantDeltaEvent(StreamEvent):
    type: Literal["assistant_delta"] = "assistant_delta"
    text: str


class AssistantCompleteEvent(StreamEvent):
    type: Literal["assistant_complete"] = "assistant_complete"
    message: ConversationMessage


class ToolStartEvent(StreamEvent):
    type: Literal["tool_start"] = "tool_start"
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(StreamEvent):
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    output: str
    is_error: bool = False


class RetryEvent(StreamEvent):
    type: Literal["retry"] = "retry"
    attempt: int
    max_attempts: int
    delay_seconds: float
    message: str


class ApprovalRequiredEvent(StreamEvent):
    type: Literal["approval_required"] = "approval_required"
    approval_id: str
    tools: list[dict[str, Any]] = Field(default_factory=list)
    reason: str


class ApprovalDecisionEvent(StreamEvent):
    type: Literal["approval_decision"] = "approval_decision"
    approval_id: str
    decision: str


class UsageEvent(StreamEvent):
    type: Literal["usage"] = "usage"
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    model_name: str


class StatusEvent(StreamEvent):
    type: Literal["status"] = "status"
    message: str


class ErrorEvent(StreamEvent):
    type: Literal["error"] = "error"
    message: str
    recoverable: bool = True


class DoneEvent(StreamEvent):
    type: Literal["done"] = "done"
