from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import UserRecord


class UserRepository:
    def create(
        self,
        *,
        username: str,
        display_name: str,
        note: str = "",
        default_model: str = "",
        preferences: dict | None = None,
    ) -> UserRecord:
        with SessionLocal() as session:
            row = UserRecord(
                user_id=uuid4().hex,
                username=username,
                display_name=display_name,
                note=note,
                default_model=default_model,
                preferences_json=json.dumps(preferences or {}, ensure_ascii=False),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_users(self) -> list[UserRecord]:
        with SessionLocal() as session:
            return list(session.scalars(select(UserRecord).order_by(UserRecord.updated_at.desc())).all())

    def get_user(self, user_id: str) -> UserRecord | None:
        with SessionLocal() as session:
            return session.scalars(select(UserRecord).where(UserRecord.user_id == user_id)).first()

    def get_by_username(self, username: str) -> UserRecord | None:
        with SessionLocal() as session:
            return session.scalars(select(UserRecord).where(UserRecord.username == username)).first()

    def update_user(self, user_id: str, **kwargs) -> UserRecord | None:
        with SessionLocal() as session:
            row = session.scalars(select(UserRecord).where(UserRecord.user_id == user_id)).first()
            if not row:
                return None
            for key, value in kwargs.items():
                if value is None:
                    continue
                if key == "preferences":
                    row.preferences_json = json.dumps(value or {}, ensure_ascii=False)
                elif hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def delete_all(self) -> None:
        with SessionLocal() as session:
            session.execute(delete(UserRecord))
            session.commit()
