# core/planning/decomposer.py
"""
Goal Decomposer and Requirement Graph Builder for HERMES 2.x (Prompt 9).
Decomposes user prompts into concrete, testable outcomes (requirements),
establishes dependency graphs, detects cycles, and identifies conflicts or duplicates.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    RequirementCategory,
    RequirementPriority,
    RequirementState,
    RequirementStatus,
)


class DependencyCycleError(ValueError):
    """Raised when a dependency cycle is detected in the requirement graph."""
    pass


class GoalDecomposer:
    """
    Decomposes unstructured user goals into structured, testable RequirementState objects
    with explicit acceptance checks and dependency relationships.
    """

    DEFAULT_KEYWORDS = {
        "auth": ("security", "User Authentication and Authorization", ["login", "logout", "session"]),
        "crud": ("functional", "CRUD Operations", ["create", "read", "update", "delete"]),
        "transaction": ("functional", "Transaction Management (Add/Edit/Delete)", ["create transaction", "update transaction", "delete transaction"]),
        "dashboard": ("ui", "Interactive Dashboard", ["render dashboard", "summary views"]),
        "filter": ("functional", "Data Filtering and Search", ["filter by criteria", "search items"]),
        "persistence": ("integration", "Data Persistence", ["save state", "load state", "persist after reload"]),
        "responsive": ("ui", "Responsive Design", ["mobile layout", "desktop layout"]),
        "validation": ("quality", "Input Validation and Error Handling", ["reject invalid data", "show error messages"]),
        "summary": ("functional", "Summary and Aggregation", ["compute totals", "grouping"]),
        "chart": ("ui", "Visual Analytics and Charts", ["render visual graphs"]),
        "test": ("verification", "Verification and Qualification", ["automated tests passing", "no regressions"]),
    }

    @classmethod
    def decompose(
        cls,
        goal_id: str,
        user_prompt: str,
        explicit_constraints: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, RequirementState], List[AcceptanceCheck]]:
        """
        Synthesize requirements and acceptance checks from prompt and constraints.
        Returns: (requirements_dict, list_of_acceptance_checks)
        """
        requirements: Dict[str, RequirementState] = {}
        all_checks: List[AcceptanceCheck] = []

        lower_prompt = user_prompt.lower()

        # Extract discrete features or sentences
        sentences = [s.strip() for s in re.split(r"[.\n;]", user_prompt) if len(s.strip()) > 5]

        # 1. Base requirements from prompt analysis
        detected_categories = []
        for kw, (cat_name, title, default_checks) in cls.DEFAULT_KEYWORDS.items():
            if kw in lower_prompt:
                req_id = f"req.{kw}"
                cat = RequirementCategory(cat_name)
                prio = RequirementPriority.HIGH if kw in ("crud", "persistence", "auth") else RequirementPriority.MEDIUM

                req = RequirementState(
                    requirement_id=req_id,
                    goal_id=goal_id,
                    title=title,
                    description=f"Requirement for {title.lower()} as requested in mission goal.",
                    category=cat,
                    priority=prio,
                    status=RequirementStatus.PENDING,
                )

                # Generate acceptance checks for this requirement
                for idx, chk_desc in enumerate(default_checks):
                    chk_id = f"chk.{kw}.{idx+1}"
                    check = AcceptanceCheck(
                        check_id=chk_id,
                        requirement_id=req_id,
                        description=f"{title}: {chk_desc}",
                        status=AcceptanceCheckStatus.NOT_RUN,
                        critical=True if idx == 0 else False,
                        verification_method="test" if "test" in kw else "command",
                    )
                    req.acceptance_check_ids.append(chk_id)
                    all_checks.append(check)

                requirements[req_id] = req
                detected_categories.append(kw)

        # 2. If nothing specific matched keywords, create general functional requirement
        if not requirements:
            req_id = "req.core_implementation"
            req = RequirementState(
                requirement_id=req_id,
                goal_id=goal_id,
                title="Core Mission Implementation",
                description=user_prompt[:200],
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.CRITICAL,
                status=RequirementStatus.PENDING,
            )
            chk_id = "chk.core.1"
            check = AcceptanceCheck(
                check_id=chk_id,
                requirement_id=req_id,
                description="Core goal implementation verified end-to-end",
                status=AcceptanceCheckStatus.NOT_RUN,
                critical=True,
            )
            req.acceptance_check_ids.append(chk_id)
            requirements[req_id] = req
            all_checks.append(check)

        # 3. Always ensure a terminal verification requirement exists
        verif_req_id = "req.verification"
        if verif_req_id not in requirements:
            verif_req = RequirementState(
                requirement_id=verif_req_id,
                goal_id=goal_id,
                title="Complete Verification & Regression Suite",
                description="Verify all functional requirements with automated tests and zero defects.",
                category=RequirementCategory.VERIFICATION,
                priority=RequirementPriority.CRITICAL,
                status=RequirementStatus.PENDING,
            )
            chk_verif = AcceptanceCheck(
                check_id="chk.verification.full",
                requirement_id=verif_req_id,
                description="Full test suite and acceptance verification pass",
                status=AcceptanceCheckStatus.NOT_RUN,
                critical=True,
                verification_method="test",
            )
            verif_req.acceptance_check_ids.append(chk_verif.check_id)
            requirements[verif_req_id] = verif_req
            all_checks.append(chk_verif)

        # 4. Synthesize natural dependencies
        # E.g. persistence depends on crud; verification depends on all
        if "req.persistence" in requirements and "req.crud" in requirements:
            requirements["req.persistence"].dependencies.append("req.crud")
        if "req.filter" in requirements and "req.crud" in requirements:
            requirements["req.filter"].dependencies.append("req.crud")
        if "req.summary" in requirements and "req.crud" in requirements:
            requirements["req.summary"].dependencies.append("req.crud")

        # Verification requirement depends on all others
        for r_id in requirements:
            if r_id != verif_req_id and r_id not in requirements[verif_req_id].dependencies:
                requirements[verif_req_id].dependencies.append(r_id)

        # 5. Validate no cycles exist
        cls.validate_dependencies(requirements)

        return requirements, all_checks

    @classmethod
    def validate_dependencies(cls, requirements: Dict[str, RequirementState]) -> None:
        """
        Verify that requirement dependencies form a valid Directed Acyclic Graph (DAG).
        Raises DependencyCycleError if a cycle is detected.
        """
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: List[str]):
            visited.add(node)
            rec_stack.add(node)

            req = requirements.get(node)
            if req:
                for dep in req.dependencies:
                    if dep not in visited:
                        dfs(dep, path + [dep])
                    elif dep in rec_stack:
                        cycle_path = " -> ".join(path + [dep])
                        raise DependencyCycleError(
                            f"REQUIREMENT_DEPENDENCY_CYCLE: Dependency cycle detected along path: {cycle_path}"
                        )

            rec_stack.remove(node)

        for req_id in requirements:
            if req_id not in visited:
                dfs(req_id, [req_id])

    @classmethod
    def find_duplicate_requirements(cls, requirements: Dict[str, RequirementState]) -> List[Tuple[str, str]]:
        """Identify potential duplicate requirements with near-identical titles or descriptions."""
        duplicates = []
        req_list = list(requirements.values())
        for i in range(len(req_list)):
            for j in range(i + 1, len(req_list)):
                r1, r2 = req_list[i], req_list[j]
                t1 = re.sub(r"\W+", "", r1.title.lower())
                t2 = re.sub(r"\W+", "", r2.title.lower())
                if t1 == t2 or (len(t1) > 6 and t1 in t2) or (len(t2) > 6 and t2 in t1):
                    duplicates.append((r1.requirement_id, r2.requirement_id))
        return duplicates

    @classmethod
    def detect_conflicts(
        cls,
        requirements: Dict[str, RequirementState],
        explicit_constraints: Optional[List[str]] = None,
    ) -> List[str]:
        """Detect obvious semantic contradictions between requirements or constraints."""
        conflicts = []
        all_text = " ".join([r.title + " " + r.description for r in requirements.values()]).lower()
        if explicit_constraints:
            all_text += " " + " ".join(explicit_constraints).lower()

        # Contradiction patterns
        if "no local storage" in all_text and ("local storage" in all_text or "local persistence" in all_text):
            if "no local storage" in all_text:
                conflicts.append("REQUIREMENT_CONFLICT: 'no local storage' conflicts with persistence requirement.")

        if "no database" in all_text and ("sqlite" in all_text or "postgres" in all_text):
            conflicts.append("REQUIREMENT_CONFLICT: 'no database' conflicts with external database requirement.")

        return conflicts
