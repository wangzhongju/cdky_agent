from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from enterprise.engine.messages import ConversationMessage
from enterprise.model.usage import UsageSnapshot


@dataclass(frozen=True)
class AssistantTextDelta:
    text: str
    type: str = "assistant_text_delta"


@dataclass(frozen=True)
class AssistantTurnComplete:
    message: ConversationMessage
    usage: UsageSnapshot
    type: str = "assistant_turn_complete"


@dataclass(frozen=True)
class ToolExecutionStarted:
    tool_name: str
    tool_input: dict[str, Any]
    type: str = "tool_execution_started"


@dataclass(frozen=True)
class ToolExecutionCompleted:
    tool_name: str
    output: str
    is_error: bool
    type: str = "tool_execution_completed"


@dataclass(frozen=True)
class ApprovalRequired:
    approval_id: str
    tool_name: str
    tool_input: dict[str, Any]
    reason: str
    type: str = "approval_required"


@dataclass(frozen=True)
class StatusEvent:
    message: str
    type: str = "status"


@dataclass(frozen=True)
class ErrorEvent:
    message: str
    type: str = "error"


StreamEvent = (
    AssistantTextDelta
    | AssistantTurnComplete
    | ToolExecutionStarted
    | ToolExecutionCompleted
    | ApprovalRequired
    | StatusEvent
    | ErrorEvent
)


def event_to_dict(event: StreamEvent) -> dict[str, Any]:
    data = asdict(event)
    if isinstance(event, AssistantTurnComplete):
        data["message"] = event.message.model_dump(mode="json")
        data["usage"] = event.usage.model_dump()
    return data
