# 企业级 Agent 详细介绍与使用流程

## 1. 项目定位

该项目是一个面向企业场景的多能力智能体系统，目标是将传统单体 ReAct Agent 升级为：

- 能力层：Skills + MCP 统一能力管理
- 编排层：LangGraph 主图路由与策略控制
- 协作层：A2A 任务协议、队列、状态机与重试恢复

系统默认采用 API-first 架构，Streamlit 作为前端客户端调用 API。

## 2. 架构全景

请求主链路：

1. 用户请求进入 `POST /v1/chat/stream`
2. API 中间件完成限流、审计、trace 注入、指标采集
3. Orchestrator 按意图进入 LangGraph 主图
4. Capability Gateway 统一调度本地 Skill 与 MCP 能力
5. Reviewer/Responder 聚合结果并输出

异步任务链路：

1. `POST /v1/tasks` 提交任务
2. Redis 队列消费任务
3. A2A Runtime 执行 `PENDING -> RUNNING -> REVIEWING -> COMPLETED/FAILED`
4. 任务状态落库 Postgres，可通过 `GET /v1/tasks/{task_id}` 追踪

## 3. 核心能力说明

### 3.1 Skills

- manifest 驱动注册，支持启停、热重载、版本化
- 核心字段：`id,name,version,entrypoint,tool_schemas,required_permissions,dependencies,enabled`
- 接口：
  - `GET /v1/skills`
  - `PATCH /v1/skills/{skill_id}`

### 3.2 MCP

- 统一挂载到 `CapabilityGateway`
- 支持：超时、重试、熔断、降级
- 同名能力通过 `namespace.tool` 规避冲突
- 支持协议层热重载与状态查询：
  - `GET /v1/mcp/servers`
  - `POST /v1/mcp/reload`

### 3.3 LangGraph 编排

固定主图节点：

- `IntentClassifier -> Planner -> CapabilityRouter -> Executor -> Reviewer -> Responder`

报告场景强约束子流程：

- `get_user_id -> get_current_month -> fill_context -> fetch_external_data -> report_writer`

### 3.4 A2A 协议

协议字段：

- `task_id,parent_task_id,goal,constraints,context_ref,input,result,status,error,retry_count,trace_id,created_at,updated_at`

状态机：

- `PENDING -> RUNNING -> REVIEWING -> COMPLETED/FAILED`

## 4. 治理能力（阶段二）

### 4.1 可观测

- OpenTelemetry tracing（可选 OTLP 上报）
- Prometheus 指标导出：`GET /metrics`
- 运行态快照：`GET /v1/metrics`

### 4.2 审计

- API 调用审计
- Capability 调用审计
- A2A 任务审计
- 落库表：`audit_events`

### 4.3 成本与策略

- 模型路由策略：`balanced / cost_preferred / quality_preferred`
- 成本估算：按输入输出 token 比例与单价模型估算
- 落库表：`cost_records`

### 4.4 安全与配额

- `x-api-key` 作为租户/调用方标识
- 每分钟限流 + 每日配额
- `x-trace-id` 全链路透传

## 5. 快速启动流程

### 5.1 准备环境变量

在 `docker/.env` 中配置：

```bash
DASHSCOPE_API_KEY=your_dashscope_api_key
GAODE_MCP_KEY=your_gaode_key
DATABASE_URL=postgresql+psycopg://agent:agent@postgres:5432/agent
REDIS_URL=redis://redis:6379/0
```

可选 OTLP：

```bash
OTLP_ENDPOINT=http://otel-collector:4317
```

并在 `config/enterprise.yml` 开启：

```yaml
observability:
  enable_otlp: true
  otlp_endpoint: ${OTLP_ENDPOINT}
  otlp_insecure: true
```

### 5.2 启动

```bash
docker compose -f docker/docker-compose-dev.yaml up -d --build
```

### 5.3 健康检查

```bash
curl "http://127.0.0.1:8000/healthz?deep=true"
```

### 5.4 调用示例

流式聊天：

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/chat/stream" \
  -H "Content-Type: application/json" \
  -H "x-api-key: demo-tenant" \
  -H "x-trace-id: trace-demo-001" \
  -d '{"message":"请给我一份扫地机器人保养建议"}'
```

提交任务：

```bash
curl -X POST "http://127.0.0.1:8000/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "x-api-key: demo-tenant" \
  -d '{"goal":"给我生成我的使用报告","constraints":{},"context_ref":{"session_id":"s1"},"input":{}}'
```

查询任务：

```bash
curl "http://127.0.0.1:8000/v1/tasks/<task_id>" -H "x-api-key: demo-tenant"
```

查看 Prometheus 指标：

```bash
curl "http://127.0.0.1:8000/metrics"
```

## 6. 完整测试流程

容器内执行：

```bash
docker exec -w /app -e PYTHONPATH=/app cdky-agent-api \
  pytest -q tests/test_api_contracts.py tests/test_functional_api.py
```

预期：全部通过。

## 7. 常见排查

1. `/healthz?deep=true` 返回 503
- 先检查 `postgres/redis` 容器是否 `Up`
- 再检查 `DATABASE_URL/REDIS_URL` 是否正确

2. `429 rate limit exceeded`
- 提升 `config/enterprise.yml` 中限流阈值
- 或更换调用方 `x-api-key`

3. `OTLP 无上报`
- 确认 `enable_otlp=true`
- 确认 `OTLP_ENDPOINT` 可达且端口正确

## 8. 生产化建议

- 对 `x-api-key` 接入真实鉴权（JWT/API Gateway）
- 将 `/metrics` 纳入 Prometheus 抓取并配置告警
- 将 trace 输出到集中式 APM（Jaeger/Tempo/OTel Collector）
- 按租户做成本预算和配额告警
