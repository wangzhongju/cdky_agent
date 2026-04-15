from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import SkillManifestRecord


class SkillRepository:
    def upsert(self, manifest: dict[str, Any], *, path: str) -> None:
        with SessionLocal() as session:
            row = session.scalars(select(SkillManifestRecord).where(SkillManifestRecord.id == manifest["id"])).first()
            if not row:
                row = SkillManifestRecord(
                    id=manifest["id"],
                    name=manifest["name"],
                    description=manifest.get("description", ""),
                    path=path,
                    manifest_json=json.dumps(manifest, ensure_ascii=False),
                    enabled=manifest.get("enabled", True),
                    updated_at=datetime.utcnow(),
                )
            else:
                row.name = manifest["name"]
                row.description = manifest.get("description", "")
                row.path = path
                row.manifest_json = json.dumps(manifest, ensure_ascii=False)
                row.enabled = manifest.get("enabled", True)
                row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()

    def list_manifests(self) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            rows = session.scalars(select(SkillManifestRecord).order_by(SkillManifestRecord.id.asc())).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "path": row.path,
                    "enabled": row.enabled,
                    **json.loads(row.manifest_json),
                }
                for row in rows
            ]

    def set_enabled(self, skill_id: str, enabled: bool) -> bool:
        with SessionLocal() as session:
            row = session.scalars(select(SkillManifestRecord).where(SkillManifestRecord.id == skill_id)).first()
            if not row:
                return False
            row.enabled = enabled
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            return True
