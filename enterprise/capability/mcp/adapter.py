from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable

from enterprise.capability.mcp.circuit_breaker import CircuitBreaker
from enterprise.capability.types import Capability
from utils.logger_handler import logger


class MCPAdapter:
    def __init__(self):
        self._capabilities: dict[str, Capability] = {}
        self._breakers: dict[str, CircuitBreaker] = {}

    def register_tool(
        self,
        namespace: str,
        name: str,
        description: str,
        handler: Callable[..., Any],
        timeout_seconds: int,
        max_retries: int,
        failure_threshold: int,
        reset_seconds: int,
    ) -> None:
        key = f"{namespace}.{name}"
        breaker = CircuitBreaker(failure_threshold=failure_threshold, reset_seconds=reset_seconds)
        self._breakers[key] = breaker

        def wrapped_handler(**kwargs):
            if not breaker.allow():
                raise RuntimeError(f"MCP服务 {key} 熔断中")

            last_error: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(handler, **kwargs)
                        result = future.result(timeout=timeout_seconds)
                    breaker.record_success()
                    return result
                except TimeoutError as exc:
                    last_error = RuntimeError(f"MCP调用超时 key={key} attempt={attempt}")
                    logger.warning(str(last_error))
                except Exception as exc:
                    last_error = exc
                    logger.warning(f"MCP调用失败 key={key} attempt={attempt} err={exc}")

            breaker.record_failure()
            raise RuntimeError(f"MCP调用失败 key={key}: {last_error}")

        self._capabilities[key] = Capability(
            name=name,
            namespace=namespace,
            description=description,
            handler=lambda **kwargs: wrapped_handler(**kwargs),
            source="mcp",
        )

    def discover_tools(self) -> list[Capability]:
        return list(self._capabilities.values())

    def discover_resources(self) -> list[dict]:
        return []

    def discover_prompts(self) -> list[dict]:
        return []
