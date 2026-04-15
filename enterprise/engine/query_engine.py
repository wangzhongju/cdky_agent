from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from enterprise.engine.cost_tracker import CostTracker
from enterprise.engine.messages import ConversationMessage
from enterprise.engine.query import QueryContext, run_query
from enterprise.engine.stream_events import StreamEvent
from enterprise.hooks.executor import HookExecutor
from enterprise.model.client import SupportsStreamingMessages
from enterprise.permissions.checker import PermissionChecker
from enterprise.tools.base import ToolRegistry


class QueryEngine:
    def __init__(
        self,
        *,
        api_client: SupportsStreamingMessages,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        max_tokens: int,
        max_turns: int,
        hook_executor: HookExecutor,
        tool_metadata: dict,
        on_approval_required,
    ) -> None:
        self.api_client = api_client
        self.tool_registry = tool_registry
        self.permission_checker = permission_checker
        self.cwd = Path(cwd).resolve()
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self.hook_executor = hook_executor
        self.tool_metadata = tool_metadata
        self.on_approval_required = on_approval_required
        self.cost_tracker = CostTracker()

    async def submit(self, *, session_id: str, messages: list[ConversationMessage]) -> AsyncIterator[StreamEvent]:
        context = QueryContext(
            session_id=session_id,
            api_client=self.api_client,
            tool_registry=self.tool_registry,
            permission_checker=self.permission_checker,
            cwd=self.cwd,
            model=self.model,
            system_prompt=self.system_prompt,
            max_tokens=self.max_tokens,
            max_turns=self.max_turns,
            hook_executor=self.hook_executor,
            tool_metadata=self.tool_metadata,
            on_approval_required=self.on_approval_required,
        )
        async for event, usage in run_query(context, messages):
            if usage is not None:
                self.cost_tracker.add(usage)
            yield event
