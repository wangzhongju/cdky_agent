from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import ChatSummaryRecord


class SummaryRepository:
    def get(self, session_id: str) -> ChatSummaryRecord | None:
        with SessionLocal() as session:
            return session.scalars(select(ChatSummaryRecord).where(ChatSummaryRecord.session_id == session_id)).first()

    def upsert(self, session_id: str, summary: str, last_message_sequence: int, token_estimate: int) -> ChatSummaryRecord:
        with SessionLocal() as session:
            row = session.scalars(select(ChatSummaryRecord).where(ChatSummaryRecord.session_id == session_id)).first()
            if not row:
                row = ChatSummaryRecord(
                    session_id=session_id,
                    summary=summary,
                    last_message_sequence=last_message_sequence,
                    token_estimate=token_estimate,
                    updated_at=datetime.utcnow(),
                )
            else:
                row.summary = summary
                row.last_message_sequence = last_message_sequence
                row.token_estimate = token_estimate
                row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            session.refresh(row)
            return row
