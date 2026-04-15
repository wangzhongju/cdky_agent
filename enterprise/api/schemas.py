from __future__ import annotations

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    title: str = ""
    user_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class SessionMessageRequest(BaseModel):
    message: str | None = None
    resume: bool = False
    trace_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approved: bool


class UserCreateRequest(BaseModel):
    username: str
    display_name: str
    note: str = ""
    default_model: str = ""
    preferences: dict = Field(default_factory=dict)


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    note: str | None = None
    default_model: str | None = None
    preferences: dict | None = None
