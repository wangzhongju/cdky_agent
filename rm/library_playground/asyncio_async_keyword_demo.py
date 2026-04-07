from __future__ import annotations

"""
演示主题：在 asyncio 中如何理解和使用 async / await。

你可以重点观察这 4 件事：
1. async def 调用后，先得到的是“协程对象”，不会立刻执行。
2. await 会把控制权交还事件循环，等待协程结果。
3. 顺序 await 与并发调度（create_task + gather）的耗时差异。
4. wait_for 超时控制如何与 await 配合使用。

建议运行：
python library_playground/asyncio_async_keyword_demo.py
"""

import asyncio
import time


def now_ms() -> int:
    return int(time.perf_counter() * 1000)


async def fake_io(name: str, delay: float) -> str:
    """模拟 I/O 场景：通过 asyncio.sleep 表示“等待外部资源”。"""
    start = now_ms()
    print(f"[{name}] 开始，delay={delay}s, t={start}")
    await asyncio.sleep(delay)
    end = now_ms()
    print(f"[{name}] 结束，耗时={end - start}ms")
    return f"{name}-ok"


async def demo_1_coroutine_object() -> None:
    """
    说明：
    - async 函数调用时不会立刻执行函数体
    - 返回的是“协程对象”
    - 真正执行发生在 await 之后
    """
    print("\n=== Demo1: 协程对象与 await ===")
    coro = fake_io("demo1", 0.2)
    print(f"coro 类型: {type(coro)}")
    result = await coro
    print(f"await 结果: {result}")


async def demo_2_sequential_await() -> None:
    """顺序 await：总耗时大约是每一步耗时之和。"""
    print("\n=== Demo2: 顺序 await ===")
    t0 = now_ms()
    r1 = await fake_io("seq-1", 0.3)
    r2 = await fake_io("seq-2", 0.3)
    t1 = now_ms()
    print(f"结果: {r1}, {r2}")
    print(f"总耗时: {t1 - t0}ms（接近 600ms）")


async def demo_3_concurrent_tasks() -> None:
    """
    并发调度：
    - create_task 把协程交给事件循环并发执行
    - gather 等待所有任务结束
    """
    print("\n=== Demo3: 并发 create_task + gather ===")
    t0 = now_ms()
    task1 = asyncio.create_task(fake_io("con-1", 0.3))
    task2 = asyncio.create_task(fake_io("con-2", 0.3))
    r1, r2 = await asyncio.gather(task1, task2)
    t1 = now_ms()
    print(f"结果: {r1}, {r2}")
    print(f"总耗时: {t1 - t0}ms（接近 300ms）")


async def demo_4_timeout_control() -> None:
    """wait_for 给 await 增加超时约束。"""
    print("\n=== Demo4: wait_for 超时控制 ===")
    try:
        await asyncio.wait_for(fake_io("timeout-demo", 1.0), timeout=0.2)
    except asyncio.TimeoutError:
        print("触发 TimeoutError：任务超过 0.2s 未完成")


async def main() -> None:
    print("开始 asyncio / async / await 示例")
    await demo_1_coroutine_object()
    await demo_2_sequential_await()
    await demo_3_concurrent_tasks()
    await demo_4_timeout_control()
    print("\n全部示例完成")


if __name__ == "__main__":
    asyncio.run(main())
