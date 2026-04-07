from __future__ import annotations

"""LangGraph 编排引擎实现。

该模块处于编排层核心位置，负责把用户输入转换为“可执行的能力调用流程”。
它不关心能力本身如何实现（那是 ``CapabilityGateway`` 的职责），而是关心：
- 以什么图结构组织节点
- 以什么状态对象在节点间传递数据
- 在 report / chat 两类请求中按什么顺序执行能力
- 如何把能力结果收敛为最终回答
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from langgraph.graph import END, StateGraph

from enterprise.capability.gateway import CapabilityGateway
from enterprise.governance.cost import CostService
from enterprise.governance.model_router import ModelRouter
from enterprise.orchestrator.state import OrchestratorState
from utils.config_handler import enterprise_conf
from utils.logger_handler import logger


class OrchestratorEngine:
    """持有编译后的图对象，以及各节点执行逻辑。

    一次请求的执行流程由该类统一管理：
    - ``run`` 构造初始状态并驱动整张图
    - 节点方法执行意图识别、规划、执行、复核和响应生成
    - 通过 ``CostService``、``ModelRouter`` 接入治理能力
    """

    def __init__(self, gateway: CapabilityGateway):
        """装配编排依赖，并在初始化阶段编译图结构。"""
        self.gateway = gateway
        self.max_parallel = int(enterprise_conf.get("orchestrator", {}).get("max_parallel_capabilities", 4))
        self.cost_service = CostService()
        self.model_router = ModelRouter()
        self.graph = self._build_graph().compile()

    def _build_graph(self):
        """构建固定节点拓扑并返回未编译图对象。

        这里采用固定顺序边而非条件边：
        ``IntentClassifier -> Planner -> CapabilityRouter -> Executor -> Reviewer -> Responder``。
        真实分支决策在节点内部通过状态字段控制。
        """
        graph = StateGraph(OrchestratorState)

        graph.add_node("IntentClassifier", self.intent_classifier)
        graph.add_node("Planner", self.planner)
        graph.add_node("CapabilityRouter", self.capability_router)
        graph.add_node("Executor", self.executor)
        graph.add_node("Reviewer", self.reviewer)
        graph.add_node("Responder", self.responder)

        graph.set_entry_point("IntentClassifier")
        graph.add_edge("IntentClassifier", "Planner")
        graph.add_edge("Planner", "CapabilityRouter")
        graph.add_edge("CapabilityRouter", "Executor")
        graph.add_edge("Executor", "Reviewer")
        graph.add_edge("Reviewer", "Responder")
        graph.add_edge("Responder", END)

        return graph

    def run(self, query: str, session_id: str, trace_id: str) -> dict[str, Any]:
        """构造初始状态并执行编译后的图。

        返回值是图执行后的最终状态快照，供 ``OrchestratorService`` 序列化输出。
        """
        state: OrchestratorState = {
            "query": query,
            "session_id": session_id,
            "trace_id": trace_id,
            "planned_capabilities": [],
            "capability_results": [],
            "report_context": {},
        }
        return self.graph.invoke(state)

    def intent_classifier(self, state: OrchestratorState) -> OrchestratorState:
        """识别粗粒度意图并写回状态。

        当前使用关键词启发式规则：
        - 命中“报告/使用记录/月报/统计” -> ``report``
        - 否则 -> ``chat``
        """
        text = state["query"]
        report_keywords = ["报告", "使用记录", "月报", "统计"]
        intent = "report" if any(k in text for k in report_keywords) else "chat"
        state["intent"] = intent
        return state

    def planner(self, state: OrchestratorState) -> OrchestratorState:
        """把意图翻译为能力执行计划。

        计划元素统一为 ``{"fqdn": "...", "args": ...}``：
        - ``report`` 场景生成固定串行计划
        - ``chat`` 场景按查询内容拼装天气与 RAG 计划
        """
        query = state["query"]
        intent = state["intent"]
        plan: list[dict[str, Any]] = []

        #! 真实“分支”不靠 LangGraph 条件边，而是在节点内部 if
        if intent == "report":
            plan = [
                {"fqdn": "enterprise.get_user_id", "args": {}},
                {"fqdn": "enterprise.get_current_month", "args": {}},
                {"fqdn": "report.fill_context", "args": {}},
                {"fqdn": "enterprise.fetch_external_data", "args": "__DEFERRED__"},
                {"fqdn": "report.report_writer", "args": "__DEFERRED__"},
            ]
        else:
            if "天气" in query:
                plan.append({"fqdn": "gaode.get_user_location", "args": {}})
                plan.append({"fqdn": "gaode.get_weather", "args": "__DEFERRED_CITY__"})
            plan.append({"fqdn": "knowledge.rag_summarize", "args": {"query": query}})

        state["planned_capabilities"] = plan
        return state

    def capability_router(self, state: OrchestratorState) -> OrchestratorState:
        """能力路由扩展点。

        当前实现为透传节点，主要用于给后续策略化路由预留稳定插点。
        """
        return state

    def executor(self, state: OrchestratorState) -> OrchestratorState:
        """根据意图把执行分派到对应流程。"""
        intent = state["intent"]
        plan = state["planned_capabilities"]

        if intent == "report":
            return self._execute_report_flow(state, plan)

        return self._execute_general_flow(state, plan)

    def _execute_report_flow(self, state: OrchestratorState, plan: list[dict[str, Any]]) -> OrchestratorState:
        """按严格顺序执行报告链路。

        报告链路存在明显的数据依赖：``user_id/month -> external_data -> report``。
        因此采用串行调用，并把关键步骤产出写入 ``capability_results`` 与 ``report_context``。
        """
        results: list[dict[str, Any]] = []
        trace_id = state["trace_id"]

        user_id = self.gateway.invoke_capability(plan[0]["fqdn"], trace_id=trace_id)
        month = self.gateway.invoke_capability(plan[1]["fqdn"], trace_id=trace_id)
        _ = self.gateway.invoke_capability(plan[2]["fqdn"], trace_id=trace_id)
        raw_data = self.gateway.invoke_capability(plan[3]["fqdn"], user_id=user_id, month=month, trace_id=trace_id)

        if isinstance(raw_data, str):
            external_data = raw_data
            try:
                external_data = json.loads(raw_data.replace("'", '"'))
            except Exception:
                pass
        else:
            external_data = raw_data

        report = self.gateway.invoke_capability(
            plan[4]["fqdn"],
            query=state["query"],
            external_data=external_data,
            trace_id=trace_id,
        )

        results.append({"fqdn": plan[0]["fqdn"], "result": user_id, "trace_id": trace_id})
        results.append({"fqdn": plan[1]["fqdn"], "result": month, "trace_id": trace_id})
        results.append({"fqdn": plan[3]["fqdn"], "result": external_data, "trace_id": trace_id})
        results.append({"fqdn": plan[4]["fqdn"], "result": report, "trace_id": trace_id})

        state["capability_results"] = results
        state["report_context"] = {"user_id": user_id, "month": month}
        return state

    def _execute_general_flow(self, state: OrchestratorState, plan: list[dict[str, Any]]) -> OrchestratorState:
        """以有限并行度执行通用聊天链路。

        执行策略：
        - 先并行执行“非天气补全”步骤（如定位、RAG）
        - 再执行依赖定位结果的天气步骤（延迟参数 ``__DEFERRED_CITY__``）
        """
        results: list[dict[str, Any]] = []
        trace_id = state["trace_id"]
        city = ""

        def run_step(step: dict[str, Any]):
            """解析步骤参数并调用单个能力。"""
            fqdn = step["fqdn"]
            args = step["args"]
            if args == "__DEFERRED_CITY__":
                final_args = {"city": city or "北京"}
            else:
                final_args = args
            final_args["trace_id"] = trace_id
            return fqdn, self.gateway.invoke_capability(fqdn, **final_args)

        immediate_steps = [s for s in plan if s["fqdn"] != "gaode.get_weather"]
        deferred_weather = [s for s in plan if s["fqdn"] == "gaode.get_weather"]

        #! 聊天链路中的并行是 ThreadPoolExecutor 手工并行，不是 LangGraph 并行节点
        max_workers = min(self.max_parallel, max(1, len(immediate_steps)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(run_step, step) for step in immediate_steps]
            for future in as_completed(futures):
                fqdn, result = future.result()
                if fqdn == "gaode.get_user_location":
                    city = str(result)
                results.append({"fqdn": fqdn, "result": result, "trace_id": trace_id})

        for step in deferred_weather:
            fqdn, result = run_step(step)
            results.append({"fqdn": fqdn, "result": result, "trace_id": trace_id})

        state["capability_results"] = results
        return state

    def reviewer(self, state: OrchestratorState) -> OrchestratorState:
        """把能力原始输出归并为可读草稿。"""
        if not state.get("capability_results"):
            state["response"] = "未获取到任何可用能力结果。"
            return state

        if state["intent"] == "report":
            report_rows = [row for row in state["capability_results"] if row["fqdn"] == "report.report_writer"]
            state["response"] = str(report_rows[0]["result"]) if report_rows else "报告生成失败"
            return state

        lines = []
        for row in state["capability_results"]:
            if row["fqdn"] == "knowledge.rag_summarize":
                lines.append(str(row["result"]))
            elif row["fqdn"] == "gaode.get_weather":
                lines.append(f"补充天气信息：{row['result']}")

        state["response"] = "\n".join(lines) if lines else "暂无可用结果"
        return state

    def responder(self, state: OrchestratorState) -> OrchestratorState:
        """对聊天草稿执行最终 LLM 汇总，并记录成本元数据。

        ``report`` 场景直接复用报告正文，不进入二次汇总。
        ``chat`` 场景会：
        - 通过 ``ModelRouter`` 选模型
        - 调用模型生成最终响应
        - 通过 ``CostService`` 落库并更新指标
        """
        if state["intent"] == "report":
            return state

        model_name, chat_model = self.model_router.pick(state["query"], state["intent"])
        prompt = (
            "你是企业级客服编排器，请基于能力结果给出最终回答。"
            f"\n用户问题：{state['query']}"
            f"\n能力结果：{state['response']}"
        )
        try:
            final = chat_model.invoke(prompt).content
            cost_meta = self.cost_service.record(
                trace_id=state["trace_id"],
                actor=state.get("session_id", "anonymous"),
                model_name=model_name,
                input_text=prompt,
                output_text=final,
            )
            state["cost"] = cost_meta
        except Exception as exc:
            logger.warning(f"[Responder] LLM聚合失败，使用fallback err={exc}")
            final = state["response"]

        state["response"] = final
        return state
