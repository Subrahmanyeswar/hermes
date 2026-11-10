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
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

import hashlib
import aiofiles
from loguru import logger
from pydantic import BaseModel, Field

from core.workspace import workspace_manager, WorkspaceBoundaryError
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from tools.platform.file_identity import file_identity_cache

_READ_LOOP_TRACKER: dict[str, tuple[str, int]] = {}


def reset_read_loop_tracker() -> None:
    """Reset the read loop tracker between mission runs."""
    _READ_LOOP_TRACKER.clear()
    try:
        from tools.platform.core_tools import READ_LOOP_TRACKER
        READ_LOOP_TRACKER.clear()
    except Exception:
        pass


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
        model_config = {"extra": "allow", "arbitrary_types_allowed": True}

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
        workspace: Optional[Any] = None

    def execute(self, inp: Input) -> ToolResult:
        """Read the requested file synchronously."""
        wm = None
        if isinstance(inp, dict):
            wm = inp.get("_workspace")
            inp_dict = dict(inp)
            for k in list(inp_dict.keys()):
                if k in ("file_path", "target_path", "filepath", "filename", "TargetFile", "target_file") and "path" not in inp_dict:
                    inp_dict["path"] = inp_dict.pop(k)
            try:
                inp = self.Input(**inp_dict)
            except Exception:
                pass
        else:
            wm = getattr(inp, "_workspace", None)
        effective_wm = wm or workspace_manager

        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = effective_wm.validate_path(inp.path if hasattr(inp, "path") else inp.get("path"))
                if not isinstance(safe_path, Path):
                    if isinstance(safe_path, str):
                        safe_path = Path(safe_path).resolve()
                    else:
                        root = getattr(effective_wm, "workspace_root", None) or getattr(effective_wm, "root_str", None)
                        safe_path = (Path(root) / inp.path).resolve() if root else (Path.cwd() / inp.path).resolve()
            except WorkspaceBoundaryError as e:
                return ToolResult(
                    success=False,
                    error=f"SECURITY: {e}",
                    exit_code=126,
                )
            except Exception:
                root = getattr(effective_wm, "workspace_root", None) or getattr(effective_wm, "root_str", None)
                safe_path = (Path(root) / inp.path).resolve() if root else (Path.cwd() / inp.path).resolve()

            if not safe_path.exists():
                return ToolResult(success=False, error=f"File not found: {inp.path}", exit_code=1)
            if not safe_path.is_file():
                if safe_path.is_dir():
                    return ToolResult(
                        success=False,
                        error=f"Path is not a regular file: '{inp.path}'. It is a directory. Use list_directory to inspect folders, or specify a file path.",
                        exit_code=1,
                        details={"code": "PATH_IS_DIRECTORY", "path": inp.path},
                    )
                return ToolResult(success=False, error=f"Path is not a file: {inp.path}", exit_code=1)

            encoding = getattr(inp, "encoding", "utf-8")
            with open(safe_path, mode="r", encoding=encoding, errors="replace") as f:
                content = f.read()

            try:
                identity = file_identity_cache.record(safe_path, encoding=encoding)
                content_hash = identity.content_hash
            except Exception:
                content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

            # Read loop detection
            track_key = str(safe_path).lower()
            prev_hash, count = _READ_LOOP_TRACKER.get(track_key, ("", 0))
            if prev_hash == content_hash:
                count += 1
            else:
                count = 1
            _READ_LOOP_TRACKER[track_key] = (content_hash, count)

            duration = time.monotonic() - start
            if count >= 4:
                return ToolResult(
                    success=False,
                    error=(
                        f"NO_PROGRESS_LOOP_ENFORCEMENT: TOOL_REJECTED_NO_PROGRESS: Target '{inp.path}' was read {count} times without intermediate modifications "
                        f"(SHA-256 {content_hash[:8]} unchanged). Re-reading without modifications is forbidden. "
                        "Proceed immediately to creating missing files using fs.write, modifying code using fs.edit, or running tests."
                    ),
                    exit_code=1,
                    duration_seconds=duration,
                    details={
                        "code": "UNCHANGED_READ",
                        "path": str(inp.path),
                        "read_count": count,
                        "hash": content_hash,
                    },
                )

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
        wm = None
        if isinstance(inp, dict):
            wm = inp.get("_workspace")
            inp_dict = dict(inp)
            for k in list(inp_dict.keys()):
                if k in ("file_path", "target_path", "filepath", "filename", "TargetFile", "target_file") and "path" not in inp_dict:
                    inp_dict["path"] = inp_dict.pop(k)
            try:
                inp = self.Input(**inp_dict)
            except Exception:
                pass
        else:
            wm = getattr(inp, "_workspace", None)
        effective_wm = wm or workspace_manager

        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = effective_wm.validate_path(inp.path if hasattr(inp, "path") else inp.get("path"))
                if not isinstance(safe_path, Path):
                    if isinstance(safe_path, str):
                        safe_path = Path(safe_path).resolve()
                    else:
                        root = getattr(effective_wm, "workspace_root", None) or getattr(effective_wm, "root_str", None)
                        safe_path = (Path(root) / inp.path).resolve() if root else (Path.cwd() / inp.path).resolve()
            except WorkspaceBoundaryError as e:
                return ToolResult(
                    success=False,
                    error=f"SECURITY: {e}",
                    exit_code=126,
                )
            except Exception:
                root = getattr(effective_wm, "workspace_root", None) or getattr(effective_wm, "root_str", None)
                safe_path = (Path(root) / inp.path).resolve() if root else (Path.cwd() / inp.path).resolve()

            if not safe_path.exists():
                return ToolResult(success=False, error=f"File not found: {inp.path}", exit_code=1)
            if not safe_path.is_file():
                if safe_path.is_dir():
                    return ToolResult(
                        success=False,
                        error=f"Path is not a regular file: '{inp.path}'. It is a directory. Use list_directory to inspect folders, or specify a file path.",
                        exit_code=1,
                        details={"code": "PATH_IS_DIRECTORY", "path": inp.path},
                    )
                return ToolResult(success=False, error=f"Path is not a file: {inp.path}", exit_code=1)

            encoding = getattr(inp, "encoding", "utf-8")
            async with aiofiles.open(str(safe_path), mode='r',
                                      encoding=encoding, errors='replace') as f:
                content = await f.read()

            try:
                identity = file_identity_cache.record(safe_path, encoding=encoding)
                content_hash = identity.content_hash
            except Exception:
                content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

            track_key = str(safe_path).lower()
            prev_hash, count = _READ_LOOP_TRACKER.get(track_key, ("", 0))
            if prev_hash == content_hash:
                count += 1
            else:
                count = 1
            _READ_LOOP_TRACKER[track_key] = (content_hash, count)

            duration = time.monotonic() - start
            if count >= 3:
                return ToolResult(
                    success=False,
                    error=(
                        f"TOOL_REJECTED_NO_PROGRESS: Target '{inp.path}' was read {count} times without intermediate modifications "
                        f"(SHA-256 {content_hash[:8]} unchanged). Re-reading without modifications is forbidden. "
                        "Proceed immediately to creating missing files using fs.write, modifying code using fs.edit, or running tests."
                    ),
                    exit_code=1,
                    duration_seconds=duration,
                    details={
                        "code": "TOOL_REJECTED_NO_PROGRESS",
                        "path": str(inp.path),
                        "read_count": count,
                        "hash": content_hash,
                    },
                )

            logger.debug(f"read_file: {inp.path} | {len(content)} chars | {duration:.3f}s")
            return ToolResult(success=True, output=content, exit_code=0, duration_seconds=duration)
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {inp.path}", exit_code=1)
        except UnicodeDecodeError as e:
            return ToolResult(success=False, error=f"Encoding error: {e}", exit_code=1)
        except Exception as e:
            return ToolResult(success=False, error=str(e), exit_code=1)


def _clean_code_content(content: str, path_str: str = "") -> str:
    """Clean accidental markdown code fences, JSON envelopes, and stack contamination from file content."""
    if not isinstance(content, str):
        return content

    text = content.strip()
    # Check if entire content was wrapped in accidental JSON envelope
    if (text.startswith("{") and text.endswith("}")) and ('"content"' in text or '"code"' in text):
        try:
            import json as _json
            parsed = _json.loads(text)
            if isinstance(parsed, dict):
                if "content" in parsed and isinstance(parsed["content"], str):
                    text = parsed["content"].strip()
                elif "code" in parsed and isinstance(parsed["code"], str):
                    text = parsed["code"].strip()
                elif "parameters" in parsed and isinstance(parsed["parameters"], dict):
                    p = parsed["parameters"]
                    if "content" in p and isinstance(p["content"], str):
                        text = p["content"].strip()
        except Exception:
            pass

    # Strip markdown code fences if wrapped
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Sanitize framework contamination if ArchitectureLock is active
    if path_str:
        try:
            from core.architecture_lock import ArchitectureLock
            arch = ArchitectureLock.get_current()
            if arch is not None:
                text = arch.sanitize_file_content(path_str, text)
        except Exception:
            pass

    # Preserve trailing newline if original content ended with a newline
    if content.endswith("\n") and not text.endswith("\n"):
        text = text + "\n"

    return text


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
        model_config = {"extra": "allow", "arbitrary_types_allowed": True}

        path: str = Field(..., min_length=1, max_length=500)
        content: str = Field(..., max_length=500_000)
        mode: Literal["create", "overwrite", "append"] = "create"
        workspace: Optional[Any] = None

    def execute(self, inp: Input) -> ToolResult:
        """Write content to the requested file synchronously with workspace boundary enforcement."""
        wm = None
        if isinstance(inp, dict):
            wm = inp.get("_workspace") or inp.get("workspace")
            inp_dict = dict(inp)
            for k in list(inp_dict.keys()):
                if k in ("file_path", "target_path", "filepath", "filename", "TargetFile", "target_file") and "path" not in inp_dict:
                    inp_dict["path"] = inp_dict.pop(k)
                elif k in ("code", "text", "body", "code_content", "CodeContent", "file_content") and "content" not in inp_dict:
                    inp_dict["content"] = inp_dict.pop(k)
            try:
                inp = self.Input(**inp_dict)
            except Exception:
                pass
        else:
            wm = getattr(inp, "_workspace", None) or getattr(inp, "workspace", None)
        effective_wm = wm or workspace_manager

        norm_path = str(inp.path).replace("\\", "/").strip("./").lower()
        if norm_path in ("three.js", "three"):
            return ToolResult(
                success=False,
                error=(
                    "FAKE_DEPENDENCY_PROHIBITED: Cannot write root-level 'Three.js' file as a substitute for the library. "
                    "Install 'three' as an npm package in package.json and import it via 'import * as THREE from \"three\"' in main.js."
                ),
                exit_code=1,
                details={"code": "FAKE_DEPENDENCY_PROHIBITED", "path": inp.path},
            )

        import re as _re
        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = effective_wm.validate_path(inp.path if hasattr(inp, "path") else inp.get("path"))
            except WorkspaceBoundaryError as e:
                return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

            # Duplicate logical artifact detection (Part B & Part H)
            if "generated_projects" in inp.path.lower():
                clean_rel = _re.sub(r"^generated_projects/[^/]+/", "", inp.path, flags=_re.IGNORECASE)
                try:
                    cand = workspace_manager.validate_path(clean_rel) if workspace_manager.is_locked else (Path.cwd() / clean_rel).resolve()
                    if cand.exists() and (cand != safe_path or inp.path.lower() != clean_rel.lower()):
                        return ToolResult(
                            success=False,
                            error=f"DUPLICATE_LOGICAL_ARTIFACT: Ambiguous path '{inp.path}' conflicts with canonical root file '{clean_rel}'. Operate directly on '{clean_rel}'.",
                            exit_code=1,
                            details={"code": "DUPLICATE_LOGICAL_ARTIFACT", "path": inp.path, "canonical_path": clean_rel},
                        )
                except Exception:
                    pass

            to_write = _clean_code_content(inp.content, path_str=inp.path)

            # Comprehensive code completeness validation for implementation files (Section 4)
            try:
                from core.code_completeness import validate_implementation_completeness
                is_complete, completeness_err = validate_implementation_completeness(to_write, inp.path)
                if not is_complete and completeness_err:
                    return ToolResult(
                        success=False,
                        error=completeness_err,
                        exit_code=1,
                        details={"code": "INCOMPLETE_IMPLEMENTATION_REJECTED", "path": inp.path},
                    )
            except Exception as comp_exc:
                pass

            content_bytes = to_write.encode("utf-8")
            new_hash = hashlib.sha256(content_bytes).hexdigest()

            # Check existing file semantics
            if safe_path.exists() and safe_path.is_file():
                existing_bytes = safe_path.read_bytes()
                existing_hash = hashlib.sha256(existing_bytes).hexdigest()

                # CASE 2: Identical content -> UNCHANGED (no filesystem mutation)
                if existing_hash == new_hash:
                    file_identity_cache.record(safe_path, encoding="utf-8")
                    duration = time.monotonic() - start
                    return ToolResult(
                        success=True,
                        output=f"UNCHANGED: File '{inp.path}' already exists with identical content (sha256: {new_hash[:8]}). No mutation performed.",
                        exit_code=0,
                        duration_seconds=duration,
                        details={"code": "UNCHANGED", "status": "UNCHANGED", "path": inp.path, "sha256": new_hash},
                    )

                # CASE 3: File exists and differs
                if inp.mode == "create":
                    _READ_LOOP_TRACKER.pop(str(safe_path).lower(), None)
                    return ToolResult(
                        success=False,
                        error=f"ALREADY_EXISTS: File '{inp.path}' already exists with different content. Read the file with read_file first and use edit_file for surgical modifications, or specify mode='overwrite'.",
                        exit_code=1,
                        details={"code": "ALREADY_EXISTS", "path": inp.path},
                    )

            # CASE 1 or controlled overwrite/append
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            if inp.mode == "append":
                with open(safe_path, mode="a", encoding="utf-8", newline="") as f:
                    f.write(to_write)
            else:
                tmp_target = safe_path.with_name(f".{safe_path.name}.tmp_{uuid.uuid4().hex[:8]}")
                try:
                    with open(tmp_target, mode="w", encoding="utf-8", newline="") as f:
                        f.write(to_write)
                    max_attempts = 5
                    for attempt in range(max_attempts):
                        try:
                            os.replace(tmp_target, safe_path)
                            break
                        except (PermissionError, OSError) as e:
                            if attempt == max_attempts - 1:
                                raise e
                            time.sleep(0.02)
                finally:
                    if tmp_target.exists():
                        try:
                            tmp_target.unlink()
                        except Exception:
                            pass

            try:
                file_identity_cache.record(safe_path, encoding="utf-8")
            except Exception:
                pass

            # Strict post-write filesystem verification
            if not safe_path.exists() or not safe_path.is_file():
                return ToolResult(
                    success=False,
                    error=f"FILESYSTEM_VERIFICATION_FAILED: Target file '{inp.path}' does not exist on disk after write.",
                    exit_code=1,
                    details={"code": "WRITE_VERIFICATION_FAILED", "path": inp.path},
                )

            duration = time.monotonic() - start
            workspace_manager.refresh_index()
            _READ_LOOP_TRACKER.clear()

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
        wm = None
        if isinstance(inp, dict):
            wm = inp.get("_workspace")
            try:
                inp = self.Input(**inp)
            except Exception:
                pass
        else:
            wm = getattr(inp, "_workspace", None)
        effective_wm = wm or workspace_manager

        norm_path = str(inp.path).replace("\\", "/").strip("./").lower()
        if norm_path in ("three.js", "three"):
            return ToolResult(
                success=False,
                error=(
                    "FAKE_DEPENDENCY_PROHIBITED: Cannot write root-level 'Three.js' file as a substitute for the library. "
                    "Install 'three' as an npm package in package.json and import it via 'import * as THREE from \"three\"' in main.js."
                ),
                exit_code=1,
                details={"code": "FAKE_DEPENDENCY_PROHIBITED", "path": inp.path},
            )

        import re as _re
        start = time.monotonic()
        try:
            # ── Workspace boundary enforcement ──────────────────────────────
            try:
                safe_path = effective_wm.validate_path(inp.path if hasattr(inp, "path") else inp.get("path"))
            except WorkspaceBoundaryError as e:
                return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

            # Duplicate logical artifact detection (Part B & Part H)
            if "generated_projects" in inp.path.lower():
                clean_rel = _re.sub(r"^generated_projects/[^/]+/", "", inp.path, flags=_re.IGNORECASE)
                try:
                    cand = workspace_manager.validate_path(clean_rel) if workspace_manager.is_locked else (Path.cwd() / clean_rel).resolve()
                    if cand.exists() and (cand != safe_path or inp.path.lower() != clean_rel.lower()):
                        return ToolResult(
                            success=False,
                            error=f"DUPLICATE_LOGICAL_ARTIFACT: Ambiguous path '{inp.path}' conflicts with canonical root file '{clean_rel}'. Operate directly on '{clean_rel}'.",
                            exit_code=1,
                            details={"code": "DUPLICATE_LOGICAL_ARTIFACT", "path": inp.path, "canonical_path": clean_rel},
                        )
                except Exception:
                    pass

            to_write = _clean_code_content(inp.content, path_str=inp.path)

            # Comprehensive code completeness validation for implementation files (Section 4)
            try:
                from core.code_completeness import validate_implementation_completeness
                is_complete, completeness_err = validate_implementation_completeness(to_write, inp.path)
                if not is_complete and completeness_err:
                    return ToolResult(
                        success=False,
                        error=completeness_err,
                        exit_code=1,
                        details={"code": "INCOMPLETE_IMPLEMENTATION_REJECTED", "path": inp.path},
                    )
            except Exception as comp_exc:
                pass

            content_bytes = to_write.encode("utf-8")
            new_hash = hashlib.sha256(content_bytes).hexdigest()

            # Check existing file semantics
            if safe_path.exists() and safe_path.is_file():
                existing_bytes = safe_path.read_bytes()
                existing_hash = hashlib.sha256(existing_bytes).hexdigest()

                # CASE 2: Identical content -> UNCHANGED
                if existing_hash == new_hash:
                    file_identity_cache.record(safe_path, encoding="utf-8")
                    duration = time.monotonic() - start
                    return ToolResult(
                        success=True,
                        output=f"UNCHANGED: File '{inp.path}' already exists with identical content (sha256: {new_hash[:8]}). No mutation performed.",
                        exit_code=0,
                        duration_seconds=duration,
                        details={"code": "UNCHANGED", "status": "UNCHANGED", "path": inp.path, "sha256": new_hash},
                    )

                # CASE 3: File exists and differs
                if inp.mode == "create":
                    _READ_LOOP_TRACKER.pop(str(safe_path).lower(), None)
                    return ToolResult(
                        success=False,
                        error=f"ALREADY_EXISTS: File '{inp.path}' already exists with different content. Read the file with read_file first and use edit_file for surgical modifications, or specify mode='overwrite'.",
                        exit_code=1,
                        details={"code": "ALREADY_EXISTS", "path": inp.path},
                    )

            # CASE 1 or controlled overwrite/append
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            if inp.mode == "append":
                async with aiofiles.open(str(safe_path), mode="a", encoding="utf-8", newline="") as f:
                    await f.write(to_write)
            else:
                tmp_target = safe_path.with_name(f".{safe_path.name}.tmp_{uuid.uuid4().hex[:8]}")
                try:
                    async with aiofiles.open(str(tmp_target), mode="w", encoding="utf-8", newline="") as f:
                        await f.write(to_write)
                    max_attempts = 5
                    for attempt in range(max_attempts):
                        try:
                            os.replace(tmp_target, safe_path)
                            break
                        except (PermissionError, OSError) as e:
                            if attempt == max_attempts - 1:
                                raise e
                            await asyncio.sleep(0.02)
                finally:
                    if tmp_target.exists():
                        try:
                            tmp_target.unlink()
                        except Exception:
                            pass

            try:
                file_identity_cache.record(safe_path, encoding="utf-8")
            except Exception:
                pass

            # Strict post-write filesystem verification
            if not safe_path.exists() or not safe_path.is_file():
                return ToolResult(
                    success=False,
                    error=f"FILESYSTEM_VERIFICATION_FAILED: Target file '{inp.path}' does not exist on disk after write.",
                    exit_code=1,
                    details={"code": "WRITE_VERIFICATION_FAILED", "path": inp.path},
                )

            duration = time.monotonic() - start
            workspace_manager.refresh_index()
            _READ_LOOP_TRACKER.clear()

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

            # 3. Commit staged files to real destinations from staging area (Section 6.6)
            for idx, (safe_dest, content, mode, rel_p) in enumerate(validated_items):
                staged_file = temp_staging_dir / f"stage_{idx}"
                safe_dest.parent.mkdir(parents=True, exist_ok=True)
                staged_content = staged_file.read_text(encoding="utf-8")
                file_mode = "w" if mode == "overwrite" else "a"
                with open(safe_dest, file_mode, encoding="utf-8", newline="") as df:
                    df.write(staged_content)
                written_destinations.append(safe_dest)

            # 4. Verify all destination hashes after commit
            verified_hashes: dict[str, str] = {}
            for idx, (safe_dest, content, mode, rel_p) in enumerate(validated_items):
                if not safe_dest.exists() or not safe_dest.is_file():
                    raise IOError(f"Destination file '{rel_p}' missing after batch commit")
                h_val = hashlib.sha256(safe_dest.read_bytes()).hexdigest()
                verified_hashes[rel_p] = h_val

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
            _READ_LOOP_TRACKER.clear()
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
            _READ_LOOP_TRACKER.clear()
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
            
            from tools.security import can_safely_delete_file, safe_delete_file
            ws_root = getattr(workspace_manager, "workspace_root", None) or Path.cwd()
            allowed, block_reason = can_safely_delete_file(safe_path, ws_root)
            if not allowed:
                return ToolResult(success=False, error=f"SECURITY: {block_reason}", exit_code=126, duration_seconds=0.0)

            deleted = safe_delete_file(safe_path, ws_root)
            if not deleted:
                return ToolResult(success=False, error=f"SECURITY: Failed to safely delete {inp.path}", exit_code=126, duration_seconds=0.0)

            workspace_manager.refresh_index()
            logger.warning(f"delete_file: DELETED {inp.path}")
            return ToolResult(success=True, output=f"Deleted: {inp.path}", exit_code=0, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)
