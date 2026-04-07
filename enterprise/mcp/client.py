from __future__ import annotations

"""MCP transport clients for stdio, streamable_http, and local server modes."""

import json
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

import requests

from enterprise.mcp.models import MCPTool
from enterprise.mcp.servers.base import LocalMCPServer


class MCPClient(Protocol):
    def initialize(self, protocol_version: str) -> dict[str, Any]:
        ...

    def list_tools(self) -> list[MCPTool]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ...

    def close(self) -> None:
        ...


class StreamableHTTPMCPClient:
    """JSON-RPC over HTTP client."""

    def __init__(self, *, url: str, headers: dict[str, str], timeout_seconds: int):
        self.url = url
        self.headers = headers
        self.timeout_seconds = timeout_seconds

    def initialize(self, protocol_version: str) -> dict[str, Any]:
        return self._request(
            "initialize",
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "cdky-agent", "version": "2.0.0"},
            },
        )

    def list_tools(self) -> list[MCPTool]:
        result = self._request_with_fallback("tools/list", "list_tools", {})
        return _parse_tools(result)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._request_with_fallback(
            "tools/call",
            "call_tool",
            {"name": name, "arguments": arguments},
        )
        return _parse_call_result(result)

    def close(self) -> None:
        return

    def _request_with_fallback(self, primary: str, fallback: str, params: dict[str, Any]) -> Any:
        try:
            return self._request(primary, params)
        except Exception:
            return self._request(fallback, params)

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        req_id = str(uuid.uuid4())
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        resp = requests.post(
            self.url,
            headers={"Content-Type": "application/json", **self.headers},
            json=payload,
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"{method} failed: {body['error']}")
        return body.get("result", {})


class StdioMCPClient:
    """JSON-RPC over stdio client."""

    def __init__(self, *, command: list[str], timeout_seconds: int):
        if not command:
            raise ValueError("stdio command is required")
        self.command = command
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def initialize(self, protocol_version: str) -> dict[str, Any]:
        return self._request(
            "initialize",
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "cdky-agent", "version": "2.0.0"},
            },
        )

    def list_tools(self) -> list[MCPTool]:
        result = self._request_with_fallback("tools/list", "list_tools", {})
        return _parse_tools(result)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._request_with_fallback(
            "tools/call",
            "call_tool",
            {"name": name, "arguments": arguments},
        )
        return _parse_call_result(result)

    def close(self) -> None:
        proc = self._process
        self._process = None
        if not proc:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _request_with_fallback(self, primary: str, fallback: str, params: dict[str, Any]) -> Any:
        try:
            return self._request(primary, params)
        except Exception:
            return self._request(fallback, params)

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        with self._lock:
            self._ensure_process()
            assert self._process is not None and self._process.stdin is not None

            req_id = str(uuid.uuid4())
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._process.stdin.flush()

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._wait_response, req_id)
                try:
                    body = future.result(timeout=self.timeout_seconds)
                except Exception as exc:
                    self.close()
                    raise RuntimeError(f"stdio mcp timeout method={method}") from exc

            if "error" in body:
                raise RuntimeError(f"{method} failed: {body['error']}")
            return body.get("result", {})

    def _ensure_process(self) -> None:
        if self._process and self._process.poll() is None:
            return
        self.close()
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def _wait_response(self, request_id: str) -> dict[str, Any]:
        assert self._process is not None and self._process.stdout is not None
        start = time.time()
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError("stdio mcp closed unexpectedly")
            try:
                body = json.loads(line.strip())
            except Exception:
                continue
            if body.get("id") == request_id:
                return body
            if time.time() - start > self.timeout_seconds:
                raise RuntimeError("stdio mcp response timeout")


class LocalMCPClient:
    """In-process local MCP server adapter."""

    def __init__(self, server: LocalMCPServer):
        self.server = server

    def initialize(self, protocol_version: str) -> dict[str, Any]:
        return self.server.initialize(protocol_version)

    def list_tools(self) -> list[MCPTool]:
        return self.server.list_tools()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self.server.call_tool(name, arguments)

    def close(self) -> None:
        return


def _parse_tools(result: Any) -> list[MCPTool]:
    raw_tools = result.get("tools", []) if isinstance(result, dict) else result
    if not isinstance(raw_tools, list):
        raise RuntimeError("invalid tools/list response")
    tools: list[MCPTool] = []
    for item in raw_tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        desc = str(item.get("description", "")).strip()
        schema = item.get("inputSchema") or item.get("input_schema") or {}
        if not isinstance(schema, dict):
            schema = {}
        tools.append(MCPTool(name=name, description=desc, input_schema=schema))
    return tools


def _parse_call_result(result: Any) -> Any:
    # MCP 2025 style.
    if isinstance(result, dict) and "structuredContent" in result:
        return result.get("structuredContent")

    # Compatible with content blocks.
    if isinstance(result, dict) and "content" in result and isinstance(result["content"], list):
        texts: list[str] = []
        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text", "")))
        if texts:
            return "\n".join(t for t in texts if t)

    # Legacy payload passthrough.
    return result
