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

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from loguru import logger


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

        # Build error summary for failed executions
        error_summary = None
        exit_code = getattr(tool_result, "exit_code", 0 if getattr(tool_result, "success", True) else 1)
        success = getattr(tool_result, "success", exit_code == 0)

        if not success and stderr:
            lines = [l for l in stderr.split("\n") if l.strip()]
            if lines:
                error_summary = lines[-1][:200]

        return cls(
            tool_name=tool_name,
            exit_code=exit_code,
            success=success,
            stdout=stdout[:1000],
            stderr=stderr[:500],
            duration_seconds=duration,
            state_delta=state_delta,
            error_summary=error_summary,
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

        return "\n".join(lines)

    def is_actionable_failure(self) -> bool:
        """
        True if the failure contains information the model can act on.
        (Some failures are transient — network timeout — vs actionable
        — syntax error at line 42.)
        """
        if self.success:
            return False
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