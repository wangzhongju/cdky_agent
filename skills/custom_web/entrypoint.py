from __future__ import annotations

"""Custom skill package: summarize a web page by calling MCP web fetch tool."""

import re

from enterprise.capability.skills.context import SkillContext
from enterprise.mcp.capability import Capability

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def register_web_skills(ctx: SkillContext | None = None) -> list[Capability]:
    def webpage_brief(query: str) -> str:
        match = _URL_RE.search(query or "")
        if not match:
            return "No URL detected. Please include an http/https URL in your query."

        if ctx is None:
            return "SkillContext is not available, so MCP web fetch cannot be used."

        url = match.group(0)
        payload = ctx.call_mcp(
            "web.fetch_page",
            url=url,
            max_chars=2600,
            extract_links=True,
            timeout=8,
        )
        if not isinstance(payload, dict):
            return f"Web fetch completed: {payload}"

        title = str(payload.get("title", "")).strip() or "(untitled)"
        text = str(payload.get("text", "")).strip()
        links = payload.get("links", [])
        status_code = payload.get("status_code", 0)

        brief = text[:360] + ("..." if len(text) > 360 else "")
        return (
            f"Web summary (status={status_code})\n"
            f"Title: {title}\n"
            f"Source: {url}\n"
            f"Snippet: {brief}\n"
            f"Link count: {len(links) if isinstance(links, list) else 0}"
        )

    return [
        Capability(
            name="webpage_brief",
            namespace="knowledge",
            description="Summarize a web page from URL",
            source="skill",
            schema={"query": "string"},
            handler=webpage_brief,
        )
    ]
