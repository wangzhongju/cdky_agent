# Agent Enterprise Guide

## 架构概览

当前工程已经从旧 `ReAct + rag + agent.tools` 迁移为会话型 Agent 系统。主 UI 是独立的 Next.js Web 应用，后端以 FastAPI `v2` API 为统一入口，核心执行链路集中在 `enterprise/`。

```mermaid
flowchart LR
    UI["Next.js Web\n/frontend"] --> API["FastAPI API\n/enterprise/api/app.py"]
    API --> GOV["治理中间件\nrate_limit / audit / tracing / metrics"]
    GOV --> SESSION["SessionService\n/enterprise/session/service.py"]
    SESSION --> USERS["UserRepository\n/enterprise/storage/user_repository.py"]
    SESSION --> SKILL["SkillService\n/enterprise/skills/service.py"]
    SESSION --> MEMORY["MemoryService\n/enterprise/memory/service.py"]
    SESSION --> ENGINE["QueryEngine\n/enterprise/engine/query_engine.py"]

    ENGINE --> MODEL["DashScope OpenAI Client\n/enterprise/model/client.py"]
    ENGINE --> TOOLS["ToolRegistry + Core Tools\n/enterprise/tools"]
    ENGINE --> PERM["PermissionChecker\n/enterprise/permissions/checker.py"]
    ENGINE --> HOOKS["HooksExecutor\n/enterprise/hooks/executor.py"]
    ENGINE --> COST["CostTracker\n/enterprise/engine/cost_tracker.py"]

    SESSION --> STORE["Repositories\n/enterprise/storage"]
    MEMORY --> STORE
    SKILL --> STORE
    COST --> STORE

    TOOLS --> MCP["Gaode MCP-style Tools\nweather / location"]
    TOOLS --> BIZ["Report Data Tools\nusage report queries"]
    STORE --> DB["Postgres"]
    STORE --> REDIS["Redis"]
```

## 聊天与工具调用链路

```mermaid
sequenceDiagram
    participant U as 用户
    participant W as Next.js Web
    participant A as FastAPI
    participant G as 治理中间件
    participant SS as SessionService
    participant KS as SkillService
    participant MS as MemoryService
    participant QE as QueryEngine
    participant MC as ModelClient
    participant TR as ToolRegistry
    participant DB as Postgres/Redis

    U->>W: 输入消息
    W->>A: POST /v2/sessions/{id}/messages/stream
    A->>G: 限流 / 审计 / tracing / metrics
    G->>SS: 进入会话服务
    SS->>KS: 选择并懒加载 skills
    SS->>MS: 检索持久化记忆
    SS->>DB: 读取会话摘要与历史消息
    SS->>QE: 组装上下文并启动查询循环

    loop 直到模型停止调用工具
        QE->>MC: 流式请求模型
        MC-->>QE: 文本增量 / tool call / usage
        alt 需要工具
            QE->>TR: 执行一个或多个工具
            TR->>QE: tool result
        else 直接回答
            QE-->>SS: assistant 文本与 usage
        end
    end

    SS->>DB: 持久化消息 / 审批 / 记忆 / 成本
    SS-->>A: SSE 事件流
    A-->>W: assistant_text_delta / tool events / approval_required
    W-->>U: 渲染消息、状态和审批弹窗
```

## 审批挂起与恢复

```mermaid
sequenceDiagram
    participant QE as QueryEngine
    participant PC as PermissionChecker
    participant DB as PendingApprovalRepository
    participant API as FastAPI
    participant UI as Next.js Web

    QE->>PC: 检查 write_file / bash / edit_file
    PC-->>QE: 需要审批
    QE->>DB: 创建 pending approval
    QE-->>API: approval_required 事件
    API-->>UI: SSE 推送审批事件
    UI->>API: POST /v2/approvals/{id}/decision
    UI->>API: POST /v2/sessions/{id}/messages/stream {resume: true}
    API-->>QE: 恢复执行
    QE-->>UI: 返回工具结果和最终回复
```

## 模块职责

- `frontend/`：Next.js + React + TypeScript Web UI，支持用户、会话、流式聊天和审批弹窗。
- `enterprise/api`：提供 `/v2/users`、`/v2/sessions`、`/v2/tools`、`/v2/skills`、`/v2/approvals` 等接口。
- `enterprise/session`：管理用户会话、消息历史、摘要、审批恢复和标题生成。
- `enterprise/engine`：负责消息模型、SSE 事件、流式工具调用循环和成本累计。
- `enterprise/model`：封装 DashScope OpenAI 兼容模型调用、重试和 usage 捕获。
- `enterprise/tools`：提供文件、检索、网页、高德天气/定位、报告数据等工具。
- `enterprise/skills`：负责 skill manifest 索引、模型选择和 `SKILL.md` 懒加载。
- `enterprise/memory`：负责持久化记忆提取与检索。
- `enterprise/governance`：提供限流、审计、Tracing、Prometheus 指标和成本落库。
- `enterprise/storage`：提供 Postgres 与 Redis 仓储访问。

## 当前接口

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
- `GET /healthz`
- `GET /metrics`
- `GET /v1/metrics`

## Docker 验证

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml up -d --build
docker exec cdky-agent-api sh -lc 'cd /app && PYTHONPATH=/app pytest -q'
docker run --rm -v D:\work\cdky_agent\frontend:/app -w /app node:20-alpine sh -lc "npm ci && npm test && npm run build"
```
