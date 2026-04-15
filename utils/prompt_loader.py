from __future__ import annotations

from utils.config_handler import prompts_conf
from utils.path_tool import get_abs_path


def _load_prompt(config_key: str) -> str:
    path = get_abs_path(prompts_conf[config_key])
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_system_prompt() -> str:
    return _load_prompt("system_prompt_path")
