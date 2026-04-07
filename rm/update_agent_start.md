

## 当前单体 ReAct Agent 升级成“三层能力系统”

1. **能力层（Skills + MCP）**：统一注册、发现、加载能力
2. **编排层（Planner + Router）**：决定“用哪个能力、何时并行、何时升级到 A2A”
3. **协作层（A2A Runtime）**：多 Agent 分工、会话共享、任务回传

下面是一个可落地的构建方案供参考。

------

**一、整体架构建议**

User -> Orchestrator Agent -> (Skill Runtime / MCP Client / A2A Coordinator) -> Tools/Services

- Orchestrator Agent：保留你现在的 ReAct 入口，但只负责“理解任务 + 调度”。
- Skill Runtime：管理本地技能包（可热加载、版本化、权限控制）。
- MCP Client Layer：统一连接外部 MCP Server，把远程能力映射成标准 Tool。
- A2A Coordinator：支持把复杂任务拆分给多个专职 Agent（报告、检索、诊断等）。

------

**二、Skills 能力加载设计**

把 skill 设计为“可安装插件”，而不是写死在 agent_tools.py：

- Skill Manifest（必需）
  - id/name/version
  - entrypoint
  - tool schemas（参数 JSON Schema）
  - required_permissions（network/fs/secrets）
  - dependencies
- Skill Runtime
  - 扫描 skills/ 目录并注册
  - 支持 enable/disable, lazy load, reload
  - 每个 skill 独立错误隔离（一个崩了不影响主 Agent）
- Skill Registry
  - 内存索引 + 持久化（sqlite）
  - 提供 list_skills, resolve_tool, health_check

你当前系统里，可先把 rag_summarize/get_weather/fetch_external_data 改成内建 skills，完成第一步抽象。

------

**三、MCP 能力接入设计**

目标：让 MCP Server 像本地 tool 一样被调度。

- MCP Adapter 层
  - 负责 discover tools/resources/prompts
  - 转换为 LangChain Tool（统一入参、出参、异常）
- 连接池与会话
  - 按 server 维护 client session（复用连接，减少握手开销）
  - 支持超时、重试、熔断、降级
- 能力路由
  - 同名工具冲突时，用 namespace.tool（如 gaode.get_weather）
- 安全
  - 每个 MCP server 单独 token
  - 白名单 + 最小权限 + 审计日志

建议增加一个 capability_gateway 模块：本地 skills 和 MCP tools 都挂在这里，给上层一个统一工具视图。

------

**四、A2A（Agent-to-Agent）可实现性方案**

A2A 关键不是“多开几个 Agent”，而是**协议和状态管理**：

- 角色划分
  - Planner Agent：拆任务，定义子任务输入/输出契约
  - Worker Agents：专职执行（RAG、报表、诊断、外呼）
  - Reviewer Agent：结果校验与合并
- 消息协议（必须结构化）
  - task_id, parent_task_id, goal, constraints, context_ref, result, status
  - 避免纯自然语言串话，降低幻觉和丢字段风险
- 共享上下文
  - 短期：Redis/内存 KV（任务态）
  - 长期：向量库/文档库（知识态）
- 调度模式
  - 串行：依赖强（先查用户ID再生成报告）
  - 并行：独立子任务（天气 + 设备日志 + RAG并行）
  - 仲裁：多个 worker 结果冲突时交由 reviewer
- 失败恢复
  - 幂等 task
  - checkpoint + retry + dead letter queue

你当前项目可以先实现“轻量 A2A”：一个主 Agent + 两个专职子 Agent（Report/RAG），先跑通任务协议。

------

**五、你这个项目的改造路径（推荐顺序）**

1. 先做 Capability Gateway
   - 把现有 tools 统一经 gateway 注册，不再在 create_agent 手工硬编码。
2. 再做 Skill Registry
   - 本地 skill manifest + 热加载，先不做远程分发。
3. 接入 MCP Adapter
   - 先接 1~2 个 MCP server（天气、企业内部数据），打通 discover + invoke。
4. 引入 A2A Coordinator
   - 先支持“主从两级”任务分发和结构化回传。
5. 最后补治理能力
   - 权限、审计、trace、成本统计、策略路由（模型/工具选择）。

------

**六、落地时最关键的 4 个非功能点**

1. **可观测性**：每次 tool/skill/mcp 调用都要有 trace_id。
2. **权限模型**：skill 与 mcp 都做最小权限。
3. **契约稳定**：所有工具严格 JSON Schema。
4. **状态一致性**：A2A 任务必须可重试、可恢复。