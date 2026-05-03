# tools/file_tools.py
# File system tools for HERMES.
# All file operations are sandboxed to the current working directory.
# Never operate on paths outside the project root.

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from tools.base import BaseTool, ToolResult
from tools.registry import tool


def _resolve_project_path(path: str) -> Path:
    """Resolve a user path and reject paths outside the current working directory."""
    project_root: Path = Path.cwd().resolve()
    resolved_path: Path = (project_root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()

    try:
        resolved_path.relative_to(project_root)
    except ValueError as exc:
        raise PermissionError(f"Path outside project root: {path}") from exc

    return resolved_path


@tool(
    name="read_file",
    description="Read the contents of a file and return them as a string",
    permissions=["filesystem_read"],
    risk_score=0.1,
    blocked_in=[],
)
class ReadFileTool(BaseTool):
    """Read a text file and return its contents."""

    class Input(BaseModel):
        """Validated input for ReadFileTool."""

        path: str = Field(
            ...,
            description="Path to the file to read, relative to project root",
            min_length=1,
            max_length=500,
        )

    def execute(self, inp: Input) -> ToolResult:
        """Read the requested file and return its contents without raising."""
        start_time: float = time.perf_counter()
        logger.debug("Reading file: {}", inp.path)

        try:
            file_path: Path = _resolve_project_path(inp.path)
            file_contents: str = file_path.read_text(encoding="utf-8")
            duration_seconds: float = time.perf_counter() - start_time
            logger.debug(
                "Read file: {} ({} bytes)",
                file_path,
                file_path.stat().st_size,
            )
            return ToolResult(
                success=True,
                output=file_contents,
                exit_code=0,
                duration_seconds=duration_seconds,
            )
        except FileNotFoundError:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"File not found: {inp.path}",
                exit_code=1,
                duration_seconds=duration_seconds,
            )
        except OSError as exc:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                exit_code=2,
                duration_seconds=duration_seconds,
            )
        except UnicodeError as exc:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                exit_code=2,
                duration_seconds=duration_seconds,
            )


@tool(
    name="write_file",
    description="Write content to a file. Creates the file and any parent directories if they do not exist",
    permissions=["filesystem_write"],
    risk_score=0.3,
    blocked_in=["safe"],
)
class WriteFileTool(BaseTool):
    """Write or append text content to a file."""

    class Input(BaseModel):
        """Validated input for WriteFileTool."""

        path: str = Field(..., min_length=1, max_length=500)
        content: str = Field(..., max_length=500_000)
        mode: Literal["overwrite", "append"] = "overwrite"

    def execute(self, inp: Input) -> ToolResult:
        """Write content to the requested file without raising."""
        start_time: float = time.perf_counter()
        write_mode: str = "w" if inp.mode == "overwrite" else "a"
        logger.debug(
            "Writing file: {} mode={} characters={}",
            inp.path,
            inp.mode,
            len(inp.content),
        )

        try:
            file_path: Path = _resolve_project_path(inp.path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open(write_mode, encoding="utf-8") as file_handle:
                file_handle.write(inp.content)
            duration_seconds: float = time.perf_counter() - start_time
            logger.debug("Wrote file: {} ({} bytes)", file_path, file_path.stat().st_size)
            return ToolResult(
                success=True,
                output=f"Written {len(inp.content)} characters to {inp.path}",
                exit_code=0,
                duration_seconds=duration_seconds,
            )
        except OSError as exc:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                exit_code=1,
                duration_seconds=duration_seconds,
            )
        except UnicodeError as exc:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                exit_code=1,
                duration_seconds=duration_seconds,
            )


@tool(
    name="list_directory",
    description="List all files and folders in a directory",
    permissions=["filesystem_read"],
    risk_score=0.0,
    blocked_in=[],
)
class ListDirectoryTool(BaseTool):
    """List files and folders in a directory."""

    class Input(BaseModel):
        """Validated input for ListDirectoryTool."""

        path: str = Field(
            default=".",
            description="Directory path to list, defaults to current directory",
        )
        include_hidden: bool = Field(default=False)

    def execute(self, inp: Input) -> ToolResult:
        """List the requested directory without raising."""
        start_time: float = time.perf_counter()
        logger.debug(
            "Listing directory: {} include_hidden={}",
            inp.path,
            inp.include_hidden,
        )

        try:
            directory_path: Path = _resolve_project_path(inp.path)
            entries: list[Path] = list(directory_path.iterdir())
            if not inp.include_hidden:
                entries = [entry for entry in entries if not entry.name.startswith(".")]

            directories: list[Path] = sorted(
                [entry for entry in entries if entry.is_dir()],
                key=lambda entry: entry.name.lower(),
            )
            files: list[Path] = sorted(
                [entry for entry in entries if entry.is_file()],
                key=lambda entry: entry.name.lower(),
            )

            lines: list[str] = []
            for directory in directories:
                lines.append(f"[DIR]  {directory.name}")
            for file in files:
                lines.append(f"[FILE] {file.name} ({file.stat().st_size} bytes)")

            duration_seconds: float = time.perf_counter() - start_time
            logger.debug(
                "Listed directory: {} entries={}",
                directory_path,
                len(lines),
            )
            return ToolResult(
                success=True,
                output="\n".join(lines),
                exit_code=0,
                duration_seconds=duration_seconds,
            )
        except FileNotFoundError:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {inp.path}",
                exit_code=1,
                duration_seconds=duration_seconds,
            )
        except NotADirectoryError as exc:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                exit_code=2,
                duration_seconds=duration_seconds,
            )
        except OSError as exc:
            duration_seconds = time.perf_counter() - start_time
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                exit_code=2,
                duration_seconds=duration_seconds,
            )
