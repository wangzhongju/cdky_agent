from __future__ import annotations

import uuid
from typing import Generator

from enterprise.capability.gateway import CapabilityGateway
from enterprise.orchestrator.engine import OrchestratorEngine


class OrchestratorService:
    def __init__(self):
        self.gateway = CapabilityGateway()
        self.engine = OrchestratorEngine(self.gateway)

    def chat(self, message: str, session_id: str | None = None, trace_id: str | None = None) -> dict:
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
        result = self.chat(message=message, session_id=session_id, trace_id=trace_id)
        text = result["response"]
        for ch in text:
            yield ch

    def list_capabilities(self) -> list[dict]:
        return self.gateway.list_capabilities()

    def list_skills(self) -> list[dict]:
        return self.gateway.list_skills()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        return self.gateway.set_skill_enabled(skill_id, enabled)
