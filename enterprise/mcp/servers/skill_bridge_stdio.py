from __future__ import annotations

"""Expose whitelisted local skills as an MCP stdio server."""

import json
import os
import sys
import traceback
import uuid
from typing import Any

from enterprise.capability.gateway import CapabilityGateway


def main() -> None:
    gateway = CapabilityGateway()
    whitelist = _parse_whitelist(os.getenv("SKILL_BRIDGE_WHITELIST", ""))
    tool_to_fqdn = _build_tool_map(gateway, whitelist)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req: dict[str, Any] | None = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = str(req.get("method", ""))
            params = req.get("params", {}) or {}
            result = _handle(gateway, method, params, tool_to_fqdn)
            _write({"jsonrpc": "2.0", "id": req_id, "result": result})
        except Exception as exc:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req.get("id") if isinstance(req, dict) else str(uuid.uuid4()),
                    "error": {"code": -32000, "message": str(exc)},
                }
            )


def _parse_whitelist(raw: str) -> set[str]:
    out: set[str] = set()
    for item in raw.split(","):
        text = item.strip()
        if text:
            out.add(text)
    return out


def _build_tool_map(gateway: CapabilityGateway, whitelist: set[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for cap in gateway.list_capabilities():
        if cap.get("source") != "skill":
            continue
        fqdn = str(cap.get("fqdn", ""))
        if not fqdn:
            continue
        if whitelist and fqdn not in whitelist:
            continue
        mapping[fqdn.replace(".", "__")] = fqdn
    return mapping


def _handle(
    gateway: CapabilityGateway,
    method: str,
    params: dict[str, Any],
    tool_to_fqdn: dict[str, str],
) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-11-25"),
            "serverInfo": {"name": "skills-bridge-stdio", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }

    if method in {"tools/list", "list_tools"}:
        tools: list[dict[str, Any]] = []
        for tool_name, fqdn in tool_to_fqdn.items():
            cap = gateway.resolve_capability(fqdn)
            tools.append(
                {
                    "name": tool_name,
                    "description": cap.description,
                    "inputSchema": {"type": "object", "properties": cap.schema if isinstance(cap.schema, dict) else {}},
                }
            )
        return {"tools": tools}

    if method in {"tools/call", "call_tool"}:
        name = str(params.get("name", "")).strip()
        args = params.get("arguments", {}) or {}
        if name not in tool_to_fqdn:
            raise ValueError(f"tool not found: {name}")
        fqdn = tool_to_fqdn[name]
        result = gateway.invoke_capability(fqdn, **args)
        return {"structuredContent": {"result": result}}

    raise ValueError(f"unsupported method: {method}")


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise
