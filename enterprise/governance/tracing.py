from __future__ import annotations

import time
import uuid
from contextvars import ContextVar  #! 上下文变量管理

"""
OpenTelemetry（OTel） 是一个统一的可观测性标准和工具集，用来收集三类数据：
    - Traces（链路追踪）
    - Metrics（指标）
    - Logs（日志）
把系统运行信息采集 → 统一格式 → 发到监控/分析系统
整体架构
OpenTelemetry SDK    #! sdk 采集数据
   ↓
Exporter（OTLP / Console / Jaeger 等） #! Exporter 导出数据
   ↓
OTel Collector（可选）  #! Collector 中转/处理
   ↓
后端（Jaeger / Prometheus / Grafana / Tempo 等）

! 核心概念
1. Trace & Span（链路）
    一个请求 = 一个 Trace
    一个步骤 = 一个 Span
    Trace
    ├── Span A（HTTP请求）
    ├── Span B（数据库查询）
    └── Span C（调用下游服务）
2. Context（上下文）
    用于在不同服务之间传递 trace 信息: trace_id   span_id
3. Exporter（导出器）
    OTLP Exporter（最常用）   OpenTelemetry 的标准协议，支持 gRPC（4317）   HTTP（4318）
    ConsoleSpanExporter（调试）
    ...

自动埋点：
pip install opentelemetry-instrumentation
opentelemetry-instrument python app.py
"""

from opentelemetry import trace     #! 可观测性框架，生成、收集和导出遥测数据
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from fastapi import Request
from utils.config_handler import enterprise_conf

TRACE_ID_CTX: ContextVar[str] = ContextVar("trace_id", default="")
ACTOR_CTX: ContextVar[str] = ContextVar("actor", default="anonymous")


def setup_tracer() -> None:
    """根据 ``enterprise.yml`` 配置初始化 Tracing 导出器。"""
    provider = TracerProvider()
    ob_conf = enterprise_conf.get("observability", {})

    if bool(ob_conf.get("enable_console_tracing", True)):
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    if bool(ob_conf.get("enable_otlp", False)):
        endpoint = str(ob_conf.get("otlp_endpoint", "")).strip()
        if endpoint:
            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                insecure=bool(ob_conf.get("otlp_insecure", True)),
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)   #! 设置 provider，指定 Exporter（导出器）


def current_trace_id() -> str:
    """返回当前 trace_id；如果没有则延迟生成一个。"""
    trace_id = TRACE_ID_CTX.get()
    if trace_id:
        return trace_id
    return str(uuid.uuid4())


def current_actor() -> str:
    """返回当前请求上下文中的调用方标识。"""
    return ACTOR_CTX.get() or "anonymous"


async def trace_context_middleware(request: Request, call_next):
    """把 ``trace_id`` 和 ``actor`` 绑定到上下文变量，供下游使用。"""
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    actor = request.headers.get("x-api-key") or "anonymous"

    token_trace = TRACE_ID_CTX.set(trace_id)
    token_actor = ACTOR_CTX.set(actor)

    tracer = trace.get_tracer("enterprise-agent")
    start = time.time()
    #! 生成 span
    with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
        span.set_attribute("trace_id", trace_id)
        span.set_attribute("actor", actor)
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)
        span.set_attribute("latency_ms", duration_ms)

    response.headers["x-trace-id"] = trace_id

    TRACE_ID_CTX.reset(token_trace)
    ACTOR_CTX.reset(token_actor)
    return response
