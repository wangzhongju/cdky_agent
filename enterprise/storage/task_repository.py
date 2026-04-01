from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Optional

from sqlalchemy import select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import TaskRecord


class TaskRepository:
    def create_task(self, payload: dict) -> TaskRecord:
        with SessionLocal() as session:
            now = datetime.utcnow()
            task = TaskRecord(
                task_id=payload["task_id"],
                parent_task_id=payload.get("parent_task_id"),
                goal=payload["goal"],
                constraints=json.dumps(payload.get("constraints", {}), ensure_ascii=False),
                context_ref=json.dumps(payload.get("context_ref", {}), ensure_ascii=False),
                input=json.dumps(payload.get("input", {}), ensure_ascii=False),
                result=json.dumps({}, ensure_ascii=False),
                status=payload.get("status", "PENDING"),
                error="",
                retry_count=0,
                trace_id=payload["trace_id"],
                goal_hash=self.build_goal_hash(payload["task_id"], payload["goal"]),
                created_at=now,
                updated_at=now,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with SessionLocal() as session:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            return session.scalars(stmt).first()

    def update_status(self, task_id: str, status: str, result: dict | None = None, error: str = "") -> None:
        with SessionLocal() as session:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            task = session.scalars(stmt).first()
            if not task:
                return
            task.status = status
            task.error = error
            if result is not None:
                task.result = json.dumps(result, ensure_ascii=False)
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()

    def increment_retry(self, task_id: str) -> int:
        with SessionLocal() as session:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            task = session.scalars(stmt).first()
            if not task:
                return 0
            task.retry_count += 1
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
            return task.retry_count

    @staticmethod
    def build_goal_hash(task_id: str, goal: str) -> str:
        return sha256(f"{task_id}:{goal}".encode("utf-8")).hexdigest()
