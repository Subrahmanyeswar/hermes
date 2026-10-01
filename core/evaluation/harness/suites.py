# core/evaluation/harness/suites.py
"""
Evaluation Suites for HERMES 2.x (Prompt 17).
Defines Capability, Regression, and Held-Out evaluation tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from core.evaluation.functional.models import CheckLayer, FunctionalCheck
from core.evaluation.harness.models import (
    EvaluationCategory,
    EvaluationDifficulty,
    EvaluationTask,
    TaskRequirement,
)


class EvaluationSuiteRegistry:
    """Registry maintaining active evaluation tasks and suites."""

    def __init__(self) -> None:
        self._tasks: Dict[str, EvaluationTask] = {}
        self._register_default_suites()

    def _register_default_suites(self) -> None:
        # ── 1. Capability Suite: Web Transaction Dashboard ───────────────────
        self.register(
            EvaluationTask(
                task_id="cap_web_transaction_dashboard",
                name="Web Transaction Dashboard Implementation",
                category=EvaluationCategory.CAPABILITY,
                difficulty=EvaluationDifficulty.MEDIUM,
                prompt="Build a responsive transaction dashboard allowing users to record and view expenses.",
                requirements=[
                    TaskRequirement("req_create", "Allow adding a transaction"),
                    TaskRequirement("req_persist", "Persist transaction across page reload"),
                    TaskRequirement("req_responsive", "Render adaptively without mobile horizontal overflow"),
                ],
                functional_checks=[
                    FunctionalCheck(
                        check_id="chk_html_exists",
                        name="HTML Dashboard File Exists",
                        layer=CheckLayer.STATIC,
                        expected="index.html",
                    ),
                    FunctionalCheck(
                        check_id="chk_add_btn",
                        name="Add Transaction Button Present",
                        layer=CheckLayer.BROWSER,
                        expected="Add Transaction",
                    ),
                    FunctionalCheck(
                        check_id="chk_saved_row",
                        name="Transaction Row Appears in Table",
                        layer=CheckLayer.BROWSER,
                        expected="Salary",
                    ),
                    FunctionalCheck(
                        check_id="chk_persistence",
                        name="Transaction Survives Reload",
                        layer=CheckLayer.PERSISTENCE,
                        expected="Salary",
                    ),
                ],
                requires_browser=True,
                requires_visual=True,
                trial_count=3,
            )
        )

        # ── 2. Capability Suite: Cross-File Symbol Rename ─────────────────────
        self.register(
            EvaluationTask(
                task_id="cap_cross_file_rename",
                name="Semantic Cross-File Symbol Rename",
                category=EvaluationCategory.CAPABILITY,
                difficulty=EvaluationDifficulty.MEDIUM,
                prompt="Rename symbol 'calculate_tax' to 'compute_sales_tax' across all dependent modules.",
                requirements=[
                    TaskRequirement("req_clean_syntax", "All modified files have valid syntax"),
                ],
                functional_checks=[
                    FunctionalCheck(
                        check_id="chk_syntax",
                        name="Syntax Check Post-Rename",
                        layer=CheckLayer.STATIC,
                        expected="main.py",
                    ),
                ],
                requires_browser=False,
                requires_visual=False,
                trial_count=1,
            )
        )

        # ── 3. Regression Suite: Code Intelligence Basics ────────────────────
        self.register(
            EvaluationTask(
                task_id="reg_code_intelligence_syntax",
                name="Code Intelligence Syntax Verification",
                category=EvaluationCategory.REGRESSION,
                difficulty=EvaluationDifficulty.SIMPLE,
                prompt="Verify syntax validation and diagnostic detection in active workspace.",
                functional_checks=[
                    FunctionalCheck(
                        check_id="chk_main_syntax",
                        name="Main Entrypoint Syntax Valid",
                        layer=CheckLayer.STATIC,
                        expected="main.py",
                    ),
                ],
                trial_count=1,
            )
        )

        # ── 4. Regression Suite: Browser Navigation Basics ───────────────────
        self.register(
            EvaluationTask(
                task_id="reg_browser_navigation_health",
                name="Browser Headless Navigation Health",
                category=EvaluationCategory.REGRESSION,
                difficulty=EvaluationDifficulty.SIMPLE,
                prompt="Verify browser launches and navigates to about:blank without errors.",
                requires_browser=True,
                trial_count=1,
            )
        )

        # ── 5. Held-Out Suite: Independent Behavioral Validation ─────────────
        self.register(
            EvaluationTask(
                task_id="heldout_persistence_contract",
                name="Held-Out Verification of Reload Durability",
                category=EvaluationCategory.HELDOUT,
                difficulty=EvaluationDifficulty.COMPLEX,
                prompt="Held-out validation: verify user state survives page refresh without session leakage.",
                requires_browser=True,
                requires_visual=False,
                trial_count=2,
            )
        )

    def register(self, task: EvaluationTask) -> None:
        self._tasks[task.task_id] = task

    def get_task(self, task_id: str) -> Optional[EvaluationTask]:
        return self._tasks.get(task_id)

    def get_tasks_by_category(self, category: EvaluationCategory) -> List[EvaluationTask]:
        return [t for t in self._tasks.values() if t.category == category]

    def list_all_tasks(self) -> List[EvaluationTask]:
        return list(self._tasks.values())


# Global default suite registry
suite_registry = EvaluationSuiteRegistry()
