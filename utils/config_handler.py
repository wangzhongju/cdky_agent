"""
yaml
k: v
"""
import os
import yaml
from utils.path_tool import get_abs_path
from typing import Any


def _load_single_dotenv(env_path: str, encoding: str = "utf-8"):
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding=encoding) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')

            if key.startswith("export "):
                key = key[len("export "):].strip()

            if key:
                os.environ.setdefault(key, value)


def load_dotenv(encoding: str = "utf-8"):
    env_candidates = (
        get_abs_path(".env"),
        get_abs_path("docker/.env"),
    )

    for env_path in env_candidates:
        _load_single_dotenv(env_path, encoding=encoding)


def load_rag_config(config_path: str=get_abs_path("config/rag.yml"), encoding: str="utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return _resolve_env_placeholders(yaml.load(f, Loader=yaml.FullLoader))


def load_chroma_config(config_path: str=get_abs_path("config/chroma.yml"), encoding: str="utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return _resolve_env_placeholders(yaml.load(f, Loader=yaml.FullLoader))


def load_prompts_config(config_path: str=get_abs_path("config/prompts.yml"), encoding: str="utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return _resolve_env_placeholders(yaml.load(f, Loader=yaml.FullLoader))


def load_agent_config(config_path: str=get_abs_path("config/agent.yml"), encoding: str="utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return _resolve_env_placeholders(yaml.load(f, Loader=yaml.FullLoader))


def load_enterprise_config(config_path: str = get_abs_path("config/enterprise.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return _resolve_env_placeholders(yaml.load(f, Loader=yaml.FullLoader))


def load_mcp_config(config_path: str = get_abs_path("config/mcp.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return _resolve_env_placeholders(yaml.load(f, Loader=yaml.FullLoader))


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_env_placeholders(v) for v in value]

    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return os.getenv(env_name, "")

    return value


def apply_env_overrides(config: dict):
    gaode_key = os.getenv("GAODE_MCP_KEY", "").strip()
    if gaode_key:
        config["gaodekey"] = gaode_key

    return config


load_dotenv()
rag_conf = load_rag_config()
chroma_conf = load_chroma_config()
prompts_conf = load_prompts_config()
agent_conf = apply_env_overrides(load_agent_config())
enterprise_conf = load_enterprise_config()
mcp_conf = load_mcp_config()


if __name__ == '__main__':
    print(rag_conf["chat_model_name"])
