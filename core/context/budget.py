# core/context/budget.py
"""
Context Budgeting, Token Accounting, and Headroom Enforcement for HERMES 2.x.
Ensures context utilization stays strictly bounded within model-specific capacities
with non-negotiable safety and output reserves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.context.models import ContextItem, ContextPriority, ContextSectionType


class BudgetHealthState(str, Enum):
    """
    Explicit context pressure states.
    Configurable percentage thresholds of usable capacity.
    """
    HEALTHY = "HEALTHY"                     # < 60%
    PRESSURE = "PRESSURE"                   # 60% - 75%
    MICROCOMPACT_REQUIRED = "MICROCOMPACT_REQUIRED" # 75% - 85%
    COMPACT_REQUIRED = "COMPACT_REQUIRED"   # 85% - 92%
    EMERGENCY = "EMERGENCY"                 # > 92%


@dataclass
class ContextCapacity:
    """Model-agnostic context capacity parameters."""
    context_window_tokens: int = 128_000
    output_reserve_tokens: int = 4_096
    safety_reserve_tokens: int = 4_096
    provider: str = "nvidia_nim"
    model: str = "z-ai/glm-5.3-flash"
    is_discovered: bool = False  # False if fallback assumption, True if confirmed via provider API

    @property
    def total_reserve_tokens(self) -> int:
        return self.output_reserve_tokens + self.safety_reserve_tokens

    @property
    def usable_capacity_tokens(self) -> int:
        return max(0, self.context_window_tokens - self.total_reserve_tokens)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_window_tokens": self.context_window_tokens,
            "output_reserve_tokens": self.output_reserve_tokens,
            "safety_reserve_tokens": self.safety_reserve_tokens,
            "total_reserve_tokens": self.total_reserve_tokens,
            "usable_capacity_tokens": self.usable_capacity_tokens,
            "provider": self.provider,
            "model": self.model,
            "is_discovered": self.is_discovered,
        }


class TokenEstimator:
    """Token estimation abstraction with explicit heuristic vs exact flagging."""

    def __init__(self, custom_tokenizer: Optional[Callable[[str], int]] = None) -> None:
        self._custom_tokenizer = custom_tokenizer
        self.is_exact: bool = custom_tokenizer is not None

    def estimate(self, text: str) -> int:
        """Estimate token count for a string."""
        if not text:
            return 0
        if self._custom_tokenizer is not None:
            try:
                return self._custom_tokenizer(text)
            except Exception:
                pass
        # Standard character-based heuristic: ~4 characters per token
        return max(1, len(text) // 4)


@dataclass
class ContextBudgetReport:
    """Comprehensive diagnostic cost breakdown of context budget usage."""
    total_capacity: int
    usable_capacity: int
    used_tokens: int
    available_tokens: int
    reserve_tokens: int
    utilization: float
    health_state: BudgetHealthState
    section_breakdown: Dict[str, int]
    is_estimated: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_capacity": self.total_capacity,
            "usable_capacity": self.usable_capacity,
            "used_tokens": self.used_tokens,
            "available_tokens": self.available_tokens,
            "reserve_tokens": self.reserve_tokens,
            "utilization": round(self.utilization, 4),
            "health_state": self.health_state.value,
            "section_breakdown": self.section_breakdown,
            "is_estimated": self.is_estimated,
        }

    def to_formatted_string(self) -> str:
        """Human-readable diagnostic table matching prompt specifications."""
        lines = [
            f"Context Budget Report ({'ESTIMATED' if self.is_estimated else 'EXACT'}):",
            f"Total Window: {self.used_tokens:,} / {self.total_capacity:,} tokens ({self.utilization * 100:.1f}%)",
            f"Usable Limit: {self.usable_capacity:,} | Reserve: {self.reserve_tokens:,} | State: {self.health_state.value}",
            "--- Section Breakdown ---",
        ]
        for sec, count in sorted(self.section_breakdown.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {sec:<22}: {count:>7,} tokens")
        lines.append(f"  {'RESERVE (Output+Safe)':<22}: {self.reserve_tokens:>7,} tokens")
        return "\n".join(lines)


class ContextBudgeter:
    """
    Enforces partitioned token budgets, non-negotiable safety headroom,
    and priority-based candidate retention.
    """

    def __init__(
        self,
        capacity: Optional[ContextCapacity] = None,
        estimator: Optional[TokenEstimator] = None,
        pressure_threshold: float = 0.60,
        microcompact_threshold: float = 0.75,
        compact_threshold: float = 0.85,
        emergency_threshold: float = 0.92,
    ) -> None:
        self.capacity = capacity or ContextCapacity()
        self.estimator = estimator or TokenEstimator()
        self.pressure_threshold = pressure_threshold
        self.microcompact_threshold = microcompact_threshold
        self.compact_threshold = compact_threshold
        self.emergency_threshold = emergency_threshold

    def calculate_health_state(self, used_tokens: int) -> BudgetHealthState:
        """Determine health state based on usable capacity utilization."""
        usable = self.capacity.usable_capacity_tokens
        if usable <= 0:
            return BudgetHealthState.EMERGENCY
        ratio = used_tokens / usable
        if ratio >= self.emergency_threshold:
            return BudgetHealthState.EMERGENCY
        if ratio >= self.compact_threshold:
            return BudgetHealthState.COMPACT_REQUIRED
        if ratio >= self.microcompact_threshold:
            return BudgetHealthState.MICROCOMPACT_REQUIRED
        if ratio >= self.pressure_threshold:
            return BudgetHealthState.PRESSURE
        return BudgetHealthState.HEALTHY

    def budget(
        self,
        candidates: List[ContextItem],
    ) -> Tuple[List[ContextItem], List[ContextItem], ContextBudgetReport]:
        """
        Evaluate candidates against usable token capacity.
        Retains MANDATORY and pinned items first, then fits high-scoring items.
        Returns: (included_items, dropped_items, budget_report)
        """
        usable = self.capacity.usable_capacity_tokens
        included: List[ContextItem] = []
        dropped: List[ContextItem] = []
        section_breakdown: Dict[str, int] = {sec.value: 0 for sec in ContextSectionType}

        # 1. First pass: Always include MANDATORY items
        current_used = 0
        non_mandatory: List[ContextItem] = []

        for item in candidates:
            # Re-estimate if needed
            if not item.token_estimate:
                item.token_estimate = self.estimator.estimate(item.content)

            if item.priority == ContextPriority.MANDATORY:
                included.append(item)
                current_used += item.token_estimate
                section_breakdown[item.section.value] = section_breakdown.get(item.section.value, 0) + item.token_estimate
            else:
                non_mandatory.append(item)

        # 2. Sort non-mandatory: pinned first, then by priority level, then by relevance_score descending
        priority_weights = {
            ContextPriority.IMPORTANT: 3,
            ContextPriority.OPTIONAL: 2,
            ContextPriority.DISCARDABLE: 1,
        }

        sorted_non_mandatory = sorted(
            non_mandatory,
            key=lambda x: (
                x.pinned,
                priority_weights.get(x.priority, 1),
                x.relevance_score,
                -x.token_estimate,  # Prefer smaller items when scores are tied
            ),
            reverse=True,
        )

        # 3. Fit non-mandatory items into remaining usable budget
        for item in sorted_non_mandatory:
            if current_used + item.token_estimate <= usable:
                included.append(item)
                current_used += item.token_estimate
                section_breakdown[item.section.value] = section_breakdown.get(item.section.value, 0) + item.token_estimate
            else:
                dropped.append(item)

        # 4. Generate report
        utilization = current_used / usable if usable > 0 else 1.0
        health = self.calculate_health_state(current_used)
        available = max(0, usable - current_used)

        report = ContextBudgetReport(
            total_capacity=self.capacity.context_window_tokens,
            usable_capacity=usable,
            used_tokens=current_used,
            available_tokens=available,
            reserve_tokens=self.capacity.total_reserve_tokens,
            utilization=utilization,
            health_state=health,
            section_breakdown=section_breakdown,
            is_estimated=not self.estimator.is_exact,
        )

        return included, dropped, report
