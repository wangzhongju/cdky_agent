from __future__ import annotations

from enterprise.storage.redis_client import get_redis_client
from utils.config_handler import enterprise_conf


class MetricsService:
    """把轻量级运行时计数存放到 Redis。"""

    def __init__(self):
        self.redis = get_redis_client()
        self.ttl = int(enterprise_conf.get("governance", {}).get("metrics_ttl_seconds", 86400))

    def incr(self, key: str, amount: int = 1) -> None:
        """递增计数器，并在首次创建时设置过期时间。"""
        val = self.redis.incrby(f"metrics:{key}", amount)
        if val == amount:
            self.redis.expire(f"metrics:{key}", self.ttl)

    def get_snapshot(self) -> dict:
        """读取所有 ``metrics:*`` 键，并整理成可序列化字典。"""
        keys = self.redis.keys("metrics:*")
        data = {}
        for key in keys:
            k = key.replace("metrics:", "", 1)
            typ = self.redis.type(key)
            if typ == "string":
                data[k] = self.redis.get(key)
            elif typ == "hash":
                data[k] = self.redis.hgetall(key)
        return data
