from __future__ import annotations

"""MCP config parsing with backward compatibility mapping."""

from typing import Any

from enterprise.mcp.models import MCPServerConfig
from utils.logger_handler import logger


LEGACY_SERVER_IDS = {"gaode", "enterprise_data"}


def parse_mcp_servers(conf: dict[str, Any]) -> list[MCPServerConfig]:
    rows = conf.get("servers", [])
    servers: list[MCPServerConfig] = []

    for raw in rows:
        server_id = str(raw.get("id", "")).strip()
        if not server_id:
            continue

        transport = str(raw.get("transport", "")).strip().lower()
        namespace = str(raw.get("namespace", server_id)).strip() or server_id
        enabled = bool(raw.get("enabled", True))
        timeout_seconds = int(raw.get("timeout_seconds", 5))
        max_retries = int(raw.get("max_retries", 2))
        failure_threshold = int(raw.get("failure_threshold", 5))
        reset_seconds = int(raw.get("reset_seconds", 30))
        headers = _as_str_dict(raw.get("headers", {}))
        options = _as_any_dict(raw.get("options", {}))
        skill_whitelist = _as_str_list(raw.get("skill_whitelist", []))
        protocol_version = str(raw.get("protocol_version", "2025-11-25")).strip() or "2025-11-25"

        # Phase-1 compatibility: old rows may not include transport.
        if not transport and server_id in LEGACY_SERVER_IDS:
            transport = "legacy"
            logger.warning(
                f"[MCPConfig] server={server_id} uses legacy format; consider adding transport"
            )

        # Secondary compatibility: infer transport from url/command.
        if not transport:
            if raw.get("url"):
                transport = "streamable_http"
            elif raw.get("command"):
                transport = "stdio"

        if not transport:
            logger.warning(f"[MCPConfig] server={server_id} missing transport and is skipped")
            continue

        servers.append(
            MCPServerConfig(
                id=server_id,
                namespace=namespace,
                transport=transport,
                enabled=enabled,
                command=_parse_command(raw.get("command")),
                url=str(raw.get("url", "")).strip(),
                headers=headers,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                failure_threshold=failure_threshold,
                reset_seconds=reset_seconds,
                server_type=str(raw.get("server_type", "")).strip(),
                skill_whitelist=skill_whitelist,
                options=options,
                protocol_version=protocol_version,
            )
        )

    return servers


def _parse_command(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str):
        text = raw.strip()
        return text.split() if text else []
    return []


def _as_str_dict(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if not key:
            continue
        out[key] = str(v)
    return out


def _as_any_dict(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _as_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            out.append(text)
    return out
