# 企业级智扫通 Agent

> 三层能力系统：Skills + MCP（能力层） / LangGraph（编排层） / A2A（协作层）

## 项目概览

当前项目已完成阶段一与阶段二升级，运行形态为 **API-first**：

- `enterprise.api` 提供统一入口与治理能力
- `app.py` 作为 Streamlit 客户端，通过 HTTP 调用 API
- `agent/react_agent.py` 保留为兼容适配器（同样走 API）

核心能力：

- 能力网关：统一管理本地 Skills 与 MCP 能力
- LangGraph 编排：意图识别、能力规划、执行、复核、响应
- A2A 任务协作：任务提交、队列消费、状态追踪、重试与死信
- 治理能力：限流配额、审计、成本估算、Tracing、Prometheus 指标

详细说明请查看：
- [企业级 Agent 详细介绍与使用流程](docs/AGENT_ENTERPRISE_GUIDE.md)
- [代码阅读指南与类图](docs/CODE_READING_GUIDE.md)
- [逐文件精读版](docs/FILE_BY_FILE_DEEP_DIVE.md)
- [字段级数据血缘图](docs/FIELD_DATA_LINEAGE.md)
- [库用法练习场](library_playground/README.md)

## 当前系统架构

```text
Client (Streamlit / API Caller)
    -> FastAPI (enterprise/api/app.py)
        -> Governance Middleware (rate-limit, audit, trace, metrics)
        -> Orchestrator Service (LangGraph)
            -> Capability Gateway
                -> Skill Runtime / Registry
                -> MCP Adapter (retry + timeout + circuit breaker)
            -> A2A Runtime (Redis queue + Postgres state)
```

## 目录说明（当前有效）

- `enterprise/`：企业级核心代码（推荐主入口）
- `config/enterprise.yml`：API、基础设施、治理、成本、观测配置
- `config/mcp.yml`：MCP server 映射与容错参数
- `docs/AGENT_ENTERPRISE_GUIDE.md`：详细介绍与操作流程
- `tests/test_api_contracts.py`：契约测试
- `tests/test_functional_api.py`：功能测试（健康检查、聊天、任务、指标）

## 对外接口

- `POST /v1/chat/stream`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/skills`
- `PATCH /v1/skills/{skill_id}`
- `GET /v1/capabilities`
- `GET /v1/metrics`（Redis 快照）
- `GET /metrics`（Prometheus）
- `GET /healthz?deep=true`

请求头：

- `x-api-key`：调用方标识（限流/配额）
- `x-trace-id`：链路追踪 ID（可选）

## 快速启动

### 1. 配置环境变量

复制并填写：

```bash
cp docker/.env.example docker/.env
```

最少需要：

```env
DASHSCOPE_API_KEY=your_dashscope_api_key
GAODE_MCP_KEY=your_gaode_key
DATABASE_URL=postgresql+psycopg://agent:agent@postgres:5432/agent
REDIS_URL=redis://redis:6379/0
```

可选 OTLP：

```env
OTLP_ENDPOINT=http://otel-collector:4317
```

### 2. 启动（UI + API + Redis + Postgres）

```bash
docker compose -f docker/docker-compose-dev.yaml up -d --build
```

### 3. 验证

```bash
curl "http://127.0.0.1:8000/healthz?deep=true"
curl "http://127.0.0.1:8000/metrics"
```

UI 访问：

- `http://127.0.0.1:8501`

## 测试

容器内执行完整测试：

```bash
docker exec -w /app -e PYTHONPATH=/app cdky-agent-api \
  pytest -q tests/test_api_contracts.py tests/test_functional_api.py
```

## 备注

- 旧单体 ReAct 架构文档与流程已淘汰，以 `enterprise/` 实现为准。
- 运行时生成内容（日志、向量库、测试缓存）不应纳入仓库版本管理。
