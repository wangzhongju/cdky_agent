from __future__ import annotations

import asyncio
import fnmatch
import json
from pathlib import Path
from typing import Any

import requests

from harness.hooks.events import HookEvent
from harness.hooks.types import AggregatedHookResult, HookResult


class HookExecutor:
    def __init__(self, cwd: str | Path, config: dict[str, Any] | None = None) -> None:
        self.cwd = Path(cwd).resolve()
        self.config = config or {}

    async def execute(self, event: HookEvent, payload: dict[str, Any]) -> AggregatedHookResult:
        hooks = self.config.get(event.value, []) or []
        results: list[HookResult] = []
        for hook in hooks:
            matcher = str(hook.get("matcher", "")).strip()
            if matcher and not fnmatch.fnmatch(str(payload.get("tool_name", "")), matcher):
                continue
            hook_type = str(hook.get("type", "command"))
            if hook_type == "http":
                results.append(await self._run_http(hook, payload))
            else:
                results.append(await self._run_command(hook, payload))
        return AggregatedHookResult(results=results)

    async def _run_command(self, hook: dict[str, Any], payload: dict[str, Any]) -> HookResult:
        command = str(hook.get("command", "")).replace("$ARGUMENTS", json.dumps(payload, ensure_ascii=False))
        if not command:
            return HookResult(hook_type="command", success=True)
        timeout = float(hook.get("timeout_seconds", 10))
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return HookResult(
                hook_type="command",
                success=False,
                blocked=bool(hook.get("block_on_failure", False)),
                reason=f"command hook timed out after {timeout}s",
            )
        output = "\n".join(
            part for part in (
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            ) if part
        )
        success = process.returncode == 0
        return HookResult(
            hook_type="command",
            success=success,
            output=output,
            blocked=bool(hook.get("block_on_failure", False)) and not success,
            reason=output or f"command hook exit={process.returncode}",
            metadata={"returncode": process.returncode},
        )

    async def _run_http(self, hook: dict[str, Any], payload: dict[str, Any]) -> HookResult:
        url = str(hook.get("url", "")).strip()
        if not url:
            return HookResult(hook_type="http", success=True)
        timeout = float(hook.get("timeout_seconds", 10))
        response = await asyncio.to_thread(
            requests.post,
            url,
            json={"event": hook.get("event"), "payload": payload},
            headers=hook.get("headers", {}) or {},
            timeout=timeout,
        )
        success = response.ok
        output = response.text
        return HookResult(
            hook_type="http",
            success=success,
            output=output,
            blocked=bool(hook.get("block_on_failure", False)) and not success,
            reason=output or f"http hook status={response.status_code}",
            metadata={"status_code": response.status_code},
        )
