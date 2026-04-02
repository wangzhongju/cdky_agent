from __future__ import annotations

"""可调用能力的共享运行时模型。"""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Capability:
    """对可执行 Skill 或 MCP 工具的统一描述。"""

    name: str
    namespace: str
    description: str
    handler: Callable[..., Any]
    source: str
    schema: dict = field(default_factory=dict)
    enabled: bool = True

    @property
    def fqdn(self) -> str:
        """返回编排器用于路由的标准全限定名。"""
        return f"{self.namespace}.{self.name}"
