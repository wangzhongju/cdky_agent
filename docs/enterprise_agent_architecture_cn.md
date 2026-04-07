# Enterprise Agent 架构图（代码实况版）

> 说明：本文件以当前代码实现为准，不依赖可能滞后的历史文档。

## 1. 总体分层架构图

```mermaid
flowchart TB
    U["用户/调用方"]

    subgraph API["API 层 enterprise/api/app.py"]
        APP["FastAPI app"]
        MWG["governance_middleware"]
        MWT["trace_context_middleware"]
        R1["POST /v1/chat/stream"]
        R2["POST /v1/tasks"]
        R3["GET /v1/tasks/{task_id}"]
        R4["GET/PATCH /v1/skills/{skill_id}"]
        R5["GET /v1/capabilities"]
        R6["GET /v1/metrics, /metrics, /healthz"]
    end

    subgraph APP_SVC["应用服务层"]
        OS["OrchestratorService"]
        A2A["A2ARuntime"]
    end

    subgraph ORCH["编排层 enterprise/orchestrator"]
        OE["OrchestratorEngine (LangGraph)"]
        LG["IntentClassifier -> Planner -> CapabilityRouter -> Executor -> Reviewer -> Responder"]
        ST["OrchestratorState"]
    end

    subgraph CAP["能力层 enterprise/capability"]
        CG["CapabilityGateway"]
        SR["SkillRuntime"]
        SREG["SkillRegistryService"]
        MCP["MCPAdapter + CircuitBreaker"]
        BSK["builtin_skills"]
        TOOLS["agent.tools.agent_tools"]
        RAG["rag.RagSummarizeService"]
    end

    subgraph GOV["治理层 enterprise/governance"]
        AUD["AuditService"]
        RL["RateLimitService"]
        MET["MetricsService"]
        TRC["Tracing(OpenTelemetry + contextvars)"]
        MR["ModelRouter"]
        CST["CostService"]
        PM["Prometheus 指标"]
        HLT["HealthService"]
    end

    subgraph STO["存储层 enterprise/storage"]
        PG["Postgres(SQLAlchemy)"]
        REDIS["Redis"]
        T_SKILL["skill_registry"]
        T_TASK["a2a_tasks"]
        T_AUDIT["audit_events"]
        T_COST["cost_records"]
    end

    subgraph EXT["外部依赖"]
        QWEN["ChatTongyi / DashScope"]
        GAODE["高德 API"]
        CHROMA["Chroma 向量库"]
        CSV["data/external/records.csv"]
    end

    U --> APP
    APP --> MWG --> MWT
    MWT --> R1 --> OS
    MWT --> R2 --> A2A
    MWT --> R3 --> A2A
    MWT --> R4 --> OS
    MWT --> R5 --> OS
    MWT --> R6

    OS --> OE --> LG --> ST
    OE --> CG

    CG --> SR
    CG --> SREG
    CG --> MCP
    SR --> BSK --> TOOLS
    TOOLS --> RAG --> CHROMA
    TOOLS --> GAODE
    TOOLS --> CSV
    OE --> MR --> QWEN
    OE --> CST --> QWEN

    MWG --> RL --> REDIS
    MWG --> MET --> REDIS
    MWG --> AUD --> PG
    MWT --> TRC
    OE --> CST --> PG
    OE --> CST --> REDIS
    CG --> AUD --> PG
    A2A --> PG
    A2A --> REDIS
    HLT --> PG
    HLT --> REDIS
    PM --> APP

    PG --> T_SKILL
    PG --> T_TASK
    PG --> T_AUDIT
    PG --> T_COST
```

## 2. 启动与生命周期图（`lifespan`）

```mermaid
sequenceDiagram
    participant P as 进程
    participant L as lifespan
    participant DB as init_storage
    participant TR as setup_tracer
    participant OS as OrchestratorService
    participant A2A as A2ARuntime
    participant S as app.state

    P->>L: FastAPI 启动
    L->>DB: create_all()
    L->>TR: 初始化 OTel TracerProvider/Exporter
    L->>OS: new OrchestratorService()
    L->>A2A: new A2ARuntime(orchestrator_service)
    L->>A2A: start() 启动 worker 线程
    L->>S: 挂载 orchestrator_service/a2a_runtime
    L->>S: 挂载 audit/rate_limit/metrics/health 服务
    L-->>P: 应用进入可用状态

    P->>L: 进程关闭
    L->>A2A: stop()
```

## 3. `POST /v1/chat/stream` 真实时序图

```mermaid
sequenceDiagram
    participant C as Client
    participant MWG as governance_middleware
    participant MWT as trace_context_middleware
    participant API as chat_stream
    participant SR as StreamingResponse
    participant GEN as stream_chat 生成器
    participant OS as OrchestratorService.chat
    participant LG as OrchestratorEngine.graph.invoke

    C->>MWG: HTTP 请求
    MWG->>MWT: call_next
    MWT->>API: 进入路由
    API->>GEN: 创建 generator 对象
    API-->>MWT: 返回 StreamingResponse(generator)
    MWT-->>MWG: 返回 Response 对象
    MWG-->>C: 返回响应头

    Note over MWG,SR: 中间件后置逻辑先结束，再开始消费流体

    loop 每次发送 chunk
        SR->>GEN: next() (iterate_in_threadpool)
        alt 首次 next
            GEN->>OS: self.chat(...)
            OS->>LG: run() -> graph.invoke(state)
            LG-->>OS: 完整 response
            OS-->>GEN: result
        end
        GEN-->>SR: yield 一个字符
        SR-->>C: 发送一个 chunk
    end
```

## 4. LangGraph 编排详图

```mermaid
flowchart LR
    START["START"] --> IC["IntentClassifier\n写入 state.intent"]
    IC --> PL["Planner\n写入 state.planned_capabilities"]
    PL --> CR["CapabilityRouter\n当前直通"]
    CR --> EX["Executor\n分发执行"]

    EX -->|intent=report| RF1
    EX -->|intent=chat| GF1

    subgraph REPORT_FLOW["报告链路（串行）"]
        RF1["enterprise.get_user_id"]
        RF2["enterprise.get_current_month"]
        RF3["report.fill_context"]
        RF4["enterprise.fetch_external_data(user_id, month)"]
        RF5["report.report_writer(query, external_data)"]
        RF1 --> RF2 --> RF3 --> RF4 --> RF5
    end

    subgraph CHAT_FLOW["聊天链路（有限并行 + 延迟参数）"]
        GF1["immediate_steps 并行执行\nThreadPoolExecutor"]
        GF2["gaode.get_user_location -> city"]
        GF3["knowledge.rag_summarize(query)"]
        GF4["deferred_weather 串行执行\ncity 未知则默认 北京"]
        GF5["gaode.get_weather(city)"]
        GF1 --> GF2
        GF1 --> GF3
        GF2 --> GF4 --> GF5
    end

    RF5 --> RV["Reviewer\n写入 state.response 草稿"]
    GF5 --> RV
    GF3 --> RV
    RV --> RS["Responder\nreport:跳过\nchat:模型汇总 + 记录 cost"]
    RS --> END["END"]
```

## 5. 能力加载与调用架构图

```mermaid
flowchart TB
    INIT["CapabilityGateway.__init__"] --> LOAD["_load_all()"]

    LOAD --> DISC["SkillRuntime.discover_manifests()\n文件系统 + builtin manifests"]
    DISC --> SYNC["SkillRegistryService.sync_manifests()"]
    SYNC --> SKR["SkillRepository.upsert() -> Postgres skill_registry"]
    SYNC --> SKC["Redis skill_registry:all 缓存"]

    DISC --> EN["按 enabled 过滤"]
    EN --> IMP["load_entrypoint() 导入注册函数"]
    IMP --> CAPS1["写入 _capabilities[fqdn] (source=skill)"]

    LOAD --> MCP_CONF["读取 config/mcp.yml"]
    MCP_CONF --> MCP_REG["MCPAdapter.register_tool()"]
    MCP_REG --> CB["CircuitBreaker + 超时 + 重试"]
    MCP_REG --> CAPS2["写入 _capabilities[fqdn] (source=mcp)"]

    INV["invoke_capability(fqdn, kwargs)"] --> RES["resolve_capability()"]
    RES --> HAND["cap.handler(**kwargs)"]
    HAND --> OK["SUCCESS: 返回结果"]
    HAND --> ERR["FAILED: 返回失败字符串"]
    OK --> AUD1["AuditService.log(capability_invoke) -> audit_events"]
    ERR --> AUD2["AuditService.log(capability_invoke) -> audit_events"]
    OK --> PM1["capability_invocations_total++"]
    ERR --> PM2["capability_invocations_total++"]
```

## 6. A2A 异步任务架构图

```mermaid
flowchart LR
    REQ["POST /v1/tasks"] --> SUB["A2ARuntime.submit_task()"]
    SUB --> DB1["TaskRepository.create_task() -> a2a_tasks(PENDING)"]
    SUB --> Q1["Redis RPUSH a2a:task_queue"]

    LOOP["worker 线程循环"] --> POP["Redis BLPOP a2a:task_queue"]
    POP --> PROC["_process_task(task)"]
    PROC --> RUN["a2a_tasks -> RUNNING"]
    RUN --> CHAT["orchestrator.chat(goal)"]
    CHAT --> REV["a2a_tasks -> REVIEWING"]
    REV --> DONE["a2a_tasks -> COMPLETED"]

    PROC -->|异常| RETRY["increment_retry()"]
    RETRY -->|<= max_retry| Q2["重新 RPUSH 到 task_queue"]
    RETRY -->|> max_retry| FAIL["a2a_tasks -> FAILED"]
    FAIL --> DLQ["Redis RPUSH a2a:dead_letter"]
```

## 7. 字段级数据血缘图（`request -> state -> capability_results -> DB/Redis`）

```mermaid
flowchart TB
    RQ["ChatStreamRequest\nmessage\nsession_id?\ntrace_id?"] --> OSN["OrchestratorService.chat\nsid=session_id or uuid\ntid=trace_id or uuid"]
    OSN --> ST0["state 初始化\nquery=session_id=trace_id\nplanned_capabilities=[]\ncapability_results=[]\nreport_context={}"]

    ST0 --> ST1["IntentClassifier\nstate.intent"]
    ST1 --> ST2["Planner\nstate.planned_capabilities[]\n元素: {fqdn,args}"]
    ST2 --> ST3["Executor\nstate.capability_results[]\n元素: {fqdn,result,trace_id}"]
    ST3 --> ST4["Reviewer\nstate.response(草稿)"]
    ST4 --> ST5["Responder(chat)\nstate.response(最终)\nstate.cost{}"]

    ST5 --> OUT["HTTP 返回\nsession_id\ntrace_id\nintent\nresponse\ncapability_results\ncost"]

    ST3 --> AUDC["capability_invoke 审计写入\naudit_events.event_type/actor/trace_id/target/payload/status/error/latency_ms"]
    ST5 --> COST["cost_records.trace_id/actor/model_name/input_tokens/output_tokens/estimated_cost"]
    COST --> RC1["Redis\nmetrics:cost:total\nmetrics:cost:model_calls"]

    MW["governance_middleware\nactor=x-api-key\ntrace_id=current_trace_id"] --> AUDA["api_request 审计写入\naudit_events.*"]
    MW --> RC2["Redis\nratelimit:{actor}:{minute}\nquota:{actor}:{day}\nmetrics:requests_*"]
    MW --> PM["Prometheus\napi_requests_total\napi_request_latency_ms\ninflight_requests"]
```

