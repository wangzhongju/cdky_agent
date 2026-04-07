from __future__ import annotations

"""企业级 Agent 运行时的 FastAPI 入口。

这个模块位于系统最外层，主要负责：
- 进程启动与关闭时的资源初始化
- HTTP 中间件挂载
- 同步聊天接口暴露
- 异步任务接口暴露

真正的业务编排逻辑都下沉到 ``app.state`` 中保存的服务对象里。
lifespan是根：创建，并托管所有基础服务实例
app.state是桥：把启动期创建的服务暴露给请求期代码
governance_middleware是治理入口：每个请求都会走限流/指标/审计
trace_context_middleware + current_trace_id() 打通链路追踪
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from enterprise.a2a.runtime import A2ARuntime
from enterprise.api.schemas import ChatStreamRequest, TaskCreateRequest, SkillPatchRequest
from enterprise.governance.audit import AuditService
from enterprise.governance.health import HealthService
from enterprise.governance.metrics import MetricsService
from enterprise.governance.prometheus_metrics import (
    api_request_latency_ms,
    api_requests_total,
    inflight_requests,
    metrics_payload,
)
from enterprise.governance.rate_limit import RateLimitService
from enterprise.governance.tracing import (
    current_trace_id,
    setup_tracer,
    trace_context_middleware,
)
from enterprise.orchestrator.service import OrchestratorService
from enterprise.storage.init_db import init_storage


"""
lifespan:应用级生命周期总控
    yield 之前: 应用启动时执行 (初始化资源)
    yiled 之后: 应用停止时执行 (释放资源)
"""
@asynccontextmanager
async def lifespan(app: FastAPI):
    """在进程级别初始化长生命周期服务。

    启动阶段会初始化存储、Tracing、编排服务，以及进程内 A2A worker。
    这些单例对象统一挂到 ``app.state`` 上，让路由函数只处理传输层逻辑。
    """
    init_storage()  #! 建表
    setup_tracer()  #! 初始化 Tracing 导出器，由配置决定导出至 console 还是 OTLP

    orchestrator_service = OrchestratorService()    #! 装配能力网关和编排引擎
    a2a_runtime = A2ARuntime(orchestrator_service)  #! 装配异步任务运行时
    a2a_runtime.start()  #! 启动 worker 线程，持续从 Redis 拉取任务并处理，异步

    app.state.orchestrator_service = orchestrator_service
    app.state.a2a_runtime = a2a_runtime
    app.state.audit_service = AuditService()          #! 把结构化审计记录写入 Postgres
    app.state.rate_limit_service = RateLimitService() #! 用粗粒度的租户级限流保护 API 调用
    app.state.metrics_service = MetricsService()      #! 运行时计数存放至 redis
    app.state.health_service = HealthService()        #! 校验 Redis 与 Postgres 的可达性

    yield
    a2a_runtime.stop()


"""把生命周期挂载到应用, 告诉FastAPI: 用上面这套生命周期逻辑管理应用"""
app = FastAPI(title="Enterprise Agent API", version="2.0.0", lifespan=lifespan)
#! 基于 contextvars 库将``trace_id`` 和 ``actor`` 绑定到上下文变量，供下游使用，以及 opentelemetry 观测
#! govermance/tracing.py, 治理, 基于 opentelemetry 的信息采集工具
"""
#**中间件关系：追踪中间件+治理中间件
#**FastAPI中间件的执行顺序：LIFO，即当前程序执行顺序为：对于 stream chat
时间线：
t=0ms   客户端发起请求
t=1ms   governance_middleware 前置执行
t=2ms   trace_context_middleware 前置执行
t=3ms   chat_stream 路由函数执行
        - 创建 generator
        - 返回 StreamingResponse
t=4ms   trace_context_middleware 后置执行
t=5ms   governance_middleware 后置执行
        - 记录延迟 5ms
        - dec inflight_requests
        - 审计日志记录 SUCCESS
t=5ms   响应头返回给客户端
t=6ms   开始发送第一个 chunk (SSE 格式)

trace_context_middleware: 追踪中间件，从请求头提取 trace/span，或生成 trace id，放入上下文
governance_middleware: 治理中间件，白名单放行、限流、统计、审计日志、inflight计数
"""
app.middleware("http")(trace_context_middleware)


@app.middleware("http")
async def governance_middleware(request: Request, call_next):
    """为业务接口统一套上限流、审计和指标采集逻辑。"""
    if request.url.path in {"/healthz", "/v1/metrics", "/metrics"}:
        return await call_next(request) #! 健康和指标端点直接放行

    actor = request.headers.get("x-api-key", "anonymous")
    trace_id = current_trace_id()
    start = time.time()

    rate_limit_service: RateLimitService = app.state.rate_limit_service
    metrics_service: MetricsService = app.state.metrics_service
    audit_service: AuditService = app.state.audit_service

    rate_limit_service.check(actor)           #! 限流
    metrics_service.incr("requests_total")    #! 运行时计数，以便于限流统计?
    inflight_requests.inc()   #! 指标：活跃数统计

    try:
        response = await call_next(request)   #! 进入 trace_context_middleware 的前置
        latency_ms = int((time.time() - start) * 1000)
        metrics_service.incr("requests_success")
        api_requests_total.labels(method=request.method, path=request.url.path, status="success").inc()
        api_request_latency_ms.labels(method=request.method, path=request.url.path).observe(latency_ms)
        audit_service.log(
            event_type="api_request",
            actor=actor,
            trace_id=trace_id,
            target=f"{request.method} {request.url.path}",
            payload={"query": dict(request.query_params)},
            status="SUCCESS",
            latency_ms=latency_ms,
        )
        return response
    except Exception as exc:
        latency_ms = int((time.time() - start) * 1000)
        metrics_service.incr("requests_failed")
        api_requests_total.labels(method=request.method, path=request.url.path, status="failed").inc()
        api_request_latency_ms.labels(method=request.method, path=request.url.path).observe(latency_ms)
        audit_service.log(
            event_type="api_request",
            actor=actor,
            trace_id=trace_id,
            target=f"{request.method} {request.url.path}",
            payload={"query": dict(request.query_params)},
            status="FAILED",
            error=str(exc),
            latency_ms=latency_ms,
        )
        raise
    finally: #! 无论成功失败都执行，保证 inflight 计数不会只增不减
        inflight_requests.dec()


@app.get("/healthz")
def healthz(deep: bool = False):
    """返回浅层存活检查结果，或执行深度依赖健康检查。"""
    if not deep:
        return {"status": "ok"}

    health_service: HealthService = app.state.health_service
    result = health_service.check()
    if result["status"] != "ok":
        raise HTTPException(status_code=503, detail=result)
    return result


@app.get("/v1/metrics")
def metrics_snapshot():
    """返回基于 Redis 的轻量级运行时计数快照。"""
    metrics_service: MetricsService = app.state.metrics_service
    return metrics_service.get_snapshot()


@app.get("/metrics")
def prometheus_metrics():
    """以 Prometheus 文本格式暴露指标，供抓取系统读取。"""
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)


@app.post("/v1/chat/stream")
def chat_stream(req: ChatStreamRequest):
    """执行一次同步编排流程，并以流式方式返回最终文本。"""
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    generator = orchestrator_service.stream_chat(
        message=req.message,
        session_id=req.session_id,
        trace_id=req.trace_id or current_trace_id(),
    )
    #! 对同步生成器使用 iterate_in_threadpool
    return StreamingResponse(generator, media_type="text/plain; charset=utf-8")


@app.post("/v1/tasks")
def create_task(req: TaskCreateRequest):
    """向 A2A 队列提交一个异步任务。"""
    a2a_runtime: A2ARuntime = app.state.a2a_runtime
    return a2a_runtime.submit_task(
        goal=req.goal,
        constraints=req.constraints,
        context_ref=req.context_ref,
        input_data=req.input,
        trace_id=req.trace_id or current_trace_id(),
    )


@app.get("/v1/tasks/{task_id}")
def get_task(task_id: str):
    """返回异步任务当前的持久化状态。"""
    a2a_runtime: A2ARuntime = app.state.a2a_runtime
    task = a2a_runtime.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@app.get("/v1/skills")
def list_skills():
    """列出注册表中的技能信息及其启用状态。"""
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    return orchestrator_service.list_skills()


@app.patch("/v1/skills/{skill_id}")
def patch_skill(skill_id: str, req: SkillPatchRequest):
    """启用或禁用技能，并刷新内存中的能力目录。"""
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    ok = orchestrator_service.set_skill_enabled(skill_id, req.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="skill not found")
    return {"skill_id": skill_id, "enabled": req.enabled}


@app.get("/v1/capabilities")
def list_capabilities():
    """返回编排器当前可见的扁平化能力目录。"""
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    return orchestrator_service.list_capabilities()
