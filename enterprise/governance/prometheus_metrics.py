from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

"""
`prometheus_client` 是 Python 官方的 Prometheus 指标客户端库，用于在 Python 应用中定义和暴露监控指标。
Prometheus 通过拉取（Pull）方式从 `/metrics` 端点获取这些指标数据
解决的问题：
- 编排器的请求量和延迟
- 各能力的调用成功率
- LLM 调用次数和成本
- RAG 检索效率
- 系统资源使用情况
Counter只增不减   Histogram分布统计   Gauge可增可减
"""

#! API 请求总数：统计 API 调用量、按接口维度分析请求分布、计算错误率（与成功请求对比）
api_requests_total = Counter(
    "enterprise_api_requests_total",
    "Total API requests",
    ["method", "path", "status"],
)

#! API 请求延迟（毫秒级）：即统计延迟在 5ms、10ms、20ms... 以内的请求数量；监控 API 响应性能、计算 P50、P95、P99 延迟、发现性能瓶颈
#! 自动生成的子指标：1._count 总请求次数  2._sum 总延迟之和（用于计算平均延迟）  3._bucket{le="..."} 各延迟分桶的计数
api_request_latency_ms = Histogram(
    "enterprise_api_request_latency_ms",
    "API latency in milliseconds",
    ["method", "path"],
    buckets=(5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000),
)

#! A2A（Agent-to-Agent）任务生命周期计数：追踪异步任务的状态分布、监控任务成功率、发现任务积压或失败情况
a2a_tasks_total = Counter(
    "enterprise_a2a_tasks_total",
    "A2A task lifecycle counter",
    ["status"],
)

#! 能力调用计数: 统计各能力的调用频率、监控能力调用的成功率、发现频繁失败的能力
capability_invocations_total = Counter(
    "enterprise_capability_invocations_total",
    "Capability invocation counter",
    ["capability", "status"],
)

#! 模型调用预估成本总计：统计不同模型的费用消耗、成本核算和预算监控、优化模型选择策略
estimated_cost_total = Counter(
    "enterprise_estimated_cost_total",
    "Estimated model cost total",
    ["model_name"],
)

#! 正在处理中的 API 请求数（瞬时值）：监控系统实时负载、检测请求积压、自动扩缩容依据
inflight_requests = Gauge(
    "enterprise_inflight_requests",
    "In-flight API requests",
)

#TODO: 告警规则？

def metrics_payload() -> tuple[bytes, str]:
    """把已注册的 Prometheus 指标渲染成可抓取文本格式。"""
    return generate_latest(), CONTENT_TYPE_LATEST
