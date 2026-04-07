from __future__ import annotations

"""Local MCP server that provides static web fetch capability."""

import ipaddress
import re
import socket
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests

from enterprise.mcp.models import MCPTool
from utils.logger_handler import logger

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


class WebFetchMCPServer:
    TOOL_NAME = "fetch_page"

    def __init__(self, *, max_response_bytes: int = 1_000_000, default_max_chars: int = 4_000):
        self.max_response_bytes = max(64_000, int(max_response_bytes))
        self.default_max_chars = max(300, int(default_max_chars))

    def initialize(self, protocol_version: str) -> dict[str, Any]:
        return {
            "protocolVersion": protocol_version,
            "serverInfo": {"name": "web-fetch-local", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }

    def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(
                name=self.TOOL_NAME,
                description="Fetch and parse web page content",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer", "minimum": 300, "maximum": 20000},
                        "extract_links": {"type": "boolean"},
                        "timeout": {"type": "number", "minimum": 1, "maximum": 20},
                    },
                    "required": ["url"],
                },
            )
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != self.TOOL_NAME:
            raise ValueError(f"unknown tool: {name}")

        url = str(arguments.get("url", "")).strip()
        if not _URL_RE.fullmatch(url):
            raise ValueError("invalid url: only http/https is allowed")

        self._guard_url(url)
        max_chars = int(arguments.get("max_chars", self.default_max_chars))
        max_chars = max(300, min(max_chars, 20_000))
        extract_links = bool(arguments.get("extract_links", False))
        timeout = float(arguments.get("timeout", 8))
        timeout = max(1.0, min(timeout, 20.0))

        resp = requests.get(
            url,
            headers={"User-Agent": "cdky-agent-web-fetch/1.0"},
            timeout=timeout,
            stream=True,
            allow_redirects=True,
        )
        content_type = str(resp.headers.get("Content-Type", "")).lower()
        if not self._is_allowed_content_type(content_type):
            raise RuntimeError(f"unsupported content type: {content_type or 'unknown'}")

        chunks: list[bytes] = []
        size = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            size += len(chunk)
            if size > self.max_response_bytes:
                raise RuntimeError("response too large")
            chunks.append(chunk)

        payload = b"".join(chunks)
        text = payload.decode(resp.encoding or "utf-8", errors="ignore")
        title = _extract_title(text)
        cleaned = _clean_text(text)[:max_chars]
        links = _extract_links(text) if extract_links else []

        return {
            "url": resp.url,
            "status_code": int(resp.status_code),
            "content_type": content_type,
            "title": title,
            "text": cleaned,
            "links": links,
        }

    def _guard_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("only http/https is allowed")

        host = (parsed.hostname or "").strip()
        if not host:
            raise ValueError("invalid url host")
        if host.lower() == "localhost":
            raise ValueError("private host is blocked")

        for ip in _resolve_host_ips(host):
            if _is_private_ip(ip):
                raise ValueError(f"private address is blocked: {ip}")

    @staticmethod
    def _is_allowed_content_type(content_type: str) -> bool:
        if not content_type:
            return True
        allow = ("text/html", "text/plain", "application/json", "application/xhtml+xml")
        return any(content_type.startswith(prefix) for prefix in allow)


def _resolve_host_ips(host: str) -> set[str]:
    ips: set[str] = set()
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as exc:
        logger.warning(f"[WebFetchMCP] resolve host failed host={host} err={exc}")
        return ips

    for item in infos:
        sockaddr = item[4]
        if not sockaddr:
            continue
        ip = str(sockaddr[0]).strip()
        if ip:
            ips.add(ip)
    return ips


def _is_private_ip(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", unescape(m.group(1))).strip()[:300]


def _clean_text(html: str) -> str:
    no_script = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    no_style = re.sub(r"<style[\s\S]*?</style>", " ", no_script, flags=re.IGNORECASE)
    plain = re.sub(r"<[^>]+>", " ", no_style)
    plain = unescape(plain)
    return re.sub(r"\s+", " ", plain).strip()


def _extract_links(html: str) -> list[str]:
    parser = _LinkCollector()
    parser.feed(html)
    out: list[str] = []
    seen: set[str] = set()
    for link in parser.links:
        text = str(link).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= 30:
            break
    return out
