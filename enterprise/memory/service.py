from __future__ import annotations

import json
from typing import Any

from enterprise.storage.memory_repository import MemoryRepository


class MemoryService:
    def __init__(self) -> None:
        self.repo = MemoryRepository()

    def recall(self, query: str, *, user_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.repo.search(query, user_id=user_id, limit=limit)
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "memory_type": row.memory_type,
                "title": row.title,
                "content": row.content,
                "tags": json.loads(row.tags_json),
            }
            for row in rows
        ]

    def extract_and_store(
        self,
        *,
        user_id: str | None,
        session_id: str,
        user_message: str,
        assistant_response: str,
    ) -> None:
        patterns = [
            ("\u8bf7\u8bb0\u4f4f", "preference"),
            ("\u6211\u559c\u6b22", "preference"),
            ("\u6211\u7684", "fact"),
            ("todo", "constraint"),
        ]
        text = f"{user_message}\n{assistant_response}"
        for keyword, memory_type in patterns:
            if keyword in text.lower() or keyword in text:
                self.repo.add(
                    user_id=user_id,
                    session_id=session_id,
                    memory_type=memory_type,
                    title=user_message[:80],
                    content=text[:500],
                    tags=[keyword],
                )
                break
