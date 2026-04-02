from __future__ import annotations

"""编排图中所有节点共享的状态类型定义。"""

from typing import Any, TypedDict


class OrchestratorState(TypedDict, total=False):
    """在图节点之间流转的可变状态对象。

    当前设计不是每个节点都返回新的领域对象，而是逐步补充同一个状态字典，
    这样更轻量，也更方便调试和观察中间结果。
    """

    query: str
    session_id: str
    trace_id: str
    intent: str
    planned_capabilities: list[dict[str, Any]]
    capability_results: list[dict[str, Any]]
    response: str
    report_context: dict[str, Any]
    cost: dict[str, Any]
