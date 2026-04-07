from __future__ import annotations

"""异步 A2A 任务执行共享的协议对象。

该模块提供 A2A 链路中的数据契约：
- ``TaskStatus``: 生命周期状态枚举
- ``A2ATaskPayload``: 队列与持久化层共享的任务载荷结构

设计原则
- 单一事实源：Redis 与 Postgres 共享同一 payload 语义。
- 可追踪：强制 ``trace_id``，便于端到端排障。
- 可演进：通过 Pydantic 统一默认值与字段类型。
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """进程内 A2A worker 使用的生命周期状态。

    状态语义
    - ``PENDING``: 已创建并入队，尚未执行
    - ``RUNNING``: worker 正在执行编排流程
    - ``REVIEWING``: 进入结果收敛阶段
    - ``COMPLETED``: 成功完成并落库
    - ``FAILED``: 达到最大重试后终态失败
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class A2ATaskPayload(BaseModel):
    """存放在 Redis 与 Postgres 中的任务协议载荷。

    字段分组
    - 标识字段：``task_id``、``parent_task_id``、``trace_id``
    - 输入字段：``goal``、``constraints``、``context_ref``、``input``
    - 输出字段：``result``、``error``
    - 状态字段：``status``、``retry_count``、``created_at``、``updated_at``
    """

    # 全局唯一任务标识；对应持久化主键与查询入口。
    task_id: str
    # 可选父任务标识，为未来任务拆分/回溯预留。
    parent_task_id: str | None = None
    # 任务目标文本；当前直接映射到 orchestrator.chat(message)。
    goal: str
    # 执行约束上下文（预算、策略开关等），当前由上层透传。
    constraints: dict[str, Any] = Field(default_factory=dict)
    # 引用型上下文（例如 session_id），用于恢复会话语义。
    context_ref: dict[str, Any] = Field(default_factory=dict)
    # 结构化输入补充信息，与 goal 共同构成输入域。
    input: dict[str, Any] = Field(default_factory=dict)
    # 任务执行结果载荷，成功路径由 worker 回填。
    result: dict[str, Any] = Field(default_factory=dict)
    # 生命周期状态；任务创建时默认为 PENDING。
    status: TaskStatus = TaskStatus.PENDING
    # 错误信息文本，仅失败路径使用。
    error: str = ""
    # 当前重试次数，由 worker 失败路径递增。
    retry_count: int = 0
    # 链路追踪 ID，跨 API/worker/审计打通请求链路。
    trace_id: str
    # 创建与更新时间戳，统一使用 UTC。
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
