from __future__ import annotations

"""为外部 MCP 工具补上超时、重试、熔断等韧性策略的适配层。"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable

from enterprise.capability.mcp.circuit_breaker import CircuitBreaker
from enterprise.capability.types import Capability
from utils.logger_handler import logger


class MCPAdapter:
    """管理 MCP 能力及其对应的熔断器。"""

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
        """注册一个带超时、重试和熔断保护的 MCP 工具。"""
        key = f"{namespace}.{name}"
        breaker = CircuitBreaker(failure_threshold=failure_threshold, reset_seconds=reset_seconds)
        self._breakers[key] = breaker

        def wrapped_handler(**kwargs):
            """在韧性控制之下执行原始 MCP 处理器。"""
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
        """以运行时能力对象的形式返回全部 MCP 工具。"""
        return list(self._capabilities.values())

    def discover_resources(self) -> list[dict]:
        """为未来的 MCP Resource 暴露预留接口。"""
        return []

    def discover_prompts(self) -> list[dict]:
        """为未来的 MCP Prompt 暴露预留接口。"""
        return []
