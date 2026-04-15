from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from enterprise.engine.messages import ConversationMessage, ToolResultBlock
from enterprise.engine.stream_events import (
    ApprovalRequired,
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from enterprise.hooks.executor import HookExecutor
from enterprise.model.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiRetryEvent,
    ApiTextDeltaEvent,
    SupportsStreamingMessages,
)
from enterprise.model.usage import UsageSnapshot
from enterprise.permissions.checker import PermissionChecker
from enterprise.tools.base import ToolExecutionContext, ToolRegistry


COMPACTED_PLACEHOLDER = "[Old tool result content cleared]"


@dataclass
class QueryContext:
    session_id: str
    api_client: SupportsStreamingMessages
    tool_registry: ToolRegistry
    permission_checker: PermissionChecker
    cwd: Path
    model: str
    system_prompt: str
    max_tokens: int
    max_turns: int
    hook_executor: HookExecutor
    tool_metadata: dict[str, Any]
    on_approval_required: Any


async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
    turn_count = 0
    while turn_count < context.max_turns:
        turn_count += 1
        _microcompact(messages)
        final_message: ConversationMessage | None = None
        usage = UsageSnapshot()
        try:
            async for event in context.api_client.stream_message(
                ApiMessageRequest(
                    model=context.model,
                    messages=messages,
                    system_prompt=context.system_prompt,
                    max_tokens=context.max_tokens,
                    tools=context.tool_registry.to_api_schema(),
                )
            ):
                if isinstance(event, ApiTextDeltaEvent):
                    yield AssistantTextDelta(text=event.text), None
                elif isinstance(event, ApiRetryEvent):
                    yield StatusEvent(message=f"Retrying model request in {event.delay_seconds:.1f}s"), None
                elif isinstance(event, ApiMessageCompleteEvent):
                    final_message = event.message
                    usage = event.usage
        except Exception as exc:
            yield ErrorEvent(message=str(exc)), None
            return

        if final_message is None:
            yield ErrorEvent(message="Model stream finished without final message"), None
            return

        messages.append(final_message)
        yield AssistantTurnComplete(message=final_message, usage=usage), usage

        if not final_message.tool_uses:
            return

        if len(final_message.tool_uses) == 1:
            tool_use = final_message.tool_uses[0]
            yield ToolExecutionStarted(tool_name=tool_use.name, tool_input=tool_use.input), None
            result = await _execute_tool_call(context, tool_use.name, tool_use.id, tool_use.input)
            if isinstance(result, ApprovalRequired):
                yield result, None
                return
            yield ToolExecutionCompleted(tool_name=tool_use.name, output=result.content, is_error=result.is_error), None
            messages.append(ConversationMessage(role="user", content=[result]))
            continue

        for tool_use in final_message.tool_uses:
            yield ToolExecutionStarted(tool_name=tool_use.name, tool_input=tool_use.input), None

        async def _run(tool_use):
            return tool_use, await _execute_tool_call(context, tool_use.name, tool_use.id, tool_use.input)

        results = await asyncio.gather(*[_run(tool_use) for tool_use in final_message.tool_uses])
        tool_blocks: list[ToolResultBlock] = []
        for tool_use, result in results:
            if isinstance(result, ApprovalRequired):
                yield result, None
                return
            tool_blocks.append(result)
            yield ToolExecutionCompleted(tool_name=tool_use.name, output=result.content, is_error=result.is_error), None
        messages.append(ConversationMessage(role="user", content=tool_blocks))

    yield ErrorEvent(message=f"Exceeded maximum turn limit: {context.max_turns}"), None


async def execute_tool_after_approval(
    *,
    tool_registry: ToolRegistry,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, Any],
    cwd: Path,
    tool_metadata: dict[str, Any],
) -> ToolResultBlock:
    tool = tool_registry.get(tool_name)
    if tool is None:
        return ToolResultBlock(tool_use_id=tool_use_id, content=f"Unknown tool: {tool_name}", is_error=True)
    parsed_input = tool.input_model.model_validate(tool_input)
    result = await tool.execute(parsed_input, ToolExecutionContext(cwd=cwd, metadata=tool_metadata))
    return ToolResultBlock(tool_use_id=tool_use_id, content=result.output, is_error=result.is_error)


async def _execute_tool_call(
    context: QueryContext,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, Any],
) -> ToolResultBlock | ApprovalRequired:
    tool = context.tool_registry.get(tool_name)
    if tool is None:
        return ToolResultBlock(tool_use_id=tool_use_id, content=f"Unknown tool: {tool_name}", is_error=True)

    parsed_input = tool.input_model.model_validate(tool_input)
    file_path = str(getattr(parsed_input, "path", "") or getattr(parsed_input, "file_path", "") or "").strip() or None
    command = str(getattr(parsed_input, "command", "")).strip() or None
    decision = context.permission_checker.evaluate(
        tool_name,
        is_read_only=tool.is_read_only(parsed_input),
        file_path=file_path,
        command=command,
    )
    if not decision.allowed and decision.requires_confirmation:
        approval_id = context.on_approval_required(
            session_id=context.session_id,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            tool_input=tool_input,
            reason=decision.reason,
        )
        return ApprovalRequired(
            approval_id=approval_id,
            tool_name=tool_name,
            tool_input=tool_input,
            reason=decision.reason,
        )
    if not decision.allowed:
        return ToolResultBlock(tool_use_id=tool_use_id, content=decision.reason, is_error=True)

    pre = await context.hook_executor.execute("pre_tool_use", {"tool_name": tool_name, "tool_input": tool_input})
    if pre.blocked:
        return ToolResultBlock(tool_use_id=tool_use_id, content=pre.reason or "Blocked by pre_tool_use hook", is_error=True)

    result = await tool.execute(
        parsed_input,
        ToolExecutionContext(
            cwd=context.cwd,
            metadata={**context.tool_metadata, "tool_registry": context.tool_registry},
        ),
    )
    await context.hook_executor.execute(
        "post_tool_use",
        {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": result.output,
            "tool_is_error": result.is_error,
        },
    )
    return ToolResultBlock(tool_use_id=tool_use_id, content=result.output, is_error=result.is_error)


def _microcompact(messages: list[ConversationMessage], keep_recent: int = 5) -> None:
    tool_result_indices = [
        idx
        for idx, message in enumerate(messages)
        if any(block.type == "tool_result" for block in message.content)
    ]
    if len(tool_result_indices) <= keep_recent:
        return
    clear_set = set(tool_result_indices[:-keep_recent])
    for idx, message in enumerate(messages):
        if idx not in clear_set:
            continue
        for block in message.content:
            if block.type == "tool_result":
                block.content = COMPACTED_PLACEHOLDER
