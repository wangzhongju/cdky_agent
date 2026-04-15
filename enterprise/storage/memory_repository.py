from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, or_, select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import MemoryEntryRecord


class MemoryRepository:
    def add(
        self,
        *,
        user_id: str | None,
        session_id: str | None,
        memory_type: str,
        title: str,
        content: str,
        tags: list[str],
    ) -> None:
        with SessionLocal() as session:
            row = MemoryEntryRecord(
                user_id=user_id,
                session_id=session_id,
                memory_type=memory_type,
                title=title,
                content=content,
                tags_json=json.dumps(tags, ensure_ascii=False),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()

    def search(self, query: str, *, user_id: str | None = None, limit: int = 5) -> list[MemoryEntryRecord]:
        with SessionLocal() as session:
            pattern = f"%{query[:50]}%"
            stmt = (
                select(MemoryEntryRecord)
                .where(
                    or_(
                        MemoryEntryRecord.title.like(pattern),
                        MemoryEntryRecord.content.like(pattern),
                        MemoryEntryRecord.tags_json.like(pattern),
                    )
                )
                .order_by(MemoryEntryRecord.updated_at.desc())
                .limit(limit)
            )
            if user_id:
                stmt = stmt.where(or_(MemoryEntryRecord.user_id == user_id, MemoryEntryRecord.user_id.is_(None)))
            return list(session.scalars(stmt).all())

    def delete_all(self) -> None:
        with SessionLocal() as session:
            session.execute(delete(MemoryEntryRecord))
            session.commit()
