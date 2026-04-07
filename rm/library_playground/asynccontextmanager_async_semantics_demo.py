from __future__ import annotations

"""
演示主题：asynccontextmanager 中 async 的语义与常见写法。

你可以重点观察：
1. @asynccontextmanager 装饰的函数必须是 async def。
2. yield 之前是“进入上下文”的异步初始化逻辑（可 await）。
3. yield 之后是“退出上下文”的异步清理逻辑（可 await）。
4. 上下文内部抛异常时，finally 仍然会执行。

建议运行：
python library_playground/asynccontextmanager_async_semantics_demo.py
"""

import asyncio
from contextlib import asynccontextmanager


class FakeAsyncResource:
    def __init__(self, name: str):
        self.name = name
        self.ready = False

    async def open(self) -> None:
        await asyncio.sleep(0.05)
        self.ready = True
        print(f"[{self.name}] open 完成")

    async def close(self) -> None:
        await asyncio.sleep(0.05)
        self.ready = False
        print(f"[{self.name}] close 完成")

    async def execute(self, command: str) -> str:
        if not self.ready:
            raise RuntimeError(f"[{self.name}] 资源未就绪")
        await asyncio.sleep(0.05)
        return f"[{self.name}] 执行命令: {command}"


@asynccontextmanager
async def resource_scope(name: str):
    """
    结构说明（和工程里 FastAPI lifespan 非常像）：
    - yield 前：初始化
    - yield 后：清理
    """
    resource = FakeAsyncResource(name)
    print(f"[{name}] 进入上下文前：开始初始化")
    await resource.open()
    try:
        # 把资源交给 async with 块使用
        yield resource
    except Exception as exc:
        print(f"[{name}] 上下文内部出现异常: {exc}")
        raise
    finally:
        print(f"[{name}] 退出上下文后：开始清理")
        await resource.close()


async def demo_normal_path() -> None:
    print("\n=== Demo1: 正常路径 ===")
    async with resource_scope("normal") as res:
        result = await res.execute("select * from table")
        print(result)


async def demo_exception_path() -> None:
    print("\n=== Demo2: 异常路径 ===")
    try:
        async with resource_scope("error") as res:
            result = await res.execute("update table set a=1")
            print(result)
            raise RuntimeError("业务代码主动抛出异常")
    except Exception as exc:
        print(f"[outer] 捕获到异常: {exc}")


class ClassStyleAsyncContext:
    """
    对照写法：不使用装饰器，而是手写 __aenter__ / __aexit__。
    """

    def __init__(self, name: str):
        self.resource = FakeAsyncResource(name)

    async def __aenter__(self) -> FakeAsyncResource:
        await self.resource.open()
        return self.resource

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.resource.close()


async def demo_class_style() -> None:
    print("\n=== Demo3: 类方式 async 上下文 ===")
    async with ClassStyleAsyncContext("class-style") as res:
        result = await res.execute("ping")
        print(result)


async def main() -> None:
    await demo_normal_path()
    await demo_exception_path()
    await demo_class_style()
    print("\nasynccontextmanager 示例结束")


if __name__ == "__main__":
    asyncio.run(main())
