# 企业级 Agent 工程

当前工程已经重构为会话型 Agent 系统，并使用独立 Next.js Web 前端承载 ChatGPT 风格交互。后端保留 `FastAPI + Postgres + Redis + Docker`，核心运行链路集中在 `enterprise/` 下。

```text
Next.js Web
  -> FastAPI v2 API
    -> Governance Middleware
    -> SessionService
      -> QueryEngine
        -> DashScope OpenAI-Compatible Model Client
        -> Tool Registry
        -> Skills Selection / Lazy Loading
        -> Memory Recall / Session Summary
        -> Approval + Hooks
```

## 当前能力

- ChatGPT 风格 Web UI，支持用户档案、历史会话、流式对话和审批弹窗。
- `v2` 会话 API，支持会话创建、续聊、历史消息、用户过滤。
- 原生流式工具调用循环、并行工具执行和指数退避模型重试。
- Token 与成本追踪、审计、限流、Tracing 和 Prometheus 指标。
- Skills 按需加载，报告生成已改写为 `report` skill。
- 持久化记忆、会话摘要、上下文压缩和历史恢复。
- 工具前后钩子、权限检查、交互式审批恢复。
- 高德天气与定位工具、报告数据工具、文件/搜索/网页等基础工具。

## 主要接口

- `POST /v2/users`
- `GET /v2/users`
- `GET /v2/users/{user_id}`
- `PATCH /v2/users/{user_id}`
- `POST /v2/sessions`
- `GET /v2/sessions?user_id=...`
- `GET /v2/sessions/{session_id}`
- `GET /v2/sessions/{session_id}/messages`
- `POST /v2/sessions/{session_id}/messages/stream`
- `GET /v2/skills`
- `GET /v2/tools`
- `GET /v2/approvals?status=pending`
- `POST /v2/approvals/{approval_id}/decision`
- `GET /healthz?deep=true`
- `GET /v1/metrics`
- `GET /metrics`

## 启动

1. 准备环境变量

```powershell
Copy-Item docker/.env.example .env
```

2. 启动容器

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml up -d --build
```

3. 访问服务

- Web UI: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- API health: [http://127.0.0.1:8000/healthz?deep=true](http://127.0.0.1:8000/healthz?deep=true)

## 测试

后端测试在 API 容器内执行：

```powershell
docker exec cdky-agent-api sh -lc 'cd /app && PYTHONPATH=/app pytest -q'
```

前端测试和构建通过 Node 容器执行，不修改主机环境：

```powershell
docker run --rm -v D:\work\cdky_agent\frontend:/app -w /app node:20-alpine sh -lc "npm ci && npm test && npm run build"
```

开发栈 smoke：

```powershell
bash docker/docker.sh smoke
```

## 说明

- 旧 `agent.tools`、`rag`、`orchestrator`、`a2a`、`capability` 链路已下线。
- Streamlit 不再作为主入口，正式 UI 由 `frontend/` 下的 Next.js 应用提供。
- 当前主链路以 `enterprise/session/service.py`、`enterprise/engine/` 和 `enterprise/tools/` 为准。
