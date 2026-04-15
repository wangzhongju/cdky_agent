from __future__ import annotations

import time
import uuid
from contextvars import ContextVar

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExportResult
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from fastapi import Request
from utils.config_handler import enterprise_conf

TRACE_ID_CTX: ContextVar[str] = ContextVar("trace_id", default="")
ACTOR_CTX: ContextVar[str] = ContextVar("actor", default="anonymous")


class SafeConsoleSpanExporter(ConsoleSpanExporter):
    def export(self, spans):
        try:
            return super().export(spans)
        except ValueError:
            return SpanExportResult.FAILURE

    def shutdown(self):
        try:
            return super().shutdown()
        except ValueError:
            return None


def setup_tracer() -> None:
    provider = TracerProvider()
    ob_conf = enterprise_conf.get("observability", {})

    if bool(ob_conf.get("enable_console_tracing", True)):
        provider.add_span_processor(BatchSpanProcessor(SafeConsoleSpanExporter()))

    if bool(ob_conf.get("enable_otlp", False)):
        endpoint = str(ob_conf.get("otlp_endpoint", "")).strip()
        if endpoint:
            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                insecure=bool(ob_conf.get("otlp_insecure", True)),
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)


def current_trace_id() -> str:
    trace_id = TRACE_ID_CTX.get()
    if trace_id:
        return trace_id
    return str(uuid.uuid4())


def current_actor() -> str:
    return ACTOR_CTX.get() or "anonymous"


async def trace_context_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    actor = request.headers.get("x-api-key") or "anonymous"

    token_trace = TRACE_ID_CTX.set(trace_id)
    token_actor = ACTOR_CTX.set(actor)

    tracer = trace.get_tracer("enterprise-agent")
    start = time.time()
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
