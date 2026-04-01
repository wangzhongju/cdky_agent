from __future__ import annotations

from typing import Any, TypedDict


class OrchestratorState(TypedDict, total=False):
    query: str
    session_id: str
    trace_id: str
    intent: str
    planned_capabilities: list[dict[str, Any]]
    capability_results: list[dict[str, Any]]
    response: str
    report_context: dict[str, Any]
    cost: dict[str, Any]
