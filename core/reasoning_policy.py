# core/reasoning_policy.py
"""
Centralized Adaptive Reasoning Policy for HERMES vNext (Prompt 3 Optimization).

Enforces task-aware reasoning budgets:
- SIMPLE tasks: think=False, small bounded num_predict, fast timeout.
- STANDARD tasks: bounded reasoning, zero runaway.
- COMPLEX tasks: deep reasoning preserved with hard timeout cap.
- REPAIR tasks: targeted bounded reasoning based on verification feedback.
- BENCHMARK mode: strictly preserves legacy frozen execution behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from loguru import logger
from config.model_config import TIER1_MODEL


class TaskComplexity(Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


@dataclass
class ResolvedReasoningPolicy:
    """Resolved reasoning parameters to pass to model client."""
    think: Optional[bool]
    num_predict: int
    timeout_seconds: int
    temperature: float
    complexity: TaskComplexity
    execution_mode: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "think": self.think,
            "num_predict": self.num_predict,
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "complexity": self.complexity.value,
            "execution_mode": self.execution_mode,
        }


# Keywords that signal genuinely complex or security-sensitive engineering
COMPLEX_INDICATORS = frozenset({
    "architecture", "redesign", "security audit", "concurrency",
    "race condition", "cryptography", "distributed", "memory leak",
    "deadlock", "vulnerability", "exploit", "auth bypass",
    "complex algorithm", "dynamic programming", "graph theory",
    "anime", "animation", "animations", "aesthetic", "genz", "super website",
    "dashboard", "interactive", "landing page", "frontend", "ui", "single-page", "website", "webpage"
})

# Keywords that signal simple, mechanical, or single-file operations
SIMPLE_INDICATORS = frozenset({
    "create file", "write file", "make file", "new file", "simple file",
    "styles.css", "app.js", "readme", "config",
    "mkdir", "directory", "list", "read", "view", "rename", "check",
    "single function", "helper function", "basic styling", "heading"
})


class ReasoningPolicy:
    """
    Centralized resolver for task complexity and reasoning execution policy.
    Never calls an LLM to classify complexity.
    Protects benchmark mode from non-frozen optimizations.
    """

    @staticmethod
    def classify_task(
        task_description: str,
        tool_name: Optional[str] = None,
        is_repair: bool = False,
        retry_count: int = 0
    ) -> TaskComplexity:
        """
        Deterministically classify a task into SIMPLE, STANDARD, or COMPLEX
        using concrete task signals rather than tool counts or word counts.
        """
        text = task_description.lower()

        # Repair with multiple retries escalates to COMPLEX
        if is_repair and retry_count >= 2:
            return TaskComplexity.COMPLEX

        # Complex engineering indicators
        if any(kw in text for kw in COMPLEX_INDICATORS):
            return TaskComplexity.COMPLEX

        # Read-only or basic filesystem operations are SIMPLE
        if tool_name in ("read_file", "list_directory", "file_exists", "search_files"):
            return TaskComplexity.SIMPLE

        # Simple file writes or standard web starter files are SIMPLE
        if tool_name in ("write_file", "create_file"):
            if any(kw in text for kw in COMPLEX_INDICATORS):
                return TaskComplexity.COMPLEX
            if any(kw in text for kw in SIMPLE_INDICATORS):
                return TaskComplexity.SIMPLE

        # General text checks: only classify as SIMPLE if explicit simple markers match
        if any(kw in text for kw in SIMPLE_INDICATORS) and not any(kw in text for kw in ("helper function", "algorithm", "implement", "logic", "route", "test")):
            return TaskComplexity.SIMPLE

        # Standard implementations (tests, single function logic, standard fixes)
        return TaskComplexity.STANDARD

    @staticmethod
    def resolve(
        task_description: str,
        tool_name: Optional[str] = None,
        is_repair: bool = False,
        retry_count: int = 0,
        model: str = TIER1_MODEL,
        execution_mode: str = "production",
        override_complexity: Optional[TaskComplexity] = None
    ) -> ResolvedReasoningPolicy:
        """
        Resolve exact thinking flag, num_predict, and timeout for a model generation call.
        """
        complexity = override_complexity or ReasoningPolicy.classify_task(
            task_description=task_description,
            tool_name=tool_name,
            is_repair=is_repair,
            retry_count=retry_count
        )

        # ── Benchmark Mode: Strictly Frozen Legacy Policy ───────────────────
        if execution_mode == "benchmark":
            logger.debug("ReasoningPolicy: resolving under frozen BENCHMARK mode")
            return ResolvedReasoningPolicy(
                think=None,             # Let runtime/model default apply
                num_predict=1536,       # Frozen L1 benchmark budget
                timeout_seconds=75,
                temperature=0.10,
                complexity=complexity,
                execution_mode="benchmark"
            )

        # ── Non-Benchmark Optimized Modes (production, demo, performance) ───
        is_deepseek_r1 = "deepseek-r1" in model.lower()

        if is_repair:
            # Targeted bounded repair policy
            return ResolvedReasoningPolicy(
                think=True if is_deepseek_r1 else None,
                num_predict=1024,
                timeout_seconds=60,
                temperature=0.05,
                complexity=TaskComplexity.STANDARD,
                execution_mode=execution_mode
            )

        if complexity == TaskComplexity.SIMPLE:
            # SIMPLE: think=False, small bounded num_predict, fast timeout
            return ResolvedReasoningPolicy(
                think=False if is_deepseek_r1 else None,
                num_predict=512,
                timeout_seconds=30,
                temperature=0.10,
                complexity=TaskComplexity.SIMPLE,
                execution_mode=execution_mode
            )

        elif complexity == TaskComplexity.STANDARD:
            # STANDARD: think=False for direct code/tool writes, bounded 1024 budget
            return ResolvedReasoningPolicy(
                think=False if is_deepseek_r1 else None,
                num_predict=1024,
                timeout_seconds=60,
                temperature=0.10,
                complexity=TaskComplexity.STANDARD,
                execution_mode=execution_mode
            )

        else:
            # COMPLEX: think=True preserved, with 360s timeout and 2560 budget
            return ResolvedReasoningPolicy(
                think=True if is_deepseek_r1 else None,
                num_predict=2560,
                timeout_seconds=360,
                temperature=0.15,
                complexity=TaskComplexity.COMPLEX,
                execution_mode=execution_mode
            )
