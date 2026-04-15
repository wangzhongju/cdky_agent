from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from utils.config_handler import enterprise_conf


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


class PermissionChecker:
    def __init__(self) -> None:
        conf = enterprise_conf.get("permissions", {})
        self.mode = conf.get("mode", "default")
        self.allowed_tools = set(conf.get("allowed_tools", []))
        self.denied_tools = set(conf.get("denied_tools", []))
        self.denied_commands = list(conf.get("denied_commands", []))
        self.sensitive_paths = list(conf.get("sensitive_paths", []))

    def evaluate(
        self,
        tool_name: str,
        *,
        is_read_only: bool,
        file_path: str | None = None,
        command: str | None = None,
    ) -> PermissionDecision:
        if tool_name in self.denied_tools:
            return PermissionDecision(False, reason=f"{tool_name} is denied")
        if tool_name in self.allowed_tools:
            return PermissionDecision(True, reason=f"{tool_name} is allowed")

        if file_path:
            for pattern in self.sensitive_paths:
                if fnmatch.fnmatch(file_path, pattern):
                    return PermissionDecision(False, reason=f"Sensitive path denied: {file_path}")

        if command:
            for pattern in self.denied_commands:
                if fnmatch.fnmatch(command, pattern):
                    return PermissionDecision(False, reason=f"Command denied by rule: {pattern}")

        if self.mode == "full_auto":
            return PermissionDecision(True, reason="Full auto mode")

        if is_read_only:
            return PermissionDecision(True, reason="Read-only tool")

        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="Mutating tools require approval",
        )
