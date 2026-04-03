from __future__ import annotations

"""
演示：并发执行 + 超时 + 重试 + 熔断。

对照工程：
- enterprise/capability/mcp/adapter.py
- enterprise/capability/mcp/circuit_breaker.py
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
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


def unstable_service(city: str) -> str:
    """
    随机模拟三种情况：
    1. 快速成功
    2. 运行超时
    3. 直接报错
    """
    x = random.random()
    if x < 0.4:
        return f"{city} 晴"
    if x < 0.75:
        time.sleep(0.4)  # 故意慢，触发超时
        return f"{city} 阴"
    raise RuntimeError("上游服务异常")


def call_with_retry_and_timeout(
    handler,
    breaker: CircuitBreaker,
    timeout_seconds: float,
    max_retries: int,
    **kwargs,
) -> str:
    if not breaker.allow():
        raise RuntimeError("熔断开启中，暂不允许调用")

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(handler, **kwargs)
                result = future.result(timeout=timeout_seconds)
            breaker.record_success()
            return result
        except TimeoutError:
            last_error = RuntimeError(f"第{attempt + 1}次调用超时")
        except Exception as exc:
            last_error = exc

    breaker.record_failure()
    raise RuntimeError(f"调用失败，最终错误：{last_error}")


if __name__ == "__main__":
    breaker = CircuitBreaker(failure_threshold=3, reset_seconds=5)

    for i in range(1, 8):
        try:
            result = call_with_retry_and_timeout(
                handler=unstable_service,
                breaker=breaker,
                timeout_seconds=0.15,
                max_retries=2,
                city="北京",
            )
            print(f"[第{i}次] success -> {result}")
        except Exception as exc:
            print(f"[第{i}次] failed -> {exc}")
