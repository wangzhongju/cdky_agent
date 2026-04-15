from __future__ import annotations

from pydantic import BaseModel, Field


class SkillDefinition(BaseModel):
    id: str
    name: str
    description: str
    content: str
    path: str
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
