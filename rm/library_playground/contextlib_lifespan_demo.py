from __future__ import annotations

"""
演示：contextlib.asynccontextmanager 的“启动-运行-关闭”生命周期模式。

对照工程：
- enterprise/api/app.py -> lifespan(app)
"""

import asyncio
from contextlib import asynccontextmanager


class FakeDb:
    def connect(self) -> None:
        print("[FakeDb] connect")

    def close(self) -> None:
        print("[FakeDb] close")


class FakeWorker:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True
        print("[FakeWorker] start")

    def stop(self) -> None:
        self.started = False
        print("[FakeWorker] stop")


@asynccontextmanager
async def app_lifespan():
    """
    这和 FastAPI 的 lifespan 思路一致：
    1. yield 前：做启动初始化
    2. yield 后：做关闭清理
    """
    db = FakeDb()
    worker = FakeWorker()

    print("[lifespan] startup begin")
    db.connect()
    worker.start()
    print("[lifespan] startup done")

    # 把资源暴露给“运行阶段”
    yield {"db": db, "worker": worker}

    print("[lifespan] shutdown begin")
    worker.stop()
    db.close()
    print("[lifespan] shutdown done")


async def handle_request(app_state: dict) -> None:
    """
    模拟业务处理阶段：这里可以使用启动阶段准备好的资源。
    """
    worker: FakeWorker = app_state["worker"]
    print(f"[request] worker.started={worker.started}")
    await asyncio.sleep(0.1)
    print("[request] done")


async def main() -> None:
    async with app_lifespan() as state:
        await handle_request(state)


if __name__ == "__main__":
    asyncio.run(main())
