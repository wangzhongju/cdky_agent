from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Optional

from sqlalchemy import select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import TaskRecord


class TaskRepository:
    """封装 ``TaskRecord`` 的 SQLAlchemy 读写操作。

    设计目标
    - 让 A2A 运行时只面向“任务语义”，不直接操作 ORM 会话细节。
    - 统一 JSON 字段序列化/反序列化边界，避免上层重复处理。
    - 提供最小但完整的状态机持久化接口（创建、查询、状态更新、重试计数）。
    """

    def create_task(self, payload: dict) -> TaskRecord:
        """创建任务初始记录。

        输入约定
        - ``payload`` 至少包含：``task_id``、``goal``、``trace_id``。
        - ``constraints/context_ref/input`` 若缺失，则按空对象入库。

        持久化语义
        - ``status`` 默认 ``PENDING``。
        - ``result`` 初始化为 ``{}``，``retry_count`` 初始化为 0。
        - ``goal_hash`` 由 ``task_id + goal`` 计算，用于快速标识任务目标。
        """
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
        """按 ``task_id`` 查询任务记录，不存在时返回 ``None``。"""
        with SessionLocal() as session:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            return session.scalars(stmt).first()

    def update_status(self, task_id: str, status: str, result: dict | None = None, error: str = "") -> None:
        """更新任务状态，并按需写入结果或错误信息。

        更新策略
        - 目标任务不存在：静默返回，调用方自行决定后续动作。
        - ``result is not None`` 时覆盖 ``task.result``。
        - 每次更新都会刷新 ``updated_at``。
        """
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
        """递增任务重试次数并返回新值。

        返回语义
        - 找到任务：返回递增后的 ``retry_count``。
        - 未找到任务：返回 0（作为防御性兜底值）。
        """
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
        """构造任务目标的稳定哈希值（``sha256(task_id:goal)``）。"""
        return sha256(f"{task_id}:{goal}".encode("utf-8")).hexdigest()
