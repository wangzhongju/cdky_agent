from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

from utils.config_handler import enterprise_conf


@dataclass(frozen=True)
class HookResult:
    success: bool
    blocked: bool = False
    reason: str = ""
    output: str = ""


@dataclass(frozen=True)
class AggregatedHookResult:
    results: list[HookResult]

    @property
    def blocked(self) -> bool:
        return any(result.blocked for result in self.results)

    @property
    def reason(self) -> str:
        for result in self.results:
            if result.blocked and result.reason:
                return result.reason
        return ""


class HookExecutor:
    def __init__(self) -> None:
        self.conf = enterprise_conf.get("hooks", {})

    async def execute(self, event: str, payload: dict[str, Any]) -> AggregatedHookResult:
        hooks = self.conf.get(event, [])
        results: list[HookResult] = []
        for hook in hooks:
            hook_type = hook.get("type", "command")
            if hook_type == "command":
                results.append(await self._run_command(hook, payload))
            elif hook_type == "http":
                results.append(await self._run_http(hook, payload))
        return AggregatedHookResult(results)

    async def _run_command(self, hook: dict[str, Any], payload: dict[str, Any]) -> HookResult:
        command = str(hook.get("command", "")).replace("$ARGUMENTS", json.dumps(payload, ensure_ascii=False))
        timeout = int(hook.get("timeout_seconds", 10))
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return HookResult(success=False, blocked=bool(hook.get("block_on_failure")), reason="hook timeout")
        output = "\n".join(
            item
            for item in (
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
            if item
        )
        success = process.returncode == 0
        return HookResult(
            success=success,
            blocked=bool(hook.get("block_on_failure")) and not success,
            reason=output or f"hook exited with {process.returncode}",
            output=output,
        )

    async def _run_http(self, hook: dict[str, Any], payload: dict[str, Any]) -> HookResult:
        timeout = int(hook.get("timeout_seconds", 10))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    str(hook.get("url", "")),
                    json=payload,
                    headers=hook.get("headers", {}),
                )
        except Exception as exc:
            return HookResult(
                success=False,
                blocked=bool(hook.get("block_on_failure")),
                reason=str(exc),
            )
        success = response.is_success
        return HookResult(
            success=success,
            blocked=bool(hook.get("block_on_failure")) and not success,
            reason=response.text or f"http {response.status_code}",
            output=response.text,
        )
