from __future__ import annotations

"""负责聊天与报告请求的 LangGraph 编排引擎。"""

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
    """持有编译后的图对象，以及各节点的具体实现。"""

    def __init__(self, gateway: CapabilityGateway):
        self.gateway = gateway
        self.max_parallel = int(enterprise_conf.get("orchestrator", {}).get("max_parallel_capabilities", 4))
        self.cost_service = CostService()
        self.model_router = ModelRouter()
        self.graph = self._build_graph().compile()

    def _build_graph(self):
        """在启动时构建一次固定的编排流水线。"""
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
        """构造初始状态并执行编译后的图。"""
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
        """将请求划分到图中使用的粗粒度执行分支。"""
        text = state["query"]
        report_keywords = ["报告", "使用记录", "月报", "统计"]
        intent = "report" if any(k in text for k in report_keywords) else "chat"
        state["intent"] = intent
        return state

    def planner(self, state: OrchestratorState) -> OrchestratorState:
        """把识别出的意图翻译成可执行的能力计划。"""
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
        """保留稳定的路由扩展点，便于后续加入策略化分流。"""
        return state

    def executor(self, state: OrchestratorState) -> OrchestratorState:
        """根据意图把执行分派到对应流程。"""
        intent = state["intent"]
        plan = state["planned_capabilities"]

        if intent == "report":
            return self._execute_report_flow(state, plan)

        return self._execute_general_flow(state, plan)

    def _execute_report_flow(self, state: OrchestratorState, plan: list[dict[str, Any]]) -> OrchestratorState:
        """按严格顺序执行报告生成流程。

        报告链路强依赖前序步骤产出的上下文，因此这里采用串行执行，
        而不是并行化。
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
        """在安全前提下，以有限并行度执行通用聊天能力。"""
        results: list[dict[str, Any]] = []
        trace_id = state["trace_id"]
        city = ""

        def run_step(step: dict[str, Any]):
            """解析延迟参数，并调用单个能力。"""
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
        """把原始能力输出归并成一份回答草稿。"""
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
        """对聊天类响应再做一次最终 LLM 汇总。

        报告类请求会跳过这一步，因为 ``report.report_writer`` 已经直接产出
        最终报告正文。
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
