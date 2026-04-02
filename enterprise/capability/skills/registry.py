from __future__ import annotations

"""负责技能注册表元数据的持久化与缓存。"""

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
        """把 manifest 元数据写入 Postgres，并刷新缓存。"""
        for m in manifests:
            self.repo.upsert(m)
        self._refresh_cache()

    def list_skills(self) -> list[dict[str, Any]]:
        """优先从短时 Redis 缓存中读取技能注册表记录。"""
        cached = self.redis.get(self.CACHE_KEY)
        if cached:
            return json.loads(cached)

        skills = self.repo.list_skills()
        self.redis.set(self.CACHE_KEY, json.dumps(skills, ensure_ascii=False), ex=60)
        return skills

    def set_enabled(self, skill_id: str, enabled: bool) -> bool:
        """切换某个技能的启用状态，并刷新注册表缓存。"""
        ok = self.repo.set_enabled(skill_id, enabled)
        if ok:
            self._refresh_cache()
        return ok

    def _refresh_cache(self) -> None:
        """以数据库为准重建缓存内容。"""
        skills = self.repo.list_skills()
        self.redis.set(self.CACHE_KEY, json.dumps(skills, ensure_ascii=False), ex=60)
        logger.info("[SkillRegistry] cache refreshed")
