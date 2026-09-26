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
    COMMAND_REJECTED = "COMMAND_REJECTED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    PROCESS_FAILED = "PROCESS_FAILED"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    USER_REQUIRED = "USER_REQUIRED"


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

        elif code == ToolErrorCode.PATH_OUTSIDE_WORKSPACE:
            path = ctx.get("path", "")
            return f"Path '{path}' escapes workspace. Use a relative path within the workspace root without '../'."

        elif code == ToolErrorCode.FILE_NOT_FOUND:
            path = ctx.get("path", "")
            return f"File '{path}' does not exist. Verify the path using 'search.glob' or parent directory listing before retrying."

        elif code == ToolErrorCode.FILE_CONFLICT:
            return "The target text does not match the current file contents exactly or appears multiple times. Read the file with 'fs.read' to inspect current lines before editing."

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
