from __future__ import annotations

import json
from typing import Any

from enterprise.storage.redis_client import get_redis_client
from enterprise.storage.skill_repository import SkillRepository
from utils.logger_handler import logger


class SkillRegistryService:
    CACHE_KEY = "skill_registry:all"

    def __init__(self):
        self.repo = SkillRepository()
        self.redis = get_redis_client()

    def sync_manifests(self, manifests: list[dict[str, Any]]) -> None:
        for m in manifests:
            self.repo.upsert(m)
        self._refresh_cache()

    def sync_skills(self, skills: list[dict[str, Any]]) -> None:
        for skill in skills:
            self.repo.upsert(skill)
        self._refresh_cache()

    def list_skills(self) -> list[dict[str, Any]]:
        cached = self.redis.get(self.CACHE_KEY)
        if cached:
            return json.loads(cached)

        skills = self.repo.list_skills()
        self.redis.set(self.CACHE_KEY, json.dumps(skills, ensure_ascii=False), ex=60)
        return skills

    def set_enabled(self, skill_id: str, enabled: bool) -> bool:
        ok = self.repo.set_enabled(skill_id, enabled)
        if ok:
            self._refresh_cache()
        return ok

    def _refresh_cache(self) -> None:
        skills = self.repo.list_skills()
        self.redis.set(self.CACHE_KEY, json.dumps(skills, ensure_ascii=False), ex=60)
        logger.info("[SkillRegistry] cache refreshed")
