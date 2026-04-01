from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, Boolean, Integer, DateTime


class Base(DeclarativeBase):
    pass


class SkillRecord(Base):
    __tablename__ = "skill_registry"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_schemas: Mapped[str] = mapped_column(Text, nullable=False)
    required_permissions: Mapped[str] = mapped_column(Text, nullable=False)
    dependencies: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class TaskRecord(Base):
    __tablename__ = "a2a_tasks"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    parent_task_id: Mapped[str] = mapped_column(String(100), nullable=True)
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
