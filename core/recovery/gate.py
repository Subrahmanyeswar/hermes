# core/recovery/gate.py
"""
Recovery Gate for HERMES 2.x session resume.

Evaluates domain reconciliation results and issues authoritative recovery decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.persistence.models import RecoveryDecisionType


@dataclass
class RecoveryVerdict:
    """The authoritative clearance verdict issued by the RecoveryGate."""
    decision: RecoveryDecisionType
    warnings: List[str] = field(default_factory=list)
    reconciliation_summary: Dict[str, Any] = field(default_factory=dict)
    can_proceed: bool = True


class RecoveryGate:
    """
    Evaluates drift across all domains and decides safe resume parameters.
    """

    @classmethod
    def evaluate(
        cls,
        fs_reconcile: Dict[str, Any],
        git_reconcile: Dict[str, Any],
        jobs_reconcile: Dict[str, Any],
        security_reconcile: Dict[str, Any],
        is_headless: bool = False,
    ) -> RecoveryVerdict:
        warnings: List[str] = []

        if fs_reconcile.get("has_drift"):
            mods = len(fs_reconcile.get("modified_files", []))
            miss = len(fs_reconcile.get("missing_files", []))
            warnings.append(f"Workspace drift detected: {mods} modified, {miss} missing files.")

        if git_reconcile.get("has_drift"):
            if git_reconcile.get("head_drift"):
                warnings.append(f"Git HEAD has moved from {git_reconcile.get('checkpoint_head', '')[:8]} to {git_reconcile.get('current_head', '')[:8]}.")
            if git_reconcile.get("branch_drift"):
                warnings.append(f"Git branch changed from '{git_reconcile.get('checkpoint_branch')}' to '{git_reconcile.get('current_branch')}'.")

        if jobs_reconcile.get("orphaned_count", 0) > 0:
            warnings.append(f"{jobs_reconcile['orphaned_count']} background jobs were found dead/orphaned.")

        if security_reconcile.get("invalidated_count", 0) > 0:
            warnings.append(f"{security_reconcile['invalidated_count']} security approval grants were expired or invalidated.")

        summary = {
            "filesystem": fs_reconcile,
            "git": git_reconcile,
            "jobs": jobs_reconcile,
            "security": security_reconcile,
        }

        if not warnings:
            return RecoveryVerdict(
                decision=RecoveryDecisionType.RESUME_CLEAN,
                reconciliation_summary=summary,
                can_proceed=True,
            )

        return RecoveryVerdict(
            decision=RecoveryDecisionType.RESUME_WITH_WARNINGS,
            warnings=warnings,
            reconciliation_summary=summary,
            can_proceed=True,
        )
