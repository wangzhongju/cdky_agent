from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    "*/.ssh/*",
    "*/.aws/credentials",
    "*/.aws/config",
    "*/.config/gcloud/*",
    "*/.azure/*",
    "*/.gnupg/*",
    "*/.docker/config.json",
    "*/.kube/config",
)


class PermissionMode(str, Enum):
    DEFAULT = "default"
    AUTO = "auto"
    PLAN = "plan"


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


@dataclass(frozen=True)
class PathRule:
    pattern: str
    allow: bool = True


class PermissionChecker:
    def __init__(
        self,
        *,
        mode: str = PermissionMode.DEFAULT.value,
        allowed_tools: list[str] | None = None,
        denied_tools: list[str] | None = None,
        path_rules: list[dict] | None = None,
        denied_commands: list[str] | None = None,
    ) -> None:
        self.mode = PermissionMode(mode)
        self.allowed_tools = set(allowed_tools or [])
        self.denied_tools = set(denied_tools or [])
        self.denied_commands = list(denied_commands or [])
        self.path_rules = [
            PathRule(pattern=str(rule.get("pattern", "")).strip(), allow=bool(rule.get("allow", True)))
            for rule in (path_rules or [])
            if str(rule.get("pattern", "")).strip()
        ]

    def evaluate(
        self,
        tool_name: str,
        *,
        is_read_only: bool,
        file_path: str | None = None,
        command: str | None = None,
    ) -> PermissionDecision:
        normalized_path = str(Path(file_path).resolve()) if file_path else None
        if normalized_path:
            for pattern in SENSITIVE_PATH_PATTERNS:
                if fnmatch.fnmatch(normalized_path, pattern):
                    return PermissionDecision(allowed=False, reason=f"sensitive path denied: {normalized_path}")
            for rule in self.path_rules:
                if fnmatch.fnmatch(normalized_path, rule.pattern) and not rule.allow:
                    return PermissionDecision(allowed=False, reason=f"path denied by rule: {rule.pattern}")

        if tool_name in self.denied_tools:
            return PermissionDecision(allowed=False, reason=f"{tool_name} is explicitly denied")

        if tool_name in self.allowed_tools:
            return PermissionDecision(allowed=True, reason=f"{tool_name} is explicitly allowed")

        if command:
            for pattern in self.denied_commands:
                if fnmatch.fnmatch(command, pattern):
                    return PermissionDecision(allowed=False, reason=f"command denied by rule: {pattern}")

        if self.mode == PermissionMode.AUTO:
            return PermissionDecision(allowed=True, reason="auto mode")

        if is_read_only:
            return PermissionDecision(allowed=True, reason="read-only tool")

        if self.mode == PermissionMode.PLAN:
            return PermissionDecision(allowed=False, reason="plan mode blocks mutating tools")

        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="mutating tool requires approval",
        )
