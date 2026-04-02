# 代码阅读总览

## 1. 阅读目标

这份文档用于帮助你从“系统整体”角度理解这个 Agent 工程。建议你带着下面四个问题去看代码：

1. 请求从哪里进入系统
2. 请求如何被编排成能力调用计划
3. 能力结果如何被汇总成最终响应
4. 状态、任务、审计、指标最终落到哪里

当前项目是 `API-first` 架构，真正的主线实现位于 `enterprise/` 目录。`agent/` 下的大部分内容要么是兼容层，要么是被企业版运行时复用的遗留工具实现。

## 2. 推荐阅读顺序

1. `enterprise/api/app.py`
2. `enterprise/orchestrator/service.py`
3. `enterprise/orchestrator/engine.py`
4. `enterprise/capability/gateway.py`
5. `enterprise/capability/builtin_skills.py`
6. `enterprise/a2a/runtime.py`
7. `enterprise/governance/*.py`
8. `enterprise/storage/*.py`
9. `rag/rag_service.py`
10. `rag/vector_store.py`
11. `utils/config_handler.py`

按这个顺序阅读，可以先看“请求怎么进来”，再看“请求怎么执行”，最后再看“数据怎么持久化与治理”。

## 3. 系统总图

```mermaid
flowchart TD
    Client["Streamlit / 外部 API 调用方 / 兼容层 ReactAgent"] --> API["enterprise.api.app"]
    API --> MW["治理中间件 + Trace 中间件"]
    MW --> SVC["OrchestratorService"]
    SVC --> ENG["OrchestratorEngine（LangGraph）"]
    ENG --> GW["CapabilityGateway"]
    GW --> SK["SkillRuntime + SkillRegistryService"]
    GW --> MCP["MCPAdapter"]
    SK --> BUILTIN["builtin_skills"]
    BUILTIN --> RAG["RAG / Prompt / 模型"]
    MCP --> EXT["高德 / 企业外部数据"]

    API --> A2A["A2ARuntime"]
    A2A --> REDIS["Redis"]
    A2A --> PG["Postgres"]
    MW --> GOV["限流 / 审计 / 指标 / Tracing / 成本"]
```

## 4. 核心类图

这个系统更偏“组合关系”而不是“继承关系”，所以类图的重点在依赖关系。

```mermaid
classDiagram
    class OrchestratorService {
        +gateway: CapabilityGateway
        +engine: OrchestratorEngine
        +chat(message, session_id, trace_id)
        +stream_chat(message, session_id, trace_id)
        +list_capabilities()
        +list_skills()
        +set_skill_enabled(skill_id, enabled)
    }

    class OrchestratorEngine {
        +gateway: CapabilityGateway
        +cost_service: CostService
        +model_router: ModelRouter
        +graph
        +run(query, session_id, trace_id)
        +intent_classifier(state)
        +planner(state)
        +capability_router(state)
        +executor(state)
        +reviewer(state)
        +responder(state)
    }

    class CapabilityGateway {
        -_capabilities
        +skill_runtime: SkillRuntime
        +skill_registry: SkillRegistryService
        +mcp_adapter: MCPAdapter
        +audit: AuditService
        +resolve_capability(fqdn)
        +invoke_capability(fqdn, kwargs)
        +list_capabilities()
        +list_skills()
        +set_skill_enabled(skill_id, enabled)
    }

    class Capability {
        +name
        +namespace
        +description
        +handler
        +source
        +schema
        +fqdn
    }

    class SkillRuntime {
        +discover_manifests()
        +load_entrypoint(dotted_path)
    }

    class SkillRegistryService {
        +sync_manifests(manifests)
        +list_skills()
        +set_enabled(skill_id, enabled)
    }

    class MCPAdapter {
        +register_tool(...)
        +discover_tools()
    }

    class CircuitBreaker {
        +allow()
        +record_success()
        +record_failure()
    }

    class A2ARuntime {
        +orchestrator: OrchestratorService
        +repo: TaskRepository
        +redis
        +submit_task(goal, constraints, context_ref, input_data, trace_id)
        +get_task(task_id)
        +start()
        +stop()
    }

    class TaskRepository {
        +create_task(payload)
        +get_task(task_id)
        +update_status(task_id, status, result, error)
        +increment_retry(task_id)
    }

    class SkillRepository {
        +upsert(manifest)
        +list_skills()
        +set_enabled(skill_id, enabled)
    }

    class CostService {
        +estimate_tokens(input_text, output_text)
        +estimate_cost(model_name, input_tokens, output_tokens)
        +record(trace_id, actor, model_name, input_text, output_text)
    }

    class ModelRouter {
        +pick(query, intent)
    }

    class RagSummarizeService {
        +vector_store: VectorStoreService
        +retriever_docs(query)
        +rag_summarize(query)
    }

    class VectorStoreService {
        +get_retriever()
        +load_document()
    }

    OrchestratorService --> OrchestratorEngine
    OrchestratorService --> CapabilityGateway
    OrchestratorEngine --> CapabilityGateway
    OrchestratorEngine --> CostService
    OrchestratorEngine --> ModelRouter
    CapabilityGateway --> Capability
    CapabilityGateway --> SkillRuntime
    CapabilityGateway --> SkillRegistryService
    CapabilityGateway --> MCPAdapter
    MCPAdapter --> CircuitBreaker
    A2ARuntime --> OrchestratorService
    A2ARuntime --> TaskRepository
    SkillRegistryService --> SkillRepository
    RagSummarizeService --> VectorStoreService
```

## 5. 同步聊天调用时序

```mermaid
sequenceDiagram
    participant U as 用户
    participant API as FastAPI
    participant GOV as 治理中间件
    participant TRACE as Trace中间件
    participant SVC as OrchestratorService
    participant ENG as OrchestratorEngine
    participant GW as CapabilityGateway
    participant CAP as Skill/MCP能力
    participant LLM as 聊天模型

    U->>API: POST /v1/chat/stream
    API->>GOV: 进入治理中间件
    GOV->>TRACE: call_next
    TRACE->>SVC: stream_chat / chat
    SVC->>ENG: run(query, session_id, trace_id)
    ENG->>ENG: IntentClassifier
    ENG->>ENG: Planner
    ENG->>ENG: CapabilityRouter
    ENG->>GW: invoke_capability(...)
    GW->>CAP: 执行实际能力
    CAP-->>GW: result
    GW-->>ENG: capability_results
    ENG->>ENG: Reviewer
    ENG->>LLM: Responder（仅聊天意图）
    LLM-->>ENG: final response
    ENG-->>SVC: response dict
    SVC-->>API: 逐字符生成器
    API-->>U: 流式文本
```

## 6. 异步任务调用时序

```mermaid
sequenceDiagram
    participant U as 用户
    participant API as FastAPI
    participant A2A as A2ARuntime
    participant REDIS as Redis队列
    participant REPO as TaskRepository
    participant ORCH as OrchestratorService

    U->>API: POST /v1/tasks
    API->>A2A: submit_task(...)
    A2A->>REPO: create_task(PENDING)
    A2A->>REDIS: rpush(queue, payload)
    API-->>U: task_id + trace_id

    loop worker循环
        A2A->>REDIS: blpop(queue)
        REDIS-->>A2A: payload
        A2A->>REPO: update_status(RUNNING)
        A2A->>ORCH: chat(goal, session_id, trace_id)
        ORCH-->>A2A: result
        A2A->>REPO: update_status(REVIEWING)
        A2A->>REPO: update_status(COMPLETED)
    end
```

## 7. 编排状态流

```mermaid
flowchart LR
    Q["query"] --> I["intent_classifier"]
    I --> P["planner"]
    P --> PC["planned_capabilities"]
    PC --> E["executor"]
    E --> CR["capability_results"]
    CR --> RV["reviewer"]
    RV --> DR["response草稿"]
    DR --> RS["responder"]
    RS --> FR["最终response"]
    RS --> COST["cost元数据"]
```

## 8. 报告流与聊天流分叉图

```mermaid
flowchart TD
    Start["进入编排器"] --> Intent{"是否命中报告关键词"}

    Intent -->|是| ReportFlow["报告流"]
    Intent -->|否| ChatFlow["聊天流"]

    ReportFlow --> R1["enterprise.get_user_id"]
    R1 --> R2["enterprise.get_current_month"]
    R2 --> R3["report.fill_context"]
    R3 --> R4["enterprise.fetch_external_data"]
    R4 --> R5["report.report_writer"]

    ChatFlow --> C1["可选：gaode.get_user_location"]
    ChatFlow --> C2["knowledge.rag_summarize"]
    C1 --> C3["可选：gaode.get_weather"]
    C2 --> C4["reviewer"]
    C3 --> C4
    C4 --> C5["responder"]
```

## 9. 存储职责图

| 组件 | 存储介质 | 职责 |
|---|---|---|
| `skill_registry` | Postgres | 保存技能清单元数据与启用状态 |
| `a2a_tasks` | Postgres | 保存异步任务状态机 |
| `audit_events` | Postgres | 保存审计日志 |
| `cost_records` | Postgres | 保存成本估算记录 |
| `skill_registry:all` | Redis | 缓存技能注册表 |
| `metrics:*` | Redis | 保存轻量运行时指标 |
| `a2a:task_queue` | Redis | 异步任务队列 |
| `a2a:dead_letter` | Redis | 死信队列 |
| `chroma_db/` | Chroma 本地目录 | 保存向量化知识库 |

## 10. 阅读时最值得盯住的点

1. `OrchestratorEngine.planner()` 决定了“请求会调用哪些能力”。
2. `CapabilityGateway.invoke_capability()` 是理解能力执行链的核心入口。
3. `A2ARuntime._process_task()` 是理解异步状态流转的关键函数。
4. `SkillRuntime + SkillRegistryService + CapabilityGateway.reload()` 组成了“配置如何变成可执行能力”的主链。
5. `rag/vector_store.py` 与 `rag/rag_service.py` 说明了知识文件如何进入向量库，再进入模型上下文。

## 11. 关键设计说明

1. 虽然用了 LangGraph，但当前图结构是固定流水线，偏确定性编排。
2. 这套代码主要依赖对象组合关系，不靠深层继承。
3. `agent/react_agent.py` 只是兼容入口，`enterprise/` 才是当前权威主线。
4. A2A worker 是进程内线程，不是独立部署的外部 worker 服务。
5. `/v1/chat/stream` 目前是“先生成完整答案，再逐字符流出”，不是真正的模型原生流。
