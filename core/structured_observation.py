# core/structured_observation.py
"""
Structured Observation Format for HERMES
Based on: InterCode (Yang et al., 2024)

InterCode insight: Coding is a POMDP. Actions (tool calls) produce
observations. Treating observations as raw unstructured strings
causes three problems:
  1. Error information gets buried in noisy output
  2. State changes are implicit and easy to miss
  3. The model cannot distinguish stdout from stderr from exit codes

This module defines a structured observation that captures all
relevant aspects of a tool execution result.

Also integrates: ToolEmu risk awareness — before gated tools,
the Thought must include an explicit risk assessment.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Dict
from loguru import logger


def extract_syntax_diagnostic(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse error output from Node.js, Python, or standard linters/compilers
    to extract structured diagnostic information:
    - file: file path or name
    - line: line number (int)
    - column: column number (int, if present)
    - error_class: error category (e.g. 'SyntaxError', 'TypeError')
    - message: specific error message
    - source_line: snippet of code where error occurred
    """
    if not text or not isinstance(text, str):
        return None

    lines = [l.rstrip("\r\n") for l in text.splitlines()]
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return None

    file_path: Optional[str] = None
    line_num: Optional[int] = None
    col_num: Optional[int] = None
    error_class: Optional[str] = None
    message: Optional[str] = None
    source_line: Optional[str] = None

    # 1. Search for error class and message (e.g. "SyntaxError: Invalid or unexpected token")
    error_re = re.compile(r"^(?:(?:Uncaught\s+)?([A-Za-z0-9_]+Error|[A-Za-z0-9_]+Exception)):\s*(.+)$")
    for line in lines:
        stripped = line.strip()
        # Skip Node.js version banners, runtime notes, stack trace frames
        if stripped.startswith("Node.js v") or stripped.startswith("at "):
            continue
        m = error_re.search(stripped)
        if m:
            error_class = m.group(1).strip()
            message = m.group(2).strip()
            break

    # 2. Search for Node.js style location: "path/to/file.ext:line[:col]" or "C:\path\to\file.ext:line[:col]"
    node_loc_re = re.compile(
        r"^([A-Za-z]:[\\/][^:\n\r]+|\.?\.?[\\/][^:\n\r]+|[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+):(\d+)(?::(\d+))?"
    )
    for i, line in enumerate(lines):
        m = node_loc_re.match(line.strip())
        if m:
            file_path = m.group(1).strip()
            try:
                line_num = int(m.group(2))
            except ValueError:
                pass
            if m.group(3):
                try:
                    col_num = int(m.group(3))
                except ValueError:
                    pass
            # Next line might be the source code line
            if i + 1 < len(lines):
                candidate_source = lines[i + 1]
                if "^" not in candidate_source and not candidate_source.strip().startswith("SyntaxError"):
                    source_line = candidate_source.strip()
            break

    # 3. Search for Python style location: File "path/to/file.py", line 42
    if not file_path:
        py_loc_re = re.compile(r'File\s+"([^"]+)",\s*line\s*(\d+)')
        for i, line in enumerate(lines):
            m = py_loc_re.search(line)
            if m:
                file_path = m.group(1).strip()
                try:
                    line_num = int(m.group(2))
                except ValueError:
                    pass
                if i + 1 < len(lines):
                    source_line = lines[i + 1].strip()
                break

    # 3b. Search for completeness/truncation gate pattern: File 'path.js' contains invalid or incomplete syntax
    if not file_path:
        trunc_re = re.compile(r"File\s+'([^']+)'\s+contains\s+invalid\s+or\s+incomplete\s+syntax:\s*(.+)", re.IGNORECASE)
        for line in lines:
            m = trunc_re.search(line)
            if m:
                file_path = m.group(1).strip()
                message = m.group(2).strip()
                line_m = re.search(r"line\s+(\d+)", line, re.IGNORECASE)
                if line_m:
                    try:
                        line_num = int(line_m.group(1))
                    except ValueError:
                        pass
                error_class = "SyntaxError"
                break

    # 4. Search for caret indicator line to determine column or source line if still missing
    for i, line in enumerate(lines):
        if "^" in line and not line.strip().startswith("SyntaxError"):
            caret_pos = line.find("^")
            if col_num is None and caret_pos >= 0:
                col_num = caret_pos + 1
            if source_line is None and i > 0:
                prev_line = lines[i - 1].strip()
                if not node_loc_re.match(prev_line) and not prev_line.startswith("File "):
                    source_line = prev_line

    if not error_class:
        # Fallback error detection
        for line in reversed(non_empty):
            stripped = line.strip()
            if stripped.startswith("Node.js v") or stripped.startswith("at "):
                continue
            if "error" in stripped.lower():
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    error_class = parts[0].strip()
                    message = parts[1].strip()
                else:
                    error_class = "Error"
                    message = stripped
                break

    # If neither error_class nor file_path was found, return None
    if not error_class and not file_path:
        return None

    return {
        "file": file_path or "unknown",
        "line": line_num or 1,
        "column": col_num,
        "error_class": error_class or "SyntaxError",
        "message": message or "Syntax/runtime execution error",
        "source_line": source_line,
    }


@dataclass
class StructuredObservation:
    """
    Structured output from a tool execution.
    Converts raw tool results into a parsed, navigable structure.
    """
    tool_name: str
    exit_code: int
    success: bool
    stdout: str
    stderr: str
    duration_seconds: float
    state_delta: dict = field(default_factory=dict)
    # state_delta tracks what changed: {"files_created": [...], "files_modified": [...]}
    error_summary: Optional[str] = None
    diagnostic: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def from_tool_result(
        cls,
        tool_name: str,
        tool_result: Any,
        duration: float,
        files_before: set[str],
        files_after: set[str],
    ) -> "StructuredObservation":
        """
        Build a StructuredObservation from a raw ToolResult.
        Computes state_delta by comparing filesystem snapshots.
        """
        output = getattr(tool_result, "output", "") or ""
        error = getattr(tool_result, "error", "") or ""

        # Separate stdout from stderr heuristically
        stdout = output
        stderr = error

        # Compute state delta
        new_files = files_after - files_before
        state_delta = {}
        if new_files:
            state_delta["files_created"] = sorted(new_files)

        # Build error summary and diagnostic for failed executions
        error_summary = None
        diagnostic = None
        exit_code = getattr(tool_result, "exit_code", 0 if getattr(tool_result, "success", True) else 1)
        success = getattr(tool_result, "success", exit_code == 0)

        if not success:
            raw_err = stderr if (stderr and stderr.strip()) else stdout
            if raw_err:
                diagnostic = extract_syntax_diagnostic(raw_err)
                if diagnostic:
                    f_name = Path(diagnostic["file"]).name if diagnostic.get("file") else "unknown"
                    error_summary = f"{diagnostic['error_class']}: {diagnostic['message']} at {f_name}:{diagnostic['line']}"
                else:
                    # Filter out version banners and runtime noise
                    valid_lines = [
                        l.strip() for l in raw_err.splitlines()
                        if l.strip() and not l.strip().startswith("Node.js v") and not l.strip().startswith("at ")
                    ]
                    if valid_lines:
                        err_lines = [l for l in valid_lines if "error" in l.lower()]
                        error_summary = err_lines[0][:200] if err_lines else valid_lines[-1][:200]

        return cls(
            tool_name=tool_name,
            exit_code=exit_code,
            success=success,
            stdout=stdout[:1000],
            stderr=stderr[:500],
            duration_seconds=duration,
            state_delta=state_delta,
            error_summary=error_summary,
            diagnostic=diagnostic,
        )

    def to_context_string(self) -> str:
        """
        Format for injection into the next T1 prompt.
        InterCode: observations must be clear, structured, and
        clearly separated from instructions.
        """
        lines = [
            f"OBSERVATION from {self.tool_name}:",
            f"  Status:   {'SUCCESS' if self.success else 'FAILED'} (exit_code={self.exit_code})",
            f"  Duration: {self.duration_seconds:.2f}s",
        ]

        if self.stdout.strip():
            lines.append(f"  Output:   {self.stdout.strip()[:300]}")

        if self.stderr.strip():
            lines.append(f"  Error:    {self.stderr.strip()[:200]}")

        if self.state_delta:
            created = self.state_delta.get("files_created", [])
            if created:
                lines.append(f"  Created:  {', '.join(Path(f).name for f in created[:5])}")

        if self.error_summary:
            lines.append(f"  Summary:  {self.error_summary}")

        if self.diagnostic:
            f_name = Path(self.diagnostic.get("file", "")).name
            lines.append(f"  Diagnostic: {self.diagnostic.get('error_class')}: {self.diagnostic.get('message')} at {f_name}:{self.diagnostic.get('line')}")
            if self.diagnostic.get("source_line"):
                lines.append(f"  Code:       {self.diagnostic['source_line']}")

        return "\n".join(lines)

    def is_actionable_failure(self) -> bool:
        """
        True if the failure contains information the model can act on.
        (Some failures are transient — network timeout — vs actionable
        — syntax error at line 42.)
        """
        if self.success:
            return False
        if self.diagnostic:
            return True
        if not self.stderr:
            return False
        actionable_signals = [
            "SyntaxError", "NameError", "ImportError", "TypeError",
            "AttributeError", "KeyError", "IndexError", "ValueError",
            "line ", "File ", "Error:", "error:",
        ]
        return any(s in self.stderr for s in actionable_signals)


# ── Risk awareness for gated tools (from ToolEmu paper) ──────────────────────

GATED_TOOLS = {
    "bash_exec", "git_push", "delete_file", "move_file", "run_tests"
}

RISK_ASSESSMENT_PROMPT = """Before executing this tool, state your risk assessment:
1. What does this tool call do exactly?
2. Is the action reversible?
3. What could go wrong?
4. Why is this action safe given the current context?
Then proceed with the tool call."""


def build_risk_aware_prompt(tool_name: str, base_prompt: str) -> str:
    """
    For gated tools, prepend the risk assessment requirement.
    Based on ToolEmu's finding that models skip risk assessment
    unless explicitly required to state it.
    """
    if tool_name not in GATED_TOOLS:
        return base_prompt

    return (
        f"RISK AWARENESS REQUIRED for {tool_name}:\n"
        f"{RISK_ASSESSMENT_PROMPT}\n\n"
        f"{base_prompt}"
    )
