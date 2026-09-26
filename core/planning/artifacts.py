# core/planning/artifacts.py
"""
Progress Artifact Generator and Human-Readable Projection Engine for HERMES 2.x (Prompt 9).
Produces:
1. .artifacts/missions/<mission_id>/progress.json (Handoff summary for future fresh sessions)
2. .artifacts/missions/<mission_id>/requirements.json (Complete requirement ledger)
3. Concise Human/TUI Projections (Replaces 'Task 1/7' with 'Goal / Requirements / Focus').
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from core.runtime_state.models import (
    AcceptanceCheckStatus,
    GoalState,
    ProgressState,
    RequirementState,
    RequirementStatus,
)


class ProgressArtifactWriter:
    """
    Writes persistent session handoff projections to HERMES-controlled .artifacts/ directory.
    Guarantees user workspace files (like MEMORY.md) are NEVER overwritten.
    """

    def __init__(self, workspace_root: Optional[Path | str] = None, artifacts_root: Optional[Path | str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.artifacts_root = Path(artifacts_root).resolve() if artifacts_root else (self.workspace_root / ".artifacts")

    def write_progress_artifact(
        self,
        mission_id: str,
        goal: GoalState,
        progress: ProgressState,
        requirements: Dict[str, RequirementState],
    ) -> Optional[Path]:
        """
        Generate .artifacts/missions/<mission_id>/progress.json for session handoff.
        """
        try:
            target_dir = self.artifacts_root / "missions" / mission_id
            target_dir.mkdir(parents=True, exist_ok=True)
            progress_file = target_dir / "progress.json"

            status_counts = {
                "verified": sum(1 for r in requirements.values() if r.status == RequirementStatus.VERIFIED),
                "in_progress": sum(1 for r in requirements.values() if r.status == RequirementStatus.IN_PROGRESS),
                "pending": sum(1 for r in requirements.values() if r.status == RequirementStatus.PENDING),
                "blocked": sum(1 for r in requirements.values() if r.status == RequirementStatus.BLOCKED),
                "failed": sum(1 for r in requirements.values() if r.status == RequirementStatus.FAILED),
                "waived": sum(1 for r in requirements.values() if r.status == RequirementStatus.WAIVED),
            }

            data = {
                "goal": {
                    "id": goal.goal_id,
                    "title": goal.title or goal.description[:60],
                    "status": goal.status.value,
                    "user_request": goal.user_request,
                    "explicit_constraints": goal.explicit_constraints,
                },
                "requirements_summary": status_counts,
                "current_focus": progress.current_focus,
                "last_meaningful_change": progress.last_meaningful_change,
                "known_failures": progress.known_failures,
                "next_action": progress.next_action,
                "blocked_reason": progress.blocked_reason,
                "recent_evidence": progress.recent_evidence,
                "progress_fingerprint": progress.progress_fingerprint,
                "fraction_complete": progress.overall_fraction,
            }

            progress_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return progress_file
        except Exception as exc:
            logger.warning(f"ProgressArtifactWriter: failed writing progress artifact: {exc}")
            return None

    def write_requirements_ledger(
        self,
        mission_id: str,
        requirements: Dict[str, RequirementState],
        acceptance_checks: Optional[List[Any]] = None,
    ) -> Optional[Path]:
        """
        Generate .artifacts/missions/<mission_id>/requirements.json.
        """
        try:
            target_dir = self.artifacts_root / "missions" / mission_id
            target_dir.mkdir(parents=True, exist_ok=True)
            req_file = target_dir / "requirements.json"

            data = {
                "requirements": [r.to_dict() for r in requirements.values()],
                "checks": [c.to_dict() for c in (acceptance_checks or [])],
            }

            req_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return req_file
        except Exception as exc:
            logger.warning(f"ProgressArtifactWriter: failed writing requirements ledger: {exc}")
            return None


class HumanProjectionRenderer:
    """
    Renders truthful, human-readable projections of Goal and Requirement states.
    Replaces the legacy 'Task 1/7' presentation with an actionable feature ledger.
    """

    STATUS_ICONS = {
        RequirementStatus.VERIFIED: "✓",
        RequirementStatus.WAIVED: "⊘",
        RequirementStatus.IN_PROGRESS: "►",
        RequirementStatus.FAILED: "✗",
        RequirementStatus.BLOCKED: "!",
        RequirementStatus.PENDING: "○",
        RequirementStatus.READY: "○",
        RequirementStatus.CANCELLED: "-",
    }

    @classmethod
    def render_progress_view(
        cls,
        goal: GoalState,
        requirements: Dict[str, RequirementState],
        progress: ProgressState,
        max_requirements_display: int = 12,
    ) -> str:
        """
        Generate model-friendly or TUI-friendly progress representation.
        """
        lines = []

        # 1. Goal Header
        goal_title = goal.title or goal.description[:60] or "Mission Goal"
        lines.append(f"GOAL: {goal_title}")
        if goal.explicit_constraints:
            lines.append(f"CONSTRAINTS: {', '.join(goal.explicit_constraints[:3])}")

        # 2. Requirements Ledger
        lines.append("\nREQUIREMENTS:")
        req_list = list(requirements.values())

        for idx, req in enumerate(req_list[:max_requirements_display]):
            icon = cls.STATUS_ICONS.get(req.status, "○")
            is_focus = (req.requirement_id == progress.current_focus)
            focus_marker = " [CURRENT]" if is_focus else ""
            lines.append(f"  {icon} {req.requirement_id}: {req.title}{focus_marker}")

        if len(req_list) > max_requirements_display:
            lines.append(f"  ... (+{len(req_list) - max_requirements_display} more requirements)")

        # 3. Progress Summary
        lines.append(f"\nPROGRESS: {progress.verified_requirements_count}/{progress.total_requirements_count} verified")

        if progress.current_focus:
            lines.append(f"CURRENT FOCUS: {progress.current_focus}")

        if progress.last_meaningful_change:
            lines.append(f"LAST CHANGE: {progress.last_meaningful_change}")

        if progress.known_failures:
            lines.append(f"KNOWN FAILURE: {progress.known_failures[0]}")

        if progress.blocked_reason:
            lines.append(f"BLOCKED: {progress.blocked_reason}")

        if progress.next_action:
            lines.append(f"NEXT ACTION: {progress.next_action}")

        return "\n".join(lines)
