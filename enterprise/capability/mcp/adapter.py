from __future__ import annotations

"""为外部 MCP 工具补上超时、重试、熔断等韧性策略的适配层。

MCPAdapter 的核心作用不是“发现工具”，而是“包装工具”：
- 对任意 handler 统一套上可靠性控制
- 输出统一的 Capability 对象给上游 Gateway 合并
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable

from enterprise.capability.mcp.circuit_breaker import CircuitBreaker
from enterprise.capability.types import Capability
from utils.logger_handler import logger


class MCPAdapter:
    """管理 MCP 能力及其对应的熔断器。"""

    def __init__(self):
        # 内存态 MCP 能力目录，key=fqdn。
        self._capabilities: dict[str, Capability] = {}
        # 每个能力一个 breaker，key=fqdn。
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
        """注册一个带超时、重试和熔断保护的 MCP 工具。

        参数说明
        - handler: 原始工具函数（可能是网络调用/IO调用）
        - timeout_seconds: 单次尝试超时阈值
        - max_retries: 重试次数（总尝试次数 = max_retries + 1）
        - failure_threshold/reset_seconds: 熔断器参数
        """
        key = f"{namespace}.{name}"

        # 为该工具创建独立熔断器。
        breaker = CircuitBreaker(failure_threshold=failure_threshold, reset_seconds=reset_seconds)
        self._breakers[key] = breaker

        def wrapped_handler(**kwargs):
            """在韧性控制之下执行原始 MCP 处理器。"""
            # 熔断打开时直接拒绝，避免持续打挂下游。
            if not breaker.allow():
                raise RuntimeError(f"MCP服务 {key} 熔断中")

            last_error: Exception | None = None

            # 注意：range(max_retries + 1) 包含首次尝试 + 重试。
            for attempt in range(max_retries + 1):
                try:
                    # 使用线程池 + future.timeout 实现“超时可控”的同步封装。
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(handler, **kwargs)
                        result = future.result(timeout=timeout_seconds)

                    # 任意一次成功即重置 breaker 并返回。
                    breaker.record_success()
                    return result
                except TimeoutError:
                    last_error = RuntimeError(f"MCP调用超时 key={key} attempt={attempt}")
                    logger.warning(str(last_error))
                except Exception as exc:
                    last_error = exc
                    logger.warning(f"MCP调用失败 key={key} attempt={attempt} err={exc}")

            # 所有尝试均失败：记录一次 breaker failure，然后统一抛错。
            breaker.record_failure()
            raise RuntimeError(f"MCP调用失败 key={key}: {last_error}")

        # 对外暴露 Capability，source 标记为 mcp。
        # handler 再包一层 lambda 是为了保持统一的 **kwargs 调用形态。
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
