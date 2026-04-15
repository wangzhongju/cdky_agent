from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Capability:
    name: str
    namespace: str
    description: str
    source: str
    schema: dict[str, Any]
    handler: Callable[..., Any]

    @property
    def fqdn(self) -> str:
        return f"{self.namespace}.{self.name}"


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int, reset_seconds: int) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.reset_seconds = max(1, int(reset_seconds))
        self.failure_count = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        if self.failure_count < self.failure_threshold:
            return True
        if time.time() - self.opened_at >= self.reset_seconds:
            self.failure_count = 0
            self.opened_at = 0.0
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = 0.0

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold and not self.opened_at:
            self.opened_at = time.time()
