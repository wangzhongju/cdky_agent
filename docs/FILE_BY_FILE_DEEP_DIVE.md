# 逐文件精读版

## 1. 阅读方法

这份文档不是简单列目录，而是按“调用会经过哪里”来逐文件拆解。建议你一边打开源码，一边对照这里的说明往下追。

推荐的跟读顺序仍然是：

1. API 入口
2. 编排服务
3. 编排引擎
4. 能力网关
5. 内置能力
6. 异步任务
7. 治理与存储
8. RAG 与配置

## 2. `enterprise/api/app.py`

### 文件职责

这是整个系统的 HTTP 入口，也是进程启动时各类服务装配的位置。

### 你要先看什么

1. `lifespan(app)`
2. `governance_middleware()`
3. `chat_stream()`
4. `create_task()`
5. `get_task()`

### 函数级调用说明

#### `lifespan(app)`

作用：
- 初始化数据库表
- 初始化 tracing
- 创建 `OrchestratorService`
- 创建 `A2ARuntime`
- 启动 A2A 后台线程
- 把这些服务挂到 `app.state`

调用链：
- `init_storage()` -> 建表
- `setup_tracer()` -> 初始化 tracing
- `OrchestratorService()` -> 装配能力网关和编排引擎
- `A2ARuntime(orchestrator_service)` -> 装配异步任务运行时
- `a2a_runtime.start()` -> 启动 worker 线程

#### `governance_middleware(request, call_next)`

作用：
- 提取 `x-api-key`
- 执行限流
- 记录请求成功/失败指标
- 写审计日志

调用链：
- `RateLimitService.check(actor)`
- `MetricsService.incr(...)`
- `AuditService.log(...)`
- `call_next(request)` -> 继续进入真正路由

#### `chat_stream(req)`

作用：
- 从请求体里取 `message/session_id/trace_id`
- 调用 `OrchestratorService.stream_chat()`
- 用 `StreamingResponse` 把结果输出

调用链：
- `app.state.orchestrator_service.stream_chat(...)`

#### `create_task(req)`

作用：
- 接收异步任务请求
- 交给 `A2ARuntime.submit_task()`

调用链：
- `app.state.a2a_runtime.submit_task(...)`

#### `get_task(task_id)`

作用：
- 查询异步任务状态
- 若不存在则返回 404

调用链：
- `app.state.a2a_runtime.get_task(task_id)`

## 3. `enterprise/orchestrator/service.py`

### 文件职责

它是 API 层与 LangGraph 引擎之间的门面。API 不直接操作图对象，而是统一通过这个服务。

### 重点函数

#### `chat(message, session_id, trace_id)`

作用：
- 补齐 `session_id`
- 补齐 `trace_id`
- 调用 `engine.run(...)`
- 重新整理输出结构

输出字段：
- `session_id`
- `trace_id`
- `response`
- `intent`
- `capability_results`
- `cost`

#### `stream_chat(...)`

作用：
- 先执行 `chat(...)`
- 再把 `response` 按字符 `yield`

注意：
- 这不是底层模型原生流
- 它只是把完整响应拆成字符流返回

#### `list_capabilities() / list_skills() / set_skill_enabled()`

作用：
- 完全透传给 `CapabilityGateway`

## 4. `enterprise/orchestrator/state.py`

### 文件职责

定义 LangGraph 中流转的状态字典结构。

### 关键字段

| 字段 | 含义 | 谁写入 |
|---|---|---|
| `query` | 用户原始问题 | `run()` |
| `session_id` | 会话标识 | `run()` |
| `trace_id` | 链路标识 | `run()` |
| `intent` | 粗粒度意图 | `intent_classifier()` |
| `planned_capabilities` | 能力执行计划 | `planner()` |
| `capability_results` | 每个能力的执行结果 | `executor()` |
| `response` | 汇总后的回答 | `reviewer()` / `responder()` |
| `report_context` | 报告链路上下文 | `_execute_report_flow()` |
| `cost` | 成本估算信息 | `responder()` |

## 5. `enterprise/orchestrator/engine.py`

### 文件职责

这是系统的编排核心。它使用 LangGraph 把请求组织成固定流水线。

### 图结构

固定节点顺序：

1. `IntentClassifier`
2. `Planner`
3. `CapabilityRouter`
4. `Executor`
5. `Reviewer`
6. `Responder`

### 函数级精读

#### `_build_graph()`

作用：
- 注册节点函数
- 定义固定边
- 返回图对象

#### `run(query, session_id, trace_id)`

作用：
- 组装初始 `OrchestratorState`
- 调用 `self.graph.invoke(state)`

这里是同步聊天链路进入 LangGraph 的唯一入口。

#### `intent_classifier(state)`

作用：
- 用关键词判断是否为报告类请求

当前规则：
- 命中 `报告/使用记录/月报/统计` -> `report`
- 否则 -> `chat`

#### `planner(state)`

作用：
- 根据 `intent` 生成 `planned_capabilities`

`report` 计划固定为：
1. `enterprise.get_user_id`
2. `enterprise.get_current_month`
3. `report.fill_context`
4. `enterprise.fetch_external_data`
5. `report.report_writer`

`chat` 计划：
- 若查询中包含“天气”，先加定位与天气
- 无论如何都会加 `knowledge.rag_summarize`

#### `capability_router(state)`

作用：
- 当前是占位节点
- 现在真正的路由决策已经在 `planner()` 内完成

为什么还保留：
- 以后可以在这里加租户策略、权限过滤、模型路由前检查等

#### `executor(state)`

作用：
- 根据 `intent` 分派到两条执行路径

调用链：
- `report` -> `_execute_report_flow()`
- `chat` -> `_execute_general_flow()`

#### `_execute_report_flow(state, plan)`

作用：
- 串行执行报告链路

执行顺序：
1. `get_user_id`
2. `get_current_month`
3. `fill_context`
4. `fetch_external_data`
5. `report_writer`

关键中间变量：
- `user_id`
- `month`
- `raw_data`
- `external_data`
- `report`

写回状态：
- `capability_results`
- `report_context`

#### `_execute_general_flow(state, plan)`

作用：
- 执行通用问答链路
- 能并行的先并行
- 依赖城市的天气查询延后执行

核心局部函数：
- `run_step(step)`：解析延迟参数并调用能力

并行策略：
- `gaode.get_weather` 会被放入 `deferred_weather`
- 其他步骤先放入线程池执行

#### `reviewer(state)`

作用：
- 把 `capability_results` 汇总成草稿回答

行为区别：
- 报告流：直接提取 `report.report_writer` 结果
- 聊天流：把 `rag_summarize` 与 `get_weather` 的输出拼起来

#### `responder(state)`

作用：
- 对聊天流草稿再做一轮模型润色
- 顺便记录成本

调用链：
- `ModelRouter.pick(...)`
- `chat_model.invoke(prompt)`
- `CostService.record(...)`

报告流不会走这一步。

## 6. `enterprise/capability/gateway.py`

### 文件职责

这是能力层的总入口。编排器只认识它，不直接认识某个 Skill 或某个 MCP 工具。

### 函数级精读

#### `__init__()`

装配：
- `SkillRuntime`
- `SkillRegistryService`
- `MCPAdapter`
- `AuditService`

然后立即执行 `_load_all()`。

#### `_load_all()`

作用：
- 发现所有 manifest
- 同步到注册表
- 过滤掉被禁用的技能
- 加载 entrypoint 并注册能力
- 最后再补上 MCP 能力

#### `_load_mcp_adapters()`

作用：
- 读取 `config/mcp.yml`
- 根据配置注册高德能力与企业数据能力

注意点：
- 注册后通过 `fqdn` 放入 `_capabilities`
- 如果同名，后注册的能力会覆盖先注册的能力

#### `resolve_capability(fqdn)`

作用：
- 从 `_capabilities` 字典中找具体能力
- 找不到直接抛错

#### `invoke_capability(fqdn, **kwargs)`

作用：
- 是所有能力调用的统一入口

统一做的事情：
- 取 `trace_id`
- 取 `actor`
- 调用真正 handler
- 写审计
- 记 Prometheus 指标
- 出错时返回错误字符串

这是全工程最关键的能力调用点之一。

## 7. `enterprise/capability/builtin_skills.py`

### 文件职责

把遗留工具封装成企业版运行时可识别的 `Capability` 对象。

### 重点函数

#### `_invoke_tool(tool_obj, payload)`

作用：
- 统一调用 LangChain Tool 对象的 `.invoke(...)`

#### `register_rag_capability()`

注册：
- `knowledge.rag_summarize`

#### `register_weather_capabilities()`

注册：
- `gaode.get_weather`
- `gaode.get_user_location`

#### `register_report_capabilities()`

注册：
- `enterprise.get_user_id`
- `enterprise.get_current_month`
- `enterprise.fetch_external_data`
- `report.fill_context`
- `report.report_writer`

#### `report_writer(query, external_data)`

作用：
- 最终报告生成器

流程：
1. 读取报告提示词
2. 规范化 `external_data`
3. 构造最终 prompt
4. 调用 `chat_model`
5. 若结果异常或含工具调用痕迹，则使用 fallback 报告模板

#### `latest_available_month()`

作用：
- 从 `data/external/records.csv` 中寻找最新可用月份

为什么重要：
- 避免当前自然月份没有数据时，报告链路直接失败

## 8. `enterprise/a2a/runtime.py`

### 文件职责

这是异步任务运行时。特点是“进程内 worker + Redis 队列 + Postgres 状态机”。

### 重点函数

#### `submit_task(...)`

作用：
- 生成 `A2ATaskPayload`
- 写入 Postgres
- 推送 Redis 队列
- 增加任务指标

#### `get_task(task_id)`

作用：
- 读取任务记录
- 把字符串化 JSON 字段转回对象

#### `_run_worker_loop()`

作用：
- 持续 `blpop` 队列
- 拿到 payload 后交给 `_process_task()`
- worker 自身异常时把原 payload 推到死信队列

#### `_process_task(task)`

作用：
- 推进状态机

状态变化：
1. `RUNNING`
2. `REVIEWING`
3. `COMPLETED`

失败时：
- 增加重试计数
- 未超上限则重新入队
- 超上限则进入 `FAILED` 与死信队列

## 9. `enterprise/governance/*.py`

### `rate_limit.py`

关注点：
- 每分钟桶
- 每日桶
- 都在 Redis 内递增
- 超过阈值直接抛 `HTTPException(429)`

### `audit.py`

关注点：
- 所有审计最终落到 `audit_events`
- API 调用、能力调用、A2A 任务都复用这里

### `metrics.py`

关注点：
- 只是轻量快照计数，不是 Prometheus 主指标实现
- `metrics:*` 都存在 Redis

### `tracing.py`

关注点：
- 用 `ContextVar` 传递 `trace_id` 与 `actor`
- `trace_context_middleware()` 是请求上下文的入口

### `cost.py`

关注点：
- 用字符长度近似 token 数
- 把估算结果同时落库和写指标

### `model_router.py`

关注点：
- 根据策略选择 `qwen3-max` 或 `qwen-plus`
- 决策维度是 `policy + intent + query长度`

## 10. `enterprise/storage/*.py`

### `models.py`

这是理解数据落表最关键的文件。

你要重点记住四张表：

1. `skill_registry`
2. `a2a_tasks`
3. `audit_events`
4. `cost_records`

### `task_repository.py`

这是任务状态机写库的实际执行点。

关注函数：
- `create_task()`
- `update_status()`
- `increment_retry()`

### `skill_repository.py`

这是技能注册表写库的实际执行点。

关注函数：
- `upsert()`
- `list_skills()`
- `set_enabled()`

### `db.py`

这里只做两件事：
- 读取数据库连接
- 暴露 `ENGINE` 与 `SessionLocal`

### `redis_client.py`

这里只做一件事：
- 根据配置创建 Redis 客户端

## 11. `rag/rag_service.py`

### 文件职责

实现“检索后总结”的 RAG 入口。

### 重点函数

#### `__init__()`

装配：
- `VectorStoreService`
- retriever
- 提示词模板
- 聊天模型
- chain

#### `_init_chain()`

链路：
- `PromptTemplate`
- `print_prompt`
- `chat_model`
- `StrOutputParser`

#### `retriever_docs(query)`

作用：
- 真正执行检索

#### `rag_summarize(query)`

作用：
- 拿到文档
- 拼接上下文
- 把 `input/context` 一起交给模型

## 12. `rag/vector_store.py`

### 文件职责

负责维护 Chroma 向量库，以及知识文件的装载过程。

### 重点函数

#### `__init__()`

装配：
- `Chroma`
- `RecursiveCharacterTextSplitter`

#### `get_retriever()`

作用：
- 返回一个按 `k` 检索的 retriever

#### `load_document()`

作用：
- 扫描知识目录
- 计算文件 md5
- 过滤已处理文件
- 读取文件
- 文本分片
- 写入向量库
- 记录 md5

这就是“知识文件如何进入向量库”的主入口。

## 13. `model/factory.py`

### 文件职责

统一创建聊天模型与嵌入模型。

### 重点点

1. `ChatModelFactory` 负责 `ChatTongyi`
2. `EmbeddingsFactory` 负责 `DashScopeEmbeddings`
3. 文件底部直接初始化 `chat_model/embed_model`

这意味着：
- 下游模块只要 `import chat_model` 就能直接用
- 模型实例是模块级单例

## 14. `utils/config_handler.py`

### 文件职责

这是全工程配置的真正入口。

### 重点函数

#### `load_dotenv()`

作用：
- 尝试读取 `.env`
- 尝试读取 `docker/.env`

#### `load_*_config()`

作用：
- 分别读取不同 YAML

#### `_resolve_env_placeholders(value)`

作用：
- 把 `${ENV_NAME}` 解析成环境变量值

#### `apply_env_overrides(config)`

作用：
- 在 YAML 基础上再做少量环境变量覆盖

### 文件底部的意义

模块导入时会直接加载：
- `rag_conf`
- `chroma_conf`
- `prompts_conf`
- `agent_conf`
- `enterprise_conf`
- `mcp_conf`

所以这个文件一旦被 import，配置就已经完成初始化。

## 15. 最后怎么把这些文件串起来

你可以用下面这条主链做脑内地图：

1. `enterprise/api/app.py` 接住请求
2. `enterprise/orchestrator/service.py` 把请求送进编排器
3. `enterprise/orchestrator/engine.py` 生成计划并执行
4. `enterprise/capability/gateway.py` 找到具体能力并调用
5. `enterprise/capability/builtin_skills.py` 或 `MCPAdapter` 执行真实能力
6. `enterprise/governance/*.py` 负责治理与观测
7. `enterprise/storage/*.py` 负责状态、审计、成本落库
8. `rag/*.py` 负责知识检索与向量库

如果你把这八步彻底走通，这个工程就已经掌握到很深的层次了。
