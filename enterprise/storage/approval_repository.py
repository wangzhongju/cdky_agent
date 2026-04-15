from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import PendingApprovalRecord


class ApprovalRepository:
    def create(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_use_id: str,
        tool_input: dict[str, Any],
        reason: str,
        actor: str,
        trace_id: str,
    ) -> PendingApprovalRecord:
        with SessionLocal() as session:
            row = PendingApprovalRecord(
                approval_id=uuid4().hex,
                session_id=session_id,
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                tool_input_json=json.dumps(tool_input, ensure_ascii=False),
                status="pending",
                reason=reason,
                actor=actor,
                trace_id=trace_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get(self, approval_id: str) -> PendingApprovalRecord | None:
        with SessionLocal() as session:
            return session.scalars(select(PendingApprovalRecord).where(PendingApprovalRecord.approval_id == approval_id)).first()

    def list_by_status(self, status: str = "pending") -> list[PendingApprovalRecord]:
        with SessionLocal() as session:
            return list(
                session.scalars(
                    select(PendingApprovalRecord)
                    .where(PendingApprovalRecord.status == status)
                    .order_by(PendingApprovalRecord.created_at.asc())
                ).all()
            )

    def update_status(self, approval_id: str, status: str) -> None:
        with SessionLocal() as session:
            row = session.scalars(select(PendingApprovalRecord).where(PendingApprovalRecord.approval_id == approval_id)).first()
            if not row:
                return
            row.status = status
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()

    def delete_all(self) -> None:
        with SessionLocal() as session:
            session.execute(delete(PendingApprovalRecord))
            session.commit()
