# core/planning/service.py
"""
Mission Planning Service for HERMES 2.x (Prompt 9).
The Single Authoritative Coordinator for:
- GoalState & User Intent
- Requirement Graph & Decomposition
- AcceptanceLedger & Evidence Verification
- TodoState & Work Items
- ProgressController & Focus Selection
- PlanController & Plan Mode
- ContextEngine 2.x Selective Context Projections
- Canonical EventBus Event Emissions
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from core.planning.acceptance import AcceptanceManager
from core.planning.artifacts import HumanProjectionRenderer, ProgressArtifactWriter
from core.planning.decomposer import GoalDecomposer
from core.planning.plan_mode import PlanController
from core.planning.progress import ProgressController
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    ExecutionMode,
    GoalState,
    GoalStatus,
    HermesRuntimeState,
    PlanState,
    ProgressState,
    RequirementCategory,
    RequirementPriority,
    RequirementState,
    RequirementStatus,
    TodoState,
    TodoStatus,
)


class MissionPlanningService:
    """
    Central coordinator managing goal decomposition, requirement ledger,
    truthful progress calculation, plan mode gating, and context projections.
    """

    def __init__(
        self,
        mission_id: str,
        workspace_root: Optional[Path | str] = None,
        event_bus: Any = None,
        state_store: Any = None,
    ) -> None:
        self.mission_id = mission_id
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.event_bus = event_bus
        self.state_store = state_store

        # 1. State entities
        self.goal = GoalState(goal_id=f"goal_{mission_id}", mission_id=mission_id)
        self.requirements: Dict[str, RequirementState] = {}
        self.acceptance_ledger = AcceptanceLedger(goal_id=self.goal.goal_id)
        self.todos: Dict[str, TodoState] = {}
        self.progress = ProgressState()

        # 2. Subsystem managers
        self.acceptance_manager = AcceptanceManager(ledger=self.acceptance_ledger)
        self.progress_controller = ProgressController(
            goal=self.goal,
            requirements=self.requirements,
            acceptance_manager=self.acceptance_manager,
            todos=self.todos,
            progress=self.progress,
        )
        self.plan_controller = PlanController(
            mission_id=mission_id,
            workspace_root=self.workspace_root,
        )
        self.artifact_writer = ProgressArtifactWriter(workspace_root=self.workspace_root)

    # ── Initialization & Goal Setup ───────────────────────────────────────────

    def initialize_goal(
        self,
        user_prompt: str,
        title: str = "",
        explicit_constraints: Optional[List[str]] = None,
        explicit_preferences: Optional[List[str]] = None,
    ) -> GoalState:
        """
        Set up the canonical user goal and decompose into requirements and acceptance checks.
        """
        self.goal.user_request = user_prompt
        self.goal.title = title or (user_prompt.split(".")[0][:60] if user_prompt else "Mission Goal")
        self.goal.description = user_prompt
        self.goal.explicit_constraints = explicit_constraints or []
        self.goal.explicit_preferences = explicit_preferences or []
        self.goal.status = GoalStatus.ACTIVE

        # Publish GOAL_CREATED
        self._publish_event(
            EventType.GOAL_CREATED,
            payload={
                "goal_id": self.goal.goal_id,
                "title": self.goal.title,
                "description": self.goal.description,
                "user_request": self.goal.user_request,
                "explicit_constraints": self.goal.explicit_constraints,
            },
        )

        # Decompose into requirements and checks
        reqs, checks = GoalDecomposer.decompose(
            goal_id=self.goal.goal_id,
            user_prompt=user_prompt,
            explicit_constraints=self.goal.explicit_constraints,
        )

        for r_id, req in reqs.items():
            self.requirements[r_id] = req
            self._publish_event(
                EventType.REQUIREMENT_CREATED,
                payload={
                    "requirement_id": r_id,
                    "title": req.title,
                    "description": req.description,
                    "category": req.category.value,
                    "priority": req.priority.value,
                    "dependencies": req.dependencies,
                },
            )

        self.acceptance_manager.register_checks(checks)
        for chk in checks:
            self._publish_event(
                EventType.ACCEPTANCE_CHECK_CREATED,
                payload={
                    "check_id": chk.check_id,
                    "requirement_id": chk.requirement_id,
                    "description": chk.description,
                    "critical": chk.critical,
                    "verification_method": chk.verification_method,
                },
            )

        # Initial progress evaluation
        self.update_progress(event_summary="Goal initialized and decomposed into requirements.")
        return self.goal

    # ── Progress & Focus ──────────────────────────────────────────────────────

    def update_progress(
        self,
        event_summary: str = "",
        modified_files: Optional[Set[str]] = None,
    ) -> ProgressState:
        """
        Evaluate requirement graph and acceptance ledger to update progress state.
        Emits PROGRESS_UPDATED event when meaningful change occurs.
        """
        has_changed, prog = self.progress_controller.update_progress(
            event_summary=event_summary,
            modified_files=modified_files,
        )

        if has_changed:
            self._publish_event(
                EventType.PROGRESS_UPDATED,
                payload={
                    "last_meaningful_change": prog.last_meaningful_change,
                    "current_focus": prog.current_focus,
                    "next_action": prog.next_action,
                    "known_failures": prog.known_failures,
                    "blocked_reason": prog.blocked_reason,
                    "progress_fingerprint": prog.progress_fingerprint,
                    "verified_requirements": prog.verified_requirements_count,
                    "total_requirements": prog.total_requirements_count,
                },
            )
            # Write handoff artifact
            self.artifact_writer.write_progress_artifact(
                mission_id=self.mission_id,
                goal=self.goal,
                progress=self.progress,
                requirements=self.requirements,
            )

        return prog

    def set_current_focus(self, requirement_id: str) -> None:
        """Explicitly switch active requirement focus."""
        if requirement_id in self.requirements:
            self.progress.current_focus = requirement_id
            self.requirements[requirement_id].active = True
            self._publish_event(
                EventType.FOCUS_CHANGED,
                payload={"requirement_id": requirement_id},
            )

    # ── Acceptance Ledger Interactions ────────────────────────────────────────

    def record_acceptance_result(
        self,
        check_id: str,
        status: AcceptanceCheckStatus,
        evidence_ref: Optional[str] = None,
        error: Optional[str] = None,
        source_versions: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Record result of an acceptance check.
        Emits corresponding canonical acceptance event and recalculates progress.
        """
        ok = self.acceptance_manager.record_check_result(
            check_id=check_id,
            status=status,
            evidence_ref=evidence_ref,
            error=error,
            source_versions=source_versions,
        )
        if not ok:
            return False

        event_type_map = {
            AcceptanceCheckStatus.PASS: EventType.ACCEPTANCE_CHECK_PASSED,
            AcceptanceCheckStatus.FAIL: EventType.ACCEPTANCE_CHECK_FAILED,
            AcceptanceCheckStatus.BLOCKED: EventType.ACCEPTANCE_CHECK_BLOCKED,
            AcceptanceCheckStatus.SKIPPED: EventType.ACCEPTANCE_CHECK_SKIPPED,
        }
        ev_type = event_type_map.get(status, EventType.ACCEPTANCE_LEDGER_UPDATED)

        self._publish_event(
            ev_type,
            payload={
                "check_id": check_id,
                "evidence_ref": evidence_ref,
                "error": error,
                "source_versions": source_versions,
            },
        )

        chk = self.acceptance_ledger.checks.get(check_id)
        desc = chk.description if chk else check_id
        summary = f"Acceptance check '{desc}' passed with evidence [{evidence_ref}]" if status == AcceptanceCheckStatus.PASS else f"Acceptance check '{desc}' failed"

        self.update_progress(event_summary=summary)
        return True

    def waive_requirement(self, requirement_id: str, reason: str, actor: str = "user") -> bool:
        """Explicitly waive a requirement with audit trail."""
        req = self.requirements.get(requirement_id)
        if not req:
            return False
        self.acceptance_manager.waive_requirement(req, reason=reason, actor=actor)
        self._publish_event(
            EventType.REQUIREMENT_WAIVED,
            payload={
                "requirement_id": requirement_id,
                "reason": reason,
                "actor": actor,
            },
        )
        self.update_progress(event_summary=f"Requirement '{requirement_id}' waived by {actor}: {reason}")
        return True

    # ── Todo Work Items ───────────────────────────────────────────────────────

    def create_todo(
        self,
        todo_id: str,
        title: str,
        requirement_ids: Optional[List[str]] = None,
        description: str = "",
        priority: RequirementPriority = RequirementPriority.MEDIUM,
        dependencies: Optional[List[str]] = None,
    ) -> TodoState:
        """Create a tractable engineering work item supporting requirements."""
        # Deduplication
        if todo_id in self.todos:
            todo = self.todos[todo_id]
            todo.title = title
            todo.description = description
            return todo

        todo = TodoState(
            todo_id=todo_id,
            goal_id=self.goal.goal_id,
            requirement_ids=requirement_ids or [],
            title=title,
            description=description,
            status=TodoStatus.PENDING,
            priority=priority,
            dependencies=dependencies or [],
        )
        self.todos[todo_id] = todo

        self._publish_event(
            EventType.TODO_CREATED,
            payload={
                "todo_id": todo_id,
                "title": title,
                "requirement_ids": todo.requirement_ids,
                "priority": priority.value,
            },
        )
        return todo

    def complete_todo(self, todo_id: str) -> bool:
        """
        Mark a Todo as DONE.
        Note: Does NOT automatically mark requirements as VERIFIED without acceptance evidence!
        """
        if todo_id not in self.todos:
            return False
        self.todos[todo_id].status = TodoStatus.DONE
        self._publish_event(
            EventType.TODO_COMPLETED,
            payload={"todo_id": todo_id},
        )
        self.update_progress(event_summary=f"Completed work item '{self.todos[todo_id].title}'")
        return True

    # ── Plan Mode ─────────────────────────────────────────────────────────────

    def enter_plan_mode(self) -> None:
        """Switch agent into Plan Mode."""
        self.plan_controller.enter_plan_mode()
        self._publish_event(EventType.PLAN_MODE_ENTERED)

    def exit_plan_mode(self) -> None:
        """Exit Plan Mode into Execution Mode."""
        self.plan_controller.exit_plan_mode()
        self._publish_event(EventType.PLAN_MODE_EXITED)

    def create_plan_proposal(
        self,
        risks: Optional[List[str]] = None,
        unknowns: Optional[List[str]] = None,
        open_questions: Optional[List[str]] = None,
    ) -> PlanState:
        """Generate ordered execution plan from current requirements."""
        plan = self.plan_controller.create_plan_proposal(
            goal_id=self.goal.goal_id,
            requirements=self.requirements,
            risks=risks,
            unknowns=unknowns,
            open_questions=open_questions,
        )
        self._publish_event(
            EventType.PLAN_CREATED,
            payload={
                "plan_id": plan.plan_id,
                "version": plan.version,
                "steps": [s.to_dict() for s in plan.steps],
                "risks": plan.risks,
                "unknowns": plan.unknowns,
                "open_questions": plan.open_questions,
            },
        )
        return plan

    def approve_plan(self, actor: str = "user") -> PlanState:
        """Approve proposed plan."""
        plan = self.plan_controller.approve_plan(actor=actor)
        self._publish_event(
            EventType.PLAN_APPROVED,
            payload={"plan_id": plan.plan_id, "actor": actor},
        )
        return plan

    # ── Context Engine 2.x Integration ────────────────────────────────────────

    def sync_to_context_engine(self, context_engine: Any) -> None:
        """
        Inject selective, budgeted Goal and Requirement projections into ContextEngine.
        Guarantees that 200 requirements never flood the context window.
        """
        from core.context.models import (
            ContextItem,
            ContextPriority,
            ContextProvenance,
            ContextSectionType,
            ContextSourceType,
        )

        # 1. CURRENT_GOAL Item
        goal_content = (
            f"<mission_goal id=\"{self.goal.goal_id}\" status=\"{self.goal.status.value}\">\n"
            f"Title: {self.goal.title}\n"
            f"User Objective: {self.goal.user_request}\n"
        )
        if self.goal.explicit_constraints:
            goal_content += f"Constraints: {', '.join(self.goal.explicit_constraints)}\n"
        goal_content += (
            f"Status: {self.progress.verified_requirements_count}/{self.progress.total_requirements_count} verified\n"
            f"</mission_goal>"
        )

        item_goal = ContextItem(
            id="goal_state_authoritative",
            section=ContextSectionType.CURRENT_GOAL,
            content=goal_content,
            provenance=ContextProvenance(
                source_type=ContextSourceType.RUNTIME_STATE,
                source_id=self.goal.goal_id,
            ),
            priority=ContextPriority.MANDATORY,
            relevance_score=1.0,
            pinned=True,
        )
        context_engine.register_item(item_goal)

        # 2. ACTIVE_REQUIREMENTS Item (Selective projection)
        # Compact ledger representation
        rendered_view = HumanProjectionRenderer.render_progress_view(
            goal=self.goal,
            requirements=self.requirements,
            progress=self.progress,
            max_requirements_display=10,
        )

        # Add detailed acceptance checks ONLY for the current focus
        cur_focus = self.progress.current_focus
        if cur_focus and cur_focus in self.requirements:
            focus_req = self.requirements[cur_focus]
            focus_checks = self.acceptance_ledger.get_checks_for_requirement(cur_focus)
            rendered_view += f"\n\nCURRENT FOCUS ACCEPTANCE CONTRACT ({cur_focus}):\n"
            for c in focus_checks:
                chk_icon = "✓" if c.status == AcceptanceCheckStatus.PASS else ("✗" if c.status == AcceptanceCheckStatus.FAIL else "○")
                crit_tag = "[CRITICAL] " if c.critical else ""
                ev_tag = f" (ev: {', '.join(c.evidence_refs)})" if c.evidence_refs else ""
                rendered_view += f"  {chk_icon} {crit_tag}{c.description}{ev_tag}\n"

        item_reqs = ContextItem(
            id="active_requirements_ledger",
            section=ContextSectionType.ACTIVE_REQUIREMENTS,
            content=f"<requirements_ledger>\n{rendered_view}\n</requirements_ledger>",
            provenance=ContextProvenance(
                source_type=ContextSourceType.RUNTIME_STATE,
                source_id="acceptance_ledger",
            ),
            priority=ContextPriority.MANDATORY,
            relevance_score=0.95,
        )
        context_engine.register_item(item_reqs)

    # ── High-Level Query APIs ─────────────────────────────────────────────────

    def get_progress_summary(self) -> Dict[str, Any]:
        """Produce a compact diagnostic dictionary."""
        return {
            "goal": self.goal.to_dict(),
            "current_focus": self.progress.current_focus,
            "last_meaningful_change": self.progress.last_meaningful_change,
            "next_action": self.progress.next_action,
            "known_failures": self.progress.known_failures,
            "blocked_reason": self.progress.blocked_reason,
            "verified_requirements": self.progress.verified_requirements_count,
            "total_requirements": self.progress.total_requirements_count,
            "overall_fraction": self.progress.overall_fraction,
            "overall_status": self.progress.overall_status,
            "plan_mode": self.plan_controller.execution_mode.value,
        }

    def is_goal_completed(self) -> Tuple[bool, str]:
        """Check if mission goal is fully completed."""
        return self.progress_controller.is_goal_completed()

    def list_requirements(
        self,
        offset: int = 0,
        limit: int = 50,
        status_filter: Optional[RequirementStatus] = None,
    ) -> List[RequirementState]:
        """Bounded query API with pagination and status filtering."""
        filtered = [
            r for r in self.requirements.values()
            if status_filter is None or r.status == status_filter
        ]
        return filtered[offset: offset + limit]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _publish_event(
        self,
        event_type: EventType,
        severity: EventSeverity = EventSeverity.INFO,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Helper to emit canonical runtime state events to event_bus."""
        if not self.event_bus:
            return

        event = HermesEvent(
            event_type=event_type,
            mission_id=self.mission_id,
            source="mission_planning",
            severity=severity,
            payload=payload or {},
        )

        if hasattr(self.event_bus, "publish"):
            self.event_bus.publish(event)
        elif hasattr(self.event_bus, "publish_nowait"):
            self.event_bus.publish_nowait(event)


