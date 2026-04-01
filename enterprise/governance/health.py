from __future__ import annotations

from sqlalchemy import text

from enterprise.storage.db import SessionLocal
from enterprise.storage.redis_client import get_redis_client


class HealthService:
    def __init__(self):
        self.redis = get_redis_client()

    def check(self) -> dict:
        status = {"api": "ok", "redis": "unknown", "postgres": "unknown"}

        try:
            pong = self.redis.ping()
            status["redis"] = "ok" if pong else "failed"
        except Exception:
            status["redis"] = "failed"

        try:
            with SessionLocal() as session:
                session.execute(text("SELECT 1"))
            status["postgres"] = "ok"
        except Exception:
            status["postgres"] = "failed"

        overall = "ok" if status["redis"] == "ok" and status["postgres"] == "ok" else "degraded"
        return {"status": overall, "components": status}
