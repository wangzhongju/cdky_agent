from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from enterprise.capability.gateway import CapabilityGateway
from enterprise.storage.message_repository import MessageRepository
from enterprise.storage.session_repository import SessionRepository
from enterprise.storage.summary_repository import SummaryRepository
from harness.engine.query_engine import QueryEngine


class OrchestratorService:
    def __init__(self, *, provider=None):
        self.gateway = CapabilityGateway()
        self.engine = QueryEngine(provider=provider)
        self.session_repo = SessionRepository()
        self.message_repo = MessageRepository()
        self.summary_repo = SummaryRepository()
        self.approval_repo = self.engine.approval_repo

    def chat(
        self,
        message: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        *,
        actor: str = "anonymous",
        permission_mode: str | None = None,
    ) -> dict:
        sid = session_id or str(uuid.uuid4())
        tid = trace_id or str(uuid.uuid4())
        result = asyncio.run(
            self.engine.run_to_completion(
                message=message,
                actor=actor,
                session_id=sid,
                trace_id=tid,
                permission_mode=permission_mode,
            )
        )
        return {
            "session_id": result["session_id"],
            "trace_id": result["trace_id"],
            "response": result.get("response", ""),
            "intent": "chat",
            "capability_results": [],
            "cost": result.get("cost", {}),
        }

    async def stream_chat(
        self,
        message: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        *,
        actor: str = "anonymous",
        permission_mode: str | None = None,
    ) -> AsyncIterator[str]:
        async for event in self.engine.stream_query(
            message=message,
            actor=actor,
            session_id=session_id,
            trace_id=trace_id,
            permission_mode=permission_mode,
        ):
            yield event.model_dump_json() + "\n"

    async def resume_chat(
        self,
        session_id: str,
        trace_id: str | None = None,
        *,
        actor: str = "anonymous",
    ) -> AsyncIterator[str]:
        async for event in self.engine.resume_query(
            session_id=session_id,
            actor=actor,
            trace_id=trace_id,
        ):
            yield event.model_dump_json() + "\n"

    def decide_approval(self, approval_id: str, decision: str) -> dict[str, Any] | None:
        row = self.approval_repo.decide(approval_id, decision)
        if not row:
            return None
        return {
            "approval_id": row.approval_id,
            "session_id": row.session_id,
            "trace_id": row.trace_id,
            "status": row.status,
            "decision": row.decision,
            "reason": row.reason,
            "payload": json.loads(row.payload or "{}"),
            "updated_at": row.updated_at.isoformat(),
        }

    def list_capabilities(self) -> list[dict]:
        return self.gateway.list_capabilities()

    def list_skills(self) -> list[dict]:
        return self.gateway.list_skills()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        ok = self.gateway.set_skill_enabled(skill_id, enabled)
        if ok:
            self.engine.skill_service.sync()
        return ok

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.session_repo.list_recent(limit=limit)
        return [
            {
                "session_id": row.session_id,
                "actor": row.actor,
                "trace_id": row.trace_id,
                "title": row.title,
                "status": row.status,
                "permission_mode": row.permission_mode,
                "last_error": row.last_error,
                "latest_approval_id": row.latest_approval_id,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.session_repo.get(session_id)
        if not row:
            return None
        summary = self.summary_repo.get(session_id)
        return {
            "session_id": row.session_id,
            "actor": row.actor,
            "trace_id": row.trace_id,
            "title": row.title,
            "status": row.status,
            "permission_mode": row.permission_mode,
            "metadata": json.loads(row.metadata_json or "{}"),
            "last_error": row.last_error,
            "latest_approval_id": row.latest_approval_id,
            "summary": summary.summary if summary else "",
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    def list_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        messages = self.message_repo.list_by_session(session_id)
        return [
            {
                "sequence": index,
                "role": message.role,
                "content": message.content,
                "tool_calls": [tool.model_dump(mode="json") for tool in message.tool_calls],
                "tool_call_id": message.tool_call_id,
                "name": message.name,
            }
            for index, message in enumerate(messages, start=1)
        ]
