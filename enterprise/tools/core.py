from __future__ import annotations

import asyncio
import csv
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field

from enterprise.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from utils.config_handler import mcp_conf
from utils.path_tool import get_abs_path


class BashToolInput(BaseModel):
    command: str
    cwd: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=300)


class BashTool(BaseTool):
    name = "bash"
    description = "Run a shell command in the local repository."
    input_model = BashToolInput

    async def execute(self, arguments: BashToolInput, context: ToolExecutionContext) -> ToolResult:
        cwd = Path(arguments.cwd).resolve() if arguments.cwd else context.cwd
        process = await asyncio.create_subprocess_shell(
            arguments.command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=arguments.timeout_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ToolResult(output=f"Command timed out after {arguments.timeout_seconds}s", is_error=True)
        output = "\n".join(
            part
            for part in (
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
            if part
        ) or "(no output)"
        return ToolResult(output=output, is_error=process.returncode != 0, metadata={"returncode": process.returncode})


class ReadFileInput(BaseModel):
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a text file from the workspace."
    input_model = ReadFileInput

    def is_read_only(self, arguments: ReadFileInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: ReadFileInput, context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)
        if not path.exists() or not path.is_file():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        text = path.read_text(encoding="utf-8", errors="replace")
        if arguments.start_line or arguments.end_line:
            lines = text.splitlines()
            start = (arguments.start_line or 1) - 1
            end = arguments.end_line or len(lines)
            text = "\n".join(lines[start:end])
        return ToolResult(output=text[:20000] if text else "")


class WriteFileInput(BaseModel):
    path: str
    content: str


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write the full content of a file."
    input_model = WriteFileInput

    async def execute(self, arguments: WriteFileInput, context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments.content, encoding="utf-8")
        return ToolResult(output=f"Wrote {path}")


class EditFileInput(BaseModel):
    path: str
    old_text: str
    new_text: str


class EditFileTool(BaseTool):
    name = "edit_file"
    description = "Replace exact text in a file."
    input_model = EditFileInput

    async def execute(self, arguments: EditFileInput, context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        text = path.read_text(encoding="utf-8", errors="replace")
        if arguments.old_text not in text:
            return ToolResult(output="old_text was not found", is_error=True)
        path.write_text(text.replace(arguments.old_text, arguments.new_text, 1), encoding="utf-8")
        return ToolResult(output=f"Edited {path}")


class GlobInput(BaseModel):
    pattern: str
    root: str | None = None


class GlobTool(BaseTool):
    name = "glob"
    description = "Find files using a glob pattern."
    input_model = GlobInput

    def is_read_only(self, arguments: GlobInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: GlobInput, context: ToolExecutionContext) -> ToolResult:
        root = _resolve_path(context.cwd, arguments.root) if arguments.root else context.cwd
        matches = sorted(str(path.relative_to(root)) for path in root.glob(arguments.pattern))
        return ToolResult(output="\n".join(matches) if matches else "(no matches)")


class GrepInput(BaseModel):
    pattern: str
    root: str | None = None
    file_glob: str = "**/*"
    case_sensitive: bool = True
    limit: int = Field(default=200, ge=1, le=1000)


class GrepTool(BaseTool):
    name = "grep"
    description = "Search file contents with a regular expression."
    input_model = GrepInput

    def is_read_only(self, arguments: GrepInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: GrepInput, context: ToolExecutionContext) -> ToolResult:
        root = _resolve_path(context.cwd, arguments.root) if arguments.root else context.cwd
        flags = 0 if arguments.case_sensitive else re.IGNORECASE
        compiled = re.compile(arguments.pattern, flags)
        results: list[str] = []
        for path in root.glob(arguments.file_glob):
            if len(results) >= arguments.limit or not path.is_file():
                break
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    results.append(f"{path.relative_to(root)}:{idx}:{line}")
                    if len(results) >= arguments.limit:
                        break
        return ToolResult(output="\n".join(results) if results else "(no matches)")


class WebFetchInput(BaseModel):
    url: str


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a web page."
    input_model = WebFetchInput

    def is_read_only(self, arguments: WebFetchInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: WebFetchInput, context: ToolExecutionContext) -> ToolResult:
        del context
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(arguments.url, follow_redirects=True)
        response.raise_for_status()
        return ToolResult(output=response.text[:20000])


class WebSearchInput(BaseModel):
    query: str


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Run a lightweight web search."
    input_model = WebSearchInput

    def is_read_only(self, arguments: WebSearchInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: WebSearchInput, context: ToolExecutionContext) -> ToolResult:
        del context
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(arguments.query)}"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)
        response.raise_for_status()
        matches = re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.+?)</a>', response.text)
        cleaned = [f"{re.sub('<.*?>', '', title)} -> {href}" for href, title in matches[:10]]
        return ToolResult(output="\n".join(cleaned) if cleaned else "(no results)")


class AskUserQuestionInput(BaseModel):
    question: str


class AskUserQuestionTool(BaseTool):
    name = "ask_user_question"
    description = "Ask the interactive user a follow-up question."
    input_model = AskUserQuestionInput

    def is_read_only(self, arguments: AskUserQuestionInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: AskUserQuestionInput, context: ToolExecutionContext) -> ToolResult:
        prompt = context.metadata.get("ask_user_prompt")
        if not callable(prompt):
            return ToolResult(output=f"User input required: {arguments.question}", is_error=True)
        answer = await prompt(arguments.question)
        return ToolResult(output=str(answer).strip() or "(no response)")


class SkillInput(BaseModel):
    name: str


class SkillTool(BaseTool):
    name = "skill"
    description = "Read the content of a skill."
    input_model = SkillInput

    def is_read_only(self, arguments: SkillInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: SkillInput, context: ToolExecutionContext) -> ToolResult:
        service = context.metadata.get("skill_service")
        if service is None:
            return ToolResult(output="Skill service unavailable", is_error=True)
        skill = service.get_skill(arguments.name)
        if not skill:
            return ToolResult(output=f"Skill not found: {arguments.name}", is_error=True)
        return ToolResult(output=skill["content"])


class ToolSearchInput(BaseModel):
    query: str


class ToolSearchTool(BaseTool):
    name = "tool_search"
    description = "Search available tools by name or description."
    input_model = ToolSearchInput

    def is_read_only(self, arguments: ToolSearchInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: ToolSearchInput, context: ToolExecutionContext) -> ToolResult:
        registry: ToolRegistry = context.metadata["tool_registry"]
        query = arguments.query.lower()
        matches = [
            f"{tool.name}: {tool.description}"
            for tool in registry.list_tools()
            if query in tool.name.lower() or query in tool.description.lower()
        ]
        return ToolResult(output="\n".join(matches) if matches else "(no matches)")


class ReportMonthsInput(BaseModel):
    user_id: str


class ReportDataInput(BaseModel):
    user_id: str
    month: str


class GetAvailableReportMonthsTool(BaseTool):
    name = "get_available_report_months"
    description = "List available report months for a user."
    input_model = ReportMonthsInput

    def is_read_only(self, arguments: ReportMonthsInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: ReportMonthsInput, context: ToolExecutionContext) -> ToolResult:
        del context
        months = sorted({row["month"] for row in _report_rows() if row["user_id"] == arguments.user_id})
        return ToolResult(output=json.dumps(months, ensure_ascii=False))


class GetUsageReportDataTool(BaseTool):
    name = "get_usage_report_data"
    description = "Read structured report data for a user and month."
    input_model = ReportDataInput

    def is_read_only(self, arguments: ReportDataInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: ReportDataInput, context: ToolExecutionContext) -> ToolResult:
        del context
        for row in _report_rows():
            if row["user_id"] == arguments.user_id and row["month"] == arguments.month:
                return ToolResult(output=json.dumps(row, ensure_ascii=False))
        return ToolResult(output="{}", is_error=True)


class GetWeatherInput(BaseModel):
    city: str


class GetWeatherTool(BaseTool):
    name = "mcp__gaode__get_weather"
    description = "Get live weather for a city using Gaode."
    input_model = GetWeatherInput

    def is_read_only(self, arguments: GetWeatherInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: GetWeatherInput, context: ToolExecutionContext) -> ToolResult:
        del context
        gaode = _gaode_server()
        api_key = str(gaode.get("api_key", "")).strip()
        base_url = str(gaode.get("base_url", "")).rstrip("/")
        if not api_key:
            return ToolResult(output=f"mock-weather:{arguments.city}")
        async with httpx.AsyncClient(timeout=float(gaode.get("timeout_seconds", 5))) as client:
            geo = await client.get(f"{base_url}/v3/geocode/geo", params={"address": arguments.city, "key": api_key})
            geo.raise_for_status()
            geo_payload = geo.json()
            if geo_payload.get("status") != "1" or not geo_payload.get("geocodes"):
                return ToolResult(output="weather lookup failed", is_error=True)
            adcode = geo_payload["geocodes"][0]["adcode"]
            weather = await client.get(
                f"{base_url}/v3/weather/weatherInfo",
                params={"city": adcode, "extensions": "base", "key": api_key},
            )
            weather.raise_for_status()
            payload = weather.json()
        return ToolResult(output=json.dumps(payload, ensure_ascii=False))


class GetUserLocationInput(BaseModel):
    dummy: str | None = None


class GetUserLocationTool(BaseTool):
    name = "mcp__gaode__get_user_location"
    description = "Resolve the user city using Gaode IP location."
    input_model = GetUserLocationInput

    def is_read_only(self, arguments: GetUserLocationInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: GetUserLocationInput, context: ToolExecutionContext) -> ToolResult:
        del arguments, context
        gaode = _gaode_server()
        api_key = str(gaode.get("api_key", "")).strip()
        base_url = str(gaode.get("base_url", "")).rstrip("/")
        if not api_key:
            return ToolResult(output="Beijing")
        async with httpx.AsyncClient(timeout=float(gaode.get("timeout_seconds", 5))) as client:
            response = await client.get(f"{base_url}/v3/ip", params={"key": api_key})
            response.raise_for_status()
            payload = response.json()
        return ToolResult(output=str(payload.get("city") or payload.get("province") or ""))


def create_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        BashTool(),
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        GlobTool(),
        GrepTool(),
        WebFetchTool(),
        WebSearchTool(),
        AskUserQuestionTool(),
        SkillTool(),
        ToolSearchTool(),
        GetAvailableReportMonthsTool(),
        GetUsageReportDataTool(),
        GetWeatherTool(),
        GetUserLocationTool(),
    ):
        registry.register(tool)
    return registry


def _resolve_path(cwd: Path, raw_path: str | None) -> Path:
    path = Path(raw_path or ".").expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def _gaode_server() -> dict[str, Any]:
    for server in mcp_conf.get("servers", []):
        if server.get("id") == "gaode":
            return server
    return {}


def _report_rows() -> list[dict[str, str]]:
    path = Path(get_abs_path("data/external/records.csv"))
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 6:
                continue
            rows.append(
                {
                    "user_id": row[0].strip().strip('"'),
                    "feature": row[1].strip().strip('"'),
                    "cleaning_efficiency": row[2].strip().strip('"'),
                    "consumables": row[3].strip().strip('"'),
                    "comparison": row[4].strip().strip('"'),
                    "month": row[5].strip().strip('"'),
                }
            )
    return rows
