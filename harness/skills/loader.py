from __future__ import annotations

from pathlib import Path

import yaml

from harness.skills.types import SkillDefinition


def load_skills(skill_dir: str | Path = "skills") -> list[SkillDefinition]:
    root = Path(skill_dir)
    if not root.exists():
        return []
    skills: list[SkillDefinition] = []
    for path in sorted(root.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(content)
        skills.append(
            SkillDefinition(
                id=str(metadata.get("id") or path.stem),
                name=str(metadata.get("name") or path.stem),
                description=str(metadata.get("description") or path.stem),
                content=body,
                path=str(path),
                enabled=bool(metadata.get("enabled", True)),
                tags=[str(item) for item in metadata.get("tags", []) or []],
                triggers=[str(item) for item in metadata.get("triggers", []) or []],
                allowed_tools=[str(item) for item in metadata.get("allowed_tools", []) or []],
            )
        )
    return skills


def select_skills(query: str, skills: list[SkillDefinition]) -> list[SkillDefinition]:
    lowered = query.lower()
    matched: list[SkillDefinition] = []
    for skill in skills:
        if not skill.enabled:
            continue
        tokens = {skill.name.lower(), skill.id.lower(), *(tag.lower() for tag in skill.tags), *(trigger.lower() for trigger in skill.triggers)}
        if any(token and token in lowered for token in tokens):
            matched.append(skill)
    return matched


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                raw = "\n".join(lines[1:index])
                metadata = yaml.safe_load(raw) or {}
                body = "\n".join(lines[index + 1:]).strip()
                return metadata, body
    return {}, content.strip()
