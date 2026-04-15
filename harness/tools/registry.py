from __future__ import annotations

from pathlib import Path

from harness.knowledge.service import KnowledgeService, ReportDataService
from harness.tools.base import ToolRegistry
from harness.tools.core import (
    GlobSearchTool,
    GrepSearchTool,
    HttpFetchTool,
    ReadFileTool,
    ShellCommandTool,
)
from harness.tools.domain import (
    FetchExternalReportDataTool,
    GaodeGetLocationTool,
    GaodeGetWeatherTool,
    KnowledgeSearchTool,
)


def build_default_tool_registry(
    cwd: str | Path | None = None,
    *,
    knowledge_service: KnowledgeService | None = None,
    report_service: ReportDataService | None = None,
) -> ToolRegistry:
    del cwd
    registry = ToolRegistry()
    knowledge_service = knowledge_service or KnowledgeService()
    report_service = report_service or ReportDataService()

    registry.register(ReadFileTool())
    registry.register(GlobSearchTool())
    registry.register(GrepSearchTool())
    registry.register(ShellCommandTool())
    registry.register(HttpFetchTool())
    registry.register(KnowledgeSearchTool(knowledge_service))
    registry.register(FetchExternalReportDataTool(report_service))
    registry.register(GaodeGetWeatherTool())
    registry.register(GaodeGetLocationTool())
    return registry
