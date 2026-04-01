from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Capability:
    name: str
    namespace: str
    description: str
    handler: Callable[..., Any]
    source: str
    schema: dict = field(default_factory=dict)
    enabled: bool = True

    @property
    def fqdn(self) -> str:
        return f"{self.namespace}.{self.name}"
