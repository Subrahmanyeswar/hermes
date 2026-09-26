# core/agent_loop/observations.py
"""
Observation Builder for HERMES 2.x Agent Loop.
Transforms tool execution results, environmental feedback, validation failures,
and user inputs into structured, ground-truth Observation objects.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from loguru import logger

from core.agent_loop.types import Observation
from core.structured_observation import StructuredObservation


class ObservationBuilder:
    """
    Constructs normalized, causal Observation instances.
    Extracts actionable summaries and preserves raw trace references.
    """

    @classmethod
    def from_tool_result(
        cls,
        tool_name: str,
        tool_result: Any,
        duration: float,
        mission_id: str,
        task_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        action_id: Optional[str] = None,
        files_before: Optional[Set[str]] = None,
        files_after: Optional[Set[str]] = None,
    ) -> Observation:
        """Build an Observation from physical tool execution."""
        files_before = files_before or set()
        files_after = files_after or set()

        structured = StructuredObservation.from_tool_result(
            tool_name=tool_name,
            tool_result=tool_result,
            duration=duration,
            files_before=files_before,
            files_after=files_after,
        )

        output_text = (getattr(tool_result, "output", "") or "").strip()
        error_text = (getattr(tool_result, "error", "") or "").strip()
        exit_code = getattr(tool_result, "exit_code", 0 if getattr(tool_result, "success", True) else 1)
        success = getattr(tool_result, "success", exit_code == 0)

        # Build concise summary
        delta = structured.state_delta or {}
        created = delta.get("files_created", [])
        if success:
            if created:
                summary = f"Created {len(created)} file(s): {', '.join(Path(f).name for f in created[:3])}"
            elif output_text:
                summary = output_text[:120].replace("\n", " ")
            else:
                summary = f"{tool_name} executed successfully"
        else:
            summary = structured.error_summary or error_text[:120].replace("\n", " ") or f"{tool_name} failed with exit code {exit_code}"

        combined_content = f"STDOUT:\n{output_text}\nSTDERR:\n{error_text}".strip() if error_text else output_text

        return Observation(
            observation_id=f"obs_{uuid.uuid4().hex[:8]}",
            mission_id=mission_id,
            task_id=task_id,
            turn_id=turn_id,
            action_id=action_id,
            source_type="tool",
            source_id=tool_name,
            timestamp=time.time(),
            success=success,
            summary=summary,
            content=combined_content,
            exit_code=exit_code,
            error_message=error_text if not success else None,
            metadata={
                "duration_seconds": duration,
                "files_created": created,
            }
        )

    @classmethod
    def from_harness_rejection(
        cls,
        tool_name: str,
        reason: str,
        mission_id: str,
        task_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        action_id: Optional[str] = None,
        rejection_type: str = "POLICY_DENIED"
    ) -> Observation:
        """Build an Observation when harness policy blocks or rejects an action."""
        return Observation(
            observation_id=f"obs_{uuid.uuid4().hex[:8]}",
            mission_id=mission_id,
            task_id=task_id,
            turn_id=turn_id,
            action_id=action_id,
            source_type="harness",
            source_id="harness_policy",
            timestamp=time.time(),
            success=False,
            summary=f"Action '{tool_name}' rejected: {reason}",
            content=f"Harness rejected action '{tool_name}': {reason}",
            exit_code=1,
            error_type=rejection_type,
            error_message=reason,
            metadata={"tool_name": tool_name, "rejection_type": rejection_type}
        )

    @classmethod
    def from_verification(
        cls,
        verdict: str,
        confidence: Optional[float],
        issues: List[str],
        mission_id: str,
        task_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        method: str = "DETERMINISTIC"
    ) -> Observation:
        """Build an Observation representing verification outcome."""
        passed = verdict == "PASSED"
        issue_summary = "; ".join(issues[:3]) if issues else "All checks passed"
        summary = f"Verification [{verdict}]: {issue_summary}"
        return Observation(
            observation_id=f"obs_{uuid.uuid4().hex[:8]}",
            mission_id=mission_id,
            task_id=task_id,
            turn_id=turn_id,
            source_type="verification",
            source_id=method,
            timestamp=time.time(),
            success=passed,
            summary=summary,
            content="\n".join([f"Verdict: {verdict}"] + [f"- Issue: {iss}" for iss in issues]),
            exit_code=0 if passed else 1,
            error_type=None if passed else "VERIFICATION_FAILURE",
            error_message=issue_summary if not passed else None,
            metadata={"verdict": verdict, "confidence": confidence, "issues": issues}
        )

    @classmethod
    def from_user_response(
        cls,
        user_response: str,
        mission_id: str,
        task_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> Observation:
        """Build an Observation capturing user input/clarification."""
        return Observation(
            observation_id=f"obs_{uuid.uuid4().hex[:8]}",
            mission_id=mission_id,
            task_id=task_id,
            turn_id=turn_id,
            source_type="user",
            source_id="user_prompt",
            timestamp=time.time(),
            success=True,
            summary=f"User responded: {user_response[:100]}",
            content=user_response,
            exit_code=0
        )
