from __future__ import annotations

from enterprise.mcp.config import parse_mcp_servers
from enterprise.mcp.runtime import MCPRuntime
from skills.custom_web.entrypoint import register_web_skills


def test_parse_mcp_servers_legacy_compat():
    conf = {
        "servers": [
            {"id": "gaode", "namespace": "gaode", "enabled": True},
            {"id": "x1", "namespace": "x", "transport": "local", "server_type": "web_fetch", "enabled": True},
        ]
    }
    rows = parse_mcp_servers(conf)
    by_id = {row.id: row for row in rows}
    assert by_id["gaode"].transport == "legacy"
    assert by_id["x1"].transport == "local"
    assert by_id["x1"].server_type == "web_fetch"


def test_mcp_runtime_local_web_fetch_discovery():
    runtime = MCPRuntime(
        {
            "servers": [
                {
                    "id": "web_fetch_local",
                    "namespace": "web",
                    "transport": "local",
                    "server_type": "web_fetch",
                    "enabled": True,
                }
            ]
        }
    )
    runtime.reload()
    caps = runtime.list_capabilities()
    assert any(cap.fqdn == "web.fetch_page" for cap in caps)
    statuses = runtime.list_server_statuses()
    assert statuses and statuses[0]["connected"] is True


class _FakeContext:
    def call_mcp(self, fqdn: str, **kwargs):
        assert fqdn == "web.fetch_page"
        return {
            "status_code": 200,
            "title": "Demo Page",
            "text": "hello world " * 100,
            "links": ["/a", "/b"],
        }


def test_custom_web_skill_uses_context_call_mcp():
    caps = register_web_skills(_FakeContext())
    assert len(caps) == 1
    result = caps[0].handler("summarize this page https://example.com/page")
    assert "Demo Page" in result
