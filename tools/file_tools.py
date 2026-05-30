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
    description="Read and display the contents of a file. Use when the user wants to see, open, or view a file. Do NOT use for counting lines — use bash_exec with wc -l instead.",
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
    description="Write or create a file with content. Use for creating new code files, config files, scripts, Dockerfiles, or any file the user wants to build/generate/write. Also creates parent directories automatically.",
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
    description="List all files and folders in a directory. Use for showing project structure, checking what files exist, or giving an overview of a folder.",
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


@tool(name="append_file", description="Append content to an existing file. Creates the file if it does not exist.", permissions=["filesystem_write"], risk_score=0.2, blocked_in=["safe"])
class AppendFileTool(BaseTool):
    class Input(BaseModel):
        path: str = Field(..., min_length=1, max_length=500)
        content: str = Field(..., max_length=100_000)
    def execute(self, inp: Input) -> ToolResult:
        import time
        start = time.monotonic()
        try:
            Path(inp.path).parent.mkdir(parents=True, exist_ok=True)
            with open(inp.path, 'a', encoding='utf-8') as f:
                f.write(inp.content)
            duration = time.monotonic() - start
            logger.debug(f"append_file: {inp.path} | appended {len(inp.content)} chars")
            return ToolResult(success=True, output=f"Appended {len(inp.content)} characters to {inp.path}", exit_code=0, duration_seconds=duration)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)


@tool(name="create_folder", description="Create a new directory/folder and any parent directories. Use when the user asks to create folders, directories, or project structure without file content.", permissions=["filesystem_write"], risk_score=0.1, blocked_in=["safe"])
class CreateFolderTool(BaseTool):
    class Input(BaseModel):
        path: str = Field(..., min_length=1, max_length=500)
    def execute(self, inp: Input) -> ToolResult:
        try:
            Path(inp.path).mkdir(parents=True, exist_ok=True)
            return ToolResult(success=True, output=f"Created directory: {inp.path}", exit_code=0, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)


@tool(name="move_file", description="Move or rename a file or directory.", permissions=["filesystem_write"], risk_score=0.3, blocked_in=["safe"])
class MoveFileTool(BaseTool):
    class Input(BaseModel):
        source: str = Field(..., min_length=1, max_length=500)
        destination: str = Field(..., min_length=1, max_length=500)
    def execute(self, inp: Input) -> ToolResult:
        import shutil
        try:
            src = Path(inp.source)
            if not src.exists():
                return ToolResult(success=False, output="", error=f"Source not found: {inp.source}", exit_code=1, duration_seconds=0.0)
            Path(inp.destination).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), inp.destination)
            return ToolResult(success=True, output=f"Moved {inp.source} → {inp.destination}", exit_code=0, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)


@tool(name="delete_file", description="Delete a file. Requires explicit confirmation in Auto mode. Never deletes directories.", permissions=["filesystem_write"], risk_score=0.8, blocked_in=["safe", "plan"])
class DeleteFileTool(BaseTool):
    class Input(BaseModel):
        path: str = Field(..., min_length=1, max_length=500)
        confirm: bool = Field(..., description="Must be explicitly True to confirm deletion")
    def execute(self, inp: Input) -> ToolResult:
        if not inp.confirm:
            return ToolResult(success=False, output="", error="Deletion requires confirm=True", exit_code=1, duration_seconds=0.0)
        try:
            p = Path(inp.path)
            if not p.exists():
                return ToolResult(success=False, output="", error=f"File not found: {inp.path}", exit_code=1, duration_seconds=0.0)
            if p.is_dir():
                return ToolResult(success=False, output="", error="delete_file cannot delete directories. Use bash_exec with caution.", exit_code=1, duration_seconds=0.0)
            p.unlink()
            logger.warning(f"delete_file: DELETED {inp.path}")
            return ToolResult(success=True, output=f"Deleted: {inp.path}", exit_code=0, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)
