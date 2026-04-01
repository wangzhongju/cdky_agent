from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class A2ATaskPayload(BaseModel):
    task_id: str
    parent_task_id: str | None = None
    goal: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    context_ref: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    error: str = ""
    retry_count: int = 0
    trace_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
