from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float = 0.0


class CircuitBreaker:
    def __init__(self, failure_threshold: int, reset_seconds: int):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.state = CircuitState()

    def allow(self) -> bool:
        if self.state.failures < self.failure_threshold:
            return True
        return (time.time() - self.state.opened_at) > self.reset_seconds

    def record_success(self) -> None:
        self.state.failures = 0
        self.state.opened_at = 0.0

    def record_failure(self) -> None:
        self.state.failures += 1
        if self.state.failures >= self.failure_threshold:
            self.state.opened_at = time.time()
