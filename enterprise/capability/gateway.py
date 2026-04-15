from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from enterprise.capability.skills.registry import SkillRegistryService
from enterprise.capability.skills.runtime import SkillRuntime
from enterprise.capability.mcp.adapter import MCPAdapter
from enterprise.capability.types import Capability
from enterprise.governance.audit import AuditService
from enterprise.governance.prometheus_metrics import capability_invocations_total
from enterprise.governance.tracing import current_actor, current_trace_id
from harness.knowledge.service import KnowledgeService, ReportDataService
from harness.tools.base import ToolExecutionContext
from harness.tools.registry import build_default_tool_registry
from utils.config_handler import mcp_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class CapabilityGateway:
    def __init__(self):
        self._capabilities: dict[str, Capability] = {}
        self.skill_runtime = SkillRuntime()
        self.skill_registry = SkillRegistryService()
        self.mcp_adapter = MCPAdapter()
        self.audit = AuditService()
        self.workspace = Path(get_abs_path(".")).resolve()
        self.knowledge_service = KnowledgeService()
        self.report_service = ReportDataService()
        self.tool_registry = build_default_tool_registry(
            cwd=self.workspace,
            knowledge_service=self.knowledge_service,
            report_service=self.report_service,
        )
        self._load_all()

    def _load_all(self) -> None:
        manifests = self.skill_runtime.discover_manifests()
        markdown_skills = self.skill_runtime.discover_markdown_skills()
        self.skill_registry.sync_manifests(manifests)
        self.skill_registry.sync_skills(markdown_skills)

        enabled_map = {row["id"]: row for row in self.skill_registry.list_skills()}

        for manifest in manifests:
            registry_row = enabled_map.get(manifest["id"])
            if registry_row and not registry_row.get("enabled", True):
                continue

            loader = self.skill_runtime.load_entrypoint(manifest["entrypoint"])
            for capability in loader():
                self._capabilities[capability.fqdn] = capability

        self._register_tool_capabilities()
        self._load_mcp_adapters()

    def _load_mcp_adapters(self) -> None:
        servers = mcp_conf.get("servers", [])
        server_map = {srv["id"]: srv for srv in servers if srv.get("enabled", True)}

        gaode = server_map.get("gaode")
        if gaode:
            self.mcp_adapter.register_tool(
                namespace=gaode["namespace"],
                name="get_weather",
                description="高德天气MCP",
                handler=lambda city: self._invoke_tool("gaode_get_weather", city=city),
                timeout_seconds=int(gaode.get("timeout_seconds", 5)),
                max_retries=int(gaode.get("max_retries", 2)),
                failure_threshold=int(gaode.get("failure_threshold", 5)),
                reset_seconds=int(gaode.get("reset_seconds", 30)),
            )
            self.mcp_adapter.register_tool(
                namespace=gaode["namespace"],
                name="get_user_location",
                description="高德定位MCP",
                handler=lambda: self._invoke_tool("gaode_get_location"),
                timeout_seconds=int(gaode.get("timeout_seconds", 5)),
                max_retries=int(gaode.get("max_retries", 2)),
                failure_threshold=int(gaode.get("failure_threshold", 5)),
                reset_seconds=int(gaode.get("reset_seconds", 30)),
            )

        enterprise_srv = server_map.get("enterprise_data")
        if enterprise_srv:
            self.mcp_adapter.register_tool(
                namespace=enterprise_srv["namespace"],
                name="fetch_external_data",
                description="企业数据MCP",
                handler=lambda user_id, month: self._invoke_tool(
                    "fetch_external_report_data",
                    user_id=user_id,
                    month=month,
                ),
                timeout_seconds=int(enterprise_srv.get("timeout_seconds", 5)),
                max_retries=int(enterprise_srv.get("max_retries", 2)),
                failure_threshold=int(enterprise_srv.get("failure_threshold", 5)),
                reset_seconds=int(enterprise_srv.get("reset_seconds", 30)),
            )

        for cap in self.mcp_adapter.discover_tools():
            self._capabilities[cap.fqdn] = cap

    def reload(self) -> None:
        self._capabilities = {}
        self._load_all()

    def _register_tool_capabilities(self) -> None:
        for tool in self.tool_registry.list_tools():
            capability = Capability(
                name=tool.name,
                namespace="tool",
                description=tool.description,
                source="tool",
                schema=tool.input_model.model_json_schema(),
                handler=lambda _tool=tool, **kwargs: self._invoke_tool(_tool.name, **kwargs),
            )
            self._capabilities[capability.fqdn] = capability

    def _invoke_tool(self, tool_name: str, **kwargs) -> Any:
        tool = self.tool_registry.get(tool_name)
        if not tool:
            raise KeyError(f"tool not registered: {tool_name}")
        arguments = tool.input_model.model_validate(kwargs)
        result = asyncio.run(tool.execute(arguments, ToolExecutionContext(cwd=self.workspace)))
        if result.is_error:
            raise RuntimeError(result.output)
        return result.output

    def list_capabilities(self) -> list[dict[str, Any]]:
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
        capability = self._capabilities.get(fqdn)
        if not capability:
            raise KeyError(f"能力未注册: {fqdn}")
        return capability

    def invoke_capability(self, fqdn: str, **kwargs) -> Any:
        cap = self.resolve_capability(fqdn)
        trace_id = str(kwargs.pop("trace_id", "") or current_trace_id())
        actor = current_actor()
        start = time.time()
        logger.info(f"[CapabilityGateway] invoke fqdn={fqdn} kwargs={kwargs} trace_id={trace_id}")
        try:
            result = cap.handler(**kwargs)
            self.audit.log(
                event_type="capability_invoke",
                actor=actor,
                trace_id=trace_id,
                target=fqdn,
                payload={"args": kwargs},
                status="SUCCESS",
                latency_ms=int((time.time() - start) * 1000),
            )
            capability_invocations_total.labels(capability=fqdn, status="success").inc()
            return result
        except Exception as exc:
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
            capability_invocations_total.labels(capability=fqdn, status="failed").inc()
            logger.warning(f"[CapabilityGateway] invoke failed fqdn={fqdn} err={exc}")
            return f"能力 {fqdn} 调用失败: {exc}"

    def list_skills(self) -> list[dict[str, Any]]:
        return self.skill_registry.list_skills()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        ok = self.skill_registry.set_enabled(skill_id, enabled)
        if ok:
            self.reload()
        return ok
