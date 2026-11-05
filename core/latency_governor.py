# core/latency_governor.py
"""
HERMES 2.x — Latency Budget Governor (Phase 2)
Provides reusable, configurable request-budget allocation, task-purpose detection,
first-token deadlines, and bounded execution budgets.

Initial operational targets:
- Short classification / planning: 8-12s (target 10s)
- Small coding operation: 15-20s (target 18s)
- Large generation segment: 20-25s (target 22s)
- Streaming first-token target: 7-8s (target 7.5s)
- Upper bound: Silent waiting above 25.0s is NOT permitted.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from loguru import logger


class RequestPurpose(str, Enum):
    CLASSIFICATION_PLANNING = "classification_planning"
    SMALL_CODING = "small_coding"
    LARGE_GENERATION = "large_generation"
    GENERAL = "general"


@dataclass
class LatencyBudget:
    """Configured execution and timeout budget for a model request."""
    purpose: RequestPurpose
    first_token_timeout: Optional[float]   # None for non-streaming transports
    stream_idle_timeout: float            # Watchdog timeout between streamed chunks
    total_timeout: float                  # Hard upper deadline for the request attempt
    max_tokens: int                       # Safe output token ceiling
    temperature: float                    # Sampling temperature
    is_streaming: bool                    # Whether streaming SSE is requested

    def to_dict(self) -> Dict[str, Any]:
        return {
            "purpose": self.purpose.value,
            "first_token_timeout": self.first_token_timeout,
            "stream_idle_timeout": self.stream_idle_timeout,
            "total_timeout": self.total_timeout,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "is_streaming": self.is_streaming,
        }


# Keywords for heuristic purpose detection
PLANNING_KEYWORDS = frozenset({
    "plan", "planning", "classify", "intent", "decompose", "work package",
    "review", "audit", "verify", "outline", "inspect", "assess", "decision"
})

LARGE_GEN_KEYWORDS = frozenset({
    "build full", "create website", "implement entire", "all sections",
    "complete application", "destination cards", "travel packages",
    "comprehensive", "full-width", "interactive components"
})

SMALL_EDIT_KEYWORDS = frozenset({
    "edit", "patch", "fix", "update class", "add function", "small change",
    "modify selector", "adjust css", "tweak", "align", "refactor single"
})


class LatencyBudgetGovernor:
    """
    Authoritative governor for model request deadlines and output budgets.
    Caps any single attempt to <= 25.0s and guarantees first-token deadlines for streaming.
    """

    # Configurable operational limits (can be tuned via env var)
    MAX_ATTEMPT_DEADLINE_CEILING: float = float(os.getenv("MODEL_MAX_ATTEMPT_DEADLINE_CEILING", os.getenv("HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS", "25.0")))
    STREAMING_FIRST_TOKEN_TARGET: float = float(os.getenv("MODEL_STREAMING_FIRST_TOKEN_TARGET", "7.5"))
    STREAM_IDLE_WATCHDOG_SECONDS: float = float(os.getenv("MODEL_STREAM_IDLE_WATCHDOG_SECONDS", "10.0"))

    def __init__(self) -> None:
        self.max_attempt_ceiling = self.MAX_ATTEMPT_DEADLINE_CEILING
        self.first_token_target = self.STREAMING_FIRST_TOKEN_TARGET
        self.idle_watchdog = self.STREAM_IDLE_WATCHDOG_SECONDS

    def classify_purpose(
        self,
        prompt: str = "",
        system: str = "",
        tools: Optional[List[Any]] = None,
        context_hint: Optional[str] = None,
    ) -> RequestPurpose:
        """Classify the intended operation purpose to select the optimal latency budget."""
        if context_hint:
            hint_lower = context_hint.lower()
            if "plan" in hint_lower or "classif" in hint_lower or "intent" in hint_lower:
                return RequestPurpose.CLASSIFICATION_PLANNING
            if "small" in hint_lower or "edit" in hint_lower or "patch" in hint_lower:
                return RequestPurpose.SMALL_CODING
            if "large" in hint_lower or "gen" in hint_lower or "full" in hint_lower:
                return RequestPurpose.LARGE_GENERATION

        combined = f"{system} {prompt}".lower()

        # Check for large generation signals
        if any(kw in combined for kw in LARGE_GEN_KEYWORDS):
            return RequestPurpose.LARGE_GENERATION

        # Check for planning / classification signals
        if any(kw in combined for kw in PLANNING_KEYWORDS) and len(prompt) < 1500:
            return RequestPurpose.CLASSIFICATION_PLANNING

        # Check for small coding signals
        if any(kw in combined for kw in SMALL_EDIT_KEYWORDS) or (tools and len(tools) <= 3 and len(prompt) < 2000):
            return RequestPurpose.SMALL_CODING

        return RequestPurpose.GENERAL

    def get_budget(
        self,
        purpose: Union[RequestPurpose, str] = RequestPurpose.GENERAL,
        is_streaming: bool = True,
        remaining_wall_time: Optional[float] = None,
        custom_timeout_cap: Optional[float] = None,
    ) -> LatencyBudget:
        """
        Allocate a bounded LatencyBudget tailored to the task purpose and transport mode.
        Guarantees that silent waiting above 25.0s is never permitted.
        """
        if isinstance(purpose, str):
            try:
                purpose = RequestPurpose(purpose.lower())
            except ValueError:
                purpose = RequestPurpose.GENERAL

        # Base budgets according to operational specification
        if purpose == RequestPurpose.CLASSIFICATION_PLANNING:
            total_target = 12.0
            max_tokens = 1024
            temp = 0.1
            first_token_to = min(self.first_token_target, 7.0) if is_streaming else None
        elif purpose == RequestPurpose.SMALL_CODING:
            total_target = 20.0
            max_tokens = 2048
            temp = 0.2
            first_token_to = self.first_token_target if is_streaming else None
        elif purpose == RequestPurpose.LARGE_GENERATION:
            total_target = min(25.0, self.max_attempt_ceiling)
            max_tokens = 4096
            temp = 0.2
            first_token_to = min(self.first_token_target + 0.5, 8.0) if is_streaming else None
        else:  # GENERAL
            total_target = 22.0
            max_tokens = 3072
            temp = 0.2
            first_token_to = self.first_token_target if is_streaming else None

        # Absolute upper bound: silent waiting above 25s not permitted
        effective_total = min(total_target, self.max_attempt_ceiling)
        if custom_timeout_cap is not None and custom_timeout_cap > 0:
            effective_total = min(effective_total, custom_timeout_cap)

        # Clamp if remaining wall time is tight
        if remaining_wall_time is not None and remaining_wall_time > 0:
            effective_total = min(effective_total, max(5.0, remaining_wall_time - 1.0))

        # First token timeout must never exceed total timeout
        if first_token_to is not None:
            first_token_to = min(first_token_to, effective_total - 1.0)
            if first_token_to < 1.0:
                first_token_to = 1.0

        return LatencyBudget(
            purpose=purpose,
            first_token_timeout=first_token_to,
            stream_idle_timeout=self.idle_watchdog,
            total_timeout=effective_total,
            max_tokens=max_tokens,
            temperature=temp,
            is_streaming=is_streaming,
        )


# Singleton instance
latency_governor = LatencyBudgetGovernor()
