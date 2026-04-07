from __future__ import annotations

"""MCP runtime for server connection, tool discovery, and invocation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from agent.tools.agent_tools import fetch_external_data, get_user_location, get_weather
from enterprise.capability.mcp.circuit_breaker import CircuitBreaker
from enterprise.capability.types import Capability
from enterprise.mcp.client import LocalMCPClient, MCPClient, StdioMCPClient, StreamableHTTPMCPClient
from enterprise.mcp.config import parse_mcp_servers
from enterprise.mcp.models import MCPServerConfig, MCPServerStatus, MCPTool
from enterprise.mcp.servers import SkillBridgeMCPServer, WebFetchMCPServer
from utils.config_handler import mcp_conf
from utils.logger_handler import logger


@dataclass
class _SkillBridgeCallbacks:
    list_skill_capabilities: Callable[[], list[Capability]] | None = None
    invoke_skill_capability: Callable[[str, dict[str, Any]], Any] | None = None


class MCPRuntime:
    """Builds MCP capabilities from configured servers."""

    def __init__(self, conf: dict[str, Any] | None = None):
        self._raw_conf = conf if conf is not None else mcp_conf
        self._clients: dict[str, MCPClient] = {}
        self._capabilities: dict[str, Capability] = {}
        self._statuses: dict[str, MCPServerStatus] = {}
        self._bridge_callbacks = _SkillBridgeCallbacks()

    def reload(
        self,
        *,
        conf: dict[str, Any] | None = None,
        list_skill_capabilities: Callable[[], list[Capability]] | None = None,
        invoke_skill_capability: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        if conf is not None:
            self._raw_conf = conf
        if list_skill_capabilities is not None:
            self._bridge_callbacks.list_skill_capabilities = list_skill_capabilities
        if invoke_skill_capability is not None:
            self._bridge_callbacks.invoke_skill_capability = invoke_skill_capability

        self.close()
        self._capabilities = {}
        self._statuses = {}

        for cfg in parse_mcp_servers(self._raw_conf):
            status = MCPServerStatus(
                id=cfg.id,
                namespace=cfg.namespace,
                transport=cfg.transport,
                enabled=cfg.enabled,
            )
            self._statuses[cfg.id] = status
            if not cfg.enabled:
                continue

            try:
                if cfg.transport == "legacy":
                    self._load_legacy_server(cfg, status)
                    continue

                client = self._build_client(cfg)
                self._clients[cfg.id] = client

                client.initialize(cfg.protocol_version)
                tools = client.list_tools()
                for tool in tools:
                    self._register_mcp_tool(cfg, client, tool)

                status.connected = True
                status.discovered_tools = len(tools)
                status.last_error = ""
                status.last_refresh_at = datetime.utcnow()
            except Exception as exc:
                status.connected = False
                status.last_error = str(exc)
                status.last_refresh_at = datetime.utcnow()
                logger.warning(f"[MCPRuntime] load server failed id={cfg.id} err={exc}")

    def close(self) -> None:
        for client in self._clients.values():
            try:
                client.close()
            except Exception:
                continue
        self._clients = {}

    def list_capabilities(self) -> list[Capability]:
        return list(self._capabilities.values())

    def list_server_statuses(self) -> list[dict[str, Any]]:
        return [status.to_dict() for status in sorted(self._statuses.values(), key=lambda x: x.id)]

    def invoke_capability(self, fqdn: str, **kwargs) -> Any:
        cap = self._capabilities.get(fqdn)
        if not cap:
            raise KeyError(f"MCP capability not found: {fqdn}")
        return cap.handler(**kwargs)

    def _build_client(self, cfg: MCPServerConfig) -> MCPClient:
        if cfg.transport == "streamable_http":
            if not cfg.url:
                raise ValueError(f"server={cfg.id} missing url")
            return StreamableHTTPMCPClient(
                url=cfg.url,
                headers=cfg.headers,
                timeout_seconds=cfg.timeout_seconds,
            )
        if cfg.transport == "stdio":
            if not cfg.command:
                raise ValueError(f"server={cfg.id} missing command")
            return StdioMCPClient(
                command=cfg.command,
                timeout_seconds=cfg.timeout_seconds,
            )
        if cfg.transport == "local":
            return LocalMCPClient(self._build_local_server(cfg))
        raise ValueError(f"unsupported transport: {cfg.transport}")

    def _build_local_server(self, cfg: MCPServerConfig):
        if cfg.server_type == "web_fetch":
            return WebFetchMCPServer(
                max_response_bytes=int(cfg.options.get("max_response_bytes", 1_000_000)),
                default_max_chars=int(cfg.options.get("default_max_chars", 4_000)),
            )

        if cfg.server_type == "skill_bridge":
            if not self._bridge_callbacks.list_skill_capabilities or not self._bridge_callbacks.invoke_skill_capability:
                raise ValueError("skill_bridge requires skill callbacks")
            return SkillBridgeMCPServer(
                namespace=cfg.namespace,
                whitelist=cfg.skill_whitelist,
                list_skill_capabilities=self._bridge_callbacks.list_skill_capabilities,
                invoke_skill_capability=self._bridge_callbacks.invoke_skill_capability,
            )

        raise ValueError(f"unsupported local server_type: {cfg.server_type}")

    def _register_mcp_tool(self, cfg: MCPServerConfig, client: MCPClient, tool: MCPTool) -> None:
        fqdn = f"{cfg.namespace}.{tool.name}"
        breaker = CircuitBreaker(
            failure_threshold=cfg.failure_threshold,
            reset_seconds=cfg.reset_seconds,
        )

        def handler(**kwargs):
            if not breaker.allow():
                raise RuntimeError(f"MCP breaker open: {fqdn}")

            last_error: Exception | None = None
            for _ in range(cfg.max_retries + 1):
                try:
                    result = client.call_tool(tool.name, kwargs)
                    breaker.record_success()
                    return result
                except Exception as exc:
                    last_error = exc
            breaker.record_failure()
            raise RuntimeError(f"MCP call failed {fqdn}: {last_error}")

        self._capabilities[fqdn] = Capability(
            name=tool.name,
            namespace=cfg.namespace,
            description=tool.description or f"MCP Tool {tool.name}",
            source="mcp",
            schema=tool.input_schema,
            handler=handler,
        )

    def _load_legacy_server(self, cfg: MCPServerConfig, status: MCPServerStatus) -> None:
        count = 0
        if cfg.id == "gaode":
            self._register_legacy_capability(
                cfg=cfg,
                name="get_weather",
                description="Gaode weather MCP (legacy compatibility)",
                schema={"city": "string"},
                call=lambda city: get_weather.invoke({"city": city}),
            )
            self._register_legacy_capability(
                cfg=cfg,
                name="get_user_location",
                description="Gaode location MCP (legacy compatibility)",
                schema={},
                call=lambda: get_user_location.invoke({}),
            )
            count = 2
        elif cfg.id == "enterprise_data":
            self._register_legacy_capability(
                cfg=cfg,
                name="fetch_external_data",
                description="Enterprise data MCP (legacy compatibility)",
                schema={"user_id": "string", "month": "string"},
                call=lambda user_id, month: fetch_external_data.invoke({"user_id": user_id, "month": month}),
            )
            count = 1
        else:
            raise ValueError(f"unknown legacy server id={cfg.id}")

        status.connected = True
        status.discovered_tools = count
        status.last_error = ""
        status.last_refresh_at = datetime.utcnow()

    def _register_legacy_capability(
        self,
        *,
        cfg: MCPServerConfig,
        name: str,
        description: str,
        schema: dict[str, Any],
        call: Callable[..., Any],
    ) -> None:
        fqdn = f"{cfg.namespace}.{name}"
        breaker = CircuitBreaker(
            failure_threshold=cfg.failure_threshold,
            reset_seconds=cfg.reset_seconds,
        )

        def handler(**kwargs):
            if not breaker.allow():
                raise RuntimeError(f"MCP breaker open: {fqdn}")

            last_error: Exception | None = None
            for _ in range(cfg.max_retries + 1):
                try:
                    result = call(**kwargs)
                    breaker.record_success()
                    return result
                except Exception as exc:
                    last_error = exc
            breaker.record_failure()
            raise RuntimeError(f"MCP call failed {fqdn}: {last_error}")

        self._capabilities[fqdn] = Capability(
            name=name,
            namespace=cfg.namespace,
            description=description,
            source="mcp",
            schema=schema,
            handler=handler,
        )
