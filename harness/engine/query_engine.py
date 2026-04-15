from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from enterprise.governance.cost import CostService
from enterprise.storage.approval_repository import ApprovalRepository
from enterprise.storage.message_repository import MessageRepository
from enterprise.storage.session_repository import SessionRepository
from enterprise.storage.summary_repository import SummaryRepository
from harness.context.assembler import build_system_prompt, compact_messages
from harness.engine.cost_tracker import CostTracker, UsageSnapshot
from harness.engine.messages import ConversationMessage, ToolCall, ToolResultMessage
from harness.engine.stream_events import (
    ApprovalDecisionEvent,
    ApprovalRequiredEvent,
    AssistantCompleteEvent,
    AssistantDeltaEvent,
    DoneEvent,
    ErrorEvent,
    RetryEvent,
    StatusEvent,
    ToolResultEvent,
    ToolStartEvent,
    UsageEvent,
)
from harness.hooks.events import HookEvent
from harness.hooks.executor import HookExecutor
from harness.knowledge.service import KnowledgeService, ReportDataService
from harness.memory.service import MemoryService
from harness.permissions.checker import PermissionChecker
from harness.providers.base import (
    ProviderCompleteEvent,
    ProviderMessageRequest,
    ProviderRetryEvent,
    ProviderTextDeltaEvent,
    StreamingProvider,
)
from harness.providers.dashscope import DashScopeProvider
from harness.skills.service import SkillSyncService
from harness.tools.base import ToolExecutionContext, ToolResult
from harness.tools.registry import build_default_tool_registry
from utils.config_handler import enterprise_conf, hooks_conf
from utils.path_tool import get_abs_path


class QueryEngine:
    def __init__(
        self,
        *,
        provider: StreamingProvider | None = None,
        tool_registry=None,
        session_repo: SessionRepository | None = None,
        message_repo: MessageRepository | None = None,
        summary_repo: SummaryRepository | None = None,
        approval_repo: ApprovalRepository | None = None,
        skill_service: SkillSyncService | None = None,
        memory_service: MemoryService | None = None,
        cost_service: CostService | None = None,
        permission_checker: PermissionChecker | None = None,
        hook_executor: HookExecutor | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self.provider_conf = enterprise_conf.get("provider", {})
        self.session_conf = enterprise_conf.get("session", {})
        self.context_conf = enterprise_conf.get("context", {})
        self.permission_conf = enterprise_conf.get("permission", {})
        self.workspace = Path(workspace or get_abs_path(".")).resolve()
        self.provider = provider or self._build_provider()
        self.knowledge_service = KnowledgeService()
        self.report_service = ReportDataService()
        self.tool_registry = tool_registry or build_default_tool_registry(
            cwd=self.workspace,
            knowledge_service=self.knowledge_service,
            report_service=self.report_service,
        )
        self.session_repo = session_repo or SessionRepository()
        self.message_repo = message_repo or MessageRepository()
        self.summary_repo = summary_repo or SummaryRepository()
        self.approval_repo = approval_repo or ApprovalRepository()
        self.skill_service = skill_service or SkillSyncService()
        self.memory_service = memory_service or MemoryService()
        self.cost_service = cost_service or CostService()
        self.permission_checker = permission_checker or PermissionChecker(
            mode=str(self.permission_conf.get("mode", "default")),
            allowed_tools=list(self.permission_conf.get("allowed_tools", []) or []),
            denied_tools=list(self.permission_conf.get("denied_tools", []) or []),
            path_rules=list(self.permission_conf.get("path_rules", []) or []),
            denied_commands=list(self.permission_conf.get("denied_commands", []) or []),
        )
        self.hook_executor = hook_executor or HookExecutor(self.workspace, hooks_conf)
        self.base_prompt = Path(get_abs_path("prompts/main_prompt.txt")).read_text(encoding="utf-8")

    async def stream_query(
        self,
        *,
        message: str,
        actor: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        permission_mode: str | None = None,
        allow_approval_requests: bool = True,
    ) -> AsyncIterator[Any]:
        sid = session_id or str(uuid.uuid4())
        tid = trace_id or str(uuid.uuid4())
        session_permission_mode = permission_mode or str(self.permission_conf.get("mode", "default"))
        self.session_repo.get_or_create(
            session_id=sid,
            actor=actor,
            trace_id=tid,
            permission_mode=session_permission_mode,
            title=message.strip()[:80],
        )

        user_message = ConversationMessage(role="user", content=message)
        self.message_repo.append(sid, user_message)
        history = self.message_repo.list_by_session(sid)
        self.session_repo.update_status(sid, status="ACTIVE", latest_approval_id="", last_error="")
        yield StatusEvent(session_id=sid, trace_id=tid, message="assembling_context")

        try:
            async for event in self._continue_from_history(
                session_id=sid,
                trace_id=tid,
                actor=actor,
                query_text=message,
                history=history,
                permission_mode=session_permission_mode,
                allow_approval_requests=allow_approval_requests,
            ):
                yield event
        except Exception as exc:
            self.session_repo.update_status(sid, status="FAILED", last_error=str(exc))
            yield ErrorEvent(session_id=sid, trace_id=tid, message=str(exc), recoverable=False)
            yield DoneEvent(session_id=sid, trace_id=tid)

    async def run_to_completion(
        self,
        *,
        message: str,
        actor: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        permission_mode: str | None = None,
    ) -> dict[str, Any]:
        final_response = ""
        sid = session_id
        tid = trace_id
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost": 0.0,
            "model_name": self._provider_model_name(),
        }
        async for event in self.stream_query(
            message=message,
            actor=actor,
            session_id=session_id,
            trace_id=trace_id,
            permission_mode=permission_mode,
            allow_approval_requests=False,
        ):
            sid = getattr(event, "session_id", sid)
            tid = getattr(event, "trace_id", tid)
            if isinstance(event, AssistantCompleteEvent) and not event.message.tool_calls:
                final_response = event.message.content
            elif isinstance(event, UsageEvent):
                usage = {
                    "input_tokens": event.input_tokens,
                    "output_tokens": event.output_tokens,
                    "estimated_cost": event.estimated_cost,
                    "model_name": event.model_name,
                }
        return {
            "session_id": sid or str(uuid.uuid4()),
            "trace_id": tid or str(uuid.uuid4()),
            "response": final_response,
            "cost": usage,
        }

    async def resume_query(
        self,
        *,
        session_id: str,
        actor: str,
        trace_id: str | None = None,
    ) -> AsyncIterator[Any]:
        session = self.session_repo.get(session_id)
        tid = trace_id or (session.trace_id if session else str(uuid.uuid4()))
        if not session:
            yield ErrorEvent(session_id=session_id, trace_id=tid, message="session not found", recoverable=False)
            yield DoneEvent(session_id=session_id, trace_id=tid)
            return

        approval_id = session.latest_approval_id or ""
        approval = self.approval_repo.get(approval_id) if approval_id else self.approval_repo.latest_for_session(session_id)
        if not approval:
            yield ErrorEvent(session_id=session_id, trace_id=tid, message="approval not found", recoverable=False)
            yield DoneEvent(session_id=session_id, trace_id=tid)
            return
        if approval.status == "PENDING":
            yield ErrorEvent(session_id=session_id, trace_id=tid, message="approval is still pending", recoverable=True)
            yield DoneEvent(session_id=session_id, trace_id=tid)
            return
        if approval.status not in {"APPROVED", "DENIED"}:
            yield ErrorEvent(session_id=session_id, trace_id=tid, message="approval already resumed", recoverable=False)
            yield DoneEvent(session_id=session_id, trace_id=tid)
            return

        payload = json.loads(approval.payload or "{}")
        tool_calls = [ToolCall.model_validate(item) for item in payload.get("tool_calls", [])]
        history = self.message_repo.list_by_session(session_id)
        query_text = str(payload.get("query") or self._latest_user_message(history))

        yield ApprovalDecisionEvent(
            session_id=session_id,
            trace_id=tid,
            approval_id=approval.approval_id,
            decision=approval.decision or approval.status.lower(),
        )

        self.session_repo.update_status(session_id, status="ACTIVE", latest_approval_id="", last_error="")
        if approval.status == "APPROVED":
            for tool_call in tool_calls:
                yield ToolStartEvent(
                    session_id=session_id,
                    trace_id=tid,
                    tool_name=tool_call.name,
                    tool_input=tool_call.arguments,
                )
            tool_results = await self._execute_tool_calls(
                session_id=session_id,
                trace_id=tid,
                tool_calls=tool_calls,
                approval_granted=True,
            )
        else:
            tool_results = [
                self._blocked_tool_result(session_id, tid, tool_call, "tool use denied by approval decision")
                for tool_call in tool_calls
            ]

        for item in tool_results:
            history.append(item["message"])
            self.message_repo.append(session_id, item["message"])
            yield item["event"]

        self.approval_repo.mark_completed(approval.approval_id)
        yield StatusEvent(session_id=session_id, trace_id=tid, message="assembling_context")

        try:
            async for event in self._continue_from_history(
                session_id=session_id,
                trace_id=tid,
                actor=actor,
                query_text=query_text or "resume session",
                history=history,
                permission_mode=session.permission_mode,
                allow_approval_requests=True,
            ):
                yield event
        except Exception as exc:
            self.session_repo.update_status(session_id, status="FAILED", last_error=str(exc))
            yield ErrorEvent(session_id=session_id, trace_id=tid, message=str(exc), recoverable=False)
            yield DoneEvent(session_id=session_id, trace_id=tid)

    async def _continue_from_history(
        self,
        *,
        session_id: str,
        trace_id: str,
        actor: str,
        query_text: str,
        history: list[ConversationMessage],
        permission_mode: str,
        allow_approval_requests: bool,
    ) -> AsyncIterator[Any]:
        self.skill_service.sync()
        selected_skills = self.skill_service.select_for_query(query_text)
        session_summary_record = self.summary_repo.get(session_id)
        session_summary = session_summary_record.summary if session_summary_record else ""
        memory_entries = self.memory_service.lookup(actor=actor, query=query_text)
        system_prompt = build_system_prompt(
            base_prompt=self.base_prompt,
            permission_summary=self._permission_summary(permission_mode),
            skills=selected_skills,
            session_summary=session_summary,
            memory_entries=memory_entries,
        )
        usage_tracker = CostTracker()
        final_assistant_message: ConversationMessage | None = None
        max_turns = int(self.session_conf.get("max_turns", 8))

        for _ in range(max_turns):
            prompt_messages, summary_text = self._build_prompt_messages(system_prompt, history)
            if summary_text:
                self.summary_repo.upsert(
                    session_id,
                    summary_text,
                    len(history),
                    self._estimate_token_count(system_prompt, history),
                )
                system_prompt = build_system_prompt(
                    base_prompt=self.base_prompt,
                    permission_summary=self._permission_summary(permission_mode),
                    skills=selected_skills,
                    session_summary=summary_text,
                    memory_entries=memory_entries,
                )
                prompt_messages, _ = self._build_prompt_messages(system_prompt, history)

            yield StatusEvent(session_id=session_id, trace_id=trace_id, message="calling_model")
            request = ProviderMessageRequest(
                model=self._provider_model_name(),
                messages=prompt_messages,
                system_prompt=system_prompt,
                max_tokens=4096,
                tools=self.tool_registry.to_api_schema(),
            )
            assistant_message: ConversationMessage | None = None
            usage = UsageSnapshot()
            async for provider_event in self.provider.stream_message(request):
                if isinstance(provider_event, ProviderTextDeltaEvent):
                    yield AssistantDeltaEvent(
                        session_id=session_id,
                        trace_id=trace_id,
                        text=provider_event.text,
                    )
                elif isinstance(provider_event, ProviderRetryEvent):
                    yield RetryEvent(
                        session_id=session_id,
                        trace_id=trace_id,
                        attempt=provider_event.attempt,
                        max_attempts=provider_event.max_attempts,
                        delay_seconds=provider_event.delay_seconds,
                        message=provider_event.message,
                    )
                elif isinstance(provider_event, ProviderCompleteEvent):
                    assistant_message = provider_event.message
                    usage = provider_event.usage
            if not assistant_message:
                raise RuntimeError("provider did not return a completion")
            usage_tracker.add(usage)
            history.append(assistant_message)
            self.message_repo.append(session_id, assistant_message)
            yield AssistantCompleteEvent(session_id=session_id, trace_id=trace_id, message=assistant_message)

            if assistant_message.tool_calls:
                approval_event = self._create_approval_event(
                    session_id=session_id,
                    trace_id=trace_id,
                    actor=actor,
                    query_text=query_text,
                    tool_calls=assistant_message.tool_calls,
                    allow_approval_requests=allow_approval_requests,
                )
                if approval_event is not None:
                    self._refresh_summary(session_id, system_prompt, history)
                    yield approval_event
                    yield self._usage_event(session_id, trace_id, actor, usage_tracker)
                    yield DoneEvent(session_id=session_id, trace_id=trace_id)
                    return

                yield StatusEvent(session_id=session_id, trace_id=trace_id, message="executing_tools")
                for tool_call in assistant_message.tool_calls:
                    yield ToolStartEvent(
                        session_id=session_id,
                        trace_id=trace_id,
                        tool_name=tool_call.name,
                        tool_input=tool_call.arguments,
                    )
                tool_results = await self._execute_tool_calls(
                    session_id=session_id,
                    trace_id=trace_id,
                    tool_calls=assistant_message.tool_calls,
                    approval_granted=False,
                )
                for item in tool_results:
                    history.append(item["message"])
                    self.message_repo.append(session_id, item["message"])
                    yield item["event"]
                continue

            final_assistant_message = assistant_message
            break

        if not final_assistant_message:
            final_assistant_message = ConversationMessage(
                role="assistant",
                content="I could not finish the request within the current turn budget.",
            )
            history.append(final_assistant_message)
            self.message_repo.append(session_id, final_assistant_message)
            yield AssistantCompleteEvent(session_id=session_id, trace_id=trace_id, message=final_assistant_message)

        self._refresh_summary(session_id, system_prompt, history)
        self.memory_service.extract_and_store(
            actor=actor,
            session_id=session_id,
            user_text=query_text,
            assistant_text=final_assistant_message.content,
        )
        self.session_repo.update_status(session_id, status="ACTIVE", latest_approval_id="", last_error="")
        yield self._usage_event(session_id, trace_id, actor, usage_tracker)
        yield DoneEvent(session_id=session_id, trace_id=trace_id)

    async def _execute_tool_calls(
        self,
        *,
        session_id: str,
        trace_id: str,
        tool_calls: list[ToolCall],
        approval_granted: bool,
    ) -> list[dict[str, Any]]:
        tasks = [
            self._run_single_tool_call(
                session_id=session_id,
                trace_id=trace_id,
                tool_call=tool_call,
                approval_granted=approval_granted,
            )
            for tool_call in tool_calls
        ]
        return await asyncio.gather(*tasks)

    async def _run_single_tool_call(
        self,
        *,
        session_id: str,
        trace_id: str,
        tool_call: ToolCall,
        approval_granted: bool,
    ) -> dict[str, Any]:
        tool = self.tool_registry.get(tool_call.name)
        if not tool:
            return self._blocked_tool_result(session_id, trace_id, tool_call, f"tool not found: {tool_call.name}")

        try:
            arguments = tool.input_model.model_validate(tool_call.arguments)
        except Exception as exc:
            return self._blocked_tool_result(session_id, trace_id, tool_call, f"invalid tool arguments: {exc}")

        permission = self.permission_checker.evaluate(
            tool_call.name,
            is_read_only=tool.is_read_only(arguments),
            file_path=self._extract_file_path(tool_call.arguments),
            command=str(tool_call.arguments.get("command", "")) or None,
        )
        if not permission.allowed and not (approval_granted and permission.requires_confirmation):
            reason = permission.reason or f"{tool_call.name} is blocked"
            if permission.requires_confirmation and not approval_granted:
                reason = f"approval required before using {tool_call.name}: {reason}"
            return self._blocked_tool_result(session_id, trace_id, tool_call, reason)

        payload = {"tool_name": tool_call.name, "arguments": tool_call.arguments}
        pre_hook = await self.hook_executor.execute(HookEvent.PRE_TOOL_USE, payload)
        if pre_hook.blocked:
            return self._blocked_tool_result(
                session_id,
                trace_id,
                tool_call,
                pre_hook.reason or "pre-tool hook blocked execution",
            )

        result = await tool.execute(arguments, ToolExecutionContext(cwd=self.workspace))
        post_hook = await self.hook_executor.execute(
            HookEvent.POST_TOOL_USE,
            {
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": result.output,
                "is_error": result.is_error,
            },
        )
        if post_hook.blocked:
            result = ToolResult(output=post_hook.reason or "post-tool hook blocked execution", is_error=True)

        return {
            "event": ToolResultEvent(
                session_id=session_id,
                trace_id=trace_id,
                tool_name=tool_call.name,
                output=result.output,
                is_error=result.is_error,
            ),
            "message": ToolResultMessage(
                content=result.output,
                tool_call_id=tool_call.id,
                name=tool_call.name,
            ),
        }

    def _create_approval_event(
        self,
        *,
        session_id: str,
        trace_id: str,
        actor: str,
        query_text: str,
        tool_calls: list[ToolCall],
        allow_approval_requests: bool,
    ) -> ApprovalRequiredEvent | None:
        if not allow_approval_requests:
            return None

        blocked_tools: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            tool = self.tool_registry.get(tool_call.name)
            if not tool:
                continue
            try:
                arguments = tool.input_model.model_validate(tool_call.arguments)
            except Exception:
                continue
            permission = self.permission_checker.evaluate(
                tool_call.name,
                is_read_only=tool.is_read_only(arguments),
                file_path=self._extract_file_path(tool_call.arguments),
                command=str(tool_call.arguments.get("command", "")) or None,
            )
            if not permission.allowed and permission.requires_confirmation:
                blocked_tools.append(
                    {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "reason": permission.reason or "requires approval",
                    }
                )

        if not blocked_tools:
            return None

        approval_id = str(uuid.uuid4())
        self.approval_repo.create(
            approval_id=approval_id,
            session_id=session_id,
            trace_id=trace_id,
            actor=actor,
            reason="tool approval required",
            payload={
                "query": query_text,
                "tool_calls": [tool_call.model_dump(mode="json") for tool_call in tool_calls],
                "tools": blocked_tools,
            },
        )
        self.session_repo.update_status(session_id, status="WAITING_APPROVAL", latest_approval_id=approval_id, last_error="")
        return ApprovalRequiredEvent(
            session_id=session_id,
            trace_id=trace_id,
            approval_id=approval_id,
            tools=blocked_tools,
            reason="tool approval required",
        )

    def _usage_event(self, session_id: str, trace_id: str, actor: str, usage_tracker: CostTracker) -> UsageEvent:
        cost_meta = self.cost_service.record_usage(
            trace_id=trace_id,
            actor=actor,
            model_name=self._provider_model_name(),
            input_tokens=usage_tracker.total.input_tokens,
            output_tokens=usage_tracker.total.output_tokens,
        )
        return UsageEvent(
            session_id=session_id,
            trace_id=trace_id,
            input_tokens=cost_meta["input_tokens"],
            output_tokens=cost_meta["output_tokens"],
            estimated_cost=cost_meta["estimated_cost"],
            model_name=cost_meta["model_name"],
        )

    @staticmethod
    def _blocked_tool_result(session_id: str, trace_id: str, tool_call: ToolCall, message: str) -> dict[str, Any]:
        result = ToolResult(output=message, is_error=True)
        return {
            "event": ToolResultEvent(
                session_id=session_id,
                trace_id=trace_id,
                tool_name=tool_call.name,
                output=result.output,
                is_error=result.is_error,
            ),
            "message": ToolResultMessage(
                content=result.output,
                tool_call_id=tool_call.id,
                name=tool_call.name,
            ),
        }

    def _build_prompt_messages(
        self,
        system_prompt: str,
        history: list[ConversationMessage],
    ) -> tuple[list[ConversationMessage], str]:
        recent_limit = int(self.session_conf.get("recent_message_limit", 12))
        recent_messages = history[-recent_limit:]
        estimated_tokens = self._estimate_token_count(system_prompt, recent_messages)
        return compact_messages(
            recent_messages,
            estimated_tokens=estimated_tokens,
            max_tokens=int(self.context_conf.get("max_prompt_tokens", 12000)),
            keep_last_messages=int(self.context_conf.get("keep_last_messages", 6)),
        )

    def _refresh_summary(self, session_id: str, system_prompt: str, history: list[ConversationMessage]) -> None:
        estimated_tokens = self._estimate_token_count(system_prompt, history)
        _, summary = compact_messages(
            history,
            estimated_tokens=estimated_tokens,
            max_tokens=int(self.context_conf.get("max_prompt_tokens", 12000)),
            keep_last_messages=int(self.context_conf.get("keep_last_messages", 6)),
        )
        if summary:
            self.summary_repo.upsert(session_id, summary, len(history), estimated_tokens)

    def _estimate_token_count(self, system_prompt: str, messages: list[ConversationMessage]) -> int:
        total_chars = len(system_prompt)
        for message in messages:
            total_chars += len(message.content)
            total_chars += sum(len(json.dumps(tool_call.arguments, ensure_ascii=False)) for tool_call in message.tool_calls)
        return max(1, total_chars // 4)

    def _permission_summary(self, mode: str) -> str:
        denied_tools = ", ".join(self.permission_checker.denied_tools) or "none"
        denied_commands = ", ".join(self.permission_checker.denied_commands) or "none"
        return (
            f"permission_mode={mode}\n"
            f"denied_tools={denied_tools}\n"
            f"denied_commands={denied_commands}"
        )

    def _provider_model_name(self) -> str:
        return str(self.provider_conf.get("model", "qwen3-max"))

    def _build_provider(self) -> StreamingProvider:
        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        return DashScopeProvider(
            api_key=api_key,
            model=self._provider_model_name(),
            timeout_seconds=int(self.provider_conf.get("timeout_seconds", 60)),
            max_retries=int(self.provider_conf.get("max_retries", 3)),
            base_delay_seconds=float(self.provider_conf.get("base_delay_seconds", 1)),
            max_delay_seconds=float(self.provider_conf.get("max_delay_seconds", 30)),
        )

    @staticmethod
    def _extract_file_path(arguments: dict[str, Any]) -> str | None:
        for key in ("path", "base_path"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @staticmethod
    def _latest_user_message(history: list[ConversationMessage]) -> str:
        for message in reversed(history):
            if message.role == "user" and message.content.strip():
                return message.content
        return ""
