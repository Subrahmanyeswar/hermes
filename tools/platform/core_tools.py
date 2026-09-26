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
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from core.workspace import workspace_manager, WorkspaceBoundaryError
from tools.base import BaseTool, ToolResult
from tools.security import check_all_gates
from tools.shell_tools import ACTIVE_SUBPROCESSES, _command_for_platform
from tools.platform.specs import ResponseFormat
from tools.platform.output import OutputShaper


def _resolve_safe_path(data: Dict[str, Any], path_str: str) -> Path:
    """Resolve path against active or global workspace manager."""
    wm = data.get("_workspace") or workspace_manager
    if wm and wm.is_locked:
        return wm.validate_path(path_str)
    return (Path.cwd() / path_str).resolve() if not Path(path_str).is_absolute() else Path(path_str).resolve()


# ─────────────────────────────────────────────────────────────────────────────
# 1. fs.read
# ─────────────────────────────────────────────────────────────────────────────

class FSReadInput(BaseModel):
    path: str = Field(..., description="Path to the file to read, relative to workspace root")
    start_line: Optional[int] = Field(None, description="Starting line number (1-based, inclusive)")
    end_line: Optional[int] = Field(None, description="Ending line number (1-based, inclusive)")
    max_lines: Optional[int] = Field(None, description="Maximum number of lines to return")
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
        start_line = data.get("start_line")
        end_line = data.get("end_line")
        max_lines = data.get("max_lines")
        encoding = data.get("encoding", "utf-8")
        fmt = ResponseFormat(data.get("response_format", "normal"))

        try:
            safe_path = _resolve_safe_path(data, path_str)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        if not safe_path.exists():
            return ToolResult(success=False, error=f"File not found: {path_str}", exit_code=1)
        if not safe_path.is_file():
            return ToolResult(success=False, error=f"Path is not a regular file: {path_str}", exit_code=1)

        # Detect binary files
        try:
            with open(safe_path, "rb") as bf:
                chunk = bf.read(1024)
                if b"\x00" in chunk:
                    size = safe_path.stat().st_size
                    return ToolResult(
                        success=False,
                        error=f"Cannot read binary file '{path_str}' ({size} bytes) as text.",
                        exit_code=1,
                    )
        except Exception as e:
            return ToolResult(success=False, error=f"Error checking file type: {e}", exit_code=1)

        try:
            content = safe_path.read_text(encoding=encoding, errors="replace")
            shaped = OutputShaper.shape(
                raw_output=content,
                response_format=fmt,
                start_line=start_line,
                end_line=end_line,
                max_lines=max_lines,
                tool_name=self.name,
            )
            duration = time.monotonic() - start_t
            return ToolResult(
                success=True,
                output=shaped.to_observation_text(),
                exit_code=0,
                duration_seconds=duration,
            )
        except UnicodeDecodeError as ue:
            return ToolResult(success=False, error=f"Encoding error reading {path_str}: {ue}", exit_code=1)
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to read {path_str}: {exc}", exit_code=1)


# ─────────────────────────────────────────────────────────────────────────────
# 2. fs.edit
# ─────────────────────────────────────────────────────────────────────────────

class FSEditInput(BaseModel):
    path: str = Field(..., description="Path to the file to edit, relative to workspace root")
    old_text: str = Field(..., description="Exact substring to find and replace in the file")
    new_text: str = Field(..., description="Replacement text")
    expected_occurrences: int = Field(default=1, description="Expected number of times old_text appears (default: 1)")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class FSEditTool(BaseTool):
    name = "fs.edit"
    description = (
        "Apply an exact, surgical text replacement to an existing file. Fails without modifying "
        "the file if old_text is absent or appears a different number of times than expected_occurrences. "
        "Always inspect the file with fs.read before calling fs.edit."
    )
    risk_score = 0.3
    blocked_in = ["plan"]

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        path_str = data.get("path", "")
        old_text = data.get("old_text", "")
        new_text = data.get("new_text", "")
        expected = data.get("expected_occurrences", 1)

        try:
            safe_path = _resolve_safe_path(data, path_str)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        if not safe_path.exists():
            return ToolResult(success=False, error=f"File not found: {path_str}", exit_code=1)
        if not safe_path.is_file():
            return ToolResult(success=False, error=f"Path is not a regular file: {path_str}", exit_code=1)

        try:
            current_content = safe_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read {path_str}: {e}", exit_code=1)

        count = current_content.count(old_text)
        if count == 0:
            return ToolResult(
                success=False,
                error=f"old_text not found in '{path_str}'. Inspect current lines with fs.read before retrying.",
                exit_code=1,
            )
        if count != expected:
            return ToolResult(
                success=False,
                error=f"old_text appears {count} times in '{path_str}', but expected_occurrences was {expected}. Refine old_text to be unique.",
                exit_code=1,
            )

        # Apply replacement
        updated_content = current_content.replace(old_text, new_text, expected)

        # Atomic write via tempfile
        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", dir=safe_path.parent, delete=False, encoding="utf-8") as tf:
                tf.write(updated_content)
                tmp_path = Path(tf.name)
            tmp_path.replace(safe_path)

            duration = time.monotonic() - start_t
            chars_delta = len(new_text) - len(old_text)
            summary = (
                f"Successfully edited '{path_str}'. Replaced {count} occurrence(s) "
                f"({chars_delta:+d} chars delta)."
            )
            return ToolResult(
                success=True,
                output=summary,
                exit_code=0,
                duration_seconds=duration,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write changes to {path_str}: {e}", exit_code=1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. fs.write
# ─────────────────────────────────────────────────────────────────────────────

class FSWriteInput(BaseModel):
    path: str = Field(..., description="Path to the file to create or overwrite, relative to workspace root")
    content: str = Field(..., description="Complete text content to write")
    create_parents: bool = Field(default=True, description="Create parent directories if they do not exist")
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

        try:
            safe_path = _resolve_safe_path(data, path_str)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        try:
            if create_parents:
                safe_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write
            with tempfile.NamedTemporaryFile("w", dir=safe_path.parent, delete=False, encoding="utf-8") as tf:
                tf.write(content)
                tmp_path = Path(tf.name)
            tmp_path.replace(safe_path)

            duration = time.monotonic() - start_t
            line_count = len(content.splitlines())
            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} bytes ({line_count} lines) to '{path_str}'.",
                exit_code=0,
                duration_seconds=duration,
            )
        except Exception as exc:
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
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class SearchGlobTool(BaseTool):
    name = "search.glob"
    description = (
        "Find files matching a glob pattern relative to the workspace root. "
        "Returns a list of matching file paths without reading file contents."
    )
    risk_score = 0.1
    blocked_in = []

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        pattern = data.get("pattern", "")
        base_path = data.get("base_path", ".")
        max_results = data.get("max_results", 50)

        try:
            root = _resolve_safe_path(data, base_path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        if not root.exists():
            return ToolResult(success=False, error=f"Base path does not exist: {base_path}", exit_code=1)

        matches: List[str] = []
        try:
            for p in root.glob(pattern):
                if p.is_file():
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
        lines = [f"{len(matches)} match(es) for pattern '{pattern}':"]
        lines.extend(f"- {m}" for m in matches)
        if truncated:
            lines.append(f"\n[Truncated: maximum of {max_results} results returned. Narrow pattern to see more.]")

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
    max_results: int = Field(default=40, description="Maximum number of matches to return")
    context_lines: int = Field(default=1, description="Number of context lines before and after match")
    case_sensitive: bool = Field(default=False, description="Whether regex match is case-sensitive")
    response_format: str = Field(default="normal", description="Output detail level: concise, normal, detailed")


class SearchGrepTool(BaseTool):
    name = "search.grep"
    description = (
        "Search file contents for a regex or string pattern across files in the workspace. "
        "Returns matching files, line numbers, and context lines without loading whole files."
    )
    risk_score = 0.1
    blocked_in = []

    def execute(self, inp: Any) -> ToolResult:
        start_t = time.monotonic()
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        pattern_str = data.get("pattern", "")
        search_path = data.get("path", ".")
        file_pat = data.get("file_pattern")
        max_results = data.get("max_results", 40)
        context_lines = data.get("context_lines", 1)
        case_sensitive = data.get("case_sensitive", False)

        try:
            root = _resolve_safe_path(data, search_path)
        except WorkspaceBoundaryError as e:
            return ToolResult(success=False, error=f"SECURITY: {e}", exit_code=126)

        if not root.exists():
            return ToolResult(success=False, error=f"Search path does not exist: {search_path}", exit_code=1)

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern_str, flags)
        except re.error as re_err:
            return ToolResult(success=False, error=f"Invalid regex pattern: {re_err}", exit_code=1)

        files_to_search: List[Path] = []
        if root.is_file():
            files_to_search.append(root)
        else:
            for p in root.rglob(file_pat or "*"):
                if p.is_file():
                    # Ignore common hidden/build dirs
                    if any(part in (".git", "node_modules", ".venv", "__pycache__") for part in p.parts):
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
                if regex.search(line):
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
            output += f"\n\n[Truncated: showing first {max_results} matches.]"

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
    target_role: str = Field(..., description="Target subagent role (e.g. 'researcher', 'debugger')")
    objective: str = Field(..., description="Specific subtask or objective to delegate")
    context_files: List[str] = Field(default_factory=list, description="Relevant files for the subagent")
    constraints: Optional[str] = Field(None, description="Execution constraints or parameters")


class TaskDelegateTool(BaseTool):
    name = "task.delegate"
    description = (
        "Request delegation of a self-contained subtask to a specialized subagent. "
        "Returns structured NOT_AVAILABLE if subagent subsystem is not enabled."
    )
    risk_score = 0.2
    blocked_in = []

    def execute(self, inp: Any) -> ToolResult:
        # Prompt 5 defines the formal delegation boundary contract; full subagents are deferred to Prompt 10.
        data = inp if isinstance(inp, dict) else (inp.model_dump() if hasattr(inp, "model_dump") else inp.dict())
        role = data.get("target_role", "subagent")
        obj = data.get("objective", "")
        return ToolResult(
            success=False,
            error=f"SUBAGENT_DELEGATION_NOT_AVAILABLE: Subagent delegation for role '{role}' is deferred to Prompt 10. Please handle objective '{obj[:50]}' directly in the current turn.",
            exit_code=1,
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
