from __future__ import annotations

"""基于 Redis 与 Postgres 的进程内 A2A 任务运行时。

模块定位
- 这是异步任务链路的执行中枢，连接 API 提交层与编排执行层。
- API 层只负责入队和查询；后台 worker 才负责真正消费与执行任务。

核心职责
- 受理任务：把请求标准化为 ``A2ATaskPayload`` 并写入 Postgres。
- 调度任务：把任务推进 Redis 主队列，供 worker 拉取。
- 执行任务：调用 ``OrchestratorService.chat`` 产出最终结果。
- 治理任务：统一记录指标与审计，处理重试与死信。

关键约定
- 队列载荷格式：``A2ATaskPayload.model_dump_json()`` 的 JSON 文本。
- 生命周期状态：``PENDING -> RUNNING -> REVIEWING -> COMPLETED/FAILED``。
- 失败重试策略：``retry_count <= max_retry`` 时重入队，否则进入死信队列。
"""

import json
import threading
import time
import uuid

from enterprise.a2a.protocol import A2ATaskPayload, TaskStatus
from enterprise.governance.audit import AuditService
from enterprise.governance.metrics import MetricsService
from enterprise.governance.prometheus_metrics import a2a_tasks_total
from enterprise.orchestrator.service import OrchestratorService
from enterprise.storage.redis_client import get_redis_client
from enterprise.storage.task_repository import TaskRepository
from utils.config_handler import enterprise_conf
from utils.logger_handler import logger


class A2ARuntime:
    """提交、执行并追踪异步编排任务。

    对外仅暴露两个稳定入口：
    - ``submit_task``: 创建任务并投递到队列
    - ``get_task``: 查询任务持久化快照

    对内维护一个后台 worker：
    - 通过 ``start``/``stop`` 管理生命周期
    - 通过 ``_run_worker_loop`` 持续消费主队列
    - 通过 ``_process_task`` 推进任务状态机
    """

    def __init__(self, orchestrator: OrchestratorService):
        """装配运行时依赖并加载配置参数。"""
        infra = enterprise_conf.get("infra", {})
        a2a_conf = enterprise_conf.get("a2a", {})

        # 编排服务入口：worker 用它执行真实业务编排。
        self.orchestrator = orchestrator

        # 持久化仓储与消息队列客户端。
        self.repo = TaskRepository()
        self.redis = get_redis_client()

        # Redis 键约定：主队列 + 死信队列。
        self.queue_key = infra.get("redis_queue_key", "a2a:task_queue")
        self.dead_letter_key = infra.get("redis_dead_letter_key", "a2a:dead_letter")

        # 轮询与重试参数。
        self.poll_seconds = int(a2a_conf.get("worker_poll_seconds", 1))
        self.max_retry = int(a2a_conf.get("max_retry", 3))

        # worker 生命周期控制：
        # - _worker: 后台线程句柄
        # - _stop: 退出信号
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

        # 治理服务：审计与指标计数。
        self.audit = AuditService()
        self.metrics = MetricsService()

    def start(self) -> None:
        """启动后台 worker（幂等）。"""
        if self._worker and self._worker.is_alive():
            return

        self._worker = threading.Thread(target=self._run_worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        """通知 worker 在下一轮循环退出。"""
        self._stop.set()

    def submit_task(self, goal: str, constraints: dict, context_ref: dict, input_data: dict, trace_id: str | None = None) -> dict:
        """创建任务、落库并入队。

        字段流转
        1) 构建 ``A2ATaskPayload``，自动补齐 ``task_id`` 与 ``trace_id``。
        2) 写入 Postgres，记录初始状态 ``PENDING``。
        3) 推入 Redis 主队列，等待 worker 消费。
        4) 更新任务提交指标并返回最小回执。
        """
        task = A2ATaskPayload(
            task_id=str(uuid.uuid4()),
            goal=goal,
            constraints=constraints,
            context_ref=context_ref,
            input=input_data,
            trace_id=trace_id or str(uuid.uuid4()),
        )

        self.repo.create_task(task.model_dump(mode="json"))
        self.redis.rpush(self.queue_key, task.model_dump_json())
        self.metrics.incr("tasks_submitted")
        a2a_tasks_total.labels(status="submitted").inc()

        return {"task_id": task.task_id, "status": task.status.value, "trace_id": task.trace_id}

    def get_task(self, task_id: str) -> dict | None:
        """查询任务快照，并反序列化 JSON 字段为结构化对象。"""
        row = self.repo.get_task(task_id)
        if not row:
            return None

        return {
            "task_id": row.task_id,
            "parent_task_id": row.parent_task_id,
            "goal": row.goal,
            "constraints": json.loads(row.constraints),
            "context_ref": json.loads(row.context_ref),
            "input": json.loads(row.input),
            "result": json.loads(row.result),
            "status": row.status,
            "error": row.error,
            "retry_count": row.retry_count,
            "trace_id": row.trace_id,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    def _run_worker_loop(self) -> None:
        """worker 主循环：从 Redis 阻塞拉取任务并处理。

        消费语义
        - 使用 ``BLPOP`` 以 ``poll_seconds`` 作为阻塞超时。
        - 解析成功时进入 ``_process_task``。
        - 解析或前置处理失败时，把原始 payload 送入死信队列。
        """
        while not self._stop.is_set():
            data = self.redis.blpop(self.queue_key, timeout=self.poll_seconds)
            if not data:
                continue

            _, payload = data
            try:
                task = A2ATaskPayload.model_validate_json(payload)
                self._process_task(task)
            except Exception as exc:
                logger.error(f"[A2ARuntime] worker消费失败 err={exc}")
                self.redis.rpush(self.dead_letter_key, payload)

    def _process_task(self, task: A2ATaskPayload) -> None:
        """执行单个任务并推进生命周期状态机。

        正常路径
        - ``RUNNING``：进入执行态
        - 调用 ``orchestrator.chat`` 获取结果
        - ``REVIEWING -> COMPLETED``：结果落库并结束

        异常路径
        - 递增 ``retry_count``
        - ``retry_count <= max_retry`` 时重入主队列
        - 否则标记 ``FAILED`` 并投递死信队列
        """
        # 1) 进入执行态并打点。
        self.repo.update_status(task.task_id, TaskStatus.RUNNING.value)
        self.metrics.incr("tasks_running")
        a2a_tasks_total.labels(status="running").inc()
        try:
            # 2) 调用编排服务执行任务目标。
            chat_result = self.orchestrator.chat(
                message=task.goal,
                session_id=task.context_ref.get("session_id"),
                trace_id=task.trace_id,
            )

            # 3) 按 REVIEWING -> COMPLETED 的顺序完成状态收敛。
            self.repo.update_status(task.task_id, TaskStatus.REVIEWING.value, result=chat_result)
            self.repo.update_status(task.task_id, TaskStatus.COMPLETED.value, result=chat_result)
            self.metrics.incr("tasks_completed")
            a2a_tasks_total.labels(status="completed").inc()

            # 4) 成功审计：当前基于 goal 关键词推断执行角色。
            self.audit.log(
                event_type="a2a_task",
                actor="worker-report" if "报告" in task.goal else "worker-rag",
                trace_id=task.trace_id,
                target=task.task_id,
                payload={"goal": task.goal},
                status="SUCCESS",
            )
        except Exception as exc:
            # 5) 失败后先递增重试计数，再按阈值决定去向。
            retry = self.repo.increment_retry(task.task_id)
            if retry <= self.max_retry:
                self.redis.rpush(self.queue_key, task.model_dump_json())
            else:
                self.repo.update_status(task.task_id, TaskStatus.FAILED.value, error=str(exc))
                self.redis.rpush(self.dead_letter_key, task.model_dump_json())
                self.metrics.incr("tasks_failed")
                a2a_tasks_total.labels(status="failed").inc()
                # 6) 仅最终失败写失败审计，避免重试阶段噪音。
                self.audit.log(
                    event_type="a2a_task",
                    actor="worker-report" if "报告" in task.goal else "worker-rag",
                    trace_id=task.trace_id,
                    target=task.task_id,
                    payload={"goal": task.goal},
                    status="FAILED",
                    error=str(exc),
                )
