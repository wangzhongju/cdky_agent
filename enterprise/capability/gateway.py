from __future__ import annotations

"""Unified capability catalog and invocation gateway."""

import inspect
import time
from typing import Any

from enterprise.capability.skills.context import SkillContext
from enterprise.capability.skills.registry import SkillRegistryService
from enterprise.capability.skills.runtime import SkillRuntime
from enterprise.capability.types import Capability
from enterprise.governance.audit import AuditService
from enterprise.governance.prometheus_metrics import capability_invocations_total
from enterprise.governance.tracing import current_actor, current_trace_id
from enterprise.mcp.runtime import MCPRuntime
from utils.config_handler import mcp_conf, load_mcp_config
from utils.logger_handler import logger


class CapabilityGateway:
    """Aggregates skill and MCP capabilities behind one API."""

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}
        self._skill_capabilities: dict[str, Capability] = {}

        self.skill_runtime = SkillRuntime()
        self.skill_registry = SkillRegistryService()
        self.mcp_runtime = MCPRuntime(mcp_conf)
        self.audit = AuditService()
        self.skill_context = SkillContext(self._invoke_mcp_from_skill)

        self._load_all()

    def _load_all(self) -> None:
        manifests = self.skill_runtime.discover_manifests()
        self.skill_registry.sync_manifests(manifests)

        self._capabilities = {}
        self._skill_capabilities = {}

        enabled_map = {row["id"]: row for row in self.skill_registry.list_skills()}
        for manifest in manifests:
            row = enabled_map.get(manifest["id"])
            if row and not row.get("enabled", True):
                continue
            loader = self.skill_runtime.load_entrypoint(manifest["entrypoint"])
            for cap in self._load_skill_capabilities(loader):
                self._skill_capabilities[cap.fqdn] = cap
                self._capabilities[cap.fqdn] = cap

        self._reload_mcp_only()

    def _load_skill_capabilities(self, loader) -> list[Capability]:
        """Support both old no-arg and new SkillContext-aware entrypoints."""
        try:
            sig = inspect.signature(loader)
            requires_args = len(sig.parameters) > 0
        except Exception:
            requires_args = False

        caps = loader(self.skill_context) if requires_args else loader()
        if not isinstance(caps, list):
            raise ValueError(f"skill entrypoint must return list[Capability], got={type(caps)}")
        return caps

    def _reload_mcp_only(self, conf: dict[str, Any] | None = None) -> None:
        if conf is None:
            conf = load_mcp_config()
        self.mcp_runtime.reload(
            conf=conf,
            list_skill_capabilities=self._list_skill_capabilities,
            invoke_skill_capability=self._invoke_skill_capability_for_bridge,
        )

        # Drop old MCP entries then merge current runtime snapshot.
        self._capabilities = {k: v for k, v in self._capabilities.items() if v.source != "mcp"}
        for cap in self.mcp_runtime.list_capabilities():
            self._capabilities[cap.fqdn] = cap

    def _list_skill_capabilities(self) -> list[Capability]:
        return list(self._skill_capabilities.values())

    def _invoke_skill_capability_for_bridge(self, fqdn: str, kwargs: dict[str, Any]) -> Any:
        cap = self._skill_capabilities.get(fqdn)
        if not cap:
            raise KeyError(f"skill capability not found: {fqdn}")
        return cap.handler(**kwargs)

    def _invoke_mcp_from_skill(self, fqdn: str, kwargs: dict[str, Any]) -> Any:
        return self.mcp_runtime.invoke_capability(fqdn, **kwargs)

    def reload(self) -> None:
        self._load_all()

    def reload_mcp(self) -> dict[str, Any]:
        self._reload_mcp_only()
        return {
            "status": "ok",
            "servers": self.list_mcp_servers(),
            "mcp_capabilities": len([cap for cap in self._capabilities.values() if cap.source == "mcp"]),
        }

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        return self.mcp_runtime.list_server_statuses()

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
        cap = self._capabilities.get(fqdn)
        if not cap:
            raise KeyError(f"capability not registered: {fqdn}")
        return cap

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
            return f"Capability {fqdn} invoke failed: {exc}"

    def list_skills(self) -> list[dict[str, Any]]:
        return self.skill_registry.list_skills()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        ok = self.skill_registry.set_enabled(skill_id, enabled)
        if ok:
            self.reload()
        return ok
