from __future__ import annotations

from harness.engine.messages import ConversationMessage
from harness.skills.types import SkillDefinition


def build_system_prompt(
    *,
    base_prompt: str,
    permission_summary: str,
    skills: list[SkillDefinition],
    session_summary: str,
    memory_entries: list[str],
) -> str:
    sections = [base_prompt.strip()]
    if permission_summary:
        sections.append(f"## Permission Rules\n{permission_summary.strip()}")
    if skills:
        skill_block = "\n\n".join(
            f"### Skill: {skill.name}\n{skill.content.strip()}"
            for skill in skills
        )
        sections.append(f"## Active Skills\n{skill_block}")
    if session_summary:
        sections.append(f"## Session Summary\n{session_summary.strip()}")
    if memory_entries:
        sections.append("## Relevant Memory\n" + "\n".join(f"- {item}" for item in memory_entries))
    return "\n\n".join(section for section in sections if section.strip())


def compact_messages(
    messages: list[ConversationMessage],
    *,
    estimated_tokens: int,
    max_tokens: int,
    keep_last_messages: int,
) -> tuple[list[ConversationMessage], str]:
    if estimated_tokens <= max_tokens or len(messages) <= keep_last_messages:
        return messages, ""

    older = messages[:-keep_last_messages]
    newer = messages[-keep_last_messages:]
    summary_lines: list[str] = []
    for message in older:
        text = message.content.strip()
        if not text and message.tool_calls:
            tool_names = ", ".join(tool.name for tool in message.tool_calls)
            text = f"tool calls: {tool_names}"
        if not text:
            continue
        snippet = text[:240]
        summary_lines.append(f"{message.role}: {snippet}")
    return newer, "\n".join(summary_lines[:20])
