from __future__ import annotations

"""审计服务：把结构化审计记录写入 Postgres。

审计记录的价值
- 追踪“谁在什么时间对什么对象做了什么操作”
- 关联 trace_id 做链路排障
- 统计成功/失败与延迟，支持治理与合规
"""

import json
from datetime import datetime

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import AuditEventRecord


class AuditService:
    """把结构化审计记录写入 Postgres。"""

    def log(
        self,
        event_type: str,
        actor: str,
        trace_id: str,
        target: str,
        payload: dict | None = None,
        status: str = "SUCCESS",
        error: str = "",
        latency_ms: int = 0,
    ) -> None:
        """插入一条审计事件记录。

        参数
        - event_type: 事件类型（如 api_request / capability_invoke / a2a_task）
        - actor: 调用方身份（通常来自 API key 或 worker 角色）
        - trace_id: 链路追踪 ID
        - target: 目标对象（接口、能力 fqdn、任务 id 等）
        - payload: 附加上下文（会序列化为 JSON 字符串）
        - status/error/latency_ms: 结果状态与时延指标
        """
        with SessionLocal() as session:
            row = AuditEventRecord(
                event_type=event_type,
                actor=actor,
                trace_id=trace_id,
                target=target,
                payload=json.dumps(payload or {}, ensure_ascii=False),
                status=status,
                error=error,
                latency_ms=latency_ms,
                created_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
