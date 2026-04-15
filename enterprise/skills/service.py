from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from enterprise.storage.skill_repository import SkillRepository
from utils.config_handler import enterprise_conf


class SkillService:
    def __init__(self, model_client) -> None:
        self.model_client = model_client
        self.repo = SkillRepository()
        self.skill_dirs = [Path(path) for path in enterprise_conf.get("skills", {}).get("skill_dirs", ["skills"])]
        self._cache: dict[str, dict[str, Any]] = {}
        self.refresh()

    def refresh(self) -> None:
        cache: dict[str, dict[str, Any]] = {}
        for root in self.skill_dirs:
            if not root.exists():
                continue
            for manifest_path in root.glob("*/manifest.json"):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                skill_dir = manifest_path.parent
                payload = {
                    **manifest,
                    "path": str(skill_dir.resolve()),
                    "skill_path": str((skill_dir / "SKILL.md").resolve()),
                }
                self.repo.upsert(manifest, path=str(skill_dir.resolve()))
                cache[payload["id"]] = payload
        self._cache = cache

    def list_manifests(self) -> list[dict[str, Any]]:
        self.refresh()
        manifests = self.repo.list_manifests()
        return [manifest for manifest in manifests if manifest.get("enabled", True)]

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        self.refresh()
        manifest = self._cache.get(skill_id)
        if not manifest or not manifest.get("enabled", True):
            return None
        skill_path = Path(manifest["skill_path"])
        content = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
        return {**manifest, "content": content}

    async def select_skills(self, user_message: str, session_summary: str) -> list[dict[str, Any]]:
        manifests = self.list_manifests()
        if not manifests:
            return []
        manifest_lines = [
            f"{item['id']}: {item.get('name', item['id'])} | {item.get('description', '')}"
            for item in manifests
        ]
        prompt = (
            "Choose the most relevant skills for the next assistant turn.\n"
            "Return only a JSON array of skill ids.\n"
            f"User message: {user_message}\n"
            f"Session summary: {session_summary}\n"
            "Available skills:\n"
            + "\n".join(manifest_lines)
        )
        raw = await self.model_client.complete_text(
            model=enterprise_conf.get("model", {}).get("lightweight_model", enterprise_conf.get("model", {}).get("default_model", "qwen-plus")),
            system_prompt="You choose the most relevant skills. Return JSON only.",
            prompt=prompt,
            max_tokens=256,
        )
        try:
            selected_ids = json.loads(raw)
        except json.JSONDecodeError:
            selected_ids = self._fallback_select(user_message, manifests)
        if not isinstance(selected_ids, list):
            selected_ids = self._fallback_select(user_message, manifests)
        max_selected = int(enterprise_conf.get("skills", {}).get("max_selected", 3))
        result = []
        for skill_id in selected_ids[:max_selected]:
            skill = self.get_skill(str(skill_id))
            if skill:
                result.append(skill)
        return result

    def _fallback_select(self, user_message: str, manifests: list[dict[str, Any]]) -> list[str]:
        message = user_message.lower()
        if "\u62a5\u544a" in user_message or "report" in message:
            return ["report"]
        if any(item["id"] == "product_knowledge" for item in manifests):
            return ["product_knowledge"]
        return [manifests[0]["id"]]
