# `cdky_agent` 基于 OpenHarness 风格的重构方案

## Summary
- 在远程仓库 `/home/cdky/workspace/github/cdky_agent` 内完成重构；所有安装、启动、测试都只通过 `docker/docker-compose-dev.yaml` 的容器执行，不改主机系统环境。
- 参考骨架对齐 [OpenHarness](https://github.com/HKUDS/OpenHarness/tree/main) 的 `engine / tools / skills / memory / permissions / hooks` 设计，以及其 [query loop](https://github.com/HKUDS/OpenHarness/blob/main/src/openharness/engine/query.py) 和 [tools base](https://github.com/HKUDS/OpenHarness/blob/main/src/openharness/tools/base.py) 的抽象方式；不实现 `plugins` 子系统。
- 新建顶层 `harness/` 作为核心运行时，`enterprise/` 只保留 API、治理、A2A、存储外壳；旧 `agent.tools`、`rag`、旧编排链路在新链路稳定后全部移除。

## Implementation Changes
- 新建 `harness/engine`，实现 OpenHarness 风格的 `QueryEngine`、消息块模型、事件模型、`run_query` 循环、使用量聚合器；废弃当前 LangGraph 主图作为交互主链路，`enterprise.orchestrator.service` 改为对 `QueryEngine` 的薄封装。
- 新建 `harness/providers`，定义统一模型客户端接口；首个实现为 DashScope/Qwen 客户端，支持流式文本、工具调用、使用量回传、指数退避重试。重试策略固定为：最多 3 次重试、基础延迟 1s、指数退避、带抖动、对 429/5xx/网络异常生效。Provider 行为以官方 [DashScope Qwen API 文档](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-dashscope) 为准。
- 工具循环固定为：用户消息入库 -> 组装上下文 -> 调用模型流 -> 若返回工具调用则进入权限检查/钩子 -> 单工具串行执行，多工具 `asyncio.gather` 并行执行 -> 工具结果作为消息块回灌 -> 继续下一轮，直到无工具调用或达到 `max_turns`。
- 新建 `harness/tools`，采用 `BaseTool + Pydantic input model + ToolRegistry + ToolExecutionContext + ToolResult` 抽象。第一阶段核心工具集固定为：`read_file`、`glob_search`、`grep_search`、`shell_command`、`http_fetch`、`knowledge_search`、`fetch_external_report_data`、`gaode_get_weather`、`gaode_get_location`。
- `shell_command` 只允许在容器内当前工作区执行；配合权限模式与命令/path 规则控制。文件写工具本阶段不单独实现，审批链路先由 `shell_command` 覆盖。
- 高德天气与定位不复用旧 `agent.tools` 代码，改为 `harness/tools/gaode.py` 的新实现；保留 `config/mcp.yml` 的服务配置语义，但实际工具注册走新 `ToolRegistry`。
- 新建 `harness/knowledge`，负责文档切片、向量索引、检索与结果格式化；继续使用 Chroma 数据目录，但不复用旧 `rag/` 包。`knowledge_search` 是新工具，不再通过旧 `rag_service.py`。
- 新建 `harness/skills`，改为 Markdown 技能体系，文件放在 `skills/` 下，使用 YAML frontmatter 保存 `id/name/description/tags/triggers/enabled/allowed_tools`。启动时只加载元数据，实际内容按需注入。
- 技能选择器在每次请求前按 `triggers/tags/关键词` 选出 0-N 个候选技能，只把命中的技能正文拼入系统上下文。报告生成改写为一个 Markdown skill，固定依赖 `fetch_external_report_data`，不再保留旧 `report_writer` 能力实现。
- 新建 `harness/context` 与 `harness/memory`。上下文组装顺序固定为：系统提示词 -> 治理/权限规则摘要 -> 选中的技能 -> 会话摘要 -> 命中的长期记忆 -> 最近 N 轮原始消息。
- 自动压缩策略固定为：每次模型调用前估算 token；超阈值时先清理陈旧工具结果正文，再对更早轮次做摘要压缩，只保留最近 N 轮原文。摘要结果持久化到数据库，并在后续会话继续使用。
- 持久化记忆固定落 Postgres。每轮完成后运行轻量 memory extractor，把“用户偏好、用户标识、设备/报告相关长期事实”提取为 memory entry，按内容 hash 去重，并按 query 相关性回注。
- 治理沿用当前 `rate limit / quota / audit / metrics / tracing / health / cost` 方案；在其上新增 `harness/permissions` 与 `harness/hooks`。权限模式固定为 `default / auto / plan`；支持 path 规则、命令 deny 规则、敏感路径硬拒绝。
- 新增 PreToolUse / PostToolUse 钩子，第一版只支持 `command` 与 `http` 两类 hook，配置放在 `config/hooks.yml`；钩子可阻断执行，结果进入审计日志。
- 交互审批固定流程为：`/v1/chat/stream` 发出 `approval_required` 事件并结束本次流 -> Streamlit 弹出审批对话框 -> 客户端调用审批接口 -> 客户端调用恢复接口继续未完成会话。
- A2A 任务复用同一 `QueryEngine`，但没有对话框时，遇到需要审批的工具默认直接拒绝并失败；不引入 `WAITING_APPROVAL` 中间态。

## Public APIs / Storage
- `POST /v1/chat/stream` 直接替换为 `application/x-ndjson` 结构化事件流，不再返回纯文本字节流。事件类型固定为：`assistant_delta`、`assistant_complete`、`tool_start`、`tool_result`、`retry`、`approval_required`、`approval_decision`、`usage`、`status`、`error`、`done`。
- 新增 `POST /v1/chat/resume`，按 `session_id` 继续一个被审批或中断的会话。
- 新增 `POST /v1/approvals/{approval_id}`，请求体固定为 `{ "decision": "approve" | "deny" }`。
- 新增 `GET /v1/sessions`、`GET /v1/sessions/{session_id}`、`GET /v1/sessions/{session_id}/messages`，用于历史会话与恢复。
- 保留 `POST /v1/tasks`、`GET /v1/tasks/{task_id}`、`GET /v1/skills`、`PATCH /v1/skills/{skill_id}`、`GET /v1/capabilities`、`GET /v1/metrics`、`GET /metrics`、`GET /healthz`。`POST /v1/tasks` 新增可选 `permission_mode` 字段，默认 `default`。
- Postgres 新增表固定为：`chat_sessions`、`chat_messages`、`chat_summaries`、`memory_entries`、`approval_requests`；复用并扩展现有 `cost_records`、`audit_events`、`a2a_tasks`。Redis 只保留队列、指标、短时状态，不再作为主存。
- `GET /v1/skills` 返回 Markdown skills 的元数据与启停状态；现有 `skill_registry` 表保留，但改存技能元信息而不是旧 manifest 结构。

## Test Plan
- 只在容器内执行：`docker compose -f docker/docker-compose-dev.yaml up -d --build` 后，在 `agent-api` 容器中跑 `pytest`；新增依赖只改仓库内 `requirements.txt`/Dockerfile。
- 单元测试覆盖：provider 重试与退避、并行工具执行、权限判定、hook 阻断、skill 元数据加载与按需注入、context compaction、memory extraction、token/cost 聚合。
- 集成测试覆盖：`/v1/chat/stream` NDJSON 契约、审批拒绝/批准/恢复链路、报告 skill 调用、知识检索工具、高德天气/定位工具、会话历史查询、A2A 任务在审批型工具上的拒绝失败、指标与审计落库。
- 功能测试覆盖：普通知识问答、报告生成、重连恢复、自动压缩后继续对话、成本累计、Prometheus 指标、深度健康检查。
- 清理验证固定包含一项：代码库中不再有运行时 import 指向旧 `agent.tools`、`rag`、旧 LangGraph 编排实现；相关目录与无用配置在切换完成后删除。

## Assumptions / Defaults
- 默认模型继续使用 Qwen via DashScope；这次只做单 provider 实现，但接口设计允许后续扩展其他 provider。
- 事件流格式默认选 `NDJSON`，不选 SSE。
- 技能是 Markdown 文件，知识检索仍走向量搜索工具；“技能”与“知识检索工具”是两层，不把整库知识直接塞进 prompt。
- `plugins`、TUI、通用多代理团队编排不纳入这次重构范围；当前 A2A 保留并接入新引擎。
