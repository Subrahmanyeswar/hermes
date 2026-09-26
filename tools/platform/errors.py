# tools/platform/errors.py
"""
Standardized Tool Error Architecture and Actionable Guidance for HERMES 2.x.
Ensures tool failures become actionable observations rather than unhandled exceptions.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ToolErrorCode(str, enum.Enum):
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PATH_OUTSIDE_WORKSPACE = "PATH_OUTSIDE_WORKSPACE"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_CONFLICT = "FILE_CONFLICT"
    FILE_EXISTS_OVERWRITE_REQUIRED = "FILE_EXISTS_OVERWRITE_REQUIRED"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    PROCESS_FAILED = "PROCESS_FAILED"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    USER_REQUIRED = "USER_REQUIRED"

    # Surgical Editing Specific Error Codes
    EDIT_TARGET_NOT_FOUND = "EDIT_TARGET_NOT_FOUND"
    EDIT_TARGET_NOT_UNIQUE = "EDIT_TARGET_NOT_UNIQUE"
    EDIT_EXPECTED_COUNT_MISMATCH = "EDIT_EXPECTED_COUNT_MISMATCH"
    EDIT_PATH_INVALID = "EDIT_PATH_INVALID"
    EDIT_PATH_OUTSIDE_WORKSPACE = "EDIT_PATH_OUTSIDE_WORKSPACE"
    EDIT_FILE_CHANGED = "EDIT_FILE_CHANGED"
    EDIT_ENCODING_ERROR = "EDIT_ENCODING_ERROR"
    EDIT_WRITE_FAILED = "EDIT_WRITE_FAILED"
    EDIT_POSTCONDITION_FAILED = "EDIT_POSTCONDITION_FAILED"
    EDIT_CONFLICT = "EDIT_CONFLICT"
    EDIT_SUSPICIOUS_LARGE_DIFF = "EDIT_SUSPICIOUS_LARGE_DIFF"

    # Search Specific Error Codes
    GREP_INVALID_PATTERN = "GREP_INVALID_PATTERN"


@dataclass
class ToolError:
    """Structured error payload providing complete diagnostic information."""
    code: ToolErrorCode
    message: str
    what_failed: str
    why_it_failed: str
    what_was_not_changed: str = "No files or environment changes were made."
    actionable_guidance: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_observation_text(self) -> str:
        """Render a concise, high-signal observation for model context."""
        lines = [
            f"ERROR [{self.code.value}]: {self.message}",
            f"Failed action: {self.what_failed}",
            f"Reason: {self.why_it_failed}",
            f"Workspace state: {self.what_was_not_changed}",
        ]
        if self.actionable_guidance:
            lines.append(f"Recommended next step: {self.actionable_guidance}")
        return "\n".join(lines)


class ErrorGuidance:
    """Translates raw errors into actionable guidance tailored to runtime context."""

    @staticmethod
    def format_guidance(code: ToolErrorCode, tool_name: str, context: Optional[Dict[str, Any]] = None) -> str:
        ctx = context or {}
        if code == ToolErrorCode.TOOL_NOT_FOUND:
            closest = ctx.get("closest", [])
            suggestions = f" Available related tools: {', '.join(closest)}" if closest else ""
            return f"Use 'tool_search' or search.grep/search.glob to discover available capabilities.{suggestions}"

        elif code == ToolErrorCode.INVALID_ARGUMENT:
            missing = ctx.get("missing", [])
            if missing:
                return f"Provide required argument(s): {', '.join(missing)}."
            return "Inspect the tool schema and supply valid parameter types and formats."

        elif code in (ToolErrorCode.PATH_OUTSIDE_WORKSPACE, ToolErrorCode.EDIT_PATH_OUTSIDE_WORKSPACE):
            path = ctx.get("path", "")
            return f"Path '{path}' escapes workspace. Use a relative path within the workspace root without '../'."

        elif code == ToolErrorCode.FILE_NOT_FOUND:
            path = ctx.get("path", "")
            matches = ctx.get("matches", [])
            guidance = f"File '{path}' does not exist."
            if matches:
                guidance += f" Did you mean one of these? {', '.join(matches[:3])}"
            else:
                guidance += " Verify the path using 'search.glob' before retrying."
            return guidance

        elif code == ToolErrorCode.FILE_EXISTS_OVERWRITE_REQUIRED:
            path = ctx.get("path", "")
            return f"File '{path}' already exists. To overwrite intentionally, set allow_overwrite=True or use 'fs.edit' for surgical modifications."

        elif code == ToolErrorCode.EDIT_TARGET_NOT_FOUND:
            path = ctx.get("path", "")
            return f"Target old_string was not found in '{path}'. Use 'fs.read' to inspect current lines and verify exact whitespace/indentation."

        elif code == ToolErrorCode.EDIT_TARGET_NOT_UNIQUE:
            count = ctx.get("count", 0)
            lines = ctx.get("lines", [])
            lines_str = f" at line(s): {', '.join(f'line {l}' for l in lines[:5])}" if lines else ""
            return (
                f"Target old_string matched {count} times{lines_str}. "
                "Include more surrounding context lines in old_string to make the match unique, "
                "or specify replace_all=True if all occurrences must be changed."
            )


        elif code == ToolErrorCode.EDIT_EXPECTED_COUNT_MISMATCH:
            actual = ctx.get("actual", 0)
            expected = ctx.get("expected", 1)
            return f"Expected {expected} occurrence(s) of old_string, but found {actual}. Inspect file lines with 'fs.read'."

        elif code == ToolErrorCode.EDIT_FILE_CHANGED:
            path = ctx.get("path", "")
            return f"File '{path}' was modified after it was last read. Re-read the file with 'fs.read' to obtain the fresh content before editing."

        elif code == ToolErrorCode.EDIT_SUSPICIOUS_LARGE_DIFF:
            diff_lines = ctx.get("diff_lines", 0)
            orig_lines = ctx.get("orig_lines", 0)
            return (
                f"Surgical edit generated a suspiciously large diff ({diff_lines} lines changed out of {orig_lines}). "
                "Ensure old_string and new_string target only the localized region, or use 'fs.write' if rewriting the whole file."
            )

        elif code == ToolErrorCode.EDIT_POSTCONDITION_FAILED:
            check_error = ctx.get("check_error", "")
            return f"Postcondition validation failed: {check_error}. The file modification was aborted and the original content was preserved."

        elif code == ToolErrorCode.GREP_INVALID_PATTERN:
            pat = ctx.get("pattern", "")
            err = ctx.get("error", "")
            return f"Search pattern '{pat}' is not a valid regular expression ({err}). For literal searches, escape regex characters or set literal=True."

        elif code in (ToolErrorCode.FILE_CONFLICT, ToolErrorCode.EDIT_CONFLICT):
            return "The target text does not match current file contents or appears multiple times. Read the file with 'fs.read' to inspect current lines before editing."

        elif code == ToolErrorCode.COMMAND_REJECTED:
            reason = ctx.get("reason", "")
            return f"Security policy blocked this command: {reason}. Choose a non-destructive alternative or run a safe script."

        elif code == ToolErrorCode.COMMAND_TIMEOUT:
            timeout = ctx.get("timeout", 60)
            return f"Command exceeded timeout limit of {timeout}s. Break into smaller commands or inspect long-running processes."

        elif code == ToolErrorCode.PROCESS_FAILED:
            cmd = ctx.get("command", "")
            if sys.platform == "win32":
                posix_commands = {"wc", "ls", "grep", "cat", "find", "sed", "awk"}
                first_tok = cmd.strip().split()[0].lower() if cmd.strip() else ""
                if first_tok in posix_commands:
                    return f"'{first_tok}' may not be natively available in Windows cmd/powershell. Consider using Python commands via python -c or canonical tools (fs.read, search.grep, search.glob)."
            return "Check error output and stderr above to diagnose test or compilation failures."

        elif code == ToolErrorCode.PERMISSION_DENIED:
            return "Action is restricted by active security mode. In 'safe' mode, mutating tools require confirmation or higher permissions."

        elif code == ToolErrorCode.USER_REQUIRED:
            return "User confirmation or interactive clarification is required before proceeding."

        return "Review the error details and adjust parameters before retrying."

