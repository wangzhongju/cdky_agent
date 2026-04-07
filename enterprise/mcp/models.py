from __future__ import annotations

"""Shared models for MCP runtime."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServerConfig:
    id: str
    namespace: str
    transport: str
    enabled: bool = True
    command: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 5
    max_retries: int = 2
    failure_threshold: int = 5
    reset_seconds: int = 30
    server_type: str = ""
    skill_whitelist: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = "2025-11-25"


@dataclass
class MCPServerStatus:
    id: str
    namespace: str
    transport: str
    enabled: bool
    connected: bool = False
    discovered_tools: int = 0
    last_error: str = ""
    last_refresh_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "transport": self.transport,
            "enabled": self.enabled,
            "connected": self.connected,
            "discovered_tools": self.discovered_tools,
            "last_error": self.last_error,
            "last_refresh_at": self.last_refresh_at.isoformat() if self.last_refresh_at else "",
        }
