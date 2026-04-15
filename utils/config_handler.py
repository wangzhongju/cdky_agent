from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from utils.path_tool import get_abs_path


def _load_single_dotenv(env_path: Path, encoding: str = "utf-8") -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding=encoding).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, value)


def load_dotenv(encoding: str = "utf-8") -> None:
    for env_path in (
        Path(get_abs_path(".env")),
        Path(get_abs_path("docker/.env")),
    ):
        _load_single_dotenv(env_path, encoding=encoding)


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(v) for v in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value


def load_yaml_config(relative_path: str, encoding: str = "utf-8") -> dict[str, Any]:
    with open(get_abs_path(relative_path), "r", encoding=encoding) as f:
        payload = yaml.load(f, Loader=yaml.FullLoader) or {}
    return _resolve_env_placeholders(payload)


load_dotenv()
enterprise_conf = load_yaml_config("config/enterprise.yml")
mcp_conf = load_yaml_config("config/mcp.yml")
prompts_conf = load_yaml_config("config/prompts.yml")
