from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import desc, select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import ApprovalRequestRecord


class ApprovalRepository:
    def create(
        self,
        *,
        approval_id: str,
        session_id: str,
        trace_id: str,
        actor: str,
        reason: str,
        payload: dict,
    ) -> ApprovalRequestRecord:
        with SessionLocal() as session:
            row = ApprovalRequestRecord(
                approval_id=approval_id,
                session_id=session_id,
                trace_id=trace_id,
                actor=actor,
                reason=reason,
                payload=json.dumps(payload, ensure_ascii=False),
                status="PENDING",
                decision="",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get(self, approval_id: str) -> ApprovalRequestRecord | None:
        with SessionLocal() as session:
            return session.scalars(
                select(ApprovalRequestRecord).where(ApprovalRequestRecord.approval_id == approval_id)
            ).first()

    def latest_pending_for_session(self, session_id: str) -> ApprovalRequestRecord | None:
        with SessionLocal() as session:
            stmt = (
                select(ApprovalRequestRecord)
                .where(
                    ApprovalRequestRecord.session_id == session_id,
                    ApprovalRequestRecord.status == "PENDING",
                )
                .order_by(desc(ApprovalRequestRecord.updated_at))
            )
            return session.scalars(stmt).first()

    def latest_for_session(self, session_id: str) -> ApprovalRequestRecord | None:
        with SessionLocal() as session:
            stmt = (
                select(ApprovalRequestRecord)
                .where(ApprovalRequestRecord.session_id == session_id)
                .order_by(desc(ApprovalRequestRecord.updated_at))
            )
            return session.scalars(stmt).first()

    def decide(self, approval_id: str, decision: str) -> ApprovalRequestRecord | None:
        with SessionLocal() as session:
            row = session.scalars(
                select(ApprovalRequestRecord).where(ApprovalRequestRecord.approval_id == approval_id)
            ).first()
            if not row:
                return None
            row.status = "APPROVED" if decision == "approve" else "DENIED"
            row.decision = decision
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def mark_completed(self, approval_id: str) -> ApprovalRequestRecord | None:
        with SessionLocal() as session:
            row = session.scalars(
                select(ApprovalRequestRecord).where(ApprovalRequestRecord.approval_id == approval_id)
            ).first()
            if not row:
                return None
            row.status = "COMPLETED"
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            session.refresh(row)
            return row
