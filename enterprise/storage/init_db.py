from sqlalchemy import inspect, text

from enterprise.storage.db import ENGINE
from enterprise.storage.models import Base


def init_storage() -> None:
    Base.metadata.create_all(bind=ENGINE)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    inspector = inspect(ENGINE)
    with ENGINE.begin() as conn:
        _ensure_column(
            inspector,
            conn,
            table_name="sessions",
            column_name="user_id",
            ddl="ALTER TABLE sessions ADD COLUMN user_id VARCHAR(120)",
        )
        _ensure_column(
            inspector,
            conn,
            table_name="memory_entries",
            column_name="user_id",
            ddl="ALTER TABLE memory_entries ADD COLUMN user_id VARCHAR(120)",
        )


def _ensure_column(inspector, conn, *, table_name: str, column_name: str, ddl: str) -> None:
    if not inspector.has_table(table_name):
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing:
        return
    conn.execute(text(ddl))
