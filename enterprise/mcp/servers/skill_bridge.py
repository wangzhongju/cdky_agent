from __future__ import annotations

"""Local MCP server that exposes whitelisted skills as MCP tools."""

from typing import Any, Callable

from enterprise.mcp.capability import Capability
from enterprise.mcp.models import MCPTool


class SkillBridgeMCPServer:
    def __init__(
        self,
        *,
        namespace: str,
        whitelist: list[str],
        list_skill_capabilities: Callable[[], list[Capability]],
        invoke_skill_capability: Callable[[str, dict[str, Any]], Any],
    ):
        self.namespace = namespace
        self.whitelist = set(whitelist)
        self._list_skill_capabilities = list_skill_capabilities
        self._invoke_skill_capability = invoke_skill_capability
        self._tool_to_fqdn: dict[str, str] = {}

    def initialize(self, protocol_version: str) -> dict[str, Any]:
        return {
            "protocolVersion": protocol_version,
            "serverInfo": {"name": "skill-bridge-local", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }

    def list_tools(self) -> list[MCPTool]:
        tools: list[MCPTool] = []
        self._tool_to_fqdn = {}

        for cap in self._list_skill_capabilities():
            if cap.source != "skill":
                continue
            if self.whitelist and cap.fqdn not in self.whitelist:
                continue

            tool_name = cap.fqdn.replace(".", "__")
            self._tool_to_fqdn[tool_name] = cap.fqdn
            tools.append(
                MCPTool(
                    name=tool_name,
                    description=cap.description or f"Skill bridge for {cap.fqdn}",
                    input_schema={
                        "type": "object",
                        "properties": cap.schema if isinstance(cap.schema, dict) else {},
                    },
                )
            )
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        fqdn = self._tool_to_fqdn.get(name)
        if not fqdn:
            raise ValueError(f"tool not found: {name}")
        return self._invoke_skill_capability(fqdn, arguments)
