from __future__ import annotations

"""一个面向不稳定 MCP 依赖的轻量级熔断器实现。"""

import time
from dataclasses import dataclass


@dataclass
class CircuitState:
    """单个 MCP 工具对应的可变熔断状态。"""

    failures: int = 0
    opened_at: float = 0.0


class CircuitBreaker:
    """在连续失败后打开熔断，并在冷却时间后允许再次尝试。"""

    def __init__(self, failure_threshold: int, reset_seconds: int):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.state = CircuitState()

    def allow(self) -> bool:
        """返回当前是否允许继续发起调用。"""
        if self.state.failures < self.failure_threshold:
            return True
        return (time.time() - self.state.opened_at) > self.reset_seconds

    def record_success(self) -> None:
        """调用成功后重置熔断状态。"""
        self.state.failures = 0
        self.state.opened_at = 0.0

    def record_failure(self) -> None:
        """记录一次失败，并在达到阈值时打开熔断。"""
        self.state.failures += 1
        if self.state.failures >= self.failure_threshold:
            self.state.opened_at = time.time()
