from __future__ import annotations

"""Protocol for local in-process MCP servers."""

from typing import Any, Protocol

from enterprise.mcp.models import MCPTool


class LocalMCPServer(Protocol):
    def initialize(self, protocol_version: str) -> dict[str, Any]:
        ...

    def list_tools(self) -> list[MCPTool]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ...
