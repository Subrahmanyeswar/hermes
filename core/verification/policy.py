# core/verification/policy.py
"""
Verification Risk Assessment & Low-Risk Bypass Policy for HERMES 2.x.

Core Invariants:
1. LOW-RISK BYPASS: Routine changes (CSS, docs, simple renames, passing localized tests) that PASS deterministic verification strictly bypass T2 Critic and T3 Judge.
2. HIGH-RISK PROTECTION: Security-sensitive files, core runtime changes, concurrency/async engines, destructive operations, and recurring failures always trigger escalation.
3. CONTEXT MINIMIZATION: Bypassing escalation on low-risk changes preserves token budgets and eliminates evaluation latency.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


class VerificationRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class VerificationPolicy:
    """
    Evaluates risk profiles of changes and determines whether escalation is warranted.
    """

    LOW_RISK_EXTENSIONS: Set[str] = {
        ".md", ".markdown", ".txt", ".rst", ".css", ".scss", ".sass", ".less",
        ".svg", ".png", ".jpg", ".jpeg", ".ico", ".html",
    }

    HIGH_RISK_PATTERNS: Set[str] = {
        "auth", "token", "secret", "crypto", "security", "permission",
        "runtime_state", "event_bus", "loop.py", "subagent", "worktree",
        "migration", "evaluator", "judge", "critic",
    }

    @classmethod
    def assess_risk(
        cls,
        files_modified: Optional[List[str]] = None,
        lines_changed: int = 0,
        commands_run: Optional[List[str]] = None,
        is_security_sensitive: bool = False,
        is_core_runtime: bool = False,
        failure_count: int = 0,
    ) -> VerificationRiskLevel:
        """
        Deterministically assess the risk level of an action or batch of changes.
        """
        # Critical conditions
        if failure_count >= 3:
            return VerificationRiskLevel.CRITICAL
        if is_security_sensitive:
            return VerificationRiskLevel.CRITICAL

        # High risk conditions
        if is_core_runtime:
            return VerificationRiskLevel.HIGH
        if failure_count >= 2:
            return VerificationRiskLevel.HIGH

        files = files_modified or []
        for f in files:
            f_lower = f.lower()
            if any(pat in f_lower for pat in cls.HIGH_RISK_PATTERNS):
                return VerificationRiskLevel.HIGH

        if commands_run:
            for cmd in commands_run:
                cmd_lower = cmd.lower()
                if any(bad in cmd_lower for bad in ["rm -rf", "git reset --hard", "drop ", "truncate "]):
                    return VerificationRiskLevel.CRITICAL

        # Check for Low Risk
        if files:
            all_low_ext = all(Path(f).suffix.lower() in cls.LOW_RISK_EXTENSIONS for f in files)
            if all_low_ext and lines_changed < 200:
                return VerificationRiskLevel.LOW

        if len(files) <= 1 and lines_changed <= 30 and failure_count == 0:
            return VerificationRiskLevel.LOW

        return VerificationRiskLevel.MEDIUM

    @classmethod
    def should_bypass_t2_t3(
        cls,
        risk_level: VerificationRiskLevel,
        deterministic_pass: bool,
    ) -> bool:
        """
        Invariant: If an operation is LOW risk and all deterministic checks passed,
        T2 and T3 evaluation MUST be bypassed completely.
        """
        if deterministic_pass and risk_level == VerificationRiskLevel.LOW:
            return True
        return False
