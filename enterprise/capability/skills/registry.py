from __future__ import annotations

"""负责技能注册表元数据的持久化与缓存。

该服务是 Skill manifest 的“控制面视图”：
- 数据源：Postgres（通过 SkillRepository）
- 缓存层：Redis（短 TTL，降低频繁读 DB 的开销）
"""

import json
from typing import Any

from enterprise.storage.redis_client import get_redis_client
from enterprise.storage.skill_repository import SkillRepository
from utils.logger_handler import logger


class SkillRegistryService:
    # 注册表缓存键：存放 list_skills() 的 JSON 串。
    CACHE_KEY = "skill_registry:all"

    def __init__(self):
        # 持久化仓储（Postgres）。
        self.repo = SkillRepository()
        # 缓存客户端（Redis）。
        self.redis = get_redis_client()

    def sync_manifests(self, manifests: list[dict[str, Any]]) -> None:
        """把 manifest 元数据写入 Postgres，并刷新缓存。

        典型调用时机：CapabilityGateway 启动或 reload 时。
        """
        for m in manifests:
            # upsert：存在则更新，不存在则插入。
            self.repo.upsert(m)
        self._refresh_cache()

    def list_skills(self) -> list[dict[str, Any]]:
        """优先从短时 Redis 缓存中读取技能注册表记录。"""
        cached = self.redis.get(self.CACHE_KEY)
        if cached:
            return json.loads(cached)

        # 缓存未命中则回源数据库，并回填缓存（TTL=60秒）。
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
