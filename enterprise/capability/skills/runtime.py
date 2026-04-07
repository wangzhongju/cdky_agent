from __future__ import annotations

"""负责发现技能清单并加载其 Python 入口点。

这个类只关注“技能代码如何被发现并导入”：
- 不负责数据库持久化（那是 SkillRegistryService 的职责）
- 不负责调用治理（那是 CapabilityGateway / MCPAdapter 的职责）
"""

import importlib
import json
from pathlib import Path
from typing import Any

from utils.logger_handler import logger


# manifest 的最小治理字段集合。
# 这些字段用于：
# - 技能身份与版本追踪（id/name/version）
# - 动态导入入口（entrypoint）
# - 能力声明与权限审计（tool_schemas/required_permissions/dependencies）
# - 运行时开关（enabled）
REQUIRED_FIELDS = {
    "id",
    "name",
    "version",
    "entrypoint",
    "tool_schemas",
    "required_permissions",
    "dependencies",
    "enabled",
}


class SkillRuntime:
    """面向文件系统的技能发现与导入加载运行时。"""

    def __init__(self, skill_dir: str = "skills"):
        # 技能根目录。默认是项目下的 skills/。
        self.skill_dir = Path(skill_dir)

    def discover_manifests(self) -> list[dict[str, Any]]:
        """从磁盘收集 manifest，并追加内置 manifest。

        返回值
        - list[dict]：所有可见的技能 manifest（外部 + 内置）

        行为细节
        - 逐个读取 `**/manifest.json`
        - 单个文件解析失败不会中断全局扫描（容错继续）
        - 最后追加 `_builtin_manifests()`
        """
        manifests: list[dict[str, Any]] = []

        # 先扫描项目技能目录。
        if self.skill_dir.exists():
            for manifest_path in self.skill_dir.glob("**/manifest.json"):
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                    # 字段校验失败会抛异常并进入 except。
                    self._validate_manifest(payload, str(manifest_path))
                    manifests.append(payload)
                except Exception as exc:
                    # 记录告警后继续扫描其他技能，避免一个坏清单影响整体启动。
                    logger.warning(f"[SkillRuntime] 加载manifest失败 path={manifest_path} err={exc}")

        # 再拼接内置技能（代码级默认能力）。
        manifests.extend(self._builtin_manifests())
        return manifests

    def load_entrypoint(self, dotted_path: str):
        """导入 manifest 中声明的入口点。

        参数格式
        - dotted_path: "module.submodule:function_name"

        例如
        - enterprise.capability.builtin_skills:register_rag_capability
        """
        module_name, attr_name = dotted_path.rsplit(":", 1)
        mod = importlib.import_module(module_name)
        return getattr(mod, attr_name)

    @staticmethod
    def _validate_manifest(payload: dict, path: str) -> None:
        """当 manifest 缺少必需治理字段时尽早失败。"""
        missing = REQUIRED_FIELDS - set(payload.keys())
        if missing:
            raise ValueError(f"manifest缺少字段{sorted(missing)} path={path}")

    @staticmethod
    def _builtin_manifests() -> list[dict[str, Any]]:
        """返回项目内置的能力包 manifest。"""
        return [
            {
                "id": "builtin.rag",
                "name": "builtin-rag",
                "version": "1.0.0",
                "entrypoint": "enterprise.capability.builtin_skills:register_rag_capability",
                "tool_schemas": [{"name": "rag_summarize", "args": {"query": "string"}}],
                "required_permissions": ["network"],
                "dependencies": ["chroma"],
                "enabled": True,
            },
            {
                "id": "builtin.report",
                "name": "builtin-report",
                "version": "1.0.0",
                "entrypoint": "enterprise.capability.builtin_skills:register_report_capabilities",
                "tool_schemas": [
                    {"name": "get_user_id", "args": {}},
                    {"name": "get_current_month", "args": {}},
                    {"name": "fetch_external_data", "args": {"user_id": "string", "month": "string"}},
                    {"name": "report_writer", "args": {"query": "string", "external_data": "object"}},
                ],
                "required_permissions": ["network"],
                "dependencies": [],
                "enabled": True,
            },
            {
                "id": "builtin.weather",
                "name": "builtin-weather",
                "version": "1.0.0",
                "entrypoint": "enterprise.capability.builtin_skills:register_weather_capabilities",
                "tool_schemas": [
                    {"name": "get_weather", "args": {"city": "string"}},
                    {"name": "get_user_location", "args": {}},
                ],
                "required_permissions": ["network"],
                "dependencies": [],
                "enabled": True,
            },
        ]
