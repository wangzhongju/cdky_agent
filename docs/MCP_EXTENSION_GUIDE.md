# MCP 扩展指南（协议层）

## 1. 架构定位

当前工程将 MCP 放在 `enterprise/mcp/`，只负责协议通信与工具发现调用：

- 配置解析：`enterprise/mcp/config.py`
- 传输客户端：`enterprise/mcp/client.py`（`stdio` / `streamable_http` / `local`）
- 协议运行时：`enterprise/mcp/runtime.py`（`initialize`、`tools/list`、`tools/call`）
- 本地 MCP server：`enterprise/mcp/servers/`

能力聚合仍由 `CapabilityGateway` 完成，但不再处理 MCP 协议细节。

## 2. 配置模型

`config/mcp.yml` 支持新旧两种格式：

1. 新格式（推荐）

```yaml
servers:
  - id: web_fetch_local
    namespace: web
    transport: local
    server_type: web_fetch
    enabled: true
    timeout_seconds: 8
    max_retries: 1
    failure_threshold: 3
    reset_seconds: 15
    protocol_version: "2025-11-25"
```

2. 旧格式（Phase-1 兼容）

```yaml
servers:
  - id: gaode
    namespace: gaode
    enabled: true
```

旧格式会自动映射为 `transport=legacy`，同时输出弃用告警。

## 3. 新接入一个外部 MCP Server

### 3.1 `streamable_http`（远端）

```yaml
servers:
  - id: remote_docs
    namespace: docs
    transport: streamable_http
    url: https://your-mcp.example.com/mcp
    headers:
      Authorization: Bearer ${MCP_TOKEN}
    enabled: true
    timeout_seconds: 8
```

### 3.2 `stdio`（本地进程）

```yaml
servers:
  - id: local_calc
    namespace: calc
    transport: stdio
    command: ["python", "-m", "my_mcp_server"]
    enabled: true
```

### 3.3 生效

无需重启，调用：

- `POST /v1/mcp/reload`
- `GET /v1/mcp/servers` 查看连接和发现状态
- `GET /v1/capabilities` 查看是否出现新 `source=mcp` 能力

## 4. 新增一个自定义 MCP 工具（本地）

以网页抓取工具为例：

1. 在 `enterprise/mcp/servers/` 新增本地 server，实现：
- `initialize(protocol_version)`
- `list_tools()`
- `call_tool(name, arguments)`

2. 在 `config/mcp.yml` 添加：

```yaml
servers:
  - id: web_fetch_local
    namespace: web
    transport: local
    server_type: web_fetch
    enabled: true
```

3. reload 后能力会以 `web.fetch_page` 形式自动暴露。

补充：项目也支持把 Skills 反向暴露为 MCP（stdio），命令：

```bash
python -m enterprise.mcp.servers.skill_bridge_stdio
```

## 5. 安全与治理建议

网页抓取 MCP 已默认包含：

- 超时和响应体大小限制
- 内容类型白名单
- 私网/回环地址拦截（SSRF 基线）
- 调用失败重试与熔断

建议生产环境进一步补充：

- 域名白名单
- 出网代理审计
- 更细粒度的租户级访问策略

## 6. 排障清单

1. `GET /v1/mcp/servers` 中 `connected=false`
- 检查 transport 配置（url/command/server_type）
- 检查下游服务可达性

2. 能力未出现在 `/v1/capabilities`
- 先看 server 是否发现到 `discovered_tools > 0`
- 再看 `namespace` 与工具名拼接的 `fqdn` 是否与调用一致

3. 调用报熔断
- 说明连续失败次数达到阈值，等待 `reset_seconds` 后恢复
