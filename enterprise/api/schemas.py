from __future__ import annotations

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    trace_id: str | None = None
    permission_mode: str | None = None


class ChatResumeRequest(BaseModel):
    session_id: str = Field(min_length=1)
    trace_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|deny)$")


class TaskCreateRequest(BaseModel):
    goal: str = Field(min_length=1)
    constraints: dict = Field(default_factory=dict)
    context_ref: dict = Field(default_factory=dict)
    input: dict = Field(default_factory=dict)
    trace_id: str | None = None
    permission_mode: str | None = None


class SkillPatchRequest(BaseModel):
    enabled: bool
