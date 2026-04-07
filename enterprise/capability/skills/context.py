from __future__ import annotations

"""Runtime context object passed to skill entrypoints."""

from typing import Any, Callable

from enterprise.governance.tracing import ACTOR_CTX, TRACE_ID_CTX, current_actor, current_trace_id
from utils.config_handler import enterprise_conf, mcp_conf


class SkillContext:
    def __init__(self, mcp_invoker: Callable[[str, dict[str, Any]], Any]):
        self._mcp_invoker = mcp_invoker

    @property
    def configs(self) -> dict[str, Any]:
        return {
            "enterprise": enterprise_conf,
            "mcp": mcp_conf,
        }

    def read_trace(self) -> str:
        return current_trace_id()

    def read_actor(self) -> str:
        return current_actor()

    def write_trace(self, trace_id: str) -> None:
        TRACE_ID_CTX.set(trace_id)

    def write_actor(self, actor: str) -> None:
        ACTOR_CTX.set(actor)

    def call_mcp(self, fqdn: str, **kwargs) -> Any:
        return self._mcp_invoker(fqdn, kwargs)
