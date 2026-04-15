from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HookResult:
    hook_type: str
    success: bool
    output: str = ""
    blocked: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregatedHookResult:
    results: list[HookResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(result.blocked for result in self.results)

    @property
    def reason(self) -> str:
        for result in self.results:
            if result.blocked:
                return result.reason or result.output
        return ""
