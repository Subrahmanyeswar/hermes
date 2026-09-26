# core/planning/plan_mode.py
"""
Plan Mode Controller and Safety Gate for HERMES 2.x (Prompt 9).
Manages:
1. Explicit Plan Mode vs Execution Mode.
2. Safety Invariant: Plan Mode strictly disallows mutation (fs.write, fs.edit, destructive bash).
3. Plan lifecycle: DRAFT -> REVIEW_REQUIRED -> APPROVED -> STALE -> SUPERSEDED.
4. Plan persistence to .artifacts/missions/<mission_id>/plan.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from core.runtime_state.models import (
    ExecutionMode,
    PlanState,
    PlanStatus,
    PlanStep,
    RequirementState,
)


class PlanModeViolationError(PermissionError):
    """Raised when an action attempts to mutate project state while Plan Mode is active."""
    pass


class PlanController:
    """
    Coordinates plan generation, approval, revisions, and enforces plan-mode safety boundaries.
    """

    SAFE_READONLY_TOOLS = {
        "fs.read",
        "search.glob",
        "search.grep",
        "task.todo",
        "user.ask",
        "tool_search",
        "search_tools",
    }

    MUTATION_TOOLS = {
        "fs.write",
        "fs.edit",
    }

    def __init__(
        self,
        mission_id: str,
        workspace_root: Optional[Path | str] = None,
        artifacts_root: Optional[Path | str] = None,
        execution_mode: ExecutionMode = ExecutionMode.EXECUTION_MODE,
    ) -> None:
        self.mission_id = mission_id
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.artifacts_root = Path(artifacts_root).resolve() if artifacts_root else (self.workspace_root / ".artifacts")
        self.execution_mode = execution_mode
        self.current_plan: Optional[PlanState] = None

    def enter_plan_mode(self) -> None:
        """Switch agent into safe, non-mutating Plan Mode."""
        self.execution_mode = ExecutionMode.PLAN_MODE
        logger.info(f"PlanController: Mission '{self.mission_id}' entered PLAN_MODE.")

    def exit_plan_mode(self) -> None:
        """Transition from Plan Mode to standard Execution Mode."""
        self.execution_mode = ExecutionMode.EXECUTION_MODE
        logger.info(f"PlanController: Mission '{self.mission_id}' exited PLAN_MODE (EXECUTION_MODE).")

    def authorize_tool_call(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """
        Enforce safety boundary: in Plan Mode, mutating tools are strictly rejected.
        Returns: (allowed: bool, reason: str)
        """
        if self.execution_mode != ExecutionMode.PLAN_MODE:
            return True, "Execution mode permits standard tool authorization."

        norm_name = tool_name.lower().strip()
        if norm_name in self.MUTATION_TOOLS:
            return False, f"PLAN_MODE_MUTATION_DENIED: Tool '{tool_name}' mutates state and is prohibited in Plan Mode."

        # Shell bash check for write/destructive commands
        if norm_name in ("shell.bash", "bash"):
            cmd = (arguments or {}).get("command", "").lower().strip()
            # Prohibit write/delete/install commands in plan mode
            blocked_prefixes = ("rm ", "del ", "erase ", "pip install", "npm install", "git commit", "git push", ">", ">>")
            if any(p in cmd for p in blocked_prefixes):
                return False, f"PLAN_MODE_SHELL_DENIED: Destructive or state-mutating shell command prohibited in Plan Mode: '{cmd[:40]}'"

        return True, "Allowed in Plan Mode"

    def create_plan_proposal(
        self,
        goal_id: str,
        requirements: Dict[str, RequirementState],
        risks: Optional[List[str]] = None,
        unknowns: Optional[List[str]] = None,
        open_questions: Optional[List[str]] = None,
    ) -> PlanState:
        """Synthesize an ordered plan proposal from the requirement graph."""
        steps: List[PlanStep] = []
        # Sort requirements by dependencies and priority
        sorted_reqs = sorted(
            requirements.values(),
            key=lambda r: (len(r.dependencies), r.priority.value),
        )

        for idx, req in enumerate(sorted_reqs):
            step = PlanStep(
                step_id=f"step_{idx+1}",
                title=f"Implement {req.title}",
                description=req.description,
                requirement_ids=[req.requirement_id],
                dependencies=list(req.dependencies),
                verification_strategy="Run automated test suite and acceptance verification",
                status="PROPOSED",
            )
            steps.append(step)

        version = (self.current_plan.version + 1) if self.current_plan else 1
        plan = PlanState(
            plan_id=f"plan_{self.mission_id}_v{version}",
            goal_id=goal_id,
            version=version,
            steps=steps,
            status=PlanStatus.DRAFT,
            risks=risks or [],
            unknowns=unknowns or [],
            open_questions=open_questions or [],
            created_at=time.time(),
            updated_at=time.time(),
        )

        self.current_plan = plan
        self.persist_plan(plan)
        return plan

    def approve_plan(self, actor: str = "user") -> PlanState:
        """Mark proposed plan as APPROVED, authorizing execution transition."""
        if not self.current_plan:
            raise ValueError("No active plan exists to approve.")
        self.current_plan.status = PlanStatus.APPROVED
        self.current_plan.approved_by = actor
        self.current_plan.approved_at = time.time()
        self.current_plan.updated_at = time.time()
        self.persist_plan(self.current_plan)
        logger.info(f"PlanController: Plan '{self.current_plan.plan_id}' APPROVED by {actor}.")
        return self.current_plan

    def reject_plan(self, reason: str = "") -> PlanState:
        """Mark proposed plan as REJECTED."""
        if not self.current_plan:
            raise ValueError("No active plan exists to reject.")
        self.current_plan.status = PlanStatus.REJECTED
        self.current_plan.reason_changed = reason
        self.current_plan.updated_at = time.time()
        self.persist_plan(self.current_plan)
        return self.current_plan

    def check_staleness(self, requirements: Dict[str, RequirementState]) -> bool:
        """
        Check if the active plan has become stale due to requirement additions or modifications.
        """
        if not self.current_plan:
            return False

        planned_req_ids = set()
        for step in self.current_plan.steps:
            planned_req_ids.update(step.requirement_ids)

        actual_req_ids = set(requirements.keys())
        if planned_req_ids != actual_req_ids:
            self.current_plan.status = PlanStatus.STALE
            self.current_plan.reason_changed = "Requirements added, removed, or scope altered."
            self.current_plan.updated_at = time.time()
            self.persist_plan(self.current_plan)
            return True

        return False

    def persist_plan(self, plan: PlanState) -> Optional[Path]:
        """Save plan to .artifacts/missions/<mission_id>/plan.json."""
        try:
            target_dir = self.artifacts_root / "missions" / self.mission_id
            target_dir.mkdir(parents=True, exist_ok=True)
            plan_file = target_dir / "plan.json"
            plan_file.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
            return plan_file
        except Exception as exc:
            logger.warning(f"PlanController: failed to persist plan to disk: {exc}")
            return None
