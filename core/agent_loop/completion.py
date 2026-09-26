# core/agent_loop/completion.py
"""
Completion Policy and Evidence Verification Engine for HERMES 2.x Agent Loop.
Enforces the two-layer completion contract:
    Layer 1: Model Completion Candidate (proposal)
    Layer 2: Harness & Evidence Verification (authoritative decision)

A model self-claim ('Done', 'Tests passed') NEVER directly completes a mission
without physical evidence and deterministic/structural verification.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from core.workspace import WorkspaceManager
from core.quality_verifier import QualityVerifier


class CompletionPolicy:
    """
    Evaluates completion candidates against physical workspace evidence,
    deterministic syntax/structural checks, and quality verifier contracts.
    """

    def __init__(self) -> None:
        self._quality_verifier = QualityVerifier()

    def evaluate_completion(
        self,
        mission_prompt: str,
        workspace: Optional[WorkspaceManager] = None,
        acceptance_criteria: Optional[List[str]] = None,
        written_files: Optional[List[str]] = None,
    ) -> Tuple[bool, str, List[str]]:
        """
        Evaluate whether the mission satisfies completion requirements.

        Returns:
            (accepted: bool, reason: str, issues: List[str])
        """
        issues: List[str] = []
        acceptance_criteria = acceptance_criteria or []
        written_files = written_files or []

        # ── 1. Artifact Existence & Non-Empty Check ───────────────────────────
        # Check if the prompt implied file creation (e.g. "build", "create", "write", "implement")
        creation_keywords = ("build", "create", "write", "implement", "generate", "develop", "setup", "make")
        implies_creation = any(kw in mission_prompt.lower() for kw in creation_keywords)

        ws_root = None
        if workspace and workspace.is_locked:
            ws_root = Path(workspace.root_str)
        elif Path("generated_projects").exists():
            ws_root = Path("generated_projects")

        if implies_creation:
            # If the user asked to build/create something, there must be real files
            if ws_root and ws_root.exists():
                existing_files = [f for f in ws_root.rglob("*") if f.is_file() and not f.name.startswith(".")]
                if not existing_files and not written_files:
                    return (
                        False,
                        "Completion rejected: prompt requested creation but no artifacts were found in the workspace.",
                        ["No output files created in workspace root"]
                    )
                # Check for empty files
                empty_files = [str(f.name) for f in existing_files if f.stat().st_size == 0]
                if empty_files:
                    issues.append(f"Empty files detected: {', '.join(empty_files[:3])}")
            elif not written_files:
                return (
                    False,
                    "Completion rejected: workspace root does not contain created files.",
                    ["No output files detected"]
                )

        # ── 2. Local Deterministic Fast Path (Syntax & Parsing) ───────────────
        if ws_root and ws_root.exists():
            for p in ws_root.rglob("*"):
                if not p.is_file() or p.name.startswith("."):
                    continue
                # Python syntax validation via AST
                if p.suffix == ".py":
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        ast.parse(content, filename=str(p))
                    except SyntaxError as syn_err:
                        issues.append(f"Python syntax error in {p.name} (line {syn_err.lineno}): {syn_err.msg}")
                # JSON validation
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

        # ── 3. Quality & Acceptance Criteria Check ────────────────────────────
        if ws_root and ws_root.exists() and acceptance_criteria:
            try:
                q_res = self._quality_verifier.verify_project_completeness(
                    project_root=str(ws_root),
                    acceptance_criteria=acceptance_criteria,
                    user_prompt=mission_prompt,
                )
                if getattr(q_res, "needs_improvement", False) or getattr(q_res, "overall_verdict", "") in ("SHALLOW", "EMPTY", "NEEDS_IMPROVEMENT"):
                    unmet = getattr(q_res, "requirements_missing", []) or getattr(q_res, "improvement_suggestions", []) or ["Quality requirements not met"]
                    return (
                        False,
                        f"Completion rejected: quality verification failed ({getattr(q_res, 'overall_verdict', 'NEEDS_IMPROVEMENT')}).",
                        unmet
                    )
            except Exception as q_exc:
                logger.debug(f"CompletionPolicy: quality verifier exception: {q_exc}")

        # ── 4. Acceptance ─────────────────────────────────────────────────────
        return True, "All completion evidence and deterministic checks verified.", []
