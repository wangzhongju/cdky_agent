from __future__ import annotations

from enterprise.storage.redis_client import get_redis_client
from utils.config_handler import enterprise_conf


class MetricsService:
    def __init__(self):
        self.redis = get_redis_client()
        self.ttl = int(enterprise_conf.get("governance", {}).get("metrics_ttl_seconds", 86400))

    def incr(self, key: str, amount: int = 1) -> None:
        val = self.redis.incrby(f"metrics:{key}", amount)
        if val == amount:
            self.redis.expire(f"metrics:{key}", self.ttl)

    def get_snapshot(self) -> dict:
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
