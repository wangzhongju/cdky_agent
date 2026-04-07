from __future__ import annotations

"""编排图中所有节点共享的状态类型定义。

该模块提供一份“跨节点共享的数据契约”，用于描述 LangGraph 在一次请求中
可读写的状态字段。节点间通过增量更新同一个状态字典协作，而不是频繁创建
新对象，从而降低编排开销并提升可观测性。
"""

from typing import Any, TypedDict


class OrchestratorState(TypedDict, total=False):
    """编排节点间流转的统一状态对象。

    字段语义：
    - ``query``: 用户原始问题
    - ``session_id``: 会话标识，用于请求归并与审计追踪
    - ``trace_id``: 链路追踪标识
    - ``intent``: 意图分类结果（如 ``chat`` / ``report``）
    - ``planned_capabilities``: 规划阶段输出的能力调用计划
    - ``capability_results``: 执行阶段产出的能力调用结果列表
    - ``response``: 复核或响应阶段生成的最终回答文本
    - ``report_context``: 报告场景中间上下文（如 user_id/month）
    - ``cost``: 成本记录元数据（模型、token、估算费用）
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
