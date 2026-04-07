# Skills 扩展指南（能力层）

## 1. 架构定位

Skills 是领域能力封装层，负责业务语义与流程编排片段，不负责协议通信。

核心组件：

- 扫描与导入：`enterprise/capability/skills/runtime.py`
- 注册表与开关：`enterprise/capability/skills/registry.py`
- 运行上下文：`enterprise/capability/skills/context.py`

Skill 能力最终由 `CapabilityGateway` 聚合并对编排器暴露。

## 2. Skill 包结构

以 `skills/custom_web/` 为例：

```text
skills/
  __init__.py
  custom_web/
    __init__.py
    manifest.json
    entrypoint.py
```

`manifest.json` 必填字段：

- `id`
- `name`
- `version`
- `entrypoint`（`module:function`）
- `tool_schemas`
- `required_permissions`
- `dependencies`
- `enabled`

## 3. entrypoint 兼容规则

支持两种写法：

1. 老写法（无参）

```python
def register_xxx() -> list[Capability]:
    ...
```

2. 新写法（推荐，支持 MCP 复用）

```python
def register_xxx(ctx: SkillContext) -> list[Capability]:
    ...
```

`SkillContext` 能力：

- `ctx.call_mcp(fqdn, **kwargs)`：在 Skill 内调用 MCP
- `ctx.configs`：读取 enterprise/mcp 配置
- `ctx.read_trace()/write_trace()`：读取或覆盖 trace

## 4. 新增一个外部 Skill 包

1. 在 `skills/<your_skill>/` 下放置 `manifest.json` 和 `entrypoint.py`
2. `entrypoint` 指向可导入模块，如：
- `skills.your_skill.entrypoint:register_your_skill`
3. 调用 `PATCH /v1/skills/{skill_id}` 可启停
4. `GET /v1/capabilities` 验证是否出现 `source=skill`

## 5. Skill 调用 MCP 示例

项目内置示例：`skills/custom_web/entrypoint.py`

- 识别用户问题中的 URL
- 通过 `ctx.call_mcp("web.fetch_page", ...)` 抓取网页
- 生成简要摘要返回给编排器

## 6. Skills 通过 MCP 暴露（双向复用）

项目提供本地 `skill_bridge` MCP server：

- 从 Skill 白名单读取能力
- 转换成 MCP tools 暴露
- 供外部 MCP host/client 调用

配置示例：

```yaml
servers:
  - id: skills_bridge
    namespace: skillbridge
    transport: local
    server_type: skill_bridge
    skill_whitelist:
      - knowledge.rag_summarize
      - knowledge.webpage_brief
```

如果需要把本项目作为外部 MCP server（stdio）暴露给其他 Host，可运行：

```bash
python -m enterprise.mcp.servers.skill_bridge_stdio
```

可选白名单环境变量：

```bash
SKILL_BRIDGE_WHITELIST=knowledge.rag_summarize,knowledge.webpage_brief
```

## 7. 验收清单

1. `GET /v1/skills` 能看到新 Skill 记录
2. `GET /v1/capabilities` 能看到 `source=skill` 能力
3. 在聊天请求中输入含 URL 的问题，触发 `knowledge.webpage_brief`
4. `POST /v1/mcp/reload` 后 `GET /v1/mcp/servers` 中 `skills_bridge` 状态正常
