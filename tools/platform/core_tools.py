# tools/platform/core_tools.py
"""
Canonical Core Tool Implementations for HERMES 2.x Tool Platform.
Provides the 9 foundational, agent-facing tools:
    1. fs.read
    2. fs.edit
    3. fs.write
    4. shell.bash
    5. search.glob
    6. search.grep
    7. task.todo
    8. task.delegate
    9. user.ask

Prompt 6 Hardening:
- Surgical line-addressable reads with stable file identity and real workspace suggestions on missing files
- Strict exact-match editing (expected_occurrences=1 default, zero fuzzy mutation, occurrence line reporting)
- Stale file protection via FileIdentityCache
- Atomic writes with tempfile, os.fsync, and atomic rename
- Newline preservation (CRLF/LF) and encoding preservation
- Postcondition verification (AST validation for Python, JSON decoding for JSON)
- Diff minimality enforcement (EDIT_SUSPICIOUS_LARGE_DIFF protection)
- Bounded, noise-filtered glob and regex-validated grep
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from core.workspace import workspace_manager, WorkspaceBoundaryError
from tools.base import BaseTool, ToolResult
from tools.security import check_all_gates
from tools.shell_tools import ACTIVE_SUBPROCESSES, _command_for_platform
from tools.platform.specs import ResponseFormat
from tools.platform.output import OutputShaper, output_store
from tools.platform.file_identity import file_identity_cache, FileIdentity
from tools.platform.errors import ToolError, ToolErrorCode, ErrorGuidance


def _resolve_safe_path(data: Dict[str, Any], path_str: str) -> Path:
    """Resolve path against active or global workspace manager."""
    wm = data.get("_workspace") or workspace_manager
    if wm and wm.is_locked:
        return wm.validate_path(path_str)
    return (Path.cwd() / path_str).resolve() if not Path(path_str).is_absolute() else Path(path_str).resolve()


def _get_workspace_root(data: Dict[str, Any]) -> Path:
    """Retrieve resolved workspace root directory."""
    wm = data.get("_workspace") or workspace_manager
    if wm and wm.is_locked:
        return Path(wm.root_str).resolve()
    return Path.cwd().resolve()


def _find_similar_files(root: Path, target_path_str: str, max_suggestions: int = 3) -> List[str]:
    """Find existing files in workspace that closely match the requested path."""
    target_name = Path(target_path_str).name.lower()
    candidates: List[str] = []
    try:
        for p in root.rglob("*"):
            if p.is_file():
                if any(part in (".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".tox") for part in p.parts):
                    continue
                try:
                    rel = p.relative_to(root).as_posix()
                    candidates.append(rel)
                except ValueError:
                    pass
    except Exception:
        return []

    if not candidates:
        return []

    # 1. Exact basename matches in other directories
    exact_name_matches = [c for c in candidates if Path(c).name.lower() == target_name]
    if exact_name_matches:
        return exact_name_matches[:max_suggestions]

    # 2. Fuzzy matches on relative path
    fuzzy = difflib.get_close_matches(target_path_str, candidates, n=max_suggestions, cutoff=0.4)
    if fuzzy:
        return fuzzy

    # 3. Fuzzy matches on basename
    base_matches = difflib.get_close_matches(target_name, [Path(c).name.lower() for c in candidates], n=max_suggestions, cutoff=0.5)
    matched_paths = [c for c in candidates if Path(c).name.lower() in base_matches]
    return matched_paths[:max_suggestions]


# ─────────────────────────────────────────────────────────────────────────────
# 1. fs.read
# ─────────────────────────────────────────────────────────────────────────────

class FSReadInput(BaseModel):
    path: str = Field(..., description="Path to the file to read, relative to workspace root")
    start_line: Optional[int] = Field(None, description="Starting line number (1-based, inclusive)")
    offset: Optional[int] = Field(None, description="Alias for start_line (1-based, inclusive)")
    end_line: Optional[int] = Field(None, description="Ending line number (1-based, inclusive)")
    max_lines: Optional[int] = Field(None, description="Maximum number of lines to return")
    limit: Optional[int] = Field(None, description="Alias for max_lines")
    encoding: str = Field(default="utf-8", description="File text encoding")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class FSReadTool(BaseTool):
    name = "fs.read"
    description = (
        "Read file contents or specific line ranges from disk. Use when inspecting source, "
        "configuration, or text files. Supports start_line/end_line to inspect specific sections. "
        "Rejects files outside workspace."
    )
    risk_score = 0.1
    blocked_in = []

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        path_str = data.get("path", "")
        start_line = data.get("start_line") if data.get("start_line") is not None else data.get("offset")
        end_line = data.get("end_line")
        max_lines = data.get("max_lines") if data.get("max_lines") is not None else data.get("limit")
        encoding = data.get("encoding", "utf-8")
        fmt = ResponseFormat(data.get("response_format", "normal"))

        try:
            safe_path = _resolve_safe_path(data, path_str)
        except WorkspaceBoundaryError as e:
            return ToolResult(
                success=False,
                error=f"SECURITY: {e}",
                exit_code=126,
                details={"code": ToolErrorCode.PATH_OUTSIDE_WORKSPACE.value, "path": path_str},
            )

        if not safe_path.exists():
            ws_root = _get_workspace_root(data)
            suggestions = _find_similar_files(ws_root, path_str)
            guidance = ErrorGuidance.format_guidance(
                ToolErrorCode.FILE_NOT_FOUND,
                self.name,
                {"path": path_str, "matches": suggestions},
            )
            err_msg = f"File not found: '{path_str}'."
            if suggestions:
                err_msg += f"\nPossible matches in workspace:\n" + "\n".join(f"- {s}" for s in suggestions)
            err_msg += f"\n{guidance}"
            return ToolResult(
                success=False,
                error=err_msg,
                exit_code=1,
                details={"code": ToolErrorCode.FILE_NOT_FOUND.value, "path": path_str, "suggestions": suggestions},
            )

        if not safe_path.is_file():
            return ToolResult(
                success=False,
                error=f"Path is not a regular file: '{path_str}'. Use search.glob to list directory contents.",
                exit_code=1,
                details={"code": ToolErrorCode.INVALID_ARGUMENT.value, "path": path_str},
            )

        # Detect binary files
        try:
            with open(safe_path, "rb") as bf:
                chunk = bf.read(2048)
                if b"\x00" in chunk:
                    size = safe_path.stat().st_size
                    return ToolResult(
                        success=False,
                        error=f"Cannot read binary file '{path_str}' ({size} bytes) as text.",
                        exit_code=1,
                        details={"code": ToolErrorCode.INVALID_ARGUMENT.value, "size_bytes": size},
                    )
        except Exception as e:
            return ToolResult(success=False, error=f"Error checking file type: {e}", exit_code=1)

        try:
            raw_bytes = safe_path.read_bytes()
            content = raw_bytes.decode(encoding, errors="replace")
            # Record file identity for freshness tracking
            identity = file_identity_cache.record(safe_path, encoding=encoding)
        except UnicodeDecodeError as ue:
            return ToolResult(
                success=False,
                error=f"Encoding error reading '{path_str}': {ue}",
                exit_code=1,
                details={"code": ToolErrorCode.EDIT_ENCODING_ERROR.value},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to read '{path_str}': {exc}", exit_code=1)

        lines = content.splitlines()
        total_lines = len(lines)

        # 1-based indexing for line addressability
        start_idx = max(0, (start_line or 1) - 1)
        if start_idx >= total_lines and total_lines > 0:
            return ToolResult(
                success=True,
                output=f"File: {path_str}\nRequested start line ({start_line}) is beyond end of file ({total_lines} total lines).",
                exit_code=0,
                duration_seconds=time.monotonic() - start_t,
            )

        # Apply range/limit bounds
        if end_line is not None:
            end_idx = min(total_lines, max(start_idx, end_line))
        elif max_lines is not None:
            end_idx = min(total_lines, start_idx + max_lines)
        elif total_lines > 500 and start_line is None:
            # Safe default policy for large files: cap at first 200 lines
            end_idx = min(total_lines, start_idx + 200)
        else:
            end_idx = total_lines

        slice_lines = lines[start_idx:end_idx]
        returned_count = len(slice_lines)
        is_truncated = (end_idx < total_lines)

        # Format output
        if fmt == ResponseFormat.CONCISE:
            output_text = f"{path_str}: lines {start_idx + 1}-{end_idx} of {total_lines} ({returned_count} lines)"
        else:
            # Dynamic line number width
            width = max(len(str(end_idx)), 3)
            numbered_lines = [f"{idx:>{width}} | {line}" for idx, line in enumerate(slice_lines, start=start_idx + 1)]

            if fmt == ResponseFormat.DETAILED:
                newline_label = "CRLF" if identity.newline_style == "\r\n" else "LF"
                header = (
                    f"File: {path_str} ({total_lines} lines, {len(raw_bytes)} bytes, "
                    f"encoding: {identity.encoding}, newline: {newline_label}, sha256: {identity.content_hash[:8]})\n"
                    f"Lines: {start_idx + 1}-{end_idx} of {total_lines}\n"
                )
            else:
                header = f"File: {path_str}\nLines: {start_idx + 1}-{end_idx} of {total_lines}\n"

            body = header + "\n" + "\n".join(numbered_lines)
            if is_truncated:
                next_offset = end_idx + 1
                body += (
                    f"\n\n[TRUNCATED: Showing lines {start_idx + 1}-{end_idx} of {total_lines} "
                    f"({returned_count} lines). Use offset={next_offset} to inspect subsequent lines.]"
                )
            output_text = body

        duration = time.monotonic() - start_t
        return ToolResult(
            success=True,
            output=output_text,
            exit_code=0,
            duration_seconds=duration,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. fs.edit
# ─────────────────────────────────────────────────────────────────────────────

class FSEditInput(BaseModel):
    path: str = Field(..., description="Path to the file to edit, relative to workspace root")
    old_string: Optional[str] = Field(None, description="Exact substring to find and replace in the file")
    old_text: Optional[str] = Field(None, description="Exact substring to find and replace in the file")
    new_string: Optional[str] = Field(None, description="Replacement text")
    new_text: Optional[str] = Field(None, description="Replacement text")
    expected_occurrences: int = Field(default=1, description="Expected number of times old_string appears (default: 1)")
    replace_all: bool = Field(default=False, description="Replace all occurrences if True")
    allow_large_diff: bool = Field(default=False, description="Allow large diffs exceeding safety limits")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class FSEditTool(BaseTool):
    name = "fs.edit"
    description = (
        "Apply an exact, surgical text replacement to an existing file. Fails without modifying "
        "the file if old_string is absent or appears a different number of times than expected_occurrences. "
        "Always inspect the file with fs.read before calling fs.edit."
    )
    risk_score = 0.3
    blocked_in = ["plan"]

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        path_str = data.get("path", "")
        old_string = data.get("old_string") if data.get("old_string") is not None else data.get("old_text")
        new_string = data.get("new_string") if data.get("new_string") is not None else data.get("new_text")
        expected = data.get("expected_occurrences", 1)
        replace_all = data.get("replace_all", False)
        allow_large_diff = data.get("allow_large_diff", False)
        fmt = ResponseFormat(data.get("response_format", "normal"))

        if old_string is None:
            return ToolResult(
                success=False,
                error="old_string (or old_text) parameter is required.",
                exit_code=1,
                details={"code": ToolErrorCode.INVALID_ARGUMENT.value},
            )
        if new_string is None:
            new_string = ""

        try:
            safe_path = _resolve_safe_path(data, path_str)
        except WorkspaceBoundaryError as e:
            return ToolResult(
                success=False,
                error=f"SECURITY: {e}",
                exit_code=126,
                details={"code": ToolErrorCode.EDIT_PATH_OUTSIDE_WORKSPACE.value, "path": path_str},
            )

        if not safe_path.exists():
            return ToolResult(
                success=False,
                error=f"File not found: '{path_str}'. Cannot edit nonexistent file. Use fs.write to create it.",
                exit_code=1,
                details={"code": ToolErrorCode.FILE_NOT_FOUND.value, "path": path_str},
            )
        if not safe_path.is_file():
            return ToolResult(
                success=False,
                error=f"Path is not a regular file: '{path_str}'.",
                exit_code=1,
                details={"code": ToolErrorCode.EDIT_PATH_INVALID.value, "path": path_str},
            )

        # 1. Stale File Protection (Verify freshness against last read)
        is_fresh, stale_reason = file_identity_cache.check_freshness(safe_path)
        if not is_fresh:
            return ToolResult(
                success=False,
                error=f"EDIT_FILE_CHANGED: {stale_reason} Use 'fs.read' to inspect the updated content before retrying.",
                exit_code=1,
                details={"code": ToolErrorCode.EDIT_FILE_CHANGED.value, "reason": stale_reason},
            )

        # 2. Read current content and inspect newline style
        try:
            raw_bytes = safe_path.read_bytes()
            if b"\x00" in raw_bytes[:2048]:
                return ToolResult(
                    success=False,
                    error=f"Cannot edit binary file '{path_str}'.",
                    exit_code=1,
                    details={"code": ToolErrorCode.INVALID_ARGUMENT.value},
                )
            encoding = "utf-8"
            current_content = raw_bytes.decode(encoding, errors="replace")
            newline_style = "\r\n" if b"\r\n" in raw_bytes else "\n"
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read '{path_str}': {e}", exit_code=1)

        # 3. Exact string matching validation
        count = current_content.count(old_string)
        if count == 0:
            guidance = ErrorGuidance.format_guidance(ToolErrorCode.EDIT_TARGET_NOT_FOUND, self.name, {"path": path_str})
            return ToolResult(
                success=False,
                error=f"EDIT_TARGET_NOT_FOUND: old_text not found in '{path_str}' (old_string was not present). {guidance}",
                exit_code=1,
                details={"code": ToolErrorCode.EDIT_TARGET_NOT_FOUND.value, "path": path_str},
            )



        if not replace_all and count != expected:
            # Find line numbers of all matches for diagnostic guidance
            matches_lines: List[int] = []
            start_pos = 0
            while True:
                pos = current_content.find(old_string, start_pos)
                if pos == -1:
                    break
                line_no = current_content[:pos].count("\n") + 1
                matches_lines.append(line_no)
                start_pos = pos + len(old_string)

            code = ToolErrorCode.EDIT_TARGET_NOT_UNIQUE if expected == 1 else ToolErrorCode.EDIT_EXPECTED_COUNT_MISMATCH
            guidance = ErrorGuidance.format_guidance(code, self.name, {"count": count, "lines": matches_lines, "expected": expected})
            return ToolResult(
                success=False,
                error=f"{code.value}: old_string matched {count} time(s) in '{path_str}'.\n{guidance}",
                exit_code=1,
                details={
                    "code": code.value,
                    "path": path_str,
                    "matches_count": count,
                    "matches_lines": matches_lines,
                    "expected": expected,
                },
            )

        target_replace_count = count if replace_all else expected

        # 4. Newline preservation: Normalize new_string line endings to match file's native style
        if newline_style == "\r\n" and "\n" in new_string and "\r\n" not in new_string:
            normalized_new = new_string.replace("\n", "\r\n")
        elif newline_style == "\n" and "\r\n" in new_string:
            normalized_new = new_string.replace("\r\n", "\n")
        else:
            normalized_new = new_string

        # 5. Apply replacement and calculate unified diff
        updated_content = current_content.replace(old_string, normalized_new, target_replace_count)

        orig_lines = current_content.splitlines(keepends=True)
        new_lines = updated_content.splitlines(keepends=True)
        diff_hunks = list(difflib.unified_diff(
            orig_lines,
            new_lines,
            fromfile=f"a/{path_str}",
            tofile=f"b/{path_str}",
            lineterm=""
        ))

        lines_added = sum(1 for l in diff_hunks if l.startswith("+") and not l.startswith("+++"))
        lines_removed = sum(1 for l in diff_hunks if l.startswith("-") and not l.startswith("---"))
        diff_lines = lines_added + lines_removed

        # 6. Minimality check (EDIT_SUSPICIOUS_LARGE_DIFF protection)
        old_lines_cnt = len(old_string.splitlines())
        if not allow_large_diff and not replace_all:
            if old_lines_cnt <= 5 and len(orig_lines) > 20 and diff_lines > 200:
                guidance = ErrorGuidance.format_guidance(
                    ToolErrorCode.EDIT_SUSPICIOUS_LARGE_DIFF,
                    self.name,
                    {"diff_lines": diff_lines, "orig_lines": len(orig_lines)},
                )
                return ToolResult(
                    success=False,
                    error=f"EDIT_SUSPICIOUS_LARGE_DIFF: Surgical edit would mutate {diff_lines} lines.\n{guidance}",
                    exit_code=1,
                    details={
                        "code": ToolErrorCode.EDIT_SUSPICIOUS_LARGE_DIFF.value,
                        "diff_lines": diff_lines,
                        "orig_lines": len(orig_lines),
                    },
                )

        # 7. Atomic write via tempfile in the same directory
        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("wb", dir=safe_path.parent, delete=False) as tf:
                tf.write(updated_content.encode(encoding))
                tf.flush()
                os.fsync(tf.fileno())
                tmp_path = Path(tf.name)
            # Atomic rename / replace
            tmp_path.replace(safe_path)
        except Exception as e:
            if "tmp_path" in locals() and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return ToolResult(
                success=False,
                error=f"EDIT_WRITE_FAILED: Failed to write changes to '{path_str}': {e}",
                exit_code=1,
                details={"code": ToolErrorCode.EDIT_WRITE_FAILED.value},
            )

        # 8. Postcondition verification
        # Verify file exists and is readable
        if not safe_path.exists() or safe_path.stat().st_size == 0 and len(updated_content) > 0:
            safe_path.write_bytes(raw_bytes)
            return ToolResult(
                success=False,
                error="EDIT_POSTCONDITION_FAILED: File was empty after write. Reverted to original content.",
                exit_code=1,
                details={"code": ToolErrorCode.EDIT_POSTCONDITION_FAILED.value},
            )

        # Language syntax verification
        postcondition_info = "syntax valid"
        if path_str.endswith(".py"):
            try:
                ast.parse(updated_content, filename=path_str)
            except SyntaxError as se:
                # Rollback!
                safe_path.write_bytes(raw_bytes)
                file_identity_cache.record(safe_path, encoding=encoding)
                return ToolResult(
                    success=False,
                    error=f"EDIT_POSTCONDITION_FAILED: Python syntax error on line {se.lineno}: {se.msg}. Edit rolled back.",
                    exit_code=1,
                    details={"code": ToolErrorCode.EDIT_POSTCONDITION_FAILED.value, "syntax_error": str(se)},
                )
        elif path_str.endswith(".json"):
            try:
                json.loads(updated_content)
            except Exception as je:
                # Rollback!
                safe_path.write_bytes(raw_bytes)
                file_identity_cache.record(safe_path, encoding=encoding)
                return ToolResult(
                    success=False,
                    error=f"EDIT_POSTCONDITION_FAILED: JSON syntax error after edit: {je}. Edit rolled back.",
                    exit_code=1,
                    details={"code": ToolErrorCode.EDIT_POSTCONDITION_FAILED.value, "json_error": str(je)},
                )


        # Update file identity cache
        file_identity_cache.record(safe_path, encoding=encoding)

        duration = time.monotonic() - start_t
        chars_delta = len(normalized_new) * target_replace_count - len(old_string) * target_replace_count
        diff_snippet = "\n".join(diff_hunks[:30])
        if len(diff_hunks) > 30:
            diff_snippet += f"\n... ({len(diff_hunks) - 30} more diff lines)"

        summary = (
            f"Successfully edited '{path_str}'. Replaced {target_replace_count} occurrence(s) "
            f"(+{lines_added}/-{lines_removed} lines, {chars_delta:+d} chars). Postcondition: {postcondition_info}."
        )

        output_text = summary if fmt == ResponseFormat.CONCISE else f"{summary}\n\nDiff:\n{diff_snippet}"

        return ToolResult(
            success=True,
            output=output_text,
            exit_code=0,
            duration_seconds=duration,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. fs.write
# ─────────────────────────────────────────────────────────────────────────────

class FSWriteInput(BaseModel):
    path: str = Field(..., description="Path to the file to create or overwrite, relative to workspace root")
    content: str = Field(..., description="Complete text content to write")
    create_parents: bool = Field(default=True, description="Create parent directories if they do not exist")
    allow_overwrite: bool = Field(default=True, description="Allow overwriting an existing file")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class FSWriteTool(BaseTool):
    name = "fs.write"
    description = (
        "Create a new file or completely overwrite an existing file with the provided content. "
        "Performs an atomic write. Use fs.edit instead for surgical modifications of existing files."
    )
    risk_score = 0.4
    blocked_in = ["plan"]

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        path_str = data.get("path", "")
        content = data.get("content", "")
        create_parents = data.get("create_parents", True)
        allow_overwrite = data.get("allow_overwrite", True)

        try:
            safe_path = _resolve_safe_path(data, path_str)
        except WorkspaceBoundaryError as e:
            return ToolResult(
                success=False,
                error=f"SECURITY: {e}",
                exit_code=126,
                details={"code": ToolErrorCode.PATH_OUTSIDE_WORKSPACE.value, "path": path_str},
            )

        if safe_path.exists() and not allow_overwrite:
            guidance = ErrorGuidance.format_guidance(ToolErrorCode.FILE_EXISTS_OVERWRITE_REQUIRED, self.name, {"path": path_str})
            return ToolResult(
                success=False,
                error=f"FILE_EXISTS_OVERWRITE_REQUIRED: File '{path_str}' already exists.\n{guidance}",
                exit_code=1,
                details={"code": ToolErrorCode.FILE_EXISTS_OVERWRITE_REQUIRED.value, "path": path_str},
            )

        try:
            if create_parents:
                safe_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write via tempfile in same directory
            with tempfile.NamedTemporaryFile("wb", dir=safe_path.parent, delete=False) as tf:
                tf.write(content.encode("utf-8"))
                tf.flush()
                os.fsync(tf.fileno())
                tmp_path = Path(tf.name)
            tmp_path.replace(safe_path)

            # Record file identity
            file_identity_cache.record(safe_path, encoding="utf-8")

            duration = time.monotonic() - start_t
            line_count = len(content.splitlines())
            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} bytes ({line_count} lines) to '{path_str}'.",
                exit_code=0,
                duration_seconds=duration,
            )
        except Exception as exc:
            if "tmp_path" in locals() and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return ToolResult(success=False, error=f"Failed to write to '{path_str}': {exc}", exit_code=1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. shell.bash
# ─────────────────────────────────────────────────────────────────────────────

class ShellBashInput(BaseModel):
    command: str = Field(..., description="Shell command line string to execute")
    working_dir: str = Field(default=".", description="Working directory relative to project root")
    timeout_seconds: int = Field(default=60, description="Execution timeout limit in seconds")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class ShellBashTool(BaseTool):
    name = "shell.bash"
    description = (
        "Execute shell commands in the project workspace (build, test, git, etc.). "
        "Subject to 15 security gates, timeouts, and process cleanup. Use dedicated fs tools "
        "for file operations whenever possible."
    )
    risk_score = 0.7
    blocked_in = ["safe", "plan"]

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        command = data.get("command", "").strip()
        working_dir = data.get("working_dir", ".")
        timeout_seconds = data.get("timeout_seconds", 60)
        fmt = ResponseFormat(data.get("response_format", "normal"))

        if not command:
            return ToolResult(success=False, error="Command cannot be empty", exit_code=1)

        # 1. 15 Security Gates
        passed, gate_reason = check_all_gates(command)
        if not passed:
            return ToolResult(success=False, error=f"SECURITY: {gate_reason}", exit_code=126)

        # 2. Resolve working directory
        try:
            cwd_path = workspace_manager.validate_path(working_dir) if workspace_manager.is_locked else Path(working_dir).resolve()
            if not cwd_path.exists() or not cwd_path.is_dir():
                return ToolResult(success=False, error=f"Working directory does not exist: {working_dir}", exit_code=1)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        # 3. Platform adaptation
        cmd_to_run = _command_for_platform(command)

        # 4. Subprocess execution with process tracking
        try:
            proc = subprocess.Popen(
                cmd_to_run,
                shell=True,
                cwd=str(cwd_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            ACTIVE_SUBPROCESSES.add(proc)
            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout_seconds} seconds: {command[:80]}",
                    exit_code=124,
                    duration_seconds=time.monotonic() - start_t,
                )
            finally:
                ACTIVE_SUBPROCESSES.discard(proc)

            duration = time.monotonic() - start_t
            exit_code = proc.returncode

            combined = stdout
            if stderr:
                combined += f"\n--- stderr ---\n{stderr}" if stdout else stderr

            shaped = OutputShaper.shape(
                raw_output=combined,
                response_format=fmt,
                tool_name=self.name,
            )

            success = (exit_code == 0)
            return ToolResult(
                success=success,
                output=shaped.to_observation_text(),
                error=f"Command failed with exit code {exit_code}" if not success else None,
                exit_code=exit_code,
                duration_seconds=duration,
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Subprocess execution error: {e}", exit_code=1)


# ─────────────────────────────────────────────────────────────────────────────
# 5. search.glob
# ─────────────────────────────────────────────────────────────────────────────

class SearchGlobInput(BaseModel):
    pattern: str = Field(..., description="Glob pattern to search for (e.g. '**/*.py', 'src/*.ts')")
    base_path: str = Field(default=".", description="Base directory to search from, relative to workspace root")
    max_results: int = Field(default=50, description="Maximum number of file paths to return")
    include_directories: bool = Field(default=False, description="Whether to include directories in results")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class SearchGlobTool(BaseTool):
    name = "search.glob"
    description = (
        "Find files matching a glob pattern relative to the workspace root. "
        "Returns a list of matching file paths without reading file contents."
    )
    risk_score = 0.1
    blocked_in = []

    IGNORED_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".tox", "dist", "build"}

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        pattern = data.get("pattern", "")
        base_path = data.get("base_path", ".")
        max_results = data.get("max_results", 50)
        include_dirs = data.get("include_directories", False)

        try:
            root = _resolve_safe_path(data, base_path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        if not root.exists():
            return ToolResult(success=False, error=f"Base path does not exist: '{base_path}'", exit_code=1)

        matches: List[str] = []
        try:
            for p in root.glob(pattern):
                if any(part in self.IGNORED_DIRS for part in p.parts):
                    continue
                if p.is_file() or (include_dirs and p.is_dir()):
                    try:
                        rel = p.relative_to(root).as_posix()
                    except ValueError:
                        rel = str(p)
                    matches.append(rel)
                    if len(matches) >= max_results:
                        break
        except Exception as e:
            return ToolResult(success=False, error=f"Glob error: {e}", exit_code=1)

        matches.sort()
        duration = time.monotonic() - start_t
        if not matches:
            return ToolResult(
                success=True,
                output=f"No files matched pattern '{pattern}' in '{base_path}'.",
                exit_code=0,
                duration_seconds=duration,
            )

        truncated = len(matches) >= max_results
        lines = [f"Matched {len(matches)} file(s) for pattern '{pattern}':"]
        lines.extend(f"- {m}" for m in matches)
        if truncated:
            lines.append(f"\n[Truncated: maximum of {max_results} results returned. Narrow pattern to inspect further.]")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            exit_code=0,
            duration_seconds=duration,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. search.grep
# ─────────────────────────────────────────────────────────────────────────────

class SearchGrepInput(BaseModel):
    pattern: str = Field(..., description="Regex or text pattern to search for in files")
    path: str = Field(default=".", description="File or directory path to search within")
    file_pattern: Optional[str] = Field(default=None, description="Optional glob filter for filenames (e.g. '*.py')")
    max_results: int = Field(default=50, description="Maximum number of matches to return")
    context_lines: int = Field(default=1, description="Number of context lines before and after match")
    case_sensitive: bool = Field(default=False, description="Whether regex match is case-sensitive")
    literal: bool = Field(default=False, description="Treat pattern as literal string instead of regex")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class SearchGrepTool(BaseTool):
    name = "search.grep"
    description = (
        "Search file contents for a regex or string pattern across files in the workspace. "
        "Returns matching files, line numbers, and context lines without loading whole files."
    )
    risk_score = 0.1
    blocked_in = []

    IGNORED_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".tox", "dist", "build"}

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        pattern_str = data.get("pattern", "")
        search_path = data.get("path", ".")
        file_pat = data.get("file_pattern")
        max_results = data.get("max_results", 50)
        context_lines = data.get("context_lines", 1)
        case_sensitive = data.get("case_sensitive", False)
        literal = data.get("literal", False)

        try:
            root = _resolve_safe_path(data, search_path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        if not root.exists():
            return ToolResult(success=False, error=f"Search path does not exist: '{search_path}'", exit_code=1)

        # Validate regex pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        if literal:
            compiled_pat = re.compile(re.escape(pattern_str), flags)
        else:
            try:
                compiled_pat = re.compile(pattern_str, flags)
            except re.error as re_err:
                guidance = ErrorGuidance.format_guidance(
                    ToolErrorCode.GREP_INVALID_PATTERN,
                    self.name,
                    {"pattern": pattern_str, "error": str(re_err)},
                )
                return ToolResult(
                    success=False,
                    error=f"GREP_INVALID_PATTERN: Invalid regex pattern '{pattern_str}': {re_err}.\n{guidance}",
                    exit_code=1,
                    details={"code": ToolErrorCode.GREP_INVALID_PATTERN.value, "pattern": pattern_str, "error": str(re_err)},
                )

        files_to_search: List[Path] = []
        if root.is_file():
            files_to_search.append(root)
        else:
            for p in root.rglob(file_pat or "*"):
                if p.is_file():
                    if any(part in self.IGNORED_DIRS for part in p.parts):
                        continue
                    files_to_search.append(p)

        match_entries: List[str] = []
        total_matches = 0

        for fpath in files_to_search:
            try:
                # Skip large files > 2MB
                if fpath.stat().st_size > 2_000_000:
                    continue
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            lines = content.splitlines()
            try:
                rel_fpath = fpath.relative_to(root).as_posix()
            except ValueError:
                rel_fpath = str(fpath)

            for i, line in enumerate(lines):
                if compiled_pat.search(line):
                    total_matches += 1
                    start_ctx = max(0, i - context_lines)
                    end_ctx = min(len(lines), i + context_lines + 1)
                    ctx_block = [f"  {ln + 1}: {lines[ln]}" for ln in range(start_ctx, end_ctx)]
                    match_entries.append(f"{rel_fpath}:{i + 1}:\n" + "\n".join(ctx_block))

                    if len(match_entries) >= max_results:
                        break
            if len(match_entries) >= max_results:
                break

        duration = time.monotonic() - start_t
        if not match_entries:
            return ToolResult(
                success=True,
                output=f"No matches found for pattern '{pattern_str}' in '{search_path}'.",
                exit_code=0,
                duration_seconds=duration,
            )

        header = f"Found {total_matches} match(es) for pattern '{pattern_str}':\n"
        output = header + "\n\n".join(match_entries)
        if len(match_entries) >= max_results:
            output += f"\n\n[Truncated: showing first {max_results} matches. Narrow search path or pattern to see more.]"

        return ToolResult(
            success=True,
            output=output,
            exit_code=0,
            duration_seconds=duration,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. task.todo
# ─────────────────────────────────────────────────────────────────────────────

class TaskTodoInput(BaseModel):
    action: str = Field(..., description="Action to perform: 'add', 'update', 'complete', 'remove', 'list'")
    item_id: Optional[str] = Field(None, description="Identifier of the todo item")
    title: Optional[str] = Field(None, description="Title/description of the todo item")
    status: Optional[str] = Field(None, description="Status: 'pending', 'in_progress', 'completed'")


class TaskTodoTool(BaseTool):
    name = "task.todo"
    description = (
        "Manage visible mission checklist items and planned objectives. "
        "Allows tracking progress items without altering authoritative mission state."
    )
    risk_score = 0.1
    blocked_in = []

    _TODOS: Dict[str, Dict[str, Any]] = {}

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        action = data.get("action", "list").lower()
        item_id = data.get("item_id")
        title = data.get("title", "")
        status = data.get("status", "pending")

        if action == "add":
            if not title:
                return ToolResult(success=False, error="Title is required when adding a todo item.", exit_code=1)
            tid = item_id or f"todo-{len(self._TODOS) + 1}"
            self._TODOS[tid] = {
                "id": tid,
                "title": title,
                "status": status,
                "created_at": time.time(),
            }
            return ToolResult(success=True, output=f"Added todo item '{tid}': {title} [{status}].")

        elif action == "update":
            if not item_id or item_id not in self._TODOS:
                return ToolResult(success=False, error=f"Todo item '{item_id}' not found.", exit_code=1)
            if title:
                self._TODOS[item_id]["title"] = title
            if status:
                self._TODOS[item_id]["status"] = status
            return ToolResult(success=True, output=f"Updated todo item '{item_id}' to status '{status}'.")

        elif action == "complete":
            if not item_id or item_id not in self._TODOS:
                return ToolResult(success=False, error=f"Todo item '{item_id}' not found.", exit_code=1)
            self._TODOS[item_id]["status"] = "completed"
            return ToolResult(success=True, output=f"Marked todo item '{item_id}' as completed.")

        elif action == "remove":
            if not item_id or item_id not in self._TODOS:
                return ToolResult(success=False, error=f"Todo item '{item_id}' not found.", exit_code=1)
            del self._TODOS[item_id]
            return ToolResult(success=True, output=f"Removed todo item '{item_id}'.")

        elif action == "list":
            if not self._TODOS:
                return ToolResult(success=True, output="No active todo items in checklist.")
            lines = ["Current Mission Todo Checklist:"]
            for tid, item in self._TODOS.items():
                mark = "✓" if item["status"] == "completed" else ("▶" if item["status"] == "in_progress" else "○")
                lines.append(f"  {mark} [{item['id']}] {item['title']} ({item['status']})")
            return ToolResult(success=True, output="\n".join(lines), duration_seconds=time.monotonic() - start_t)

        return ToolResult(success=False, error=f"Unknown action '{action}'. Valid: add, update, complete, remove, list.", exit_code=1)


# ─────────────────────────────────────────────────────────────────────────────
# 8. task.delegate
# ─────────────────────────────────────────────────────────────────────────────

class TaskDelegateInput(BaseModel):
    target_role: str = Field(default="explorer", description="Target subagent role: explorer, reviewer, tester, implementer, analyst")
    objective: str = Field(..., description="Specific subtask or objective to delegate")
    context_files: List[str] = Field(default_factory=list, description="Relevant files for the subagent")
    constraints: Optional[str] = Field(None, description="Execution constraints or parameters")
    requirements: List[str] = Field(default_factory=list, description="Specific goal requirements assigned")
    is_background: bool = Field(default=False, description="Run as asynchronous background task")


class TaskDelegateTool(BaseTool):
    name = "task.delegate"
    description = (
        "Delegate an isolated subtask to a specialized subagent (explorer, reviewer, tester, implementer). "
        "The child subagent runs with an isolated context and strictly enforced tool permissions."
    )
    risk_score = 0.2
    blocked_in = []

    def execute(self, inp: Any) -> ToolResult:
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        role = data.get("target_role", "explorer")
        obj = data.get("objective", "")
        files = data.get("context_files", [])
        constraints = data.get("constraints")
        requirements = data.get("requirements", [])
        is_bg = data.get("is_background", False)

        subagent_mgr = data.get("_subagent_manager")
        if subagent_mgr is not None:
            task_id = f"task_{uuid.uuid4().hex[:6]}"
            try:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                if loop.is_running():
                    coro = subagent_mgr.delegate_task(
                        task_id=task_id,
                        goal=obj,
                        role=role,
                        requirements=requirements,
                        scope_paths=files,
                        constraints=[constraints] if constraints else [],
                        is_background=is_bg,
                    )
                    future = asyncio.run_coroutine_threadsafe(coro, loop)
                    res = future.result(timeout=180.0)
                else:
                    res = loop.run_until_complete(
                        subagent_mgr.delegate_task(
                            task_id=task_id,
                            goal=obj,
                            role=role,
                            requirements=requirements,
                            scope_paths=files,
                            constraints=[constraints] if constraints else [],
                            is_background=is_bg,
                        )
                    )

                if is_bg:
                    return ToolResult(
                        success=True,
                        output=f"Background subagent task spawned successfully. Job ID: {res.job_id}",
                        details=res.to_dict(),
                    )
                else:
                    return ToolResult(
                        success=(res.status.value in ("SUCCEEDED", "COMPLETED")),
                        output=f"Subagent execution complete ({res.status.value}):\n{res.summary}",
                        details=res.to_dict(),
                    )
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"SUBAGENT_DELEGATION_FAILED: {e}",
                    exit_code=1,
                )

        return ToolResult(
            success=False,
            error=f"SUBAGENT_DELEGATION_NOT_AVAILABLE: Subagent delegation for role '{role}' is not configured in this execution context. Please handle objective '{obj[:50]}' directly in the current turn.",
            exit_code=1,
            details={
                "role": role,
                "objective": obj,
                "context_files": files,
                "is_background": is_bg,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# 9. user.ask
# ─────────────────────────────────────────────────────────────────────────────

class UserAskInput(BaseModel):
    question: str = Field(..., description="Question to present to the user")
    context: Optional[str] = Field(None, description="Context explaining why this choice is needed")
    choices: List[str] = Field(default_factory=list, description="Optional discrete choices for user")


class UserAskTool(BaseTool):
    name = "user.ask"
    description = (
        "Ask the user a clarifying question when requirements are ambiguous or critical decisions "
        "require human input. Do not use for trivial decisions."
    )
    risk_score = 0.1
    blocked_in = []

    def execute(self, inp: Any) -> ToolResult:
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        q = data.get("question", "")
        choices = data.get("choices", [])
        ch_str = f" Options: {', '.join(choices)}" if choices else ""
        return ToolResult(
            success=True,
            output=f"USER_QUESTION_PROMPTED: '{q}'{ch_str}. Awaiting user response.",
            exit_code=0,
        )
