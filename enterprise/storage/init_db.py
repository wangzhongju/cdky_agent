from __future__ import annotations

from sqlalchemy import text

from enterprise.storage.db import ENGINE
from enterprise.storage.models import Base


MIGRATIONS = (
    "ALTER TABLE skill_registry ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE skill_registry ADD COLUMN IF NOT EXISTS path VARCHAR(255) NOT NULL DEFAULT ''",
    "ALTER TABLE skill_registry ADD COLUMN IF NOT EXISTS tags TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE skill_registry ADD COLUMN IF NOT EXISTS triggers TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE skill_registry ADD COLUMN IF NOT EXISTS allowed_tools TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE skill_registry ADD COLUMN IF NOT EXISTS source VARCHAR(50) NOT NULL DEFAULT 'markdown'",
    "ALTER TABLE a2a_tasks ADD COLUMN IF NOT EXISTS permission_mode VARCHAR(20) NOT NULL DEFAULT 'default'",
)


def init_storage() -> None:
    Base.metadata.create_all(bind=ENGINE)
    with ENGINE.begin() as conn:
        for statement in MIGRATIONS:
            try:
                conn.execute(text(statement))
            except Exception:
                continue
