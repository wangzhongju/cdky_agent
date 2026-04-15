from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256

from sqlalchemy import asc, desc, select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import MemoryEntryRecord


class MemoryRepository:
    def upsert(
        self,
        *,
        actor: str,
        content: str,
        category: str = "general",
        session_id: str = "",
        keywords: list[str] | None = None,
    ) -> MemoryEntryRecord:
        content_hash = sha256(content.strip().encode("utf-8")).hexdigest()
        with SessionLocal() as session:
            row = session.scalars(select(MemoryEntryRecord).where(MemoryEntryRecord.content_hash == content_hash)).first()
            if not row:
                row = MemoryEntryRecord(
                    actor=actor,
                    session_id=session_id,
                    category=category,
                    content=content.strip(),
                    content_hash=content_hash,
                    keywords=json.dumps(keywords or [], ensure_ascii=False),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            else:
                row.actor = actor
                row.session_id = session_id
                row.category = category
                row.keywords = json.dumps(keywords or [], ensure_ascii=False)
                row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def search(self, actor: str, query: str, limit: int = 10) -> list[str]:
        tokens = {token.strip().lower() for token in query.split() if token.strip()}
        with SessionLocal() as session:
            stmt = (
                select(MemoryEntryRecord)
                .where(MemoryEntryRecord.actor == actor)
                .order_by(desc(MemoryEntryRecord.updated_at), asc(MemoryEntryRecord.id))
            )
            rows = session.scalars(stmt).all()
            scored: list[tuple[int, str]] = []
            for row in rows:
                haystacks = [row.content.lower(), " ".join(json.loads(row.keywords or "[]")).lower()]
                score = sum(1 for token in tokens if any(token in haystack for haystack in haystacks))
                scored.append((score, row.content))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [content for score, content in scored if score > 0][:limit]
