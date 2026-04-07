from __future__ import annotations

"""统一的能力目录与调用网关。

编排器不会直接触达原始 Skill 或 MCP 处理器，而是统一经过这里完成：
- 能力加载
- 能力查找
- 调用审计
- 运行时调用
"""

import time
from typing import Any

from agent.tools.agent_tools import get_weather, get_user_location, fetch_external_data
from enterprise.capability.skills.registry import SkillRegistryService
from enterprise.capability.skills.runtime import SkillRuntime
from enterprise.capability.mcp.adapter import MCPAdapter
from enterprise.capability.types import Capability
from enterprise.governance.audit import AuditService
from enterprise.governance.prometheus_metrics import capability_invocations_total
from enterprise.governance.tracing import current_actor, current_trace_id
from utils.config_handler import mcp_conf
from utils.logger_handler import logger


class CapabilityGateway:
    """把技能能力与 MCP 工具聚合成统一的运行时命名空间。

    设计目标
    - 对编排层暴露稳定入口：上层只关心 `fqdn + args`，不关心能力来自 skill 还是 mcp。
    - 对治理层集中接入：审计、trace、指标在网关统一落地，避免分散在每个工具里。
    - 对运维层提供可观测目录：可列出能力快照、按开关热重载能力。

    关键约定
    - 能力唯一键：`fqdn = "{namespace}.{name}"`。
    - 目录结构：`self._capabilities: dict[fqdn, Capability]`。
    - 调用失败语义：`invoke_capability` 返回失败字符串（不向上抛异常）。
    """

    def __init__(self):
        # 运行时内存目录：所有可调用能力都注册在这张字典里。
        # key: capability.fqdn（例如 "knowledge.rag_summarize"）
        # value: Capability（包含 handler/source/schema）
        self._capabilities: dict[str, Capability] = {}

        # SkillRuntime
        # - 负责发现技能 manifest（本地 skills + 内置 builtin）
        # - 负责按 manifest.entrypoint 动态导入注册函数
        self.skill_runtime = SkillRuntime()

        # SkillRegistryService
        # - 负责把 manifest 元数据同步到 Postgres
        # - 负责维护 Redis 缓存视图与技能开关状态
        self.skill_registry = SkillRegistryService()

        # MCPAdapter
        # - 负责把外部工具封装为 Capability
        # - 在 handler 外层统一补齐超时/重试/熔断
        self.mcp_adapter = MCPAdapter()

        # AuditService
        # - 负责记录能力调用审计日志（成功/失败）
        self.audit = AuditService()

        # 网关实例化后立即装配一次完整能力目录。
        self._load_all()

    def _load_all(self) -> None:
        """全量加载能力目录。

        执行顺序
        1) 发现 manifest（本地 + builtin）
        2) 同步注册表（DB + 缓存）
        3) 按 enabled 过滤并导入 Skill 能力
        4) 注册并合并 MCP 能力

        注意：最终统一写入 `self._capabilities`，若 fqdn 冲突，后写覆盖先写。
        """
        # 1. 收集全部技能清单。
        manifests = self.skill_runtime.discover_manifests()

        # 2. 以扫描结果刷新注册表，保证数据库/缓存与当前代码一致。
        self.skill_registry.sync_manifests(manifests)

        # 3. 读取技能开关状态，用于过滤 disabled 的技能。
        enabled_map = {row["id"]: row for row in self.skill_registry.list_skills()}

        for manifest in manifests:
            registry_row = enabled_map.get(manifest["id"])
            if registry_row and not registry_row.get("enabled", True):
                # 注册表已禁用时，跳过该技能的能力注入。
                continue

            # 按 entrypoint 动态导入注册函数。
            loader = self.skill_runtime.load_entrypoint(manifest["entrypoint"])
            for capability in loader():
                # 统一按 fqdn 放入内存目录。
                self._capabilities[capability.fqdn] = capability

        # 4. 合并 MCP 能力。
        self._load_mcp_adapters()

    def _load_mcp_adapters(self) -> None:
        """注册配置中的 MCP 工具，并合并进能力目录。

        配置来源：`config/mcp.yml` -> `mcp_conf["servers"]`
        当前内置注册：
        - gaode.get_weather
        - gaode.get_user_location
        - enterprise.fetch_external_data
        """
        servers = mcp_conf.get("servers", [])

        # 只保留启用态 server，并按 id 建索引。
        server_map = {srv["id"]: srv for srv in servers if srv.get("enabled", True)}

        gaode = server_map.get("gaode")
        if gaode:
            # 天气查询能力
            self.mcp_adapter.register_tool(
                namespace=gaode["namespace"],
                name="get_weather",
                description="高德天气MCP",
                handler=lambda city: get_weather.invoke({"city": city}),
                timeout_seconds=int(gaode.get("timeout_seconds", 5)),
                max_retries=int(gaode.get("max_retries", 2)),
                failure_threshold=int(gaode.get("failure_threshold", 5)),
                reset_seconds=int(gaode.get("reset_seconds", 30)),
            )
            # 用户定位能力
            self.mcp_adapter.register_tool(
                namespace=gaode["namespace"],
                name="get_user_location",
                description="高德定位MCP",
                handler=lambda: get_user_location.invoke({}),
                timeout_seconds=int(gaode.get("timeout_seconds", 5)),
                max_retries=int(gaode.get("max_retries", 2)),
                failure_threshold=int(gaode.get("failure_threshold", 5)),
                reset_seconds=int(gaode.get("reset_seconds", 30)),
            )

        enterprise_srv = server_map.get("enterprise_data")
        if enterprise_srv:
            # 企业外部数据查询能力
            self.mcp_adapter.register_tool(
                namespace=enterprise_srv["namespace"],
                name="fetch_external_data",
                description="企业数据MCP",
                handler=lambda user_id, month: fetch_external_data.invoke({"user_id": user_id, "month": month}),
                timeout_seconds=int(enterprise_srv.get("timeout_seconds", 5)),
                max_retries=int(enterprise_srv.get("max_retries", 2)),
                failure_threshold=int(enterprise_srv.get("failure_threshold", 5)),
                reset_seconds=int(enterprise_srv.get("reset_seconds", 30)),
            )

        # 将 MCPAdapter 维护的工具目录并入网关能力目录。
        # 若与已有 skill fqdn 冲突，这里会覆盖已有项。
        for cap in self.mcp_adapter.discover_tools():
            self._capabilities[cap.fqdn] = cap

    def reload(self) -> None:
        """根据配置与注册表状态重建内存中的能力目录。"""
        # 清空后全量重建，避免残留过期能力。
        self._capabilities = {}
        self._load_all()

    def list_capabilities(self) -> list[dict[str, Any]]:
        """返回当前运行时可见能力的序列化快照。"""
        return [
            {
                "name": cap.name,
                "namespace": cap.namespace,
                "fqdn": cap.fqdn,
                "source": cap.source,
                "description": cap.description,
                "schema": cap.schema,
            }
            for cap in self._capabilities.values()
        ]

    def resolve_capability(self, fqdn: str) -> Capability:
        """根据全限定名解析一个能力对象。"""
        capability = self._capabilities.get(fqdn)
        if not capability:
            raise KeyError(f"能力未注册: {fqdn}")
        return capability

    def invoke_capability(self, fqdn: str, **kwargs) -> Any:
        """以统一的审计与指标逻辑调用单个能力。

        字段流转
        - 输入：fqdn, kwargs
        - trace_id：优先取 kwargs 中的 trace_id，没有则回退当前上下文
        - actor：由 tracing context 提供
        - 输出：成功返回 handler 原始结果；失败返回错误字符串
        """
        # 1) 先解析能力，保证 fqdn 有效。
        cap = self.resolve_capability(fqdn)

        # 2) 从 kwargs 中弹出 trace_id，避免向真实 handler 透传治理字段。
        trace_id = str(kwargs.pop("trace_id", "") or current_trace_id())

        # 3) 读取调用方身份（通常来自请求头 x-api-key）。
        actor = current_actor()

        # 4) 记录起始时间，用于统计调用延迟。
        start = time.time()
        logger.info(f"[CapabilityGateway] invoke fqdn={fqdn} kwargs={kwargs} trace_id={trace_id}")
        try:
            # 5) 执行真实能力。
            result = cap.handler(**kwargs)

            # 6) 成功审计。
            self.audit.log(
                event_type="capability_invoke",
                actor=actor,
                trace_id=trace_id,
                target=fqdn,
                payload={"args": kwargs},
                status="SUCCESS",
                latency_ms=int((time.time() - start) * 1000),
            )

            # 7) 成功指标。
            capability_invocations_total.labels(capability=fqdn, status="success").inc()
            return result
        except Exception as exc:
            # 8) 失败审计。
            self.audit.log(
                event_type="capability_invoke",
                actor=actor,
                trace_id=trace_id,
                target=fqdn,
                payload={"args": kwargs},
                status="FAILED",
                error=str(exc),
                latency_ms=int((time.time() - start) * 1000),
            )

            # 9) 失败指标。
            capability_invocations_total.labels(capability=fqdn, status="failed").inc()
            logger.warning(f"[CapabilityGateway] invoke failed fqdn={fqdn} err={exc}")

            # 10) 失败语义：返回错误字符串，而不是抛异常。
            return f"能力 {fqdn} 调用失败: {exc}"

    def list_skills(self) -> list[dict[str, Any]]:
        """返回持久化后的技能注册表视图。"""
        return self.skill_registry.list_skills()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        """切换技能开关，并在需要时刷新能力目录。"""
        ok = self.skill_registry.set_enabled(skill_id, enabled)
        if ok:
            # 技能状态变更后立即重载，使内存目录与注册表保持一致。
            self.reload()
        return ok
