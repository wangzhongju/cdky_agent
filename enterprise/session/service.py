from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from enterprise.engine.messages import ConversationMessage, ToolResultBlock
from enterprise.engine.query import execute_tool_after_approval
from enterprise.engine.query_engine import QueryEngine
from enterprise.engine.stream_events import StreamEvent
from enterprise.governance.audit import AuditService
from enterprise.governance.cost import CostService
from enterprise.hooks.executor import HookExecutor
from enterprise.memory.service import MemoryService
from enterprise.model.client import create_model_client
from enterprise.permissions.checker import PermissionChecker
from enterprise.skills.service import SkillService
from enterprise.storage.approval_repository import ApprovalRepository
from enterprise.storage.session_repository import SessionRepository
from enterprise.storage.user_repository import UserRepository
from enterprise.tools import create_default_tool_registry
from utils.config_handler import enterprise_conf
from utils.prompt_loader import load_system_prompt

DEFAULT_SESSION_TITLE = "新对话"


class SessionService:
    def __init__(self) -> None:
        model_conf = enterprise_conf.get("model", {})
        self.model_name = str(model_conf.get("default_model", "qwen3-max"))
        self.max_tokens = int(model_conf.get("max_tokens", 4096))
        self.max_turns = int(model_conf.get("max_turns", 8))
        self.cwd = Path(".").resolve()
        self.model_client = create_model_client()
        self.tool_registry = create_default_tool_registry()
        self.permission_checker = PermissionChecker()
        self.hook_executor = HookExecutor()
        self.skill_service = SkillService(self.model_client)
        self.memory_service = MemoryService()
        self.session_repo = SessionRepository()
        self.approval_repo = ApprovalRepository()
        self.user_repo = UserRepository()
        self.audit = AuditService()
        self.cost = CostService()
        self.default_system_prompt = load_system_prompt()

    def create_session(
        self,
        *,
        title: str = "",
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged_metadata = dict(metadata or {})
        effective_user_id = user_id or merged_metadata.get("user_id")
        if effective_user_id:
            merged_metadata["user_id"] = effective_user_id
        row = self.session_repo.create_session(
            title=title or DEFAULT_SESSION_TITLE,
            model_name=self.model_name,
            system_prompt=self.default_system_prompt,
            user_id=effective_user_id,
            metadata=merged_metadata,
        )
        return self._serialize_session(row)

    def list_sessions(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        return [self._serialize_session(row) for row in self.session_repo.list_sessions(user_id=user_id)]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.session_repo.get_session(session_id)
        return self._serialize_session(row) if row else None

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return [message.model_dump(mode="json") for message in self.session_repo.list_messages(session_id)]

    def list_skills(self) -> list[dict[str, Any]]:
        return self.skill_service.list_manifests()

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.input_model.model_json_schema(),
            }
            for tool in self.tool_registry.list_tools()
        ]

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        note: str = "",
        default_model: str = "",
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.user_repo.get_by_username(username)
        if existing:
            raise ValueError("username already exists")
        row = self.user_repo.create(
            username=username,
            display_name=display_name,
            note=note,
            default_model=default_model or self.model_name,
            preferences=preferences or {},
        )
        return self._serialize_user(row)

    def list_users(self) -> list[dict[str, Any]]:
        return [self._serialize_user(row) for row in self.user_repo.list_users()]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        row = self.user_repo.get_user(user_id)
        return self._serialize_user(row) if row else None

    def update_user(self, user_id: str, **kwargs) -> dict[str, Any] | None:
        row = self.user_repo.update_user(user_id, **kwargs)
        return self._serialize_user(row) if row else None

    def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        rows = self.approval_repo.list_by_status(status)
        return [
            {
                "approval_id": row.approval_id,
                "session_id": row.session_id,
                "tool_name": row.tool_name,
                "tool_use_id": row.tool_use_id,
                "tool_input": json.loads(row.tool_input_json),
                "status": row.status,
                "reason": row.reason,
                "actor": row.actor,
                "trace_id": row.trace_id,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    async def decide_approval(self, approval_id: str, *, approved: bool) -> dict[str, Any]:
        row = self.approval_repo.get(approval_id)
        if row is None:
            raise KeyError("approval not found")
        tool_input = json.loads(row.tool_input_json)
        if approved:
            tool_result = await execute_tool_after_approval(
                tool_registry=self.tool_registry,
                tool_name=row.tool_name,
                tool_use_id=row.tool_use_id,
                tool_input=tool_input,
                cwd=self.cwd,
                tool_metadata=self._tool_metadata(),
            )
            self.approval_repo.update_status(approval_id, "approved")
        else:
            tool_result = ToolResultBlock(tool_use_id=row.tool_use_id, content="Permission denied by user", is_error=True)
            self.approval_repo.update_status(approval_id, "rejected")
        self.session_repo.append_messages(row.session_id, [ConversationMessage(role="user", content=[tool_result])])
        self.session_repo.update_session(row.session_id, status="ACTIVE", pending_approval_id=None)
        return {"approval_id": approval_id, "status": "approved" if approved else "rejected"}

    async def stream(self, *, session_id: str, prompt: str | None, trace_id: str, actor: str, resume: bool = False) -> AsyncIterator[StreamEvent]:
        row = self.session_repo.get_session(session_id)
        if row is None:
            raise KeyError("session not found")
        messages = self.session_repo.list_messages(session_id)
        if prompt and not resume:
            user_message = ConversationMessage.from_user_text(prompt)
            messages.append(user_message)
            self.session_repo.append_messages(session_id, [user_message])

        active_prompt = prompt or (messages[-1].text if messages else "")
        skills = await self.skill_service.select_skills(active_prompt, row.summary)
        memories = self.memory_service.recall(
            active_prompt,
            user_id=row.user_id,
            limit=int(enterprise_conf.get("session", {}).get("memory_limit", 5)),
        )
        system_prompt = self._build_system_prompt(row.system_prompt, skills, row.summary, memories)
        initial_count = len(messages)

        def on_approval_required(*, session_id: str, tool_name: str, tool_use_id: str, tool_input: dict[str, Any], reason: str) -> str:
            approval = self.approval_repo.create(
                session_id=session_id,
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                tool_input=tool_input,
                reason=reason,
                actor=actor,
                trace_id=trace_id,
            )
            self.session_repo.update_session(session_id, status="PENDING_APPROVAL", pending_approval_id=approval.approval_id)
            return approval.approval_id

        engine = QueryEngine(
            api_client=self.model_client,
            tool_registry=self.tool_registry,
            permission_checker=self.permission_checker,
            cwd=self.cwd,
            model=row.model_name,
            system_prompt=system_prompt,
            max_tokens=self.max_tokens,
            max_turns=self.max_turns,
            hook_executor=self.hook_executor,
            tool_metadata=self._tool_metadata(skills=skills),
            on_approval_required=on_approval_required,
        )

        last_assistant_text = ""
        async for event in engine.submit(session_id=session_id, messages=messages):
            if getattr(event, "type", "") == "assistant_turn_complete":
                last_assistant_text = event.message.text
            yield event

        if len(messages) > initial_count:
            self.session_repo.append_messages(session_id, messages[initial_count:])

        total_usage = engine.cost_tracker.total
        if total_usage.total_tokens:
            self.cost.record_usage(
                trace_id=trace_id,
                actor=actor,
                model_name=row.model_name,
                input_tokens=total_usage.input_tokens,
                output_tokens=total_usage.output_tokens,
            )

        latest = self.session_repo.get_session(session_id)
        if latest and latest.pending_approval_id:
            return

        summary = await self._summarize(messages[-8:])
        title = row.title
        if self._should_generate_title(row.title) and active_prompt and last_assistant_text:
            title = await self._generate_title(active_prompt, last_assistant_text)
        self.session_repo.update_session(session_id, title=title, summary=summary, status="ACTIVE")
        if active_prompt and last_assistant_text:
            self.memory_service.extract_and_store(
                user_id=row.user_id,
                session_id=session_id,
                user_message=active_prompt,
                assistant_response=last_assistant_text,
            )

    def _tool_metadata(self, *, skills: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "skill_service": self.skill_service,
            "selected_skills": skills or [],
        }

    def _build_system_prompt(self, base_prompt: str, skills: list[dict[str, Any]], summary: str, memories: list[dict[str, Any]]) -> str:
        skill_text = "\n\n".join(f"[skill:{skill['id']}]\n{skill['content']}" for skill in skills)
        memory_text = "\n".join(f"- {item['title']}: {item['content']}" for item in memories)
        parts = [base_prompt]
        if skill_text:
            parts.append("Selected skills:\n" + skill_text)
        if summary:
            parts.append("Session summary:\n" + summary)
        if memory_text:
            parts.append("Relevant memory:\n" + memory_text)
        return "\n\n".join(part for part in parts if part)

    async def _summarize(self, messages: list[ConversationMessage]) -> str:
        transcript = "\n".join(f"{message.role}: {message.text}" for message in messages if message.text)
        if not transcript:
            return ""
        return await self.model_client.complete_text(
            model=enterprise_conf.get("model", {}).get("lightweight_model", self.model_name),
            system_prompt="Summarize the conversation in 3 short sentences.",
            prompt=f"Summarize the conversation for future turns:\n{transcript}",
            max_tokens=256,
        )

    async def _generate_title(self, user_message: str, assistant_response: str) -> str:
        prompt = f"User: {user_message}\nAssistant: {assistant_response}"
        title = await self.model_client.complete_text(
            model=enterprise_conf.get("model", {}).get("lightweight_model", self.model_name),
            system_prompt="Generate a concise conversation title. Return only the title, under 12 characters if possible.",
            prompt=prompt,
            max_tokens=32,
        )
        cleaned = " ".join((title or "").strip().split())
        if cleaned:
            return cleaned[:40]
        return user_message.strip()[:40] or DEFAULT_SESSION_TITLE

    def _should_generate_title(self, title: str) -> bool:
        normalized = (title or "").strip()
        return normalized in {"", "New Session", DEFAULT_SESSION_TITLE}

    def _serialize_session(self, row) -> dict[str, Any]:
        return {
            "session_id": row.session_id,
            "user_id": row.user_id,
            "title": row.title,
            "model_name": row.model_name,
            "summary": row.summary,
            "metadata": json.loads(row.metadata_json),
            "status": row.status,
            "pending_approval_id": row.pending_approval_id,
            "message_count": self.session_repo.message_count(row.session_id),
            "last_message_preview": self.session_repo.last_message_preview(row.session_id),
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    def _serialize_user(self, row) -> dict[str, Any]:
        return {
            "user_id": row.user_id,
            "username": row.username,
            "display_name": row.display_name,
            "note": row.note,
            "default_model": row.default_model,
            "preferences": json.loads(row.preferences_json),
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
