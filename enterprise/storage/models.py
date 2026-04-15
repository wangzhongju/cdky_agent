from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SkillRecord(Base):
    __tablename__ = "skill_registry"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0.0")
    entrypoint: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    tool_schemas: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_permissions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    dependencies: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    triggers: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    allowed_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="markdown")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class TaskRecord(Base):
    __tablename__ = "a2a_tasks"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    context_ref: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    input: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    goal_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    permission_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ChatSessionRecord(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False, default="anonymous")
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    permission_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latest_approval_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    tool_call_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ChatSummaryRecord(Base):
    __tablename__ = "chat_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_message_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MemoryEntryRecord(Base):
    __tablename__ = "memory_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ApprovalRequestRecord(Base):
    __tablename__ = "approval_requests"

    approval_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CostRecord(Base):
    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
