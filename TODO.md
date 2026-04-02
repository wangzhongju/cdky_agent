## 企业级 Agent 升级方案（两阶段，API 优先，生产基础设施）

### Summary

基于 update_agent.md，将现有单体 ReAct 升级为三层系统并按两阶段交付：

1. 阶段一交付可运行企业化 v1：能力层(Skills+MCP)、编排层(Planner+Router)、协作层(轻量A2A)。
2. 阶段二补齐企业治理：高可用、审计、成本与策略控制、运维观测完善。
   运行形态采用 API-first，现有 Streamlit 变为 API 客户端；状态与任务基础设施采用 Redis + Postgres。

### Implementation Changes

1. 系统分层重构（保持现有业务能力不丢）
   - 新建 orchestrator service 作为唯一入口，承接会话、路由、任务编排、流式输出。
   - 保留现有 RAG/天气/报告业务逻辑，但迁移为可注册能力，不再在 create_agent 手工硬编码。
   - 现有 D:/work/cdky_agent/agent/react_agent.py 收敛为编排适配层，不直接持有全部工具定义。
2. 能力层：Capability Gateway + Skill Runtime + MCP Adapter
   - 统一能力网关接口：list_capabilities / resolve_capability / invoke_capability。
   - Skill 采用 manifest 驱动，固定字段：id,name,version,entrypoint,tool_schemas,required_permissions,dependencies,enabled。
   - Skill Registry 落 Postgres，缓存到 Redis；支持 enable/disable、热重载、健康检查、版本回滚。
   - MCP Adapter 支持 server 发现与工具映射，统一命名 namespace.tool，统一超时/重试/熔断/降级策略。
   - 首批 MCP 接入：天气与企业记录查询；现有本地 weather/external_data 工具迁移为 capability 形态。
3. 编排层：LangGraph 主图 + 路由策略
   - 图节点固定为：IntentClassifier -> Planner -> CapabilityRouter -> Executor -> Reviewer -> Responder。
   - 报告场景走强约束子图：get_user_id -> get_current_month -> fill_context -> fetch_external_data -> report_writer，避免仅依赖 prompt 约束。
   - 普通客服场景允许多能力并行查询并聚合返回。
   - 会话状态、路由决策、工具调用 trace_id 全链路透传。
4. 协作层：轻量 A2A Runtime（阶段一）
   - 角色固定：planner-agent、worker-rag、worker-report、reviewer-agent。
   - A2A 协议固定字段：task_id,parent_task_id,goal,constraints,context_ref,input,result,status,error,retry_count,trace_id,created_at,updated_at。
   - 状态机固定：PENDING -> RUNNING -> REVIEWING -> COMPLETED/FAILED。
   - 任务队列使用 Redis（streams 或 list+ack 机制），失败重试与死信队列启用，任务幂等键为 task_id+goal_hash。
5. API-first 对外接口（阶段一定版）
   - POST /v1/chat/stream：流式对话入口，支持会话 ID 与 trace_id。
   - POST /v1/tasks：提交 A2A 任务。
   - GET /v1/tasks/{task_id}：查询任务状态与结果。
   - GET /v1/skills、PATCH /v1/skills/{skill_id}：技能列表与启停。
   - GET /v1/capabilities：统一能力视图（本地 skill + mcp）。
   - Streamlit 仅保留 UI 交互，改为调用上述 API，不再直接操作 Agent 内部对象（涉及 D:/work/cdky_agent/app.py）。
6. 企业治理（阶段二）
   - 可观测：OpenTelemetry + 结构化日志 + 指标（调用耗时、成功率、重试率、token/cost）。
   - 安全：能力白名单、密钥托管、最小权限、审计日志（谁在何时调用了什么能力）。
   - 策略：模型路由（成本优先/质量优先）、工具路由（主备切换）、限流与配额。
   - 高可用：多实例无状态化、Redis/Postgres 健康探针、关键链路熔断降级。

### Test Plan

1. 功能验收
   - 客服问答、报告生成、天气查询、企业记录查询均可通过统一 capability 网关调用成功。
   - 报告强约束流程必须按固定子图执行，缺步骤时返回可诊断错误。
   - A2A 任务可创建、可追踪、可重试、可恢复，最终状态一致。
2. 契约与兼容
   - Skill manifest、A2A 消息协议、API 请求响应均做 schema 校验测试。
   - 能力重命名规则 namespace.tool 冲突测试通过。
   - 旧 UI 路径通过 API 适配后保持业务可用。
3. 稳定性与安全
   - MCP 不可达、超时、返回异常时，触发重试/熔断/降级并有明确错误码。
   - Redis/Postgres 短暂故障可恢复，任务不丢失（至少一次投递 + 幂等去重）。
   - 敏感配置不落代码仓，审计日志可追溯到 trace_id。
4. **性能基线（阶段一）**
   - 单会话端到端 P95 延迟、能力调用成功率、任务完成率、重试率建立基线并纳入监控看板。

### Assumptions

- 本次不做“全量一次性交付”，按你选择采用“两阶段落地”。
- 运行形态最终以 API-first 为主，Streamlit 仅作为客户端保留。
- 生产基础设施默认启用 Redis + Postgres；不提供纯本地文件模式作为主路径。
- 首批上线能力范围固定为“客服 + 报告 + 运维”三类，其他行业能力后续增量接入。
- update_agent.md 中的三层能力架构与四个非功能点作为验收主基准（可观测性、权限模型、契约稳定、状态一致性）。









### 阶段一已完成

已按你的方案完成一次可运行的**阶段一企业化升级**（API-first + Skills/MCP + LangGraph 编排 + 轻量 A2A），并补了阶段二治理的落点骨架。

**核心落地**

- 新增 API 服务与生命周期启动（含任务 worker）
  enterprise/api/app.py
  api_server.py
- 新增三层架构实现
  能力层：
  enterprise/capability/gateway.py
  enterprise/capability/skills/runtime.py
  enterprise/capability/skills/registry.py
  enterprise/capability/mcp/adapter.py

  编排层（LangGraph 固定节点）：
  enterprise/orchestrator/engine.py
  enterprise/orchestrator/service.py

  协作层（A2A 协议 + Redis 队列 + 状态机）：
  enterprise/a2a/protocol.py
  enterprise/a2a/runtime.py

- 新增 Postgres/Redis 持久化
  enterprise/storage/models.py
  enterprise/storage/db.py
  enterprise/storage/task_repository.py
  enterprise/storage/skill_repository.py
- API 接口已实现
  POST /v1/chat/stream
  POST /v1/tasks
  GET /v1/tasks/{task_id}
  GET /v1/skills
  PATCH /v1/skills/{skill_id}
  GET /v1/capabilities
- Streamlit 已改为 API 客户端
  app.py
- 旧 ReactAgent 改为编排适配（走 API）
  agent/react_agent.py
- 配置与依赖补齐（enterprise/mcp、fastapi、redis、postgres、sqlalchemy）
  config/enterprise.yml
  config/mcp.yml
  utils/config_handler.py
  requirements.txt
- Docker 组合升级（UI + API + Redis + Postgres）
  docker/docker-compose-dev.yaml
  docker/.env
  docker/.env.example
- 阶段二治理路线骨架
  enterprise/ROADMAP.md

**顺手修复**

- fetch_external_data 返回统一字符串 JSON、CSV 解析改为 DictReader
  agent/tools/agent_tools.py
- get_current_month 改为真实当前月份
- Streamlit assistant 消息改为完整拼接，避免只存最后 chunk

**我没法在当前终端完成的验证**

- 当前环境没有可用 python / git 命令，无法实际执行 pytest、启动 API、或做 git 状态检查。
- 已补最小契约测试文件：
  tests/test_api_contracts.py

**建议你本地立即执行**

1. pip install -r requirements.txt
2. 启动 Redis/Postgres（或直接 docker compose -f docker/docker-compose-dev.yaml up --build）
3. 启动 API：python api_server.py
4. 再启动 UI：streamlit run app.py







### 阶段二已完成

- 可观测：OpenTelemetry trace 中间件、x-trace-id 透传、指标快照接口
  enterprise/governance/tracing.py
  enterprise/governance/metrics.py
  enterprise/api/app.py
- 审计：API/Capability/A2A 追加式审计落库
  enterprise/governance/audit.py
  enterprise/storage/models.py
- 策略路由与成本：模型路由（balanced/cost_preferred/quality_preferred）+ 成本估算落库
  enterprise/governance/model_router.py
  enterprise/governance/cost.py
  enterprise/orchestrator/engine.py
- 限流配额：按 x-api-key 的每分钟限流与日配额
  enterprise/governance/rate_limit.py
- 深度健康检查：/healthz?deep=true 检查 Redis/Postgres
  enterprise/governance/health.py
- 稳定性增强：能力调用审计/降级、A2A 指标与审计
  enterprise/capability/gateway.py
  enterprise/a2a/runtime.py

**配置与容器修复**

- 修复 docker compose 相对路径与构建上下文问题，增加深度健康探针。
  docker/docker-compose-dev.yaml
- 修复依赖冲突：requests==2.32.5。
  requirements.txt
- 新增治理配置项与价格表。
  config/enterprise.yml

**Docker 内完整测试结果**

- 启动：docker compose -f docker/docker-compose-dev.yaml up -d --build
- 执行测试：
  docker exec -w /app -e PYTHONPATH=/app cdky-agent-api pytest -q tests/test_api_contracts.py tests/test_functional_api.py
- 结果：9 passed in 3.35s

**新增测试**

- 契约测试：tests/test_api_contracts.py
- 功能测试（健康检查、能力列表、流式聊天、A2A任务生命周期、指标）：
  tests/test_functional_api.py

> TODO:  Prometheus 指标导出和 OTLP 上报（现在是 ConsoleSpanExporter)
>
> | 项目     | Prometheus 指标导出 | OTLP 上报               | ConsoleSpanExporter |
> | -------- | ------------------- | ----------------------- | ------------------- |
> | 数据类型 | Metrics             | Traces / Metrics / Logs | Traces / Spans      |
> | 方式     | Pull                | Push                    | 本地打印            |
> | 目标     | Prometheus          | OTel Collector / APM    | 控制台              |
> | 用途     | 监控指标            | 统一可观测性上报        | 本地调试            |
> | 生产可用 | 是                  | 是                      | 通常否              |
>
> ------
>
> 







### 阶段二 ---补充

包含 Prometheus 指标导出、OTLP 上报配置、完整容器内功能测试，以及详细介绍文档与使用流程。

**本次新增/完成**

- Prometheus 指标与导出
  - 指标定义与导出： prometheus_metrics.py
  - API 增加 GET /metrics： app.py
  - 请求延迟/成功失败/并发、A2A 状态、能力调用、成本均已打点
- OTLP 上报（可配置）
  - tracing 支持 Console + OTLP 双 exporter： tracing.py
  - 配置项新增： enterprise.yml
  - .env 示例新增 OTLP_ENDPOINT： docker/.env.example
- 治理能力联动增强
  - 成本统计接入 Prometheus： cost.py
  - Capability 调用成功/失败计数： gateway.py
  - A2A 生命周期计数： runtime.py
- 详细文档与使用流程
  - 新增完整企业级文档： AGENT_ENTERPRISE_GUIDE.md
  - README 补充 /metrics 与文档入口： README.md

**完整测试（Docker 容器内）**

- 执行命令：
  - docker exec -w /app -e PYTHONPATH=/app cdky-agent-api pytest -q tests/test_api_contracts.py tests/test_functional_api.py
- 结果：
  - 10 passed in 3.25s
- 额外验证 Prometheus：
  - /metrics 返回 200
  - 包含 enterprise_api_requests_total
  - 包含 enterprise_a2a_tasks_total

**你现在可直接用**

1. 启动：docker compose -f docker/docker-compose-dev.yaml up -d --build
2. 健康检查：GET /healthz?deep=true
3. 业务指标：GET /metrics
4. 运行态快照：GET /v1/metrics

> 把 Prometheus + Grafana + OTel Collector 也一起接进 docker-compose，给你一键可视化监控面板。







### 全盘检查

已完成全盘复查与清理，并按你的要求用**现有镜像**完成收尾测试（未重头构建）。

**已更新**

- 重写主文档为企业版现状（移除旧单体 ReAct 架构描述）：
  README.md
- 更新本地 Docker 运行文档为当前服务形态（API/UI/Redis/Postgres）：
  LOCAL_DOCKER_RUN.md
- 补充忽略规则，避免运行产物再次进入版本管理：
  .gitignore
- 增强日志初始化容错（避免挂载场景下日志文件创建失败导致启动失败）：
  logger_handler.py

**已删除冗余文件**

- update_agent.md
- 企业级Agent升级方案.md
- middleware.py（已无任何引用）
- 运行缓存与旧日志产物（.pytest_cache/、logs/*.log）已清理

**测试（不重建镜像）**

- 执行命令：
  docker exec -w /app -e PYTHONPATH=/app cdky-agent-api pytest -q tests/test_api_contracts.py tests/test_functional_api.py
- 结果：10 passed in 3.38s

**说明**

- chroma_db/chroma.sqlite3 当前保留为运行占位，避免容器挂载环境下 Chroma 初始化失败。
- 后续如你希望，我可以再做一轮“进一步瘦身”，把遗留兼容层（如 react_agent.py）也迁移为可选模块并默认关闭。







```shell
docker compose -f docker/docker-compose-dev.yaml up -d --force-recreate --no-deps agent-api agent-dev
```

