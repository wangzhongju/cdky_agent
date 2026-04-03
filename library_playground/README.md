# 库用法练习场（结合本工程）

这个目录用于把项目里常见库的用法拆成“可单独阅读/运行”的小示例，帮助你从源码中抽离出关键模式。

## 目录说明

1. `contextlib_lifespan_demo.py`
- 主题：`contextlib.asynccontextmanager`    生命周期
- 对应工程：`enterprise/api/app.py` 里的 `lifespan`

2. `opentelemetry_tracing_demo.py`
- 主题：`opentelemetry` Tracer 初始化、Span 属性、可选 OTLP 上报
- 对应工程：`enterprise/governance/tracing.py`

3. `contextvars_trace_demo.py`
- 主题：`contextvars.ContextVar` 在请求链路中传递 `trace_id/actor`
- 对应工程：`enterprise/governance/tracing.py` 的上下文透传逻辑

4. `concurrent_retry_breaker_demo.py`
- 主题：`ThreadPoolExecutor` + 超时 + 重试 + 熔断
- 对应工程：`enterprise/capability/mcp/adapter.py` 与 `circuit_breaker.py`

5. `sqlalchemy_repository_demo.py`
- 主题：SQLAlchemy ORM + Repository 模式
- 对应工程：`enterprise/storage/models.py`、`task_repository.py`、`skill_repository.py`

6. `asyncio_async_keyword_demo.py`
- 主题：`asyncio` 中 `async/await`、协程对象、顺序/并发、超时控制
- 对应工程：异步中间件与并发调用模式（如 `enterprise/api/app.py`、`enterprise/capability/mcp/adapter.py`）

7. `asynccontextmanager_async_semantics_demo.py`
- 主题：`contextlib.asynccontextmanager` 里 `async` 的前后语义与异常路径
- 对应工程：`enterprise/api/app.py` 的 `lifespan` 资源生命周期管理

## 运行方式

在项目根目录执行：

```powershell
python library_playground/contextlib_lifespan_demo.py
python library_playground/opentelemetry_tracing_demo.py
python library_playground/contextvars_trace_demo.py
python library_playground/concurrent_retry_breaker_demo.py
python library_playground/sqlalchemy_repository_demo.py
python library_playground/asyncio_async_keyword_demo.py
python library_playground/asynccontextmanager_async_semantics_demo.py
```

## 建议阅读顺序

1. `contextlib_lifespan_demo.py`
2. `contextvars_trace_demo.py`
3. `opentelemetry_tracing_demo.py`
4. `concurrent_retry_breaker_demo.py`
5. `sqlalchemy_repository_demo.py`
6. `asyncio_async_keyword_demo.py`
7. `asynccontextmanager_async_semantics_demo.py`

## 你可以怎么对照工程源码

1. 先看这里的最小示例，把概念理解清楚。
2. 再回到对应工程文件看“真实业务版本”。
3. 最后对照调用链，回答三个问题：
- 这个库解决了什么问题？
- 项目里把它放在了哪一层？
- 如果不用它，会出现什么复杂度或风险？
