from __future__ import annotations

"""
演示：OpenTelemetry 的常见用法（初始化 Tracer、创建 Span、打属性）。

对照工程：
- enterprise/governance/tracing.py -> setup_tracer / trace_context_middleware
"""

import os
import time
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def setup_tracer() -> None:
    """
    1. 配置 TracerProvider
    2. 添加 Console 导出器
    3. 如果配置了 OTLP endpoint，则再添加 OTLP 导出器
    """
    provider = TracerProvider()

    # 本地调试最直观：直接把 span 打印到控制台
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    otlp_endpoint = os.getenv("DEMO_OTLP_ENDPOINT", "").strip()
    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    trace.set_tracer_provider(provider)


def do_business(actor: str, trace_id: str) -> None:
    tracer = trace.get_tracer("library-playground")

    # 顶层 Span，模拟一次 HTTP 请求
    with tracer.start_as_current_span("POST /demo") as span:
        span.set_attribute("actor", actor)
        span.set_attribute("trace_id", trace_id)

        # 子 Span，模拟业务逻辑
        with tracer.start_as_current_span("orchestrator.run") as child:
            child.set_attribute("intent", "chat")
            time.sleep(0.05)

        # 子 Span，模拟外部能力调用
        with tracer.start_as_current_span("capability.invoke") as child:
            child.set_attribute("capability", "knowledge.rag_summarize")
            time.sleep(0.03)


if __name__ == "__main__":
    setup_tracer()
    do_business(actor="demo-user", trace_id="trace-demo-001")
    print("done")
