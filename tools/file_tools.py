# tools/file_tools.py
# File system tools for HERMES.
# All file operations are sandboxed to the workspace root when locked.
# Never operate on paths outside the project root.

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Literal

import aiofiles
from loguru import logger
from pydantic import BaseModel, Field

from core.workspace import workspace_manager, WorkspaceBoundaryError
from tools.base import BaseTool, ToolResult
from tools.registry import tool


def _resolve_project_path(path: str) -> Path:
    """Resolve a user path using workspace_manager when locked, or cwd."""
    if workspace_manager.is_locked:
        return workspace_manager.validate_path(path)
    return (Path.cwd() / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()


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
        encoding: str = Field(
            default="utf-8",
            description="File encoding, defaults to utf-8",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Read the requested file synchronously."""
        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = workspace_manager.validate_path(inp.path)
            except WorkspaceBoundaryError as e:
                return ToolResult(
                    success=False,
                    error=f"SECURITY: {e}",
                    exit_code=126,
                )

            if not safe_path.exists():
                return ToolResult(success=False, error=f"File not found: {inp.path}", exit_code=1)
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path is not a file: {inp.path}", exit_code=1)

            encoding = getattr(inp, "encoding", "utf-8")
            with open(safe_path, mode="r", encoding=encoding, errors="replace") as f:
                content = f.read()

            duration = time.monotonic() - start
            logger.debug(f"read_file: {inp.path} | {len(content)} chars | {duration:.3f}s")
            return ToolResult(success=True, output=content, exit_code=0, duration_seconds=duration)
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {inp.path}", exit_code=1)
        except UnicodeDecodeError as e:
            return ToolResult(success=False, error=f"Encoding error: {e}", exit_code=1)
        except Exception as e:
            return ToolResult(success=False, error=str(e), exit_code=1)

    async def execute_async(self, inp: Input) -> ToolResult:
        """Async file read using aiofiles with workspace boundary enforcement."""
        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = workspace_manager.validate_path(inp.path)
            except WorkspaceBoundaryError as e:
                return ToolResult(
                    success=False,
                    error=f"SECURITY: {e}",
                    exit_code=126,
                )

            if not safe_path.exists():
                return ToolResult(success=False, error=f"File not found: {inp.path}", exit_code=1)
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path is not a file: {inp.path}", exit_code=1)

            encoding = getattr(inp, "encoding", "utf-8")
            async with aiofiles.open(str(safe_path), mode='r',
                                      encoding=encoding, errors='replace') as f:
                content = await f.read()

            duration = time.monotonic() - start
            logger.debug(f"read_file: {inp.path} | {len(content)} chars | {duration:.3f}s")
            return ToolResult(success=True, output=content, exit_code=0, duration_seconds=duration)
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {inp.path}", exit_code=1)
        except UnicodeDecodeError as e:
            return ToolResult(success=False, error=f"Encoding error: {e}", exit_code=1)
        except Exception as e:
            return ToolResult(success=False, error=str(e), exit_code=1)


def _clean_code_content(content: str) -> str:
    """Clean accidental markdown code fences from file content without mutating valid whitespace."""
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return content


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
        """Write content to the requested file synchronously with workspace boundary enforcement."""
        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = workspace_manager.validate_path(inp.path)
            except WorkspaceBoundaryError as e:
                return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

            safe_path.parent.mkdir(parents=True, exist_ok=True)
            file_mode = "w" if inp.mode == "overwrite" else "a"
            to_write = _clean_code_content(inp.content)

            with open(safe_path, mode=file_mode, encoding="utf-8", newline="") as f:
                f.write(to_write)

            duration = time.monotonic() - start

            # Refresh workspace index — new file detected
            workspace_manager.refresh_index()

            logger.debug(f"write_file: {inp.path} | {len(to_write)} chars | {inp.mode} | {duration:.3f}s")
            return ToolResult(
                success=True,
                output=f"Written {len(to_write)} characters to {safe_path}",
                exit_code=0,
                duration_seconds=duration,
            )
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {inp.path}", exit_code=1)
        except Exception as e:
            return ToolResult(success=False, error=str(e), exit_code=1)

    async def execute_async(self, inp: Input) -> ToolResult:
        """Write content to the requested file with workspace boundary enforcement."""
        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = workspace_manager.validate_path(inp.path)
            except WorkspaceBoundaryError as e:
                return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

            safe_path.parent.mkdir(parents=True, exist_ok=True)
            file_mode = "w" if inp.mode == "overwrite" else "a"
            to_write = _clean_code_content(inp.content)

            async with aiofiles.open(str(safe_path), mode=file_mode, encoding="utf-8", newline="") as f:
                await f.write(to_write)

            duration = time.monotonic() - start

            # Refresh workspace index — new file detected
            workspace_manager.refresh_index()

            logger.debug(f"write_file: {inp.path} | {len(inp.content)} chars | {inp.mode} | {duration:.3f}s")
            return ToolResult(
                success=True,
                output=f"Written {len(inp.content)} characters to {safe_path}",
                exit_code=0,
                duration_seconds=duration,
            )
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {inp.path}", exit_code=1)
        except Exception as e:
            return ToolResult(success=False, error=str(e), exit_code=1)


MAX_BATCH_FILES: int = 3
MAX_BATCH_TOTAL_BYTES: int = 1_000_000


class BatchFileItem(BaseModel):
    """Entry for a single file in a batch write operation."""

    path: str = Field(..., min_length=1, max_length=500, description="Path to file, relative to project root")
    content: str = Field(..., max_length=500_000, description="Content to write")
    mode: Literal["overwrite", "append"] = "overwrite"


@tool(
    name="write_files_batch",
    description="Write between 1 and 3 text/code files in a single atomic batch with transactional staging and all-or-nothing rollback.",
    permissions=["filesystem_write"],
    risk_score=0.35,
    blocked_in=["safe"],
)
class WriteFilesBatchTool(BaseTool):
    """Write 1 to 3 files atomically with staging and rollback."""

    class Input(BaseModel):
        files: list[BatchFileItem] = Field(
            ...,
            min_length=1,
            max_length=3,
            description="List of 1 to 3 files to write atomically",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Synchronously write batch files with transactional staging and boundary validation."""
        start = time.monotonic()
        files = inp.files
        if not files or len(files) == 0:
            return ToolResult(success=False, error="Batch files list cannot be empty", exit_code=1)
        if len(files) > MAX_BATCH_FILES:
            return ToolResult(
                success=False,
                error=f"Batch size exceeds maximum limit of {MAX_BATCH_FILES} files (received {len(files)})",
                exit_code=1,
            )

        total_bytes = sum(len(f.content.encode("utf-8")) for f in files)
        if total_bytes > MAX_BATCH_TOTAL_BYTES:
            return ToolResult(
                success=False,
                error=f"Batch payload exceeds maximum limit of {MAX_BATCH_TOTAL_BYTES} bytes ({total_bytes} bytes)",
                exit_code=1,
            )

        # Pre-validate all paths and check for duplicates
        validated_items: list[tuple[Path, str, str, str]] = []
        seen_normalized = set()

        for item in files:
            cleaned = _clean_code_content(item.content)
            if cleaned.strip() in (
                "full content here", "the code string", "# full content here", "# the code string",
                "// full content here", "/* full content here */"
            ):
                return ToolResult(
                    success=False,
                    error=f"Rejected placeholder content in batch for path: {item.path}",
                    exit_code=1,
                )

            try:
                safe_path = workspace_manager.validate_path(item.path)
            except WorkspaceBoundaryError as e:
                return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

            norm_path = os.path.normpath(str(safe_path)).lower() if os.name == "nt" else os.path.normpath(str(safe_path))
            if norm_path in seen_normalized:
                return ToolResult(
                    success=False,
                    error=f"Duplicate path detected in batch: {item.path}",
                    exit_code=1,
                )
            seen_normalized.add(norm_path)
            validated_items.append((safe_path, cleaned, item.mode, item.path))

        # Staging and Backup
        temp_staging_dir = Path(tempfile.mkdtemp(prefix="hermes_batch_staging_"))
        temp_backup_dir = Path(tempfile.mkdtemp(prefix="hermes_batch_backup_"))
        written_destinations: list[Path] = []
        backed_up_destinations: list[tuple[Path, Path]] = []

        try:
            # 1. Stage all files in staging directory
            for idx, (safe_dest, content, mode, rel_p) in enumerate(validated_items):
                staged_file = temp_staging_dir / f"stage_{idx}"
                with open(staged_file, "w", encoding="utf-8", newline="") as sf:
                    sf.write(content)

            # 2. Backup existing destination files before committing
            for safe_dest, _, _, _ in validated_items:
                if safe_dest.exists() and safe_dest.is_file():
                    b_file = temp_backup_dir / f"backup_{len(backed_up_destinations)}"
                    shutil.copy2(safe_dest, b_file)
                    backed_up_destinations.append((safe_dest, b_file))

            # 3. Commit staged files to real destinations
            for idx, (safe_dest, content, mode, rel_p) in enumerate(validated_items):
                safe_dest.parent.mkdir(parents=True, exist_ok=True)
                file_mode = "w" if mode == "overwrite" else "a"
                with open(safe_dest, file_mode, encoding="utf-8", newline="") as df:
                    df.write(content)
                written_destinations.append(safe_dest)

            workspace_manager.refresh_index()
            duration = time.monotonic() - start
            paths_str = ", ".join(item.path for item in files)
            logger.debug(f"write_files_batch: wrote {len(files)} files ({paths_str}) in {duration:.3f}s")
            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(files)} files: {paths_str}",
                exit_code=0,
                duration_seconds=duration,
            )

        except Exception as e:
            logger.error(f"write_files_batch failed during commit, rolling back: {e}")
            for safe_dest in written_destinations:
                try:
                    orig_backup = next((b for orig, b in backed_up_destinations if orig == safe_dest), None)
                    if orig_backup and orig_backup.exists():
                        shutil.copy2(orig_backup, safe_dest)
                    else:
                        if safe_dest.exists():
                            safe_dest.unlink()
                except Exception as rollback_err:
                    logger.critical(f"Failed to rollback file {safe_dest}: {rollback_err}")

            workspace_manager.refresh_index()
            return ToolResult(
                success=False,
                error=f"write_files_batch transaction failed and rolled back: {e}",
                exit_code=1,
            )

        finally:
            shutil.rmtree(temp_staging_dir, ignore_errors=True)
            shutil.rmtree(temp_backup_dir, ignore_errors=True)

    async def execute_async(self, inp: Input) -> ToolResult:
        """Asynchronously write batch files with transactional staging."""
        return await asyncio.to_thread(self.execute, inp)


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
            safe_path = workspace_manager.validate_path(inp.path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            entries: list[Path] = list(safe_path.iterdir())
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
                safe_path,
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
        """Append content to the requested file synchronously. Creates the file if it does not exist."""
        start = time.monotonic()
        try:
            safe_path = workspace_manager.validate_path(inp.path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            with open(safe_path, 'a', encoding='utf-8') as f:
                f.write(inp.content)
            duration = time.monotonic() - start
            workspace_manager.refresh_index()
            logger.debug(f"append_file: {inp.path} | appended {len(inp.content)} chars")
            return ToolResult(success=True, output=f"Appended {len(inp.content)} characters to {inp.path}", exit_code=0, duration_seconds=duration)
        except Exception as e:
            duration = time.monotonic() - start
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=duration)

    async def execute_async(self, inp: Input) -> ToolResult:
        """Append content to the requested file asynchronously using aiofiles. Creates the file if it does not exist."""
        start = time.monotonic()
        try:
            safe_path = workspace_manager.validate_path(inp.path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(str(safe_path), 'a', encoding='utf-8') as f:
                await f.write(inp.content)
            duration = time.monotonic() - start
            workspace_manager.refresh_index()
            logger.debug(f"append_file: {inp.path} | appended {len(inp.content)} chars")
            return ToolResult(success=True, output=f"Appended {len(inp.content)} characters to {inp.path}", exit_code=0, duration_seconds=duration)
        except Exception as e:
            duration = time.monotonic() - start
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=duration)


@tool(name="create_folder", description="Create a new directory/folder and any parent directories. Use when the user asks to create folders, directories, or project structure without file content.", permissions=["filesystem_write"], risk_score=0.1, blocked_in=["safe"])
class CreateFolderTool(BaseTool):
    class Input(BaseModel):
        path: str = Field(..., min_length=1, max_length=500)

    def execute(self, inp: Input) -> ToolResult:
        try:
            safe_path = workspace_manager.validate_path(inp.path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            safe_path.mkdir(parents=True, exist_ok=True)
            workspace_manager.refresh_index()
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
            src = workspace_manager.validate_path(inp.source)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            dest = workspace_manager.validate_path(inp.destination)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            if not src.exists():
                return ToolResult(success=False, output="", error=f"Source not found: {inp.source}", exit_code=1, duration_seconds=0.0)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            workspace_manager.refresh_index()
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
            safe_path = workspace_manager.validate_path(inp.path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            if not safe_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {inp.path}", exit_code=1, duration_seconds=0.0)
            if safe_path.is_dir():
                return ToolResult(success=False, output="", error="delete_file cannot delete directories. Use bash_exec with caution.", exit_code=1, duration_seconds=0.0)
            safe_path.unlink()
            workspace_manager.refresh_index()
            logger.warning(f"delete_file: DELETED {inp.path}")
            return ToolResult(success=True, output=f"Deleted: {inp.path}", exit_code=0, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)
