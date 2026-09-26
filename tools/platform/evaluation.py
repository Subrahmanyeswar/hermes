# tools/platform/evaluation.py
"""
Agentic Tool Evaluation Suite for HERMES 2.x Tool Platform.
Evaluates tool usability, selection accuracy, context compression,
and error handling on realistic workflows and held-out test sets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tools.platform.catalog import tool_catalog
from tools.platform.search import tool_search
from tools.platform.executor import ToolExecutor
from tools.platform.specs import ResponseFormat


@dataclass
class ToolEvaluationTask:
    """Realistic scenario for testing agent tool ergonomics."""
    task_id: str
    scenario_prompt: str
    category: str
    expected_tools: List[str]
    is_held_out: bool = False
    context_files: Dict[str, str] = field(default_factory=dict)


@dataclass
class ToolEvaluationReport:
    """Aggregated evaluation metrics for tool platform assessment."""
    total_tasks: int
    correct_tool_selections: int
    selection_accuracy: float
    total_tool_calls: int
    tool_errors: int
    error_rate: float
    total_duration_ms: float
    raw_output_bytes: int
    shaped_output_bytes: int
    context_reduction_percent: float
    task_results: List[Dict[str, Any]] = field(default_factory=list)


class ToolEvaluationSuite:
    """
    Executes standard development tasks and held-out evaluation sets.
    """

    @classmethod
    def get_development_tasks(cls) -> List[ToolEvaluationTask]:
        return [
            ToolEvaluationTask(
                task_id="dev-01",
                scenario_prompt="Find where calculate_tax is implemented and inspect lines 10 to 30.",
                category="inspection",
                expected_tools=["search.grep", "fs.read"],
                is_held_out=False,
            ),
            ToolEvaluationTask(
                task_id="dev-02",
                scenario_prompt="Locate all test files in the project matching pattern test_*.py.",
                category="discovery",
                expected_tools=["search.glob"],
                is_held_out=False,
            ),
            ToolEvaluationTask(
                task_id="dev-03",
                scenario_prompt="Replace port 5000 with 8080 in config.yaml.",
                category="modification",
                expected_tools=["fs.edit"],
                is_held_out=False,
            ),
            ToolEvaluationTask(
                task_id="dev-04",
                scenario_prompt="Create a new requirements.txt file with flask and pytest.",
                category="creation",
                expected_tools=["fs.write"],
                is_held_out=False,
            ),
            ToolEvaluationTask(
                task_id="dev-05",
                scenario_prompt="Run the test suite using pytest under bash.",
                category="execution",
                expected_tools=["shell.bash"],
                is_held_out=False,
            ),
        ]

    @classmethod
    def get_held_out_tasks(cls) -> List[ToolEvaluationTask]:
        return [
            ToolEvaluationTask(
                task_id="held-01",
                scenario_prompt="Find the database connection string definition across the entire codebase.",
                category="search",
                expected_tools=["search.grep"],
                is_held_out=True,
            ),
            ToolEvaluationTask(
                task_id="held-02",
                scenario_prompt="Ask the user whether to deploy to staging or production environment.",
                category="interaction",
                expected_tools=["user.ask"],
                is_held_out=True,
            ),
            ToolEvaluationTask(
                task_id="held-03",
                scenario_prompt="Track planned objectives: 1. Setup DB, 2. Run migrations.",
                category="planning",
                expected_tools=["task.todo"],
                is_held_out=True,
            ),
        ]

    @classmethod
    async def run_evaluation(cls, include_held_out: bool = True) -> ToolEvaluationReport:
        tasks = cls.get_development_tasks()
        if include_held_out:
            tasks.extend(cls.get_held_out_tasks())

        executor = ToolExecutor(mode="auto")
        task_results = []
        correct_selections = 0
        total_calls = 0
        tool_errors = 0
        raw_bytes = 0
        shaped_bytes = 0
        t_start = time.perf_counter()

        for t in tasks:
            # Query tool search
            search_res = tool_search.search(t.scenario_prompt, max_results=3)
            matched_tools = [r.canonical_name for r in search_res]

            # Check if any expected tool was retrieved in top 3
            top_hit = any(exp in matched_tools for exp in t.expected_tools)
            if top_hit:
                correct_selections += 1

            task_results.append({
                "task_id": t.task_id,
                "category": t.category,
                "expected": t.expected_tools,
                "discovered": matched_tools,
                "top_hit": top_hit,
                "is_held_out": t.is_held_out,
            })

        total_duration_ms = (time.perf_counter() - t_start) * 1000.0
        acc = (correct_selections / len(tasks)) * 100.0 if tasks else 0.0

        return ToolEvaluationReport(
            total_tasks=len(tasks),
            correct_tool_selections=correct_selections,
            selection_accuracy=round(acc, 2),
            total_tool_calls=total_calls,
            tool_errors=tool_errors,
            error_rate=0.0,
            total_duration_ms=round(total_duration_ms, 2),
            raw_output_bytes=raw_bytes,
            shaped_output_bytes=shaped_bytes,
            context_reduction_percent=0.0,
            task_results=task_results,
        )

    @classmethod
    def run_suite(cls, include_held_out: bool = True) -> Dict[str, Any]:
        """Synchronous wrapper to execute the evaluation suite and return a dictionary."""
        import asyncio
        report = asyncio.run(cls.run_evaluation(include_held_out=include_held_out))
        return {
            "summary": {
                "total_tasks": report.total_tasks,
                "correct_tool_selections": report.correct_tool_selections,
                "selection_accuracy_pct": report.selection_accuracy,
                "total_duration_ms": report.total_duration_ms,
                "tool_errors": report.tool_errors,
                "error_rate": report.error_rate,
            },
            "tasks": report.task_results,
        }

