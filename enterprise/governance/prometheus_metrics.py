from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

api_requests_total = Counter(
    "enterprise_api_requests_total",
    "Total API requests",
    ["method", "path", "status"],
)

api_request_latency_ms = Histogram(
    "enterprise_api_request_latency_ms",
    "API latency in milliseconds",
    ["method", "path"],
    buckets=(5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000),
)

a2a_tasks_total = Counter(
    "enterprise_a2a_tasks_total",
    "A2A task lifecycle counter",
    ["status"],
)

capability_invocations_total = Counter(
    "enterprise_capability_invocations_total",
    "Capability invocation counter",
    ["capability", "status"],
)

estimated_cost_total = Counter(
    "enterprise_estimated_cost_total",
    "Estimated model cost total",
    ["model_name"],
)

inflight_requests = Gauge(
    "enterprise_inflight_requests",
    "In-flight API requests",
)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
