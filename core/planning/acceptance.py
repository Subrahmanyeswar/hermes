# core/planning/acceptance.py
"""
Acceptance Contract and Ledger Engine for HERMES 2.x (Prompt 9).
Manages the completion contract:
Requirement -> Acceptance Checks -> Verification -> Evidence -> Verified Status.

Enforces:
1. No evidence = No verified.
2. Critical check failure blocks requirement verification.
3. Stale evidence detection upon source file modification.
4. Regression reopening when later checks fail.
5. Explicit waiver mechanism with actor and reason audit trail.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger

from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    RequirementState,
    RequirementStatus,
)


class AcceptanceManager:
    """
    Evaluator and auditor for the AcceptanceLedger.
    Guarantees that requirements transition to VERIFIED only with valid evidence.
    """

    def __init__(self, ledger: Optional[AcceptanceLedger] = None) -> None:
        self.ledger = ledger or AcceptanceLedger()

    def register_checks(self, checks: List[AcceptanceCheck]) -> None:
        """Register initial acceptance checks in ledger."""
        for c in checks:
            self.ledger.add_check(c)

    def record_check_result(
        self,
        check_id: str,
        status: AcceptanceCheckStatus,
        evidence_ref: Optional[str] = None,
        error: Optional[str] = None,
        source_versions: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Record check execution result with evidence reference."""
        return self.ledger.record_result(
            check_id=check_id,
            status=status,
            evidence_ref=evidence_ref,
            error=error,
            source_versions=source_versions,
        )

    def evaluate_requirement_status(self, requirement: RequirementState) -> RequirementStatus:
        """Evaluate and mutate requirement status in-place based on acceptance checks."""
        status, reason = self.evaluate_requirement(requirement)
        requirement.transition_status(status, reason=reason, actor="acceptance_evaluator")
        return status

    def invalidate_for_modified_files(self, modified_files: Set[str]) -> List[str]:
        """Invalidate checks referencing modified source files."""
        return self.ledger.mark_stale_for_files(modified_files)

    def evaluate_requirement(
        self,
        requirement: RequirementState,
    ) -> Tuple[RequirementStatus, str]:
        """
        Evaluate requirement status against acceptance ledger checks.
        Returns: (derived_status, rationale)
        """
        # If explicitly waived, retain waiver
        if requirement.status == RequirementStatus.WAIVED:
            return RequirementStatus.WAIVED, f"Requirement waived by {requirement.waiver_actor}: {requirement.waiver_reason}"

        if requirement.status == RequirementStatus.CANCELLED:
            return RequirementStatus.CANCELLED, "Requirement was cancelled"

        checks = self.ledger.get_checks_for_requirement(requirement.requirement_id)
        if not checks:
            return RequirementStatus.PENDING, "No acceptance checks registered for requirement"

        has_failure = False
        has_blocked = False
        has_not_run = False
        has_pass = False
        has_verified_evidence = False

        failed_reasons = []

        for chk in checks:
            if chk.status == AcceptanceCheckStatus.FAIL:
                has_failure = True
                failed_reasons.append(f"Check '{chk.description}' failed: {chk.error_message or 'Failure'}")
            elif chk.status == AcceptanceCheckStatus.BLOCKED:
                has_blocked = True
                failed_reasons.append(f"Check '{chk.description}' is blocked")
            elif chk.status == AcceptanceCheckStatus.NOT_RUN:
                has_not_run = True
            elif chk.status == AcceptanceCheckStatus.PASS:
                has_pass = True
                if chk.evidence_refs:
                    has_verified_evidence = True

        # Regression detection: if previously VERIFIED but now has failure
        if has_failure:
            if requirement.status == RequirementStatus.VERIFIED:
                logger.warning(f"AcceptanceManager: requirement '{requirement.requirement_id}' was VERIFIED but has regressions!")
            return RequirementStatus.FAILED, "; ".join(failed_reasons)

        if has_blocked:
            return RequirementStatus.BLOCKED, "; ".join(failed_reasons)

        # Incomplete checks
        if has_not_run:
            if has_pass:
                return RequirementStatus.IN_PROGRESS, "Partial acceptance checks passing; remaining checks not run"
            return RequirementStatus.PENDING, "Acceptance checks have not been run"

        # All checks passed: Must have evidence!
        if not has_verified_evidence:
            return RequirementStatus.IN_PROGRESS, "All checks marked pass, but no verifiable evidence recorded (No Evidence = No Verified)"

        # All checks passed with valid evidence
        evidence_summary = []
        for chk in checks:
            evidence_summary.extend(chk.evidence_refs)

        # Update requirement evidence refs
        requirement.evidence_refs = list(set(evidence_summary))

        return RequirementStatus.VERIFIED, f"All {len(checks)} acceptance checks passed with verified evidence: {', '.join(requirement.evidence_refs)}"

    def check_file_modifications(
        self,
        modified_files: Set[str],
        requirements: Dict[str, RequirementState],
    ) -> List[str]:
        """
        Invalidate checks and requirements whose verified evidence depends on modified files.
        Returns list of invalidated requirement IDs.
        """
        stale_checks = self.ledger.mark_stale_for_files(modified_files)
        if not stale_checks:
            return []

        affected_req_ids = set()
        for cid in stale_checks:
            chk = self.ledger.checks.get(cid)
            if chk and chk.requirement_id in requirements:
                req = requirements[chk.requirement_id]
                affected_req_ids.add(req.requirement_id)
                if req.status == RequirementStatus.VERIFIED:
                    req.reopen(reason=f"Acceptance check '{chk.description}' became stale due to file changes.")
                    logger.info(f"AcceptanceManager: reopened requirement '{req.requirement_id}' due to stale evidence")

        return list(affected_req_ids)

    def waive_requirement(
        self,
        requirement: RequirementState,
        reason: str,
        actor: str = "user",
    ) -> None:
        """Waive requirement with explicit decision audit trail."""
        requirement.waive(reason=reason, actor=actor)
        logger.info(f"AcceptanceManager: requirement '{requirement.requirement_id}' waived by {actor}: {reason}")
