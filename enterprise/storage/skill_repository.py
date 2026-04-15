from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import SkillRecord


class SkillRepository:
    def upsert(self, payload: dict) -> None:
        with SessionLocal() as session:
            row = session.scalars(select(SkillRecord).where(SkillRecord.id == payload["id"])).first()
            if not row:
                row = SkillRecord(
                    id=payload["id"],
                    name=payload.get("name", payload["id"]),
                    version=payload.get("version", "1.0.0"),
                    entrypoint=payload.get("entrypoint", payload.get("path", "")),
                    tool_schemas=json.dumps(payload.get("tool_schemas", []), ensure_ascii=False),
                    required_permissions=json.dumps(payload.get("required_permissions", []), ensure_ascii=False),
                    dependencies=json.dumps(payload.get("dependencies", []), ensure_ascii=False),
                    description=payload.get("description", ""),
                    path=payload.get("path", ""),
                    tags=json.dumps(payload.get("tags", []), ensure_ascii=False),
                    triggers=json.dumps(payload.get("triggers", []), ensure_ascii=False),
                    allowed_tools=json.dumps(payload.get("allowed_tools", []), ensure_ascii=False),
                    source=payload.get("source", "markdown"),
                    enabled=payload.get("enabled", True),
                    updated_at=datetime.utcnow(),
                )
            else:
                row.name = payload.get("name", row.name)
                row.version = payload.get("version", row.version)
                row.entrypoint = payload.get("entrypoint", payload.get("path", row.entrypoint))
                row.tool_schemas = json.dumps(payload.get("tool_schemas", json.loads(row.tool_schemas or "[]")), ensure_ascii=False)
                row.required_permissions = json.dumps(payload.get("required_permissions", json.loads(row.required_permissions or "[]")), ensure_ascii=False)
                row.dependencies = json.dumps(payload.get("dependencies", json.loads(row.dependencies or "[]")), ensure_ascii=False)
                row.description = payload.get("description", row.description)
                row.path = payload.get("path", row.path)
                row.tags = json.dumps(payload.get("tags", json.loads(row.tags or "[]")), ensure_ascii=False)
                row.triggers = json.dumps(payload.get("triggers", json.loads(row.triggers or "[]")), ensure_ascii=False)
                row.allowed_tools = json.dumps(payload.get("allowed_tools", json.loads(row.allowed_tools or "[]")), ensure_ascii=False)
                row.source = payload.get("source", row.source)
                row.enabled = payload.get("enabled", row.enabled)
                row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()

    def list_skills(self) -> list[dict]:
        with SessionLocal() as session:
            rows = session.scalars(select(SkillRecord)).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "path": row.path,
                    "version": row.version,
                    "entrypoint": row.entrypoint,
                    "tool_schemas": json.loads(row.tool_schemas or "[]"),
                    "required_permissions": json.loads(row.required_permissions or "[]"),
                    "dependencies": json.loads(row.dependencies or "[]"),
                    "tags": json.loads(row.tags or "[]"),
                    "triggers": json.loads(row.triggers or "[]"),
                    "allowed_tools": json.loads(row.allowed_tools or "[]"),
                    "source": row.source,
                    "enabled": row.enabled,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ]

    def set_enabled(self, skill_id: str, enabled: bool) -> bool:
        with SessionLocal() as session:
            row = session.scalars(select(SkillRecord).where(SkillRecord.id == skill_id)).first()
            if not row:
                return False
            row.enabled = enabled
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            return True
