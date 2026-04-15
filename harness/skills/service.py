from __future__ import annotations

from harness.skills.loader import load_skills, select_skills
from harness.skills.types import SkillDefinition
from enterprise.storage.skill_repository import SkillRepository


class SkillSyncService:
    """Loads markdown skills and synchronizes them into the skill registry table."""

    def __init__(self, skill_dir: str = "skills") -> None:
        self.skill_dir = skill_dir
        self.repo = SkillRepository()

    def sync(self, *, persist: bool = True) -> list[SkillDefinition]:
        skills = load_skills(self.skill_dir)
        if persist:
            for skill in skills:
                self.repo.upsert(
                    {
                        "id": skill.id,
                        "name": skill.name,
                        "description": skill.description,
                        "path": skill.path,
                        "version": "1.0.0",
                        "entrypoint": skill.path,
                        "tool_schemas": [],
                        "required_permissions": [],
                        "dependencies": [],
                        "tags": skill.tags,
                        "triggers": skill.triggers,
                        "allowed_tools": skill.allowed_tools,
                        "source": "markdown",
                        "enabled": skill.enabled,
                    }
                )
        return skills

    def select_for_query(self, query: str) -> list[SkillDefinition]:
        return select_skills(query, load_skills(self.skill_dir))
