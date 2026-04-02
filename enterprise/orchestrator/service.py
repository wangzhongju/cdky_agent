from __future__ import annotations

"""LangGraph 编排引擎的高层门面服务。"""

import uuid
from typing import Generator

from enterprise.capability.gateway import CapabilityGateway
from enterprise.orchestrator.engine import OrchestratorEngine


class OrchestratorService:
    """以适合 API 调用的形式暴露编排能力。"""

    def __init__(self):
        self.gateway = CapabilityGateway()
        self.engine = OrchestratorEngine(self.gateway)

    def chat(self, message: str, session_id: str | None = None, trace_id: str | None = None) -> dict:
        """执行一次完整编排流程，并统一补齐会话与追踪元数据。"""
        sid = session_id or str(uuid.uuid4())
        tid = trace_id or str(uuid.uuid4())
        result = self.engine.run(message, sid, tid)
        return {
            "session_id": sid,
            "trace_id": tid,
            "response": result.get("response", ""),
            "intent": result.get("intent", "chat"),
            "capability_results": result.get("capability_results", []),
            "cost": result.get("cost", {}),
        }

    def stream_chat(self, message: str, session_id: str | None = None, trace_id: str | None = None) -> Generator[str, None, None]:
        """按字符逐步产出最终回答。

        当前不是模型原生分词流，而是先得到完整答案，再逐字符输出，
        方便前端实现“打字机效果”。
        """
        result = self.chat(message=message, session_id=session_id, trace_id=trace_id)
        text = result["response"]
        for ch in text:
            yield ch

    def list_capabilities(self) -> list[dict]:
        """返回运行时能力元数据。"""
        return self.gateway.list_capabilities()

    def list_skills(self) -> list[dict]:
        """返回持久化后的技能注册表记录。"""
        return self.gateway.list_skills()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        """切换技能启用状态，并在需要时重载能力目录。"""
        return self.gateway.set_skill_enabled(skill_id, enabled)
