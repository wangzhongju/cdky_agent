from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from enterprise.capability.types import Capability
from harness.knowledge.service import KnowledgeService, ReportDataService
from harness.tools.base import ToolExecutionContext
from harness.tools.domain import GaodeGetLocationTool, GaodeGetWeatherTool
from model.factory import chat_model
from utils.path_tool import get_abs_path
from utils.prompt_loader import load_report_prompts


@lru_cache(maxsize=1)
def _knowledge_service() -> KnowledgeService:
    return KnowledgeService()


@lru_cache(maxsize=1)
def _report_service() -> ReportDataService:
    return ReportDataService()


@lru_cache(maxsize=1)
def _workspace_path() -> Path:
    return Path(get_abs_path(".")).resolve()


def _tool_context() -> ToolExecutionContext:
    return ToolExecutionContext(cwd=_workspace_path())


def _run_async_tool(tool, payload: dict[str, Any]) -> str:
    arguments = tool.input_model.model_validate(payload)
    result = asyncio.run(tool.execute(arguments, _tool_context()))
    if result.is_error:
        raise RuntimeError(result.output)
    return result.output


def register_rag_capability() -> list[Capability]:
    return [
        Capability(
            name="rag_summarize",
            namespace="knowledge",
            description="Search the local knowledge base and summarize relevant facts.",
            source="skill",
            schema={"query": "string"},
            handler=lambda query: _knowledge_service().search(query),
        )
    ]


def register_weather_capabilities() -> list[Capability]:
    weather_tool = GaodeGetWeatherTool()
    location_tool = GaodeGetLocationTool()
    return [
        Capability(
            name="get_weather",
            namespace="gaode",
            description="Query city weather via Gaode.",
            source="skill",
            schema={"city": "string"},
            handler=lambda city: _run_async_tool(weather_tool, {"city": city}),
        ),
        Capability(
            name="get_user_location",
            namespace="gaode",
            description="Resolve the current city via Gaode IP geolocation.",
            source="skill",
            schema={},
            handler=lambda: _run_async_tool(location_tool, {}),
        ),
    ]


def register_report_capabilities() -> list[Capability]:
    return [
        Capability(
            name="get_user_id",
            namespace="enterprise",
            description="Return a default report user id from the local data set.",
            source="skill",
            schema={},
            handler=default_user_id,
        ),
        Capability(
            name="get_current_month",
            namespace="enterprise",
            description="Return the latest month available in the report data set.",
            source="skill",
            schema={},
            handler=latest_available_month,
        ),
        Capability(
            name="fetch_external_data",
            namespace="enterprise",
            description="Read structured monthly enterprise report data.",
            source="skill",
            schema={"user_id": "string", "month": "string"},
            handler=lambda user_id, month: _report_service().fetch(user_id=user_id, month=month),
        ),
        Capability(
            name="fill_context",
            namespace="report",
            description="Legacy compatibility hook for the report pipeline.",
            source="skill",
            schema={},
            handler=lambda: {"status": "context_ready"},
        ),
        Capability(
            name="report_writer",
            namespace="report",
            description="Generate a human-readable report from structured external data.",
            source="skill",
            schema={"query": "string", "external_data": "object"},
            handler=report_writer,
        ),
    ]


def default_user_id() -> str:
    user_ids = _report_service().available_user_ids()
    return user_ids[0] if user_ids else "1001"


def latest_available_month() -> str:
    return _report_service().latest_month()


def report_writer(query: str, external_data: dict | str) -> str:
    payload = external_data
    if isinstance(external_data, str):
        try:
            payload = json.loads(external_data)
        except Exception:
            payload = {"raw": external_data}

    prompt = (
        f"{load_report_prompts()}\n\n"
        "Only use the data already provided. Do not emit any tool tags or function calls.\n"
        f"User question: {query}\n"
        f"Structured data: {json.dumps(payload, ensure_ascii=False)}\n"
    )
    try:
        result = chat_model.invoke(prompt).content
        cleaned = str(result).strip()
        if cleaned:
            return cleaned
    except Exception:
        pass
    return _render_report_fallback(query, payload if isinstance(payload, dict) else {"raw": payload})


def _render_report_fallback(query: str, payload: dict[str, Any]) -> str:
    lines = [
        "## Robot Usage Report",
        "",
        f"- Request: {query}",
        f"- User ID: {payload.get('user_id', 'unknown')}",
        f"- Month: {payload.get('month', 'unknown')}",
        f"- Usage profile: {payload.get('feature', 'n/a')}",
        f"- Cleaning efficiency: {payload.get('cleaning_efficiency', 'n/a')}",
        f"- Consumables: {payload.get('consumables', 'n/a')}",
        f"- Comparison: {payload.get('comparison', 'n/a')}",
        "- Suggestion: Inspect the brush, filter, and dust bin, then adjust the cleaning schedule to match the home layout.",
    ]
    return "\n".join(lines)
