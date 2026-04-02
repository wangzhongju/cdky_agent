from __future__ import annotations

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
        """插入一条审计事件记录。"""
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
