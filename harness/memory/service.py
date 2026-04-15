from __future__ import annotations

import re

from enterprise.storage.memory_repository import MemoryRepository


class MemoryService:
    """Extracts simple persistent facts and retrieves relevant memory."""

    def __init__(self) -> None:
        self.repo = MemoryRepository()

    def extract_and_store(self, *, actor: str, session_id: str, user_text: str, assistant_text: str = "") -> list[str]:
        entries = self._extract_entries(user_text) + self._extract_entries(assistant_text)
        stored: list[str] = []
        for entry in entries:
            self.repo.upsert(
                actor=actor,
                session_id=session_id,
                category=entry["category"],
                content=entry["content"],
                keywords=entry["keywords"],
            )
            stored.append(entry["content"])
        return stored

    def lookup(self, *, actor: str, query: str, limit: int = 8) -> list[str]:
        return self.repo.search(actor, query, limit=limit)

    @staticmethod
    def _extract_entries(text: str) -> list[dict]:
        candidates: list[dict] = []
        normalized = (text or "").strip()
        if not normalized:
            return candidates

        patterns = [
            ("identity", r"我叫([^\s，。,.]{1,20})", lambda m: f"用户名字是{m.group(1)}"),
            ("preference", r"我喜欢([^，。,.]{1,40})", lambda m: f"用户偏好{m.group(1)}"),
            ("home", r"我家里有([^，。,.]{1,40})", lambda m: f"用户家里有{m.group(1)}"),
            ("device", r"我的机器人是([^，。,.]{1,40})", lambda m: f"用户设备是{m.group(1)}"),
        ]
        for category, pattern, builder in patterns:
            for match in re.finditer(pattern, normalized):
                content = builder(match)
                candidates.append(
                    {
                        "category": category,
                        "content": content,
                        "keywords": [category, match.group(1)],
                    }
                )
        return candidates
