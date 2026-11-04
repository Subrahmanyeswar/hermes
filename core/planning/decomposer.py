# core/planning/decomposer.py
"""
Goal Decomposer and Requirement Graph Builder for HERMES 2.x (Prompt 9).
Decomposes user prompts into concrete, testable outcomes (requirements),
establishes dependency graphs, detects cycles, and eliminates duplicate requirements.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple
from loguru import logger

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
    with explicit acceptance checks, deduplicated concepts, and dependency relationships.
    """

    # Canonical concept definitions with word-boundary regex patterns to avoid substring collisions
    CANONICAL_CONCEPTS = [
        {
            "id": "req.auth",
            "patterns": [r"\b(?:auth|authentication|login|logout|jwt|oauth|credentials)\b"],
            "category": RequirementCategory.SECURITY,
            "title": "User Authentication and Authorization",
            "checks": ["login and logout lifecycle", "session management", "credential validation"],
            "priority": RequirementPriority.HIGH,
        },
        {
            "id": "req.crud",
            "patterns": [r"\b(?:crud|create\s+read\s+update\s+delete)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "CRUD Operations",
            "checks": ["create records", "read/display records", "update and delete records"],
            "priority": RequirementPriority.HIGH,
        },
        {
            "id": "req.transaction",
            "patterns": [r"\b(?:transactions?|transaction\s+management)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Transaction Management (Add/Edit/Delete)",
            "checks": ["create transaction", "update transaction", "delete transaction"],
            "priority": RequirementPriority.HIGH,
        },
        {
            "id": "req.dashboard",
            "patterns": [r"\b(?:dashboard|metrics\s+view|admin\s+overview)\b"],
            "category": RequirementCategory.UI,
            "title": "Interactive Dashboard",
            "checks": ["render dashboard", "summary views", "metric updates"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.filter",
            "patterns": [r"\b(?:filters?|filtering|search\s+items?|data\s+filtering)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Data Filtering and Search",
            "checks": ["filter by criteria", "search items", "clear filter state"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.persistence",
            "patterns": [r"\b(?:persistence|persist|localstorage|indexeddb|sqlite|database)\b"],
            "category": RequirementCategory.INTEGRATION,
            "title": "Data Persistence",
            "checks": ["save state", "load state", "persist after reload"],
            "priority": RequirementPriority.HIGH,
        },
        {
            "id": "req.responsive",
            "patterns": [r"\b(?:responsive|mobile\s+layout|desktop\s+layout|viewport)\b"],
            "category": RequirementCategory.UI,
            "title": "Responsive Design",
            "checks": ["mobile layout", "desktop layout", "zero horizontal overflow"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.validation",
            "patterns": [r"\b(?:validation|validate|input\s+validation|error\s+feedback)\b"],
            "category": RequirementCategory.QUALITY,
            "title": "Input Validation and Error Handling",
            "checks": ["reject invalid data", "show error messages", "clear error states"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.summary",
            "patterns": [r"\b(?:summary|aggregation|compute\s+totals?)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Summary and Aggregation",
            "checks": ["compute totals", "grouping and summaries"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.chart",
            "patterns": [r"\b(?:charts?|graphs?|analytics\s+visuals?)\b"],
            "category": RequirementCategory.UI,
            "title": "Visual Analytics and Charts",
            "checks": ["render visual graphs", "chart data updates"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.website",
            "patterns": [r"\b(?:website|web\s+app|web\s+application|html5\s+layout|web\s+page)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Web Application & Page Architecture",
            "checks": ["semantic html layout", "navigation header", "responsive structure"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.landing",
            "patterns": [r"\b(?:landing\s+page|hero\s+section|hero\s+presentation)\b"],
            "category": RequirementCategory.UI,
            "title": "Landing Page Layout & Hero Presentation",
            "checks": ["hero presentation", "concept feature showcase", "call to action"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.dialog",
            "patterns": [r"\b(?:modal|modals|dialog|dialogs|popup|popups)\b"],
            "category": RequirementCategory.UI,
            "title": "Interactive Modal & Dialog Components",
            "checks": ["dialog open/close lifecycle", "focus management", "escape key dismissal"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.form",
            "patterns": [r"\b(?:forms?|questionnaires?|booking\s+form|consultation\s+form|input\s+fields?)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Interactive Form & Client Validation",
            "checks": ["input field validation", "accessible error feedback", "submission state"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.asset",
            "patterns": [r"\b(?:assets?|images?|photos?|photographic|textures?|media)\b"],
            "category": RequirementCategory.INTEGRATION,
            "title": "Local Media & Photographic Assets",
            "checks": ["image files exist", "clean image decoding", "no broken resources"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.style",
            "patterns": [r"\b(?:styles?|styling|css|css3|design\s+system|glassmorphism|color\s+palette)\b"],
            "category": RequirementCategory.UI,
            "title": "Visual Design & CSS Styling",
            "checks": ["luxury color palette", "typography", "glassmorphism card surfaces"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.3d_graphics",
            "patterns": [r"\b(?:three\.?js|webgl|3d|geometry|mesh|camera\s+controls?)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Interactive 3D Graphics & Scene Rendering",
            "checks": ["three.js or webgl scene initialized", "interactive 3d rendering loop", "camera manipulation and controls"],
            "priority": RequirementPriority.HIGH,
        },
        {
            "id": "req.simulation",
            "patterns": [r"\b(?:simulation|launch\s+countdown|rocket\s+animations?|propulsion\s+section|launch\s+simulation)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Interactive Simulation & Animations",
            "checks": ["animation loop running", "interactive simulation controls", "state transitions verified"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.car",
            "patterns": [r"\b(?:cars?|automotive|vehicles?|hypercars?)\b"],
            "category": RequirementCategory.FUNCTIONAL,
            "title": "Concept Vehicle Showcase & Specifications",
            "checks": ["concept vehicle models", "technical specifications", "detail views"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.browser",
            "patterns": [r"\b(?:browser|browser\s+preview|browser\s+acceptance|cdp)\b"],
            "category": RequirementCategory.VERIFICATION,
            "title": "Browser Acceptance Qualification",
            "checks": ["real browser rendering", "zero console errors", "no horizontal overflow"],
            "priority": RequirementPriority.MEDIUM,
        },
        {
            "id": "req.test",
            "patterns": [r"\b(?:tests?|pytest|unit\s+tests?|regression\s+suite)\b"],
            "category": RequirementCategory.VERIFICATION,
            "title": "Verification and Qualification",
            "checks": ["automated tests passing", "no regressions"],
            "priority": RequirementPriority.MEDIUM,
        },
    ]

    # Legacy keywords dictionary for backwards compatibility
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
        "website": ("functional", "Web Application & Page Architecture", ["semantic html layout", "navigation header", "responsive structure"]),
        "landing": ("ui", "Landing Page Layout & Hero Presentation", ["hero presentation", "concept feature showcase", "call to action"]),
        "modal": ("ui", "Interactive Modal & Dialog Components", ["dialog open/close lifecycle", "focus management", "escape key dismissal"]),
        "dialog": ("ui", "Interactive Modal & Dialog Components", ["dialog open/close lifecycle", "focus management", "escape key dismissal"]),
        "form": ("functional", "Interactive Form & Client Validation", ["input field validation", "accessible error feedback", "submission state"]),
        "asset": ("integration", "Local Media & Photographic Assets", ["image files exist", "clean image decoding", "no broken resources"]),
        "image": ("integration", "Local Media & Photographic Assets", ["image files exist", "clean image decoding", "no broken resources"]),
        "car": ("functional", "Concept Vehicle Showcase & Specifications", ["concept vehicle models", "technical specifications", "detail views"]),
        "automotive": ("functional", "Concept Vehicle Showcase & Specifications", ["concept vehicle models", "technical specifications", "detail views"]),
        "style": ("ui", "Visual Design & CSS Styling", ["luxury color palette", "typography", "glassmorphism card surfaces"]),
        "css": ("ui", "Visual Design & CSS Styling", ["luxury color palette", "typography", "glassmorphism card surfaces"]),
        "browser": ("verification", "Browser Acceptance Qualification", ["real browser rendering", "zero console errors", "no horizontal overflow"]),
        "test": ("verification", "Verification and Qualification", ["automated tests passing", "no regressions"]),
    }

    @classmethod
    def is_large_mission(cls, prompt: str) -> bool:
        """
        Detect whether a user prompt represents a large/complex software mission
        requiring structured Work Package decomposition and bounded phased execution.
        """
        p = (prompt or "").strip()
        p_lower = p.lower()

        # Check negative/smoke indicators
        if len(p) < 300 and any(k in p_lower for k in ("smoke", "single file", "profile a", "quick check", "hello world", "prints 'hello")):
            return False

        words = p.split()
        structural_cues = [
            r"\b(?:sections?|hero\s+section|destinations?|packages?|catalog|showcase|cards?|directory)\b",
            r"\b(?:modals?|dialogs?|popups?)\b",
            r"\b(?:filters?|filtering|search|calculator)\b",
            r"\b(?:forms?|booking|inquiry|consultation|questionnaire|appointment)\b",
            r"\b(?:assets?|photographic|images?|gallery)\b",
            r"\b(?:responsive|mobile\s+and\s+desktop|viewports?)\b",
            r"\b(?:browser|preview|acceptance|zero\s+console\s+errors)\b",
        ]
        matches = sum(1 for pat in structural_cues if re.search(pat, p_lower))
        if len(p) > 500 or (len(words) >= 20 and matches >= 3) or (matches >= 4):
            return True
        return False

    @classmethod
    def _decompose_large_mission(
        cls,
        goal_id: str,
        user_prompt: str,
        explicit_constraints: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, RequirementState], List[AcceptanceCheck]]:
        """
        Synthesize cohesive, high-level Work Packages for large missions.
        Groups requirements into Foundation, Content, Functional, and Verification packages.
        """
        requirements: Dict[str, RequirementState] = {}
        all_checks: List[AcceptanceCheck] = []
        lower_prompt = user_prompt.lower()

        # Check negative constraints
        no_persistence = bool(re.search(r"\b(?:no|without|zero|not\s+needed|no\s+need\s+for)\s+[^.!?\n]*\b(?:database|backend|persistence|storage)\b", lower_prompt))
        no_auth = bool(re.search(r"\b(?:no|without|zero|not\s+needed|no\s+need\s+for)\s+[^.!?\n]*\b(?:auth|authentication|login)\b", lower_prompt))

        # 1. Foundation Work Package
        wp_found = RequirementState(
            requirement_id="wp.foundation",
            goal_id=goal_id,
            title="Foundation & Architecture Work Package",
            description="HTML semantic layout scaffold, base CSS design system and theming, linked assets and scripts structure, data contracts.",
            category=RequirementCategory.FUNCTIONAL,
            priority=RequirementPriority.CRITICAL,
            status=RequirementStatus.PENDING,
            dependencies=[],
        )
        chk_found_1 = AcceptanceCheck(
            check_id="chk.foundation.scaffold",
            requirement_id="wp.foundation",
            description="Foundation & Architecture: semantic html layout scaffold created",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="filesystem",
        )
        chk_found_2 = AcceptanceCheck(
            check_id="chk.foundation.styles",
            requirement_id="wp.foundation",
            description="Foundation & Architecture: base css styling and layout system linked",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="filesystem",
        )
        chk_found_3 = AcceptanceCheck(
            check_id="chk.foundation.data",
            requirement_id="wp.foundation",
            description="Foundation & Architecture: core data structures and contracts defined",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=False,
            verification_method="command",
        )
        wp_found.acceptance_check_ids.extend([chk_found_1.check_id, chk_found_2.check_id, chk_found_3.check_id])
        requirements["wp.foundation"] = wp_found
        all_checks.extend([chk_found_1, chk_found_2, chk_found_3])

        # 2. Content & Visual Layout Work Package
        wp_content = RequirementState(
            requirement_id="wp.content",
            goal_id=goal_id,
            title="Content & Visual Layout Work Package",
            description="Implement all requested content sections, feature/destination cards, packages/items, and visual media assets.",
            category=RequirementCategory.UI,
            priority=RequirementPriority.HIGH,
            status=RequirementStatus.PENDING,
            dependencies=["wp.foundation"],
        )
        chk_cont_1 = AcceptanceCheck(
            check_id="chk.content.sections",
            requirement_id="wp.content",
            description="Content & Visual Layout: all requested structural content sections rendered",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="filesystem",
        )
        chk_cont_2 = AcceptanceCheck(
            check_id="chk.content.cards",
            requirement_id="wp.content",
            description="Content & Visual Layout: cards and package details populated with data",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="filesystem",
        )
        chk_cont_3 = AcceptanceCheck(
            check_id="chk.content.assets",
            requirement_id="wp.content",
            description="Content & Visual Layout: visual photographic media assets integrated",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=False,
            verification_method="filesystem",
        )
        wp_content.acceptance_check_ids.extend([chk_cont_1.check_id, chk_cont_2.check_id, chk_cont_3.check_id])
        requirements["wp.content"] = wp_content
        all_checks.extend([chk_cont_1, chk_cont_2, chk_cont_3])

        # 3. Functional Interactions & State Work Package
        wp_func = RequirementState(
            requirement_id="wp.functional",
            goal_id=goal_id,
            title="Functional Interactions & State Work Package",
            description="Implement interactive search/filter logic, modal dialog lifecycles, booking/inquiry forms, and client validation.",
            category=RequirementCategory.FUNCTIONAL,
            priority=RequirementPriority.HIGH,
            status=RequirementStatus.PENDING,
            dependencies=["wp.content"],
        )
        chk_func_1 = AcceptanceCheck(
            check_id="chk.functional.filters",
            requirement_id="wp.functional",
            description="Functional Interactions: interactive search and category filtering operational",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="command",
        )
        chk_func_2 = AcceptanceCheck(
            check_id="chk.functional.modals",
            requirement_id="wp.functional",
            description="Functional Interactions: modal dialogs open/close with proper focus and dismissal",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="command",
        )
        chk_func_3 = AcceptanceCheck(
            check_id="chk.functional.forms",
            requirement_id="wp.functional",
            description="Functional Interactions: form input validation and submission feedback verified",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=False,
            verification_method="command",
        )
        wp_func.acceptance_check_ids.extend([chk_func_1.check_id, chk_func_2.check_id, chk_func_3.check_id])
        requirements["wp.functional"] = wp_func
        all_checks.extend([chk_func_1, chk_func_2, chk_func_3])

        # Optional 3D Graphics / Simulation Work Package if requested
        if re.search(r"\b(?:three\.?js|webgl|3d|geometry|mesh)\b", lower_prompt):
            wp_3d = RequirementState(
                requirement_id="wp.3d_graphics",
                goal_id=goal_id,
                title="Interactive 3D Graphics & Scene Rendering",
                description="Initialize 3D canvas, rendering loop, and interactive camera/object controls.",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.HIGH,
                status=RequirementStatus.PENDING,
                dependencies=["wp.foundation"],
            )
            chk_3d_1 = AcceptanceCheck(
                check_id="chk.3d.scene",
                requirement_id="wp.3d_graphics",
                description="3D Graphics: scene and rendering loop operational",
                status=AcceptanceCheckStatus.NOT_RUN,
                critical=True,
                verification_method="command",
            )
            wp_3d.acceptance_check_ids.append(chk_3d_1.check_id)
            requirements["wp.3d_graphics"] = wp_3d
            all_checks.append(chk_3d_1)
            wp_func.dependencies.append("wp.3d_graphics")

        # 4. Comprehensive Acceptance & Browser Qualification Work Package
        wp_verif = RequirementState(
            requirement_id="wp.verification",
            goal_id=goal_id,
            title="Comprehensive Acceptance & Browser Qualification",
            description="Browser qualification, zero console errors, responsive layout verification, and automated tests.",
            category=RequirementCategory.VERIFICATION,
            priority=RequirementPriority.CRITICAL,
            status=RequirementStatus.PENDING,
            dependencies=["wp.functional"],
        )
        chk_verif_1 = AcceptanceCheck(
            check_id="chk.verification.browser",
            requirement_id="wp.verification",
            description="Acceptance & Browser: browser preview rendering passed",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="command",
        )
        chk_verif_2 = AcceptanceCheck(
            check_id="chk.verification.errors",
            requirement_id="wp.verification",
            description="Acceptance & Browser: zero console or runtime errors",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="command",
        )
        chk_verif_3 = AcceptanceCheck(
            check_id="chk.verification.responsive",
            requirement_id="wp.verification",
            description="Acceptance & Browser: responsive layout with zero horizontal overflow",
            status=AcceptanceCheckStatus.NOT_RUN,
            critical=True,
            verification_method="command",
        )
        wp_verif.acceptance_check_ids.extend([chk_verif_1.check_id, chk_verif_2.check_id, chk_verif_3.check_id])
        requirements["wp.verification"] = wp_verif
        all_checks.extend([chk_verif_1, chk_verif_2, chk_verif_3])

        # Deduplicate, break cycles, validate DAG
        requirements, all_checks = cls.deduplicate_requirements(requirements, all_checks)
        cls.break_cycles(requirements)
        cls.validate_dependencies(requirements)

        return requirements, all_checks

    @classmethod
    def decompose(
        cls,
        goal_id: str,
        user_prompt: str,
        explicit_constraints: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, RequirementState], List[AcceptanceCheck]]:
        if cls.is_large_mission(user_prompt):
            return cls._decompose_large_mission(goal_id, user_prompt, explicit_constraints)
        """
        Synthesize requirements and acceptance checks from prompt and constraints.
        Returns: (requirements_dict, list_of_acceptance_checks)
        """
        requirements: Dict[str, RequirementState] = {}
        all_checks: List[AcceptanceCheck] = []

        # Strip negative constraints and agent safety guidance from prompt for requirement analysis
        actionable_prompt_lines = []
        for line in user_prompt.splitlines():
            low = line.lower().strip()
            if re.search(r"\bdo\s+not\s+(?:modify|overwrite|edit|delete)\s+(?:hermes|source|credentials|database|other\s+projects)\b", low):
                continue
            if re.search(r"\bdo\s+not\s+(?:modify|overwrite|delete|change)\b.*?\bexisting\b", low):
                continue
            if re.search(r"\bpreserve\s+(?:hermes|other\s+projects)\b", low):
                continue
            actionable_prompt_lines.append(line)
        cleaned_prompt = " ".join(actionable_prompt_lines)
        lower_prompt = cleaned_prompt.lower()
        is_aerospace_mission = bool(re.search(r"\b(?:rocket|orbital|spacecraft|aerospace|launch\s+vehicle)\b", lower_prompt))

        # 1. Base requirements from prompt analysis with word boundaries
        for concept in cls.CANONICAL_CONCEPTS:
            cid = concept["id"]
            # Exclude automotive concept for aerospace/rocket missions unless explicitly requested
            if cid == "req.car" and is_aerospace_mission and not re.search(r"\b(?:hypercar|automobile|car\s+brand)\b", lower_prompt):
                continue

            # Check explicit exclusions / negative constraints
            if cid == "req.persistence" and re.search(r"\b(?:no|without|zero|not\s+needed|no\s+need\s+for)\s+[^.!?\n]*\b(?:database|backend|persistence|storage)\b", lower_prompt):
                continue
            if cid == "req.auth" and re.search(r"\b(?:no|without|zero|not\s+needed|no\s+need\s+for)\s+[^.!?\n]*\b(?:auth|authentication|login)\b", lower_prompt):
                continue
            if cid == "req.backend" and re.search(r"\b(?:no|without|zero|not\s+needed|no\s+need\s+for)\s+[^.!?\n]*\b(?:backend|server)\b", lower_prompt):
                continue

            matches = False
            for pat in concept["patterns"]:
                if re.search(pat, lower_prompt):
                    matches = True
                    break

            if matches:
                req_id = cid
                req = RequirementState(
                    requirement_id=req_id,
                    goal_id=goal_id,
                    title=concept["title"],
                    description=f"Requirement for {concept['title'].lower()} as requested in mission goal.",
                    category=concept["category"],
                    priority=concept["priority"],
                    status=RequirementStatus.PENDING,
                )

                # Generate acceptance checks for this requirement
                short_key = req_id.replace("req.", "")
                for idx, chk_desc in enumerate(concept["checks"]):
                    chk_id = f"chk.{short_key}.{idx+1}"
                    check = AcceptanceCheck(
                        check_id=chk_id,
                        requirement_id=req_id,
                        description=f"{concept['title']}: {chk_desc}",
                        status=AcceptanceCheckStatus.NOT_RUN,
                        critical=True if idx == 0 else False,
                        verification_method="test" if "test" in short_key else "command",
                    )
                    req.acceptance_check_ids.append(chk_id)
                    all_checks.append(check)

                requirements[req_id] = req

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

        # 3. Always ensure an appropriate terminal verification requirement exists
        verif_req_id = "req.verification"
        if verif_req_id not in requirements:
            is_simple_smoke = False
            try:
                from core.verification_profiles import classify_verification_profile, VerificationProfile
                is_simple_smoke = (classify_verification_profile(user_prompt) == VerificationProfile.PROFILE_A)
            except Exception:
                pass

            if is_simple_smoke:
                verif_req = RequirementState(
                    requirement_id=verif_req_id,
                    goal_id=goal_id,
                    title="Deliverable & Content Verification",
                    description="Verify requested deliverable file(s) exist and match specified content.",
                    category=RequirementCategory.VERIFICATION,
                    priority=RequirementPriority.CRITICAL,
                    status=RequirementStatus.PENDING,
                )
                chk_verif = AcceptanceCheck(
                    check_id="chk.verification.smoke",
                    requirement_id=verif_req_id,
                    description="Deliverables exist on disk and content matches requested specification",
                    status=AcceptanceCheckStatus.NOT_RUN,
                    critical=True,
                    verification_method="filesystem",
                )
            else:
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

        # 4. Deduplicate requirements that share identical or near-identical normalized titles
        requirements, all_checks = cls.deduplicate_requirements(requirements, all_checks)

        # 5. Synthesize natural dependencies
        if "req.persistence" in requirements and "req.crud" in requirements:
            requirements["req.persistence"].dependencies.append("req.crud")
        if "req.filter" in requirements and "req.crud" in requirements:
            requirements["req.filter"].dependencies.append("req.crud")
        if "req.summary" in requirements and "req.crud" in requirements:
            requirements["req.summary"].dependencies.append("req.crud")
        if "req.style" in requirements and "req.website" in requirements:
            requirements["req.style"].dependencies.append("req.website")
        if "req.dialog" in requirements and "req.website" in requirements:
            requirements["req.dialog"].dependencies.append("req.website")
        if "req.form" in requirements and "req.website" in requirements:
            requirements["req.form"].dependencies.append("req.website")
        if "req.3d_graphics" in requirements and "req.website" in requirements:
            requirements["req.3d_graphics"].dependencies.append("req.website")
        if "req.simulation" in requirements and "req.3d_graphics" in requirements:
            requirements["req.simulation"].dependencies.append("req.3d_graphics")
        elif "req.simulation" in requirements and "req.website" in requirements:
            requirements["req.simulation"].dependencies.append("req.website")

        if "req.browser" in requirements:
            for r_id in requirements:
                if r_id not in ("req.browser", verif_req_id) and r_id not in requirements["req.browser"].dependencies:
                    requirements["req.browser"].dependencies.append(r_id)

        # Verification requirement depends on all others
        for r_id in requirements:
            if r_id != verif_req_id and r_id not in requirements[verif_req_id].dependencies:
                requirements[verif_req_id].dependencies.append(r_id)

        # 6. Automatic cycle break and DAG validation
        cls.break_cycles(requirements)
        cls.validate_dependencies(requirements)

        return requirements, all_checks

    @classmethod
    def deduplicate_requirements(
        cls,
        requirements: Dict[str, RequirementState],
        all_checks: List[AcceptanceCheck],
    ) -> Tuple[Dict[str, RequirementState], List[AcceptanceCheck]]:
        """
        Merge requirements with near-identical normalized titles,
        preserving checks and remapping dependencies.
        """
        deduped: Dict[str, RequirementState] = {}
        remap: Dict[str, str] = {}
        seen_titles: Dict[str, str] = {}  # norm_title -> kept_req_id

        for req_id, req in requirements.items():
            norm_title = re.sub(r"\W+", "", req.title.lower())
            if norm_title in seen_titles:
                primary_id = seen_titles[norm_title]
                remap[req_id] = primary_id
                # Merge acceptance check IDs
                primary_req = deduped[primary_id]
                for chk_id in req.acceptance_check_ids:
                    if chk_id not in primary_req.acceptance_check_ids:
                        primary_req.acceptance_check_ids.append(chk_id)
            else:
                seen_titles[norm_title] = req_id
                deduped[req_id] = req

        # Remap checks and dependencies if any duplicates were merged
        if remap:
            logger.info(f"GoalDecomposer: deduplicated requirements {list(remap.keys())} -> {list(remap.values())}")
            # Remap check requirement_ids
            for chk in all_checks:
                if chk.requirement_id in remap:
                    chk.requirement_id = remap[chk.requirement_id]
            # Remap dependencies
            for req in deduped.values():
                new_deps = []
                for dep in req.dependencies:
                    target_dep = remap.get(dep, dep)
                    if target_dep != req.requirement_id and target_dep not in new_deps:
                        new_deps.append(target_dep)
                req.dependencies = new_deps

        # Filter orphaned checks
        active_req_ids = set(deduped.keys())
        filtered_checks = [c for c in all_checks if c.requirement_id in active_req_ids]

        return deduped, filtered_checks

    @classmethod
    def break_cycles(cls, requirements: Dict[str, RequirementState]) -> None:
        """
        Detect and break dependency cycles by removing offending back-edges.
        """
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str, path: List[str]):
            visited.add(node)
            rec_stack.add(node)

            req = requirements.get(node)
            if req:
                for dep in list(req.dependencies):
                    if dep not in visited:
                        dfs(dep, path + [dep])
                    elif dep in rec_stack:
                        # Cycle found! Break back-edge
                        logger.warning(
                            f"GoalDecomposer: Breaking cycle between '{node}' and '{dep}' along path {' -> '.join(path + [dep])}"
                        )
                        req.dependencies.remove(dep)

            rec_stack.remove(node)

        for req_id in list(requirements.keys()):
            if req_id not in visited:
                dfs(req_id, [req_id])

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
