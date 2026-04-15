from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import desc, select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import ChatSessionRecord


class SessionRepository:
    def get_or_create(
        self,
        *,
        session_id: str,
        actor: str,
        trace_id: str,
        permission_mode: str = "default",
        title: str = "",
    ) -> ChatSessionRecord:
        with SessionLocal() as session:
            row = session.scalars(select(ChatSessionRecord).where(ChatSessionRecord.session_id == session_id)).first()
            if row:
                row.actor = actor
                row.trace_id = trace_id
                row.permission_mode = permission_mode
                row.updated_at = datetime.utcnow()
            else:
                row = ChatSessionRecord(
                    session_id=session_id,
                    actor=actor,
                    trace_id=trace_id,
                    permission_mode=permission_mode,
                    title=title,
                    status="ACTIVE",
                    metadata_json=json.dumps({}, ensure_ascii=False),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get(self, session_id: str) -> ChatSessionRecord | None:
        with SessionLocal() as session:
            return session.scalars(select(ChatSessionRecord).where(ChatSessionRecord.session_id == session_id)).first()

    def list_recent(self, limit: int = 20) -> list[ChatSessionRecord]:
        with SessionLocal() as session:
            stmt = select(ChatSessionRecord).order_by(desc(ChatSessionRecord.updated_at)).limit(limit)
            return list(session.scalars(stmt).all())

    def update_status(
        self,
        session_id: str,
        *,
        status: str,
        latest_approval_id: str = "",
        last_error: str = "",
    ) -> None:
        with SessionLocal() as session:
            row = session.scalars(select(ChatSessionRecord).where(ChatSessionRecord.session_id == session_id)).first()
            if not row:
                return
            row.status = status
            row.latest_approval_id = latest_approval_id
            row.last_error = last_error
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
