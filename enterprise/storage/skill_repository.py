from __future__ import annotations

import json
from datetime import datetime
from sqlalchemy import select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import SkillRecord


class SkillRepository:
    """封装 ``SkillRecord`` 对应的 SQLAlchemy 读写操作。"""

    def upsert(self, manifest: dict) -> None:
        """插入或更新一条技能 manifest 记录。"""
        with SessionLocal() as session:
            stmt = select(SkillRecord).where(SkillRecord.id == manifest["id"])
            row = session.scalars(stmt).first()
            if not row:
                row = SkillRecord(
                    id=manifest["id"],
                    name=manifest["name"],
                    version=manifest["version"],
                    entrypoint=manifest["entrypoint"],
                    tool_schemas=json.dumps(manifest.get("tool_schemas", []), ensure_ascii=False),
                    required_permissions=json.dumps(manifest.get("required_permissions", []), ensure_ascii=False),
                    dependencies=json.dumps(manifest.get("dependencies", []), ensure_ascii=False),
                    enabled=manifest.get("enabled", True),
                    updated_at=datetime.utcnow(),
                )
            else:
                row.name = manifest["name"]
                row.version = manifest["version"]
                row.entrypoint = manifest["entrypoint"]
                row.tool_schemas = json.dumps(manifest.get("tool_schemas", []), ensure_ascii=False)
                row.required_permissions = json.dumps(manifest.get("required_permissions", []), ensure_ascii=False)
                row.dependencies = json.dumps(manifest.get("dependencies", []), ensure_ascii=False)
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
                    "version": row.version,
                    "entrypoint": row.entrypoint,
                    "tool_schemas": json.loads(row.tool_schemas),
                    "required_permissions": json.loads(row.required_permissions),
                    "dependencies": json.loads(row.dependencies),
                    "enabled": row.enabled,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ]

    def set_enabled(self, skill_id: str, enabled: bool) -> bool:
        """切换单个技能的启用状态。"""
        with SessionLocal() as session:
            stmt = select(SkillRecord).where(SkillRecord.id == skill_id)
            row = session.scalars(stmt).first()
            if not row:
                return False
            row.enabled = enabled
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            return True
