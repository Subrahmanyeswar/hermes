# core/planning/progress.py
"""
Progress Controller, Focus Selector, and Truthful Progress Engine for HERMES 2.x (Prompt 9).
Derives truthful progress from requirements, acceptance ledger, observations, and evidence.
Enforces:
1. Progress is a descriptive projection, never an authority that overrides evidence.
2. Noise filtering: repetitive identical tool calls do not trigger progress events.
3. Deterministic Focus Selection with oscillation protection.
4. Semantic stall detection based on progress fingerprints.
5. Goal completion requires all requirements VERIFIED or WAIVED with zero blocking defects.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from core.planning.acceptance import AcceptanceManager
from core.runtime_state.models import (
    AcceptanceCheckStatus,
    GoalState,
    GoalStatus,
    ProgressState,
    RequirementPriority,
    RequirementState,
    RequirementStatus,
    TodoState,
    TodoStatus,
)


class ProgressController:
    """
    Coordinates truthful progress evaluation, focus recommendation, noise filtering,
    stall detection, and goal completion determination.
    """

    STALL_TURN_THRESHOLD = 5

    def __init__(
        self,
        goal: GoalState,
        requirements: Dict[str, RequirementState],
        acceptance_manager: AcceptanceManager,
        todos: Optional[Dict[str, TodoState]] = None,
        progress: Optional[ProgressState] = None,
    ) -> None:
        self.goal = goal
        self.requirements = requirements
        self.acceptance_manager = acceptance_manager
        self.todos = todos or {}
        self.progress = progress or ProgressState()

        # Oscillation protection & stall tracking
        self._focus_history: List[str] = []
        self._last_meaningful_events: List[Dict[str, Any]] = []
        self._consecutive_identical_fingerprints: int = 0
        self._last_fingerprint: str = ""

    def update_progress(
        self,
        event_summary: str = "",
        modified_files: Optional[Set[str]] = None,
    ) -> Tuple[bool, ProgressState]:
        """
        Evaluate full requirement graph and acceptance ledger to derive current progress.
        Returns: (has_meaningful_change: bool, updated_progress: ProgressState)
        """
        # 1. Stale evidence check if files changed
        if modified_files:
            self.acceptance_manager.check_file_modifications(modified_files, self.requirements)

        # 2. Update all requirements according to acceptance checks
        for req in self.requirements.values():
            new_status, reason = self.acceptance_manager.evaluate_requirement(req)
            if new_status != req.status:
                req.transition_status(new_status, reason=reason, actor="acceptance_evaluator")

        # 3. Compute metrics
        total_reqs = len(self.requirements)
        verified_reqs = sum(
            1 for r in self.requirements.values() if r.status in (RequirementStatus.VERIFIED, RequirementStatus.WAIVED)
        )
        ledger_rep = self.acceptance_manager.ledger.report()

        self.progress.total_requirements_count = total_reqs
        self.progress.verified_requirements_count = verified_reqs
        self.progress.total_checks_count = ledger_rep["total_checks"]
        self.progress.passing_checks_count = ledger_rep["passed"]
        self.progress.overall_fraction = (verified_reqs / total_reqs) if total_reqs > 0 else 0.0

        # 4. Identify known failures
        known_fails = []
        for chk in self.acceptance_manager.ledger.checks.values():
            if chk.status == AcceptanceCheckStatus.FAIL:
                known_fails.append(f"{chk.description} (Error: {chk.error_message or 'Check failed'})")
            elif chk.status == AcceptanceCheckStatus.BLOCKED:
                known_fails.append(f"{chk.description} (Blocked: {chk.error_message or 'Prerequisites missing'})")
        self.progress.known_failures = known_fails

        # 5. Select next recommended focus
        current_focus = self.select_current_focus()
        self.progress.current_focus = current_focus

        # 6. Derive next descriptive action
        self.progress.next_action = self._derive_next_action(current_focus)

        # 7. Check blockers
        if current_focus and current_focus in self.requirements:
            req = self.requirements[current_focus]
            if req.status == RequirementStatus.BLOCKED:
                self.progress.blocked_reason = req.last_failure or f"Requirement '{req.title}' is blocked."
            else:
                self.progress.blocked_reason = None
        else:
            self.progress.blocked_reason = None

        # 8. Compute fingerprint
        fingerprint = self.compute_fingerprint()
        has_meaningful_change = fingerprint != self._last_fingerprint

        if has_meaningful_change:
            self._last_fingerprint = fingerprint
            self._consecutive_identical_fingerprints = 0
            if event_summary:
                self.progress.last_meaningful_change = event_summary
        else:
            self._consecutive_identical_fingerprints += 1

        self.progress.progress_fingerprint = fingerprint

        # 9. Update Goal status
        self._evaluate_goal_completion()

        return has_meaningful_change, self.progress

    def select_current_focus(self) -> Optional[str]:
        """
        Deterministic selector for next requirement to focus on.
        Picks:
        1. Currently active requirement if still IN_PROGRESS and not BLOCKED.
        2. Highest priority READY requirement whose dependencies are satisfied.
        3. Oscillating candidate filtered if repeated without progress.
        """
        # If current focus is valid and in progress, stick to it for stability
        cur = self.progress.current_focus
        if cur and cur in self.requirements:
            req = self.requirements[cur]
            if req.status == RequirementStatus.IN_PROGRESS:
                return cur

        candidates: List[Tuple[RequirementState, int]] = []

        for req in self.requirements.values():
            # Skip verified, waived, or cancelled
            if req.status in (RequirementStatus.VERIFIED, RequirementStatus.WAIVED, RequirementStatus.CANCELLED):
                continue

            # Check dependencies
            deps_satisfied = True
            for dep_id in req.dependencies:
                dep_req = self.requirements.get(dep_id)
                if not dep_req or dep_req.status not in (RequirementStatus.VERIFIED, RequirementStatus.WAIVED):
                    deps_satisfied = False
                    break

            if not deps_satisfied:
                continue

            # Score by priority and failure state
            prio_weights = {
                RequirementPriority.CRITICAL: 1000,
                RequirementPriority.HIGH: 500,
                RequirementPriority.MEDIUM: 200,
                RequirementPriority.LOW: 50,
            }
            score = prio_weights.get(req.priority, 100)

            # Ready requirement gets bonus
            if req.status in (RequirementStatus.READY, RequirementStatus.PENDING):
                score += 100
            elif req.status == RequirementStatus.FAILED:
                # Needs repair
                score += 50

            # Oscillation penalty: if visited frequently recently
            penalty = self._compute_oscillation_penalty(req.requirement_id)
            score -= penalty

            candidates.append((req, score))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        chosen = candidates[0][0].requirement_id

        # Update history
        self._focus_history.append(chosen)
        if len(self._focus_history) > 20:
            self._focus_history.pop(0)

        return chosen

    def _compute_oscillation_penalty(self, req_id: str) -> int:
        """Compute penalty based on how many times req_id appeared in recent focus history."""
        recent_count = self._focus_history[-6:].count(req_id)
        return recent_count * 150

    def compute_fingerprint(self) -> str:
        """Compute compact SHA-256 fingerprint of current requirement states and failures."""
        parts = []
        for r_id in sorted(self.requirements.keys()):
            r = self.requirements[r_id]
            parts.append(f"{r_id}:{r.status.value}")

        parts.append(f"focus:{self.progress.current_focus or 'none'}")
        parts.append(f"fails:{len(self.progress.known_failures)}")
        parts.append(f"checks:{self.progress.passing_checks_count}/{self.progress.total_checks_count}")

        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def compute_progress_fingerprint(self) -> str:
        """Alias for compute_fingerprint."""
        return self.compute_fingerprint()

    def record_turn_fingerprint(self, fingerprint: str) -> None:
        """Record turn fingerprint for turn-based stall detection."""
        if fingerprint == self._last_fingerprint:
            self._consecutive_identical_fingerprints += 1
        else:
            self._last_fingerprint = fingerprint
            self._consecutive_identical_fingerprints = 1
        self.progress.progress_fingerprint = fingerprint

    def detect_stall(self, stall_threshold_turns: int = 5) -> Tuple[bool, str, str]:
        """
        Check if mission progress has stagnated without state change for threshold turns.
        Returns: (is_stalled: bool, reason: str, recovery_advice: str)
        """
        if self._consecutive_identical_fingerprints >= stall_threshold_turns:
            focus = self.progress.current_focus or "current requirement"
            reason = f"No progress detected for {self._consecutive_identical_fingerprints} turns on requirement '{focus}'."
            advice = (
                f"Try an alternative implementation strategy or inspect failures: {self.progress.known_failures}"
                if self.progress.known_failures
                else "Break down the task or verify dependencies."
            )
            return True, reason, advice
        return False, "", ""

    def is_stalled(self) -> Tuple[bool, Optional[str]]:
        """
        Check if mission progress has stagnated without state change.
        Returns: (is_stalled: bool, recovery_advice: Optional[str])
        """
        if self._consecutive_identical_fingerprints >= self.STALL_TURN_THRESHOLD:
            focus = self.progress.current_focus or "current requirement"
            advice = (
                f"No meaningful progress on requirement '{focus}' for {self._consecutive_identical_fingerprints} turns. "
            )
            if self.progress.known_failures:
                advice += f"Active failure: {self.progress.known_failures[0]}. Inspect implementation and failing test."
            else:
                advice += "Inspect dependencies or run acceptance checks."
            return True, advice
        return False, None

    def is_goal_completed(self) -> Tuple[bool, str]:
        """
        Evaluate if Goal is complete.
        Requires:
        1. All requirements VERIFIED or WAIVED.
        2. All critical acceptance checks PASS.
        3. Zero blocking failures.
        """
        if not self.requirements:
            return False, "No requirements defined for goal"

        unverified = []
        for r in self.requirements.values():
            if r.status not in (RequirementStatus.VERIFIED, RequirementStatus.WAIVED):
                unverified.append(f"{r.requirement_id} ({r.status.value})")

        if unverified:
            return False, f"Incomplete requirements: {', '.join(unverified[:5])}"

        # Critical acceptance checks check
        rep = self.acceptance_manager.ledger.report()
        if rep["critical_failed"] > 0:
            return False, f"{rep['critical_failed']} critical acceptance checks failed"

        if rep["not_run"] > 0:
            return False, f"{rep['not_run']} acceptance checks have not been run"

        return True, f"All {len(self.requirements)} requirements verified with {rep['passed']} passing acceptance checks."

    def _evaluate_goal_completion(self) -> None:
        """Update Goal status based on strict completion rules."""
        is_done, reason = self.is_goal_completed()
        if is_done:
            self.goal.status = GoalStatus.COMPLETED
            self.progress.overall_status = "COMPLETED"
            logger.info(f"ProgressController: Goal '{self.goal.goal_id}' COMPLETED: {reason}")
        else:
            # Check if blocked
            has_blocked = any(r.status == RequirementStatus.BLOCKED for r in self.requirements.values())
            if has_blocked:
                self.goal.status = GoalStatus.BLOCKED
                self.progress.overall_status = "BLOCKED"
            elif self.goal.status not in (GoalStatus.COMPLETED, GoalStatus.ABORTED, GoalStatus.CANCELLED):
                self.goal.status = GoalStatus.ACTIVE
                self.progress.overall_status = "WORKING"

    def _derive_next_action(self, current_focus: Optional[str]) -> str:
        """Synthesize descriptive, non-dogmatic guidance for next turn."""
        if not current_focus or current_focus not in self.requirements:
            return "Review project requirements and select starting focus."

        req = self.requirements[current_focus]
        if req.status == RequirementStatus.FAILED:
            return f"Inspect failure on '{req.title}' and apply targeted repair."
        elif req.status == RequirementStatus.BLOCKED:
            return f"Investigate blocker for '{req.title}': {req.last_failure or 'prerequisites missing'}."
        elif req.status == RequirementStatus.IN_PROGRESS:
            checks = self.acceptance_manager.ledger.get_checks_for_requirement(req.requirement_id)
            unrun = [c for c in checks if c.status == AcceptanceCheckStatus.NOT_RUN]
            if unrun:
                return f"Implement and execute acceptance check '{unrun[0].description}'."
            return f"Verify implementation of '{req.title}'."
        elif req.status in (RequirementStatus.READY, RequirementStatus.PENDING):
            return f"Begin implementation of '{req.title}'."

        return f"Continue mission on '{req.title}'."
