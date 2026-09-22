# core/reasoning_budget.py
"""
Task-Aware Reasoning & Generation Budget Manager for HERMES vNext (Phase 6.3).
Allocates task-appropriate token and timeout budgets to Tier 1 (DeepSeek-R1 8B),
preventing unbounded reasoning on simple tasks while preserving full reasoning
depth for complex engineering.

Hierarchy:
  L0 — DIRECT / TRIVIAL  : 768 tokens, 45s timeout (Filesystem, read-only, git status)
  L1 — SIMPLE            : 1,536 tokens, 75s timeout (Simple file write, small helper)
  L2 — NORMAL            : 2,560 tokens, 120s timeout (Single-file coding, unit tests, bugfix)
  L3 — COMPLEX           : 4,096 tokens, 180s timeout (Multi-file, refactoring, algorithms)
  L4 — VERY COMPLEX      : 8,192 tokens, 240s timeout (Architecture, security, concurrency)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger

from config.model_config import (
    ADAPTIVE_T1_BUDGET_ENABLED,
    T1_BUDGET_L0,
    T1_BUDGET_L1,
    T1_BUDGET_L2,
    T1_BUDGET_L3,
    T1_BUDGET_L4,
    MODEL_TIMEOUT_SECONDS
)


class ComplexityLevel(Enum):
    L0_DIRECT = "L0_DIRECT"
    L1_SIMPLE = "L1_SIMPLE"
    L2_NORMAL = "L2_NORMAL"
    L3_COMPLEX = "L3_COMPLEX"
    L4_VERY_COMPLEX = "L4_VERY_COMPLEX"


@dataclass
class BudgetProfile:
    """Configuration profile for a Tier 1 model generation call."""
    level: ComplexityLevel
    num_predict: int
    timeout_seconds: int
    temperature: float
    description: str


# Complexity keywords
L0_KEYWORDS = frozenset({
    "list files", "list directory", "check if file exists", "file exists",
    "git status", "git log", "git diff", "view file", "show contents"
})

L3_KEYWORDS = frozenset({
    "refactor", "multi-file", "multiple files", "algorithm", "optimize",
    "cross-module", "integration", "debug across", "full pipeline",
    "website", "webpage", "super website", "anime", "animation", "animations", "aesthetic", "genz"
})

L4_KEYWORDS = frozenset({
    "architecture", "redesign", "security audit", "concurrency",
    "race condition", "cryptography", "distributed", "memory leak"
})


class ReasoningBudgetManager:
    """
    Evaluates task complexity and selects appropriate token/timeout budgets.
    Detects budget exhaustion and provides controlled single-step escalation.
    """

    def __init__(self, enabled: bool = ADAPTIVE_T1_BUDGET_ENABLED):
        self.enabled = enabled
        self._profiles: Dict[ComplexityLevel, BudgetProfile] = {
            ComplexityLevel.L0_DIRECT: BudgetProfile(
                level=ComplexityLevel.L0_DIRECT,
                num_predict=T1_BUDGET_L0,
                timeout_seconds=45,
                temperature=0.10,
                description="Direct read-only or trivial operation"
            ),
            ComplexityLevel.L1_SIMPLE: BudgetProfile(
                level=ComplexityLevel.L1_SIMPLE,
                num_predict=T1_BUDGET_L1,
                timeout_seconds=75,
                temperature=0.10,
                description="Simple single-file creation or transformation"
            ),
            ComplexityLevel.L2_NORMAL: BudgetProfile(
                level=ComplexityLevel.L2_NORMAL,
                num_predict=T1_BUDGET_L2,
                timeout_seconds=120,
                temperature=0.10,
                description="Standard single-file implementation, bugfix, or tests"
            ),
            ComplexityLevel.L3_COMPLEX: BudgetProfile(
                level=ComplexityLevel.L3_COMPLEX,
                num_predict=T1_BUDGET_L3,
                timeout_seconds=180,
                temperature=0.10,
                description="Multi-file implementation, refactoring, or algorithms"
            ),
            ComplexityLevel.L4_VERY_COMPLEX: BudgetProfile(
                level=ComplexityLevel.L4_VERY_COMPLEX,
                num_predict=T1_BUDGET_L4,
                timeout_seconds=240,
                temperature=0.15,
                description="System architecture, security, or complex concurrency"
            ),
        }
        logger.info("ReasoningBudgetManager initialized | adaptive_enabled={}", self.enabled)

    def classify_complexity(
        self,
        task_description: str,
        tools_needed: Optional[List[str]] = None,
        permission_level: str = "read_only",
        planner_complexity: float = 0.5
    ) -> ComplexityLevel:
        """
        Classify task into L0-L4 complexity level based on task wording,
        planner complexity score, tools needed, and permissions.
        """
        text = task_description.lower()
        tools = tools_needed or []

        # L0 check: Direct read-only / trivial filesystem operations / inspections
        is_read_only_tool = all(t in ("list_directory", "read_file", "file_exists", "git_status", "git_log", "search_files") for t in tools) if tools else False
        has_l0_keywords = any(kw in text for kw in L0_KEYWORDS) or any(kw in text for kw in ("inspect workspace", "check workspace", "list files"))
        if (is_read_only_tool or has_l0_keywords) and not any(kw in text for kw in ("security audit", "concurrency", "architecture", "refactor")):
            return ComplexityLevel.L0_DIRECT

        # L1 check: Simple file creation / small script / single file
        if any(kw in text for kw in ("create file", "write file", "simple file", "index.html", "styles.css", "app.js", "create simple", "write simple", "helper function")):
            if not any(kw in text for kw in L4_KEYWORDS) and not any(kw in text for kw in L3_KEYWORDS):
                return ComplexityLevel.L1_SIMPLE

        # L4 check: Architecture / security / concurrency (requires real L4 domain keywords)
        if any(kw in text for kw in L4_KEYWORDS):
            return ComplexityLevel.L4_VERY_COMPLEX

        # L3 check: Multi-file / refactor / algorithms (requires real L3 domain keywords or high complexity)
        if any(kw in text for kw in L3_KEYWORDS) or (planner_complexity >= 0.75 and len(tools) >= 4):
            return ComplexityLevel.L3_COMPLEX

        if planner_complexity <= 0.45:
            return ComplexityLevel.L1_SIMPLE

        # Default: L2 NORMAL
        return ComplexityLevel.L2_NORMAL

    def get_budget(self, level: ComplexityLevel) -> BudgetProfile:
        """Retrieve the budget profile for a given complexity level."""
        if not self.enabled:
            # Fallback: unconstrained fixed budget
            return BudgetProfile(
                level=ComplexityLevel.L4_VERY_COMPLEX,
                num_predict=8192,
                timeout_seconds=MODEL_TIMEOUT_SECONDS,
                temperature=0.10,
                description="Legacy unconstrained budget"
            )
        return self._profiles.get(level, self._profiles[ComplexityLevel.L2_NORMAL])

    def check_truncation(
        self,
        raw_text: str,
        output_tokens: int,
        budget: BudgetProfile
    ) -> bool:
        """
        Detect whether model output was truncated due to budget exhaustion.
        Signals: output_tokens close to num_predict, unclosed <think> tag,
        or unclosed JSON brackets.
        """
        if not self.enabled:
            return False

        # If model generated at or very close to limit
        hit_token_limit = output_tokens >= (budget.num_predict - 15)

        # Incomplete structure signals
        has_unclosed_think = ("<think>" in raw_text) and ("</think>" not in raw_text)
        has_unclosed_json = raw_text.count("{") > raw_text.count("}")

        if hit_token_limit and (has_unclosed_think or has_unclosed_json):
            logger.warning(
                "ReasoningBudgetManager: output truncation detected! (tokens={}/{}, unclosed_think={}, unclosed_json={})",
                output_tokens, budget.num_predict, has_unclosed_think, has_unclosed_json
            )
            return True

        return False

    def escalate_budget(self, current_level: ComplexityLevel) -> ComplexityLevel:
        """Escalate complexity level by +1 tier on truncation or retry."""
        escalation_map = {
            ComplexityLevel.L0_DIRECT: ComplexityLevel.L1_SIMPLE,
            ComplexityLevel.L1_SIMPLE: ComplexityLevel.L2_NORMAL,
            ComplexityLevel.L2_NORMAL: ComplexityLevel.L3_COMPLEX,
            ComplexityLevel.L3_COMPLEX: ComplexityLevel.L4_VERY_COMPLEX,
            ComplexityLevel.L4_VERY_COMPLEX: ComplexityLevel.L4_VERY_COMPLEX,
        }
        next_level = escalation_map.get(current_level, ComplexityLevel.L4_VERY_COMPLEX)
        logger.info("ReasoningBudgetManager: escalated budget {} -> {}", current_level.value, next_level.value)
        return next_level
