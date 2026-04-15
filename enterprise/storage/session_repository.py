from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select

from enterprise.engine.messages import ConversationMessage
from enterprise.storage.db import SessionLocal
from enterprise.storage.models import SessionMessageRecord, SessionRecord


class SessionRepository:
    def create_session(
        self,
        *,
        title: str,
        model_name: str,
        system_prompt: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionRecord:
        with SessionLocal() as session:
            row = SessionRecord(
                session_id=uuid4().hex,
                user_id=user_id,
                title=title,
                model_name=model_name,
                system_prompt=system_prompt,
                summary="",
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
                status="ACTIVE",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_sessions(self, user_id: str | None = None) -> list[SessionRecord]:
        with SessionLocal() as session:
            stmt = select(SessionRecord).order_by(SessionRecord.updated_at.desc())
            if user_id:
                stmt = stmt.where(SessionRecord.user_id == user_id)
            return list(session.scalars(stmt).all())

    def get_session(self, session_id: str) -> SessionRecord | None:
        with SessionLocal() as session:
            return session.scalars(select(SessionRecord).where(SessionRecord.session_id == session_id)).first()

    def update_session(self, session_id: str, **kwargs) -> None:
        with SessionLocal() as session:
            row = session.scalars(select(SessionRecord).where(SessionRecord.session_id == session_id)).first()
            if not row:
                return
            for key, value in kwargs.items():
                if key == "metadata":
                    row.metadata_json = json.dumps(value or {}, ensure_ascii=False)
                elif hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()

    def append_messages(self, session_id: str, messages: list[ConversationMessage]) -> None:
        with SessionLocal() as session:
            for message in messages:
                row = SessionMessageRecord(
                    session_id=session_id,
                    role=message.role,
                    content_json=json.dumps(message.to_storage(), ensure_ascii=False),
                    created_at=datetime.utcnow(),
                )
                session.add(row)
            session.commit()
            owner = session.scalars(select(SessionRecord).where(SessionRecord.session_id == session_id)).first()
            if owner:
                owner.updated_at = datetime.utcnow()
                session.add(owner)
                session.commit()

    def list_messages(self, session_id: str) -> list[ConversationMessage]:
        with SessionLocal() as session:
            rows = session.scalars(
                select(SessionMessageRecord)
                .where(SessionMessageRecord.session_id == session_id)
                .order_by(SessionMessageRecord.id.asc())
            ).all()
            return [ConversationMessage.from_storage(json.loads(row.content_json)) for row in rows]

    def message_count(self, session_id: str) -> int:
        with SessionLocal() as session:
            count = session.scalar(
                select(func.count(SessionMessageRecord.id)).where(SessionMessageRecord.session_id == session_id)
            )
            return int(count or 0)

    def last_message_preview(self, session_id: str) -> str:
        with SessionLocal() as session:
            row = session.scalars(
                select(SessionMessageRecord)
                .where(SessionMessageRecord.session_id == session_id)
                .order_by(SessionMessageRecord.id.desc())
            ).first()
            if not row:
                return ""
            message = ConversationMessage.from_storage(json.loads(row.content_json))
            text = message.text.strip()
            return text[:160]

    def delete_all(self) -> None:
        with SessionLocal() as session:
            session.execute(delete(SessionMessageRecord))
            session.execute(delete(SessionRecord))
            session.commit()
