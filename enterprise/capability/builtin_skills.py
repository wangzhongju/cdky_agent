from __future__ import annotations

"""内置能力注册函数集合。

这些函数把遗留的工具对象封装成 ``Capability``，供 ``CapabilityGateway``
统一消费。
"""

import csv
import json
from datetime import datetime

from agent.tools.agent_tools import (
    fetch_external_data,
    fill_context_for_report,
    get_user_id,
    get_user_location,
    get_weather,
    rag_summarize,
)
from enterprise.capability.types import Capability
from model.factory import chat_model
from utils.path_tool import get_abs_path
from utils.prompt_loader import load_report_prompts


def _invoke_tool(tool_obj, payload: dict):
    """按 LangChain 工具期望的 payload 结构发起调用。"""
    return tool_obj.invoke(payload)


def register_rag_capability() -> list[Capability]:
    """注册知识检索与总结能力。"""
    return [
        Capability(
            name="rag_summarize",
            namespace="knowledge",
            description="从向量库检索并总结知识",
            source="skill",
            schema={"query": "string"},
            handler=lambda query: _invoke_tool(rag_summarize, {"query": query}),
        )
    ]


def register_weather_capabilities() -> list[Capability]:
    """注册聊天流程中会用到的天气与定位能力。"""
    return [
        Capability(
            name="get_weather",
            namespace="gaode",
            description="查询城市天气",
            source="skill",
            schema={"city": "string"},
            handler=lambda city: _invoke_tool(get_weather, {"city": city}),
        ),
        Capability(
            name="get_user_location",
            namespace="gaode",
            description="查询用户所在城市",
            source="skill",
            schema={},
            handler=lambda: _invoke_tool(get_user_location, {}),
        ),
    ]


def register_report_capabilities() -> list[Capability]:
    """注册报告生成流程固定使用的一组能力。"""
    return [
        Capability(
            name="get_user_id",
            namespace="enterprise",
            description="获取当前用户ID",
            source="skill",
            schema={},
            handler=lambda: _invoke_tool(get_user_id, {}),
        ),
        Capability(
            name="get_current_month",
            namespace="enterprise",
            description="获取当前月份",
            source="skill",
            schema={},
            handler=latest_available_month,
        ),
        Capability(
            name="fetch_external_data",
            namespace="enterprise",
            description="读取企业使用记录",
            source="skill",
            schema={"user_id": "string", "month": "string"},
            handler=lambda user_id, month: _invoke_tool(fetch_external_data, {"user_id": user_id, "month": month}),
        ),
        Capability(
            name="fill_context",
            namespace="report",
            description="报告上下文填充标记",
            source="skill",
            schema={},
            handler=lambda: _invoke_tool(fill_context_for_report, {}),
        ),
        Capability(
            name="report_writer",
            namespace="report",
            description="根据外部数据生成报告",
            source="skill",
            schema={"query": "string", "external_data": "object"},
            handler=report_writer,
        ),
    ]


def report_writer(query: str, external_data: dict | str) -> str:
    """根据已经拿到的外部数据生成最终报告文本。

    这里会显式告诉模型：当前阶段已经没有工具调用权限，从而保证报告生成
    保持确定性，不再递归触发工具调用。
    """
    prompt = load_report_prompts()
    payload = external_data
    if isinstance(external_data, str):
        try:
            payload = json.loads(external_data)
        except Exception:
            payload = {"raw": external_data}

    content = (
        f"{prompt}\n\n"
        "重要约束：你当前不具备任何工具调用能力，禁止输出 tool_call/function_call/XML 调用标签。"
        " 你必须直接基于已提供数据生成最终报告。\n"
        f"用户问题：{query}\n"
        f"外部记录：{json.dumps(payload, ensure_ascii=False)}\n"
    )
    try:
        result = chat_model.invoke(content).content
        if "<tool_call>" in result or "</tool_call>" in result or "function=" in result:
            return (
                "## 仿黑马程序员扫地机器人使用情况报告与保养建议\n\n"
                f"- 用户问题：{query}\n"
                f"- 核心数据：{json.dumps(payload, ensure_ascii=False)}\n"
                "- 建议：请按月检查滤网、主刷与边刷耗损，按家庭场景优化清扫频次。"
            )
        return result
    except Exception:
        return (
            "## 仿黑马程序员扫地机器人使用情况报告与保养建议\n\n"
            f"- 用户问题：{query}\n"
            f"- 核心数据：{json.dumps(payload, ensure_ascii=False)}\n"
            "- 建议：请按月检查滤网、主刷与边刷耗损，按家庭场景优化清扫频次。"
        )


def latest_available_month() -> str:
    """返回 CSV 数据中实际存在的最新月份。

    报告流程这里使用“数据可用月份”而不是“真实当前月份”，避免当前月份
    还没有导入数据时整条报告链路失败。
    """
    csv_path = get_abs_path("data/external/records.csv")
    months: set[str] = set()
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month = str(row.get("时间", "")).strip()
                if month:
                    months.add(month)
    except Exception:
        return datetime.now().strftime("%Y-%m")

    if not months:
        return datetime.now().strftime("%Y-%m")

    return sorted(months)[-1]
