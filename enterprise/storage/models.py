from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, Boolean, Integer, DateTime


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


class SkillRecord(Base):
    """技能 manifest 及其启用状态的持久化视图。"""

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
    """异步 A2A 任务状态机对应的持久化记录。

    这是 ``A2ATaskPayload`` 在数据库中的落地形态：
    - 面向存储层，JSON 结构字段采用 ``Text`` 列保存序列化文本
    - 面向运行时，``task_id`` 作为全局查询主键
    - 面向治理层，保留 ``trace_id`` 与 ``retry_count`` 便于排障与统计
    """

    __tablename__ = "a2a_tasks"

    # 主键：任务唯一标识。
    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    # 可选父任务 ID，用于未来子任务编排扩展。
    parent_task_id: Mapped[str] = mapped_column(String(100), nullable=True)
    # 人类可读的任务目标文本。
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON 文本：任务执行约束。
    constraints: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON 文本：上下文引用（如 session_id）。
    context_ref: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON 文本：结构化输入参数。
    input: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON 文本：执行结果输出。
    result: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # 生命周期状态值（PENDING/RUNNING/...）。
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # 错误文本，仅失败路径使用。
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 重试次数计数器。
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 链路追踪标识。
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # task_id + goal 的稳定哈希，用于目标指纹标识。
    goal_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # 行创建/更新时间。
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AuditEventRecord(Base):
    """只追加不修改的审计日志记录。"""

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
    """按请求记录的模型成本估算数据。"""

    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
