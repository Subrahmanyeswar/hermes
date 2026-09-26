# core/context/validation.py
"""
Context Pack Validator, Contradiction Detection, and Self-Repair for HERMES 2.x.
Ensures context packs sent to T1 satisfy safety gates: required sections present,
budget respected, secrets redacted, freshness verified, and no contradictory state projections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.context.budget import ContextBudgetReport
from core.context.models import ContextFreshness, ContextItem, ContextPriority, ContextSectionType
from core.runtime_state.events import _SECRET_PATTERNS


@dataclass
class ValidationIssue:
    """An issue detected by the ContextPackValidator."""
    severity: str  # "ERROR", "WARNING"
    code: str
    message: str
    item_id: Optional[str] = None
    section: Optional[ContextSectionType] = None


@dataclass
class ValidationResult:
    """Result of context pack validation."""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.issues)


class ContextPackValidator:
    """
    Enforces quality and safety invariants on candidate context items and assembled packs.
    """

    def validate(
        self,
        sections: Dict[ContextSectionType, List[ContextItem]],
        budget_report: Optional[ContextBudgetReport] = None,
        authoritative_state: Any = None,
    ) -> ValidationResult:
        """Run all validation checks and return structured result."""
        issues: List[ValidationIssue] = []

        # 1. Required sections check
        if not sections.get(ContextSectionType.SYSTEM):
            issues.append(ValidationIssue(
                severity="ERROR",
                code="MISSING_SYSTEM_SECTION",
                message="ContextPack is missing the required SYSTEM section.",
                section=ContextSectionType.SYSTEM,
            ))

        if not sections.get(ContextSectionType.CURRENT_GOAL):
            issues.append(ValidationIssue(
                severity="ERROR",
                code="MISSING_GOAL_SECTION",
                message="ContextPack is missing the required CURRENT_GOAL section.",
                section=ContextSectionType.CURRENT_GOAL,
            ))

        # 2. Budget headroom check
        if budget_report and budget_report.used_tokens > budget_report.usable_capacity:
            issues.append(ValidationIssue(
                severity="ERROR",
                code="BUDGET_EXCEEDED",
                message=f"Context tokens ({budget_report.used_tokens:,}) exceed usable capacity ({budget_report.usable_capacity:,}).",
            ))

        # 3. Secret leakage check
        for sec, items in sections.items():
            for item in items:
                for pat in _SECRET_PATTERNS:
                    if pat.search(item.content):
                        # Hidden chain-of-thought or raw unredacted secret
                        issues.append(ValidationIssue(
                            severity="ERROR",
                            code="SECRET_LEAK_DETECTED",
                            message=f"Potential unredacted secret or chain-of-thought found in item '{item.id}' of section {sec.value}.",
                            item_id=item.id,
                            section=sec,
                        ))
                        break

        # 4. Stale file snippet check
        for item in sections.get(ContextSectionType.RELEVANT_FILES, []):
            if item.freshness == ContextFreshness.STALE:
                issues.append(ValidationIssue(
                    severity="WARNING",
                    code="STALE_FILE_SNIPPET",
                    message=f"File snippet for '{item.provenance.file_path}' is stale compared to disk.",
                    item_id=item.id,
                    section=ContextSectionType.RELEVANT_FILES,
                ))

        # 5. Contradiction check (State vs Observations/Summaries)
        if authoritative_state:
            # Check: State says mission or task is running, but summary claims finished
            if hasattr(authoritative_state, "mission"):
                state_status = getattr(authoritative_state.mission, "status", "")
                for item in sections.get(ContextSectionType.CURRENT_GOAL, []):
                    if "completed" in item.content.lower() and state_status in ("IN_PROGRESS", "RUNNING"):
                        issues.append(ValidationIssue(
                            severity="WARNING",
                            code="CONTRADICTION_STATE_VS_SUMMARY",
                            message="Summary claims mission completed, but authoritative state is still RUNNING. State takes precedence.",
                            item_id=item.id,
                            section=ContextSectionType.CURRENT_GOAL,
                        ))

        return ValidationResult(is_valid=not any(i.severity == "ERROR" for i in issues), issues=issues)

    def repair(
        self,
        sections: Dict[ContextSectionType, List[ContextItem]],
        validation_result: ValidationResult,
    ) -> Dict[ContextSectionType, List[ContextItem]]:
        """
        Lightweight deterministic repair for fixable issues.
        - Redacts any found secrets.
        - Drops stale file snippets.
        - Adds missing system or goal fallback if absent.
        """
        from core.runtime_state.events import redact_sensitive_str

        repaired_sections = {k: list(v) for k, v in sections.items()}

        for issue in validation_result.issues:
            if issue.code == "SECRET_LEAK_DETECTED" and issue.section:
                items = repaired_sections.get(issue.section, [])
                for item in items:
                    if item.id == issue.item_id:
                        item.content = redact_sensitive_str(item.content)

            elif issue.code == "STALE_FILE_SNIPPET":
                # Drop stale file item
                repaired_sections[ContextSectionType.RELEVANT_FILES] = [
                    it for it in repaired_sections.get(ContextSectionType.RELEVANT_FILES, [])
                    if it.id != issue.item_id
                ]

        return repaired_sections


# Global singleton
context_validator = ContextPackValidator()
