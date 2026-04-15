from __future__ import annotations

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
    def __init__(self, orchestrator: OrchestratorService):
        infra = enterprise_conf.get("infra", {})
        a2a_conf = enterprise_conf.get("a2a", {})

        self.orchestrator = orchestrator
        self.repo = TaskRepository()
        self.redis = get_redis_client()
        self.queue_key = infra.get("redis_queue_key", "a2a:task_queue")
        self.dead_letter_key = infra.get("redis_dead_letter_key", "a2a:dead_letter")
        self.poll_seconds = int(a2a_conf.get("worker_poll_seconds", 1))
        self.max_retry = int(a2a_conf.get("max_retry", 3))
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self.audit = AuditService()
        self.metrics = MetricsService()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        self._worker = threading.Thread(target=self._run_worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()

    def submit_task(
        self,
        goal: str,
        constraints: dict,
        context_ref: dict,
        input_data: dict,
        trace_id: str | None = None,
        permission_mode: str = "default",
    ) -> dict:
        task = A2ATaskPayload(
            task_id=str(uuid.uuid4()),
            goal=goal,
            constraints=constraints,
            context_ref=context_ref,
            input=input_data,
            trace_id=trace_id or str(uuid.uuid4()),
            permission_mode=permission_mode,
        )

        self.repo.create_task(task.model_dump(mode="json"))
        self.redis.rpush(self.queue_key, task.model_dump_json())
        self.metrics.incr("tasks_submitted")
        a2a_tasks_total.labels(status="submitted").inc()

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "trace_id": task.trace_id,
            "permission_mode": task.permission_mode,
        }

    def get_task(self, task_id: str) -> dict | None:
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
            "permission_mode": row.permission_mode,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    def _run_worker_loop(self) -> None:
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
        self.repo.update_status(task.task_id, TaskStatus.RUNNING.value)
        self.metrics.incr("tasks_running")
        a2a_tasks_total.labels(status="running").inc()
        try:
            chat_result = self.orchestrator.chat(
                message=task.goal,
                session_id=task.context_ref.get("session_id"),
                trace_id=task.trace_id,
                permission_mode=task.permission_mode,
            )
            self.repo.update_status(task.task_id, TaskStatus.REVIEWING.value, result=chat_result)
            self.repo.update_status(task.task_id, TaskStatus.COMPLETED.value, result=chat_result)
            self.metrics.incr("tasks_completed")
            a2a_tasks_total.labels(status="completed").inc()
            self.audit.log(
                event_type="a2a_task",
                actor="worker-report" if "报告" in task.goal else "worker-rag",
                trace_id=task.trace_id,
                target=task.task_id,
                payload={"goal": task.goal},
                status="SUCCESS",
            )
        except Exception as exc:
            retry = self.repo.increment_retry(task.task_id)
            if retry <= self.max_retry:
                self.redis.rpush(self.queue_key, task.model_dump_json())
            else:
                self.repo.update_status(task.task_id, TaskStatus.FAILED.value, error=str(exc))
                self.redis.rpush(self.dead_letter_key, task.model_dump_json())
                self.metrics.incr("tasks_failed")
                a2a_tasks_total.labels(status="failed").inc()
                self.audit.log(
                    event_type="a2a_task",
                    actor="worker-report" if "报告" in task.goal else "worker-rag",
                    trace_id=task.trace_id,
                    target=task.task_id,
                    payload={"goal": task.goal},
                    status="FAILED",
                    error=str(exc),
                )
