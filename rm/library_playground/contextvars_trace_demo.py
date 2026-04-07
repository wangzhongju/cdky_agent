from __future__ import annotations

"""
演示：contextvars 在“请求作用域”中传递 trace_id / actor。

对照工程：
- enterprise/governance/tracing.py

contextvars：
用于管理**上下文变量**（Context Variables）。它提供了在异步编程中传递和隔离上下文数据的能力，类似于线程本地存储，但专门为**异步/协程**设计
解决的问题：
- 全局变量并发不安全
- Thread Local 协程不安全
- 显示传递方式代码冗长
"""

import asyncio
import uuid
from contextvars import ContextVar


TRACE_ID_CTX: ContextVar[str] = ContextVar("trace_id", default="")
ACTOR_CTX: ContextVar[str] = ContextVar("actor", default="anonymous")


def current_trace_id() -> str:
    trace_id = TRACE_ID_CTX.get()
    return trace_id or str(uuid.uuid4())


def current_actor() -> str:
    return ACTOR_CTX.get() or "anonymous"


async def fake_middleware(headers: dict, handler):
    """
    模拟中间件：
    - 从“请求头”提取 trace_id / actor
    - 写入 ContextVar
    - 调用下游处理函数
    - 结束后恢复上下文（避免串请求）
    """
    trace_id = headers.get("x-trace-id") or str(uuid.uuid4())
    actor = headers.get("x-api-key") or "anonymous"

    token_trace = TRACE_ID_CTX.set(trace_id)
    token_actor = ACTOR_CTX.set(actor)
    try:
        return await handler()
    finally:
        TRACE_ID_CTX.reset(token_trace)
        ACTOR_CTX.reset(token_actor)


async def business_layer() -> None:
    # 业务层无需显式传参，也能拿到当前请求上下文
    print(f"[business] trace_id={current_trace_id()} actor={current_actor()}")
    await asyncio.sleep(0.05)
    print(f"[business] again trace_id={current_trace_id()} actor={current_actor()}")


async def main() -> None:
    headers = {"x-trace-id": "trace-ctx-001", "x-api-key": "tenant-a"}
    await fake_middleware(headers, business_layer)


if __name__ == "__main__":
    asyncio.run(main())
