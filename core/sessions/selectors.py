# core/sessions/selectors.py
"""
Selectors and presentation models for HERMES 2.x sessions, checkpoints, and recovery.

Answers:
- Where was I?
- What was completed?
- What failed?
- What changed?
- What is next?
- What checkpoint should I rewind to?
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.checkpoints.engine import CheckpointEngine
from core.persistence.models import CheckpointManifest
from core.recovery.gate import RecoveryVerdict
from core.runtime_state.models import HermesRuntimeState
from core.sessions.models import DurableSession


def get_session_viewmodel(session: DurableSession) -> Dict[str, Any]:
    """Presentation model for session status."""
    return {
        "session_id": session.session_id,
        "mission_id": session.mission_id,
        "branch_name": session.branch_name,
        "status": session.status.value,
        "current_checkpoint": session.current_checkpoint_id or "None",
        "current_sequence": session.current_sequence,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.created_at)),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.updated_at)),
    }


def get_checkpoint_timeline(
    checkpoint_engine: CheckpointEngine,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Chronological timeline of session checkpoints."""
    checkpoints = checkpoint_engine.list_checkpoints(session_id)
    timeline = []
    for chk in checkpoints:
        timeline.append({
            "checkpoint_id": chk.checkpoint_id,
            "sequence": chk.sequence,
            "reason": chk.reason.value,
            "created_at": time.strftime("%H:%M:%S", time.localtime(chk.created_at)),
            "files_count": chk.workspace.total_files,
            "git_head": chk.git.head_sha[:8] if chk.git.head_sha else "NO_GIT",
            "is_milestone": (chk.reason.value in ("POST_VERIFICATION", "MANUAL")),
        })
    return timeline


def get_where_was_i(
    session: DurableSession,
    runtime_state: HermesRuntimeState,
    checkpoint: Optional[CheckpointManifest] = None,
) -> Dict[str, Any]:
    """
    Structured projection answering the operator's recovery orientation questions.
    """
    # 1. Completed
    completed_tasks = [t.title for t in runtime_state.tasks.values() if t.status.value == "COMPLETED"]
    passed_requirements = [r.title for r in runtime_state.requirements.values() if r.status.value == "PASS"]

    # 2. Failed
    failed_tasks = [t.title for t in runtime_state.tasks.values() if t.status.value == "FAILED"]
    failed_repairs = [f"Repair {k}: {v.error_message}" for k, v in runtime_state.repairs.items() if v.status.value == "FAILED"]

    # 3. Changed
    files_changed_count = checkpoint.workspace.total_files if checkpoint else 0

    # 4. Next action
    next_action = "Execute next planned task."
    if runtime_state.current_task:
        next_action = f"Continue task '{runtime_state.current_task.title}'"
    elif failed_tasks:
        next_action = f"Review or repair failed task '{failed_tasks[-1]}'"

    # 5. Recommended rewind checkpoint
    recommended_rewind = checkpoint.checkpoint_id if checkpoint else None

    return {
        "completed": {
            "tasks": completed_tasks,
            "requirements": passed_requirements,
        },
        "failed": {
            "tasks": failed_tasks,
            "repairs": failed_repairs,
        },
        "files_changed_count": files_changed_count,
        "next_action": next_action,
        "recommended_rewind_checkpoint": recommended_rewind,
    }


def get_recovery_summary(
    session_id: str,
    verdict: RecoveryVerdict,
    checkpoint: Optional[CheckpointManifest],
) -> str:
    """Format human-readable recovery summary banner."""
    chk_str = checkpoint.checkpoint_id if checkpoint else "None"
    lines = [
        f"Session '{session_id}' Resumed [{verdict.decision.value}]",
        f"Checkpoint: {chk_str}",
    ]
    if verdict.warnings:
        lines.append("Warnings:")
        for w in verdict.warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("Environment and Workspace: Clean Match")
    return "\n".join(lines)
