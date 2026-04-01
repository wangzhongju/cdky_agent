from __future__ import annotations

import time

from fastapi import HTTPException

from enterprise.storage.redis_client import get_redis_client
from utils.config_handler import enterprise_conf


class RateLimitService:
    def __init__(self):
        self.redis = get_redis_client()
        gov = enterprise_conf.get("governance", {})
        self.rate_limit = int(gov.get("rate_limit_per_minute", 120))
        self.daily_quota = int(gov.get("daily_quota", 2000))

    def check(self, actor: str) -> None:
        now = int(time.time())
        minute_bucket = now // 60
        day_bucket = now // 86400

        key_min = f"ratelimit:{actor}:{minute_bucket}"
        key_day = f"quota:{actor}:{day_bucket}"

        minute_count = self.redis.incr(key_min)
        if minute_count == 1:
            self.redis.expire(key_min, 120)

        day_count = self.redis.incr(key_day)
        if day_count == 1:
            self.redis.expire(key_day, 172800)

        if minute_count > self.rate_limit:
            raise HTTPException(status_code=429, detail="rate limit exceeded")

        if day_count > self.daily_quota:
            raise HTTPException(status_code=429, detail="daily quota exceeded")
