

```
远程服务器，ip：192.168.88.92，用户名：cdky，密码：1234qqqq，路径/home/cdky/workspace/github/cdky_agent与本地是同一个agent仓库代码，按以下需求，在本地修改，同步到远程服务器进行测试：
1.禁止修改远程服务器主机环境，本地只修改文件不执行测试，本地修改后同步到远程执行测试；
2.在远程服务器上构建docker镜像并在docker中进行该agent测试；
3.给出完整镜像环境构建的dockerfile文件，以及容器操作的docker-compose-dev.yaml文件与docker.sh脚本文件；
4.相关的密钥以.env的方式提供，DASHSCOPE_API_KEY为sk-1754211741af44c3b072d06389848681，GAODE_MCP_KEY与配置文件中一致。
```



```
TODO
没有创建md5.text文件情况下 chroma_db 也会生成

执行 python3 ./rag/vector_store.py 报错：ModuleNotFoundError: No module named 'utils'， 执行 python3 -m rag.vector_store 成功
```



```
远程服务器，ip：192.168.88.92，用户名：cdky，密码：1234qqqq，路径/home/cdky/workspace/github/cdky_agent，是一个具有三层能力系统：Skills + MCP（能力层） / LangGraph（编排层） / A2A（协作层）的Agent，按以下要求进行操作：
1.禁止修改远程主机系统环境；
2.项目中有些文档可能是过期的，项目功能以目前代码实现为主，所以你需要先仔细阅读代码，理解代码架构以实现逻辑；
3.在远程主机按照项目的docker部署方式，执行完整的部署与测试。
```





```
请阅读该Agent工程，给出代码的整体架构，调用时许图，数据流等，以便于我可以深度地掌握该代码。


按如下需求更改：
1.输出一份“逐文件精读版”，按函数一层层讲每个调用点；
2.再补一份“字段级数据血缘图”，把 request -> state -> capability_results -> DB/Redis 画到字段级；
3.所有的注释与文档使用中文；
```









> 一、**SQLAlchemy** 库
>
> Python 中最流行的**数据库工具包**和**对象关系映射（ORM）（Object-Relational Mapping）框架**。它提供了一个完整的企业级持久化模式，用于高效、灵活地与数据库进行交互
>
> **1. 解决的问题**
>
> 在没有 ORM 框架的情况下，直接使用原生 SQL 进行数据库操作会面临以下问题：
>
> - **字符串拼接 SQL**：容易出错，且存在 SQL 注入风险
> - **手动转换数据**：需要将数据库行转换为 Python 对象
> - **代码重复**：大量的 CRUD 操作代码重复编写
> - **数据库切换困难**：SQL 语法因数据库而异（MySQL、PostgreSQL、SQLite 等）
>
> **2. 核心**
>
> SQLAlchemy 提供两层抽象
>
> 
>
> 二、**opentelemetry** 库  （telemetry təˈlemətrē  遥测）
>
> openTelemetry 是一个**可观测性框架**，用于生成、收集和导出遥测数据（Telemetry Data），包括**分布式追踪（Traces）**、**指标（Metrics）** 和**日志（Logs）**。它是 CNCF（云原生计算基金会）的孵化项目，由 OpenTracing 和 OpenCensus 合并而成
>
> **1. 解决的问题**
>
> 在微服务和分布式系统中，排查问题变得极其困难：
>
> - **调用链复杂**：一个请求可能经过数十个服务，难以追踪
> - **故障定位困难**：不知道哪个服务出问题，耗时在哪里
> - **性能瓶颈难发现**：无法精确知道慢在哪里
> - **各厂商标准不一**：不同 APM 工具使用不同协议
>
> **2. 核心**
>
> - **统一标准**：一套 API 支持所有可观测性后端
> - **降低复杂度**：自动埋点，减少手动代码
> - **提升效率**：快速定位分布式系统问题
> - **厂商无关**：避免供应商锁定
>
> **3. 三大支柱**
>
> **Traces（分布式追踪）**
>
> 追踪请求在分布式系统中的完整路径。
>
> **Metrics（指标）**
>
> 收集和聚合度量数据，如请求计数、响应时间、错误率等。
>
> **Logs（日志）**
>
> 关联日志与追踪，实现日志的上下文关联。
>
> **4. 常用导出器**
>
> | 导出器         | 用途       | 命令                                            |
> | :------------- | :--------- | :---------------------------------------------- |
> | **Jaeger**     | 分布式追踪 | `pip install opentelemetry-exporter-jaeger`     |
> | **Zipkin**     | 分布式追踪 | `pip install opentelemetry-exporter-zipkin`     |
> | **Prometheus** | 指标收集   | `pip install opentelemetry-exporter-prometheus` |
> | **OTLP**       | 通用协议   | `pip install opentelemetry-exporter-otlp`       |
> | **Console**    | 调试       | 内置                                            |
>
> 
>
> 三、**contextvars** 库
>
> 用于管理**上下文变量**（Context Variables）。它提供了在异步编程中传递和隔离上下文数据的能力，类似于线程本地存储，但专门为**异步/协程**设计
>
> **1. 解决的问题**
>
> 全局变量并发不安全
>
> Thread Local 协程不安全
>
> 显示传递方式代码冗长
>
> **2. 核心**
>
> 协程安全、隐式传递、自动传播、类型安全
>
> 
>
> 四、**prometheus_client** 库
>
> `prometheus_client` 是 Python 官方的 Prometheus 指标客户端库，用于在 Python 应用中定义和暴露监控指标。Prometheus 通过拉取（Pull）方式从 `/metrics` 端点获取这些指标数据
>
> **1. 解决的问题**
>
> 如在Agent系统中，指标统计可以监控：
>
> - 编排器的请求量和延迟
> - 各能力的调用成功率
> - LLM 调用次数和成本
> - RAG 检索效率
> - 系统资源使用情况
>
> **2. 核心**
>
> | 指标类型      | 特点             | 典型用途                       |
> | :------------ | :--------------- | :----------------------------- |
> | **Counters**  | 计数器：只增不减 | 请求总数、错误数、处理任务数   |
> | **Histogram** | 直方图：分布统计 | 响应时间、延迟分布、数据大小   |
> | **Gauge**     | 仪表盘：可增可减 | 活跃连接数、队列长度、内存使用 |
>
> generate_latest()：生成当前所有指标的 Prometheus 格式输出
>
> CONTENT_TYPE_LATEST：Prometheus 格式的 HTTP Content-Type 常量

