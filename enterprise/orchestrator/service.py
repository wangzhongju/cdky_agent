from __future__ import annotations

"""
编排层的应用服务门面。

API 层不会直接操作 ``OrchestratorEngine`` 或图对象，而是统一通过本服务交互。
该门面主要负责：
- 注入并持有 ``CapabilityGateway`` 与 ``OrchestratorEngine``
- 统一补齐 ``session_id`` / ``trace_id`` 这类请求元数据
- 把编排结果整理成 API 友好的输出结构
- 提供字符级流式输出能力，兼容前端打字机体验
"""

import uuid
from typing import Generator

from enterprise.capability.gateway import CapabilityGateway
from enterprise.orchestrator.engine import OrchestratorEngine


class OrchestratorService:
    """对外暴露编排能力的应用服务层。"""

    def __init__(self):
        """装配能力网关与编排引擎。"""
        self.gateway = CapabilityGateway()
        self.engine = OrchestratorEngine(self.gateway)

    def chat(self, message: str, session_id: str | None = None, trace_id: str | None = None) -> dict:
        """执行一次完整编排流程，并返回结构化结果。"""
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

        注意：这不是模型原生 token 流。
        这里的实现是先同步拿到完整 ``chat`` 结果，再逐字符 ``yield``。
        """
        result = self.chat(message=message, session_id=session_id, trace_id=trace_id)
        text = result["response"]
        for ch in text:
            yield ch

    def list_capabilities(self) -> list[dict]:
        """返回编排器当前可见的能力目录快照。"""
        return self.gateway.list_capabilities()

    def list_skills(self) -> list[dict]:
        """返回持久化后的技能注册表记录。"""
        return self.gateway.list_skills()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        """切换技能启用状态，并在需要时重载能力目录。"""
        return self.gateway.set_skill_enabled(skill_id, enabled)
