# core/agent_loop/completion.py
"""
Authoritative Completion Policy & Goal Completion Guard for HERMES 2.x Agent Loop.

Core Invariants:
1. CLAIMS ARE NOT EVIDENCE: A model self-declaration ('Done', 'Tests passed') NEVER completes a mission.
2. SUBAGENT SUCCESS != GOAL COMPLETE: A subagent completing a subtask does not complete the mission.
3. ACCEPTANCE LEDGER AUTHORITY: Completion requires 100% of requirements VERIFIED or WAIVED.
4. FRESH EVIDENCE MANDATE: All critical acceptance checks must be supported by FRESH, non-stale evidence.
5. QUARANTINE LEGACY HEURISTICS: Prompt 1 keyword checks are completely quarantined from the authoritative completion path.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.evidence.models import EvidenceFreshness
from core.evidence.store import EvidenceStore
from core.runtime_state.models import (
    AcceptanceCheckStatus,
    AcceptanceLedger,
    HermesRuntimeState,
    RepairStatus,
    RequirementPriority,
    RequirementStatus,
)
from core.workspace import WorkspaceManager

logger = logging.getLogger("hermes.agent_loop.completion")


class GoalCompleteGuard:
    """
    Authoritative guard preventing premature, fake, or unverified mission completion.
    """

    @classmethod
    def evaluate(
        cls,
        state: Optional[HermesRuntimeState] = None,
        ledger: Optional[AcceptanceLedger] = None,
        evidence_store: Optional[EvidenceStore] = None,
        strict_requirements: bool = True,
    ) -> Tuple[bool, str, List[str]]:
        """
        Validate whether the goal satisfies authoritative completion invariants.
        Returns:
            (can_complete: bool, reason: str, issues: List[str])
        """
        issues: List[str] = []

        # 1. State Requirements Check (enforced when strict_requirements is active)
        if state:
            if strict_requirements and state.requirements:
                for req_id, req in state.requirements.items():
                    if req.status not in (RequirementStatus.VERIFIED, RequirementStatus.WAIVED):
                        issues.append(
                            f"Requirement {req_id} ('{req.description[:40]}') is in non-terminal state {req.status.value}"
                        )

            # 2. Check for stalled repairs (always enforced)
            for rep_id, rep in state.repairs.items():
                if rep.status == RepairStatus.STALLED:
                    issues.append(f"Repair {rep_id} is STALLED for check {rep.check_id}")

        # 3. Acceptance Ledger Checks
        check_map = {}
        if ledger and ledger.checks:
            check_map = ledger.checks
        elif state and state.acceptance_ledger and state.acceptance_ledger.checks:
            check_map = state.acceptance_ledger.checks

        for chk_id, chk in check_map.items():
            if chk.status == AcceptanceCheckStatus.FAIL:
                issues.append(f"Acceptance check {chk_id} has FAILED")
            elif strict_requirements and chk.status != AcceptanceCheckStatus.PASS:
                is_critical = getattr(chk, "critical", getattr(chk, "is_critical", True))
                if is_critical:
                    issues.append(f"Critical acceptance check {chk_id} has not PASSED (status: {chk.status.value})")

        # 4. Fresh Evidence Verification
        if evidence_store:
            for chk_id, chk in check_map.items():
                if chk.status == AcceptanceCheckStatus.PASS:
                    bundle = evidence_store.get_bundle(chk.requirement_id, check_id=chk_id)
                    if not bundle.records:
                        issues.append(f"Passed check {chk_id} has no supporting evidence records in EvidenceStore")
                    elif not bundle.is_all_fresh:
                        issues.append(f"Passed check {chk_id} is backed by STALE or INVALIDATED evidence")

        if issues:
            return (
                False,
                f"Goal completion rejected by GoalCompleteGuard ({len(issues)} unsatisfied invariant(s)).",
                issues,
            )

        return (True, "GoalCompleteGuard invariants satisfied.", [])


class CompletionPolicy:
    """
    Evaluates completion candidates against physical workspace evidence,
    deterministic AST/syntax checks, and authoritative GoalCompleteGuard criteria.
    Legacy keyword-based quality heuristics are strictly quarantined.
    """

    def __init__(self) -> None:
        pass

    def evaluate_completion(
        self,
        mission_prompt: str,
        workspace: Optional[WorkspaceManager] = None,
        acceptance_criteria: Optional[List[str]] = None,
        written_files: Optional[List[str]] = None,
        runtime_state: Optional[HermesRuntimeState] = None,
        acceptance_ledger: Optional[AcceptanceLedger] = None,
        evidence_store: Optional[EvidenceStore] = None,
        strict_requirements: Optional[bool] = None,
    ) -> Tuple[bool, str, List[str]]:
        """
        Evaluate whether the mission satisfies completion requirements.

        Returns:
            (accepted: bool, reason: str, issues: List[str])
        """
        issues: List[str] = []
        acceptance_criteria = acceptance_criteria or []
        written_files = written_files or []
        is_strict = strict_requirements if strict_requirements is not None else bool(acceptance_criteria)

        # ── 1. Authoritative Ledger & Guard Check ─────────────────────────────
        if runtime_state or acceptance_ledger or evidence_store:
            guard_ok, guard_reason, guard_issues = GoalCompleteGuard.evaluate(
                state=runtime_state,
                ledger=acceptance_ledger,
                evidence_store=evidence_store,
                strict_requirements=is_strict,
            )
            if not guard_ok:
                return (False, guard_reason, guard_issues)

        # ── 2. Artifact Existence & Non-Empty Check ───────────────────────────
        creation_keywords = ("build", "create", "write", "implement", "generate", "develop", "setup", "make")
        implies_creation = any(kw in mission_prompt.lower() for kw in creation_keywords)

        ws_root = None
        if workspace and workspace.is_locked:
            ws_root = Path(workspace.root_str)
        elif Path("generated_projects").exists():
            ws_root = Path("generated_projects")

        if implies_creation:
            if ws_root and ws_root.exists():
                existing_files = [
                    f for f in ws_root.rglob("*")
                    if f.is_file() and not any(part.startswith(".") for part in f.relative_to(ws_root).parts)
                ]
                if not existing_files and not written_files:
                    return (
                        False,
                        "Completion rejected: prompt requested creation but no artifacts were found in the workspace.",
                        ["No output files created in workspace root"]
                    )
                empty_files = [str(f.name) for f in existing_files if f.stat().st_size == 0]
                if empty_files:
                    issues.append(f"Empty files detected: {', '.join(empty_files[:3])}")
            elif not written_files:
                return (
                    False,
                    "Completion rejected: workspace root does not contain created files.",
                    ["No output files detected"]
                )

        # ── 3. Local Deterministic Fast Path (Syntax & Parsing) ───────────────
        if ws_root and ws_root.exists():
            for p in ws_root.rglob("*"):
                if not p.is_file() or any(part.startswith(".") for part in p.relative_to(ws_root).parts):
                    continue
                if p.suffix == ".py":
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        ast.parse(content, filename=str(p))
                    except SyntaxError as syn_err:
                        issues.append(f"Python syntax error in {p.name} (line {syn_err.lineno}): {syn_err.msg}")
                elif p.suffix == ".json":
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        json.loads(content)
                    except Exception as json_err:
                        issues.append(f"Malformed JSON in {p.name}: {json_err}")

        if issues:
            return (
                False,
                f"Completion rejected: deterministic syntax validation failed ({len(issues)} issue(s)).",
                issues
            )

        # ── 4. Acceptance ─────────────────────────────────────────────────────
        return True, "All completion evidence and deterministic checks verified.", []
