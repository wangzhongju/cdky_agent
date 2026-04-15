from __future__ import annotations

import asyncio
import re
from pathlib import Path

import requests
from pydantic import BaseModel, Field

from harness.tools.base import BaseTool, ToolExecutionContext, ToolResult


def _resolve_workspace_path(cwd: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = cwd / path
    path = path.resolve()
    workspace = cwd.resolve()
    if workspace not in path.parents and path != workspace:
        raise ValueError(f"path escapes workspace: {path}")
    return path


class ReadFileInput(BaseModel):
    path: str
    max_chars: int = Field(default=4000, ge=1, le=20000)


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a text file from the current workspace."
    input_model = ReadFileInput

    def is_read_only(self, arguments: ReadFileInput) -> bool:
        return True

    async def execute(self, arguments: ReadFileInput, context: ToolExecutionContext) -> ToolResult:
        try:
            path = _resolve_workspace_path(context.cwd, arguments.path)
            text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
            return ToolResult(output=text[: arguments.max_chars])
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)


class GlobSearchInput(BaseModel):
    pattern: str
    base_path: str = "."
    limit: int = Field(default=100, ge=1, le=500)


class GlobSearchTool(BaseTool):
    name = "glob_search"
    description = "Find files in the current workspace using a glob pattern."
    input_model = GlobSearchInput

    def is_read_only(self, arguments: GlobSearchInput) -> bool:
        return True

    async def execute(self, arguments: GlobSearchInput, context: ToolExecutionContext) -> ToolResult:
        try:
            base = _resolve_workspace_path(context.cwd, arguments.base_path)
            matches = [str(path.relative_to(context.cwd)) for path in base.glob(arguments.pattern) if path.exists()]
            return ToolResult(output="\n".join(matches[: arguments.limit]) or "(no matches)")
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)


class GrepSearchInput(BaseModel):
    pattern: str
    base_path: str = "."
    limit: int = Field(default=50, ge=1, le=200)


class GrepSearchTool(BaseTool):
    name = "grep_search"
    description = "Search text content recursively in the workspace."
    input_model = GrepSearchInput

    def is_read_only(self, arguments: GrepSearchInput) -> bool:
        return True

    async def execute(self, arguments: GrepSearchInput, context: ToolExecutionContext) -> ToolResult:
        try:
            base = _resolve_workspace_path(context.cwd, arguments.base_path)
            pattern = re.compile(arguments.pattern, re.IGNORECASE)
            results: list[str] = []
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if pattern.search(line):
                        results.append(f"{path.relative_to(context.cwd)}:{lineno}: {line.strip()}")
                        if len(results) >= arguments.limit:
                            return ToolResult(output="\n".join(results))
            return ToolResult(output="\n".join(results) or "(no matches)")
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)


class ShellCommandInput(BaseModel):
    command: str
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class ShellCommandTool(BaseTool):
    name = "shell_command"
    description = "Run a shell command inside the current workspace."
    input_model = ShellCommandInput

    READ_ONLY_PREFIXES = ("ls", "pwd", "cat", "find", "grep", "head", "tail", "wc", "echo", "git status", "git diff")

    def is_read_only(self, arguments: ShellCommandInput) -> bool:
        command = arguments.command.strip().lower()
        return any(command.startswith(prefix) for prefix in self.READ_ONLY_PREFIXES)

    async def execute(self, arguments: ShellCommandInput, context: ToolExecutionContext) -> ToolResult:
        process = await asyncio.create_subprocess_shell(
            arguments.command,
            cwd=str(context.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=arguments.timeout_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ToolResult(output=f"command timed out after {arguments.timeout_seconds}s", is_error=True)
        output = "\n".join(
            part for part in (
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            ) if part
        )
        return ToolResult(output=output or "(no output)", is_error=process.returncode != 0)


class HttpFetchInput(BaseModel):
    url: str
    method: str = "GET"
    timeout_seconds: int = Field(default=20, ge=1, le=60)


class HttpFetchTool(BaseTool):
    name = "http_fetch"
    description = "Fetch a URL over HTTP."
    input_model = HttpFetchInput

    def is_read_only(self, arguments: HttpFetchInput) -> bool:
        return True

    async def execute(self, arguments: HttpFetchInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            method = arguments.method.upper()
            if method != "GET":
                return ToolResult(output="only GET is supported", is_error=True)
            response = await asyncio.to_thread(requests.get, arguments.url, timeout=arguments.timeout_seconds)
            return ToolResult(output=response.text[:8000], is_error=not response.ok, metadata={"status_code": response.status_code})
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)
