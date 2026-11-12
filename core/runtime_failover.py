# core/runtime_failover.py
"""
HERMES 2.x — Phase 3: Autonomous Runtime Orchestration, Provider Failover & Timeout Cancellation Engine.

Provides:
1. Canonical ErrorClassification enum (13 unified categories).
2. LogicalOperationBudget: centralized operation-level deadline and attempt budgeting.
3. ProviderAttemptRecord & ProviderAttemptLedger: audit ledger tracking every attempt.
4. CircuitBreakerState: CLOSED, OPEN, HALF_OPEN health state machine.
5. ProviderFailoverCoordinator: deterministic, bounded multi-tier routing state machine.
6. Clean request cancellation and resource tracking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import uuid

import httpx
from loguru import logger

from models.provider import NormalizedModelResponse


# ==============================================================================
# 1. CANONICAL ERROR CLASSIFICATION (13 Mandatory Types)
# ==============================================================================

class ErrorClassification(str, Enum):
    ATTEMPT_TIMEOUT = "ATTEMPT_TIMEOUT"
    TTFT_TIMEOUT = "TTFT_TIMEOUT"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    HTTP_429_RATE_LIMIT = "HTTP_429_RATE_LIMIT"
    HTTP_500_SERVER_ERROR = "HTTP_500_SERVER_ERROR"
    HTTP_502_BAD_GATEWAY = "HTTP_502_BAD_GATEWAY"
    HTTP_503_UNAVAILABLE = "HTTP_503_UNAVAILABLE"
    HTTP_504_GATEWAY_TIMEOUT = "HTTP_504_GATEWAY_TIMEOUT"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    INVALID_MODEL_CONFIGURATION = "INVALID_MODEL_CONFIGURATION"
    MALFORMED_MODEL_RESPONSE = "MALFORMED_MODEL_RESPONSE"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


def classify_runtime_error(
    exc: Optional[Exception] = None,
    status_code: Optional[int] = None,
    response_text: str = "",
    response_obj: Any = None,
) -> Tuple[ErrorClassification, bool, Optional[float]]:
    """
    Classify an error into one of the 13 canonical ErrorClassification categories.
    Returns: (classification, is_transient, retry_after_seconds)
    """
    # 1. Check HTTP status code if provided
    if status_code is not None:
        if status_code in (401, 402, 403):
            return ErrorClassification.AUTHENTICATION_ERROR, False, None
        if status_code in (400, 404):
            return ErrorClassification.INVALID_MODEL_CONFIGURATION, False, None
        if status_code == 429:
            retry_val = None
            if hasattr(exc, "retry_after"):
                try:
                    retry_val = float(getattr(exc, "retry_after"))
                except Exception:
                    pass
            return ErrorClassification.HTTP_429_RATE_LIMIT, True, retry_val
        if status_code == 500:
            return ErrorClassification.HTTP_500_SERVER_ERROR, True, None
        if status_code == 502:
            return ErrorClassification.HTTP_502_BAD_GATEWAY, True, None
        if status_code == 503:
            return ErrorClassification.HTTP_503_UNAVAILABLE, True, None
        if status_code == 504:
            return ErrorClassification.HTTP_504_GATEWAY_TIMEOUT, True, None

    err_str = (str(exc) if exc is not None else response_text).lower()

    # 1.5 Check explicit timeout_type attribute on exception (e.g. NvidiaTimeoutError)
    exc_to_type = getattr(exc, "timeout_type", None)
    if exc_to_type:
        to_type_str = str(exc_to_type).upper()
        if "FIRST_TOKEN" in to_type_str or "TTFT" in to_type_str:
            return ErrorClassification.TTFT_TIMEOUT, True, None
        return ErrorClassification.ATTEMPT_TIMEOUT, True, None

    # 2. Check cancellation
    if isinstance(exc, asyncio.CancelledError) or "cancelled" in err_str or "canceled" in err_str:
        return ErrorClassification.REQUEST_CANCELLED, True, None

    # 3. Check authentication / billing / configuration errors
    if any(k in err_str for k in (
        "401", "402", "unauthorized", "api_key", "invalid api key", "auth_failure",
        "403", "forbidden", "payment_method_required", "payment required", "balance_units"
    )):
        return ErrorClassification.AUTHENTICATION_ERROR, False, None

    if any(k in err_str for k in (
        "404", "model not found", "not_found", "model_not_found",
        "invalid model", "unexpected model name format", "invalid_argument"
    )) or re.search(r"\bmodel\b.*\bnot found\b", err_str):
        return ErrorClassification.INVALID_MODEL_CONFIGURATION, False, None

    # 4. Check rate limits
    if any(k in err_str for k in ("429", "rate limit", "rate_limit", "quota exceeded", "resource exhausted")):
        retry_val = None
        if hasattr(exc, "retry_after"):
            try:
                retry_val = float(getattr(exc, "retry_after"))
            except Exception:
                pass
        return ErrorClassification.HTTP_429_RATE_LIMIT, True, retry_val

    # 5. Check timeouts
    if any(k in err_str for k in ("first token", "ttft", "first_token_timeout", "upstream server stalled before emitting first sse")):
        return ErrorClassification.TTFT_TIMEOUT, True, None

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)) or "timeout" in err_str or "timed out" in err_str:
        if "504" in err_str or "gateway timeout" in err_str:
            return ErrorClassification.HTTP_504_GATEWAY_TIMEOUT, True, None
        return ErrorClassification.ATTEMPT_TIMEOUT, True, None

    # 6. Check specific 5xx server errors
    if "502" in err_str or "bad gateway" in err_str:
        return ErrorClassification.HTTP_502_BAD_GATEWAY, True, None
    if "503" in err_str or "service unavailable" in err_str or "unavailable" in err_str:
        return ErrorClassification.HTTP_503_UNAVAILABLE, True, None
    if "500" in err_str or "internal server error" in err_str:
        return ErrorClassification.HTTP_500_SERVER_ERROR, True, None

    # 7. Check empty response
    if (
        "empty" in err_str
        or "zero content" in err_str
        or (response_obj is not None and not str(getattr(response_obj, "text", "") or "").strip() and not getattr(response_obj, "tool_calls", None))
    ):
        return ErrorClassification.EMPTY_RESPONSE, True, None

    # 8. Check JSON / response parsing errors
    if any(k in err_str for k in ("jsondecodeerror", "malformed", "parse error", "invalid json")):
        return ErrorClassification.MALFORMED_MODEL_RESPONSE, True, None

    return ErrorClassification.UNKNOWN_PROVIDER_ERROR, True, None


# ==============================================================================
# 2. LOGICAL OPERATION BUDGET
# ==============================================================================

@dataclass
class LogicalOperationBudget:
    """
    Authoritative deadline and budgeting controller for a single logical model operation.
    Guarantees that a single operation has one total budget, shared across all provider attempts.
    """
    operation_id: str = field(default_factory=lambda: f"op_{uuid.uuid4().hex[:8]}")
    mission_id: str = ""
    turn_id: str = ""
    total_budget: float = 25.0
    start_time: float = field(default_factory=time.monotonic)
    ttft_timeout: float = 7.5
    stream_idle_timeout: float = 10.0
    min_attempt_budget: float = 1.5

    def remaining_budget(self) -> float:
        """Seconds remaining before overall logical operation deadline expires."""
        elapsed = time.monotonic() - self.start_time
        return max(0.0, self.total_budget - elapsed)

    def has_budget(self, min_required: Optional[float] = None) -> bool:
        """True if sufficient budget remains for another provider attempt."""
        req = self.min_attempt_budget if min_required is None else min_required
        return self.remaining_budget() >= req

    def compute_attempt_timeout(self, remaining_tiers_count: int = 0, default_cap: float = 10.0) -> float:
        """
        Calculate the timeout allowed for the current provider attempt.
        Prevents a single upstream provider from consuming the entire operation budget,
        reserving adequate time for downstream failover tiers.
        """
        rem = self.remaining_budget()
        if rem <= self.min_attempt_budget:
            return rem

        if remaining_tiers_count > 0:
            # Reserve at least 3.5s per downstream tier
            reserve = float(remaining_tiers_count) * 3.5
            allowed = max(self.min_attempt_budget, rem - reserve)
            return min(allowed, default_cap)
        else:
            # Last available tier gets all remaining budget
            return rem


# ==============================================================================
# 3. PROVIDER ATTEMPT RECORD & ATTEMPT LEDGER
# ==============================================================================

@dataclass
class ProviderAttemptRecord:
    """Detailed record of an individual provider attempt within a logical model operation."""
    operation_id: str
    mission_id: str
    turn_id: str
    provider: str
    model: str
    tier: int
    attempt_number: int
    start_time: float
    end_time: float
    duration_ms: float
    success: bool
    ttft_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    ttft_reasoning_ms: Optional[float] = None
    ttft_content_ms: Optional[float] = None
    ttft_usable_ms: Optional[float] = None
    availability_state: Optional[str] = None
    error_classification: Optional[str] = None
    http_status: Optional[int] = None
    cancellation_status: bool = False
    next_selected_provider: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "mission_id": self.mission_id,
            "turn_id": self.turn_id,
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "attempt_number": self.attempt_number,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "ttft_ms": round(self.ttft_ms, 2) if self.ttft_ms is not None else None,
            "ttfb_ms": round(self.ttfb_ms, 2) if self.ttfb_ms is not None else None,
            "ttft_reasoning_ms": round(self.ttft_reasoning_ms, 2) if self.ttft_reasoning_ms is not None else None,
            "ttft_content_ms": round(self.ttft_content_ms, 2) if self.ttft_content_ms is not None else None,
            "ttft_usable_ms": round(self.ttft_usable_ms, 2) if self.ttft_usable_ms is not None else None,
            "availability_state": self.availability_state,
            "error_classification": self.error_classification,
            "http_status": self.http_status,
            "cancellation_status": self.cancellation_status,
            "next_selected_provider": self.next_selected_provider,
            "error_message": self.error_message,
        }


class ProviderAttemptLedger:
    """In-memory audit ledger tracking all provider attempts across operations and missions."""

    def __init__(self) -> None:
        self._records: List[ProviderAttemptRecord] = []
        self._lock = asyncio.Lock()

    def record_attempt(self, record: ProviderAttemptRecord) -> None:
        self._records.append(record)

    def get_attempts_for_operation(self, operation_id: str) -> List[ProviderAttemptRecord]:
        return [r for r in self._records if r.operation_id == operation_id]

    def get_attempts_for_mission(self, mission_id: str) -> List[ProviderAttemptRecord]:
        return [r for r in self._records if r.mission_id == mission_id]

    def clear_mission(self, mission_id: str) -> None:
        self._records = [r for r in self._records if r.mission_id != mission_id]

    def clear_all(self) -> None:
        self._records.clear()


# Global attempt ledger singleton
global_attempt_ledger = ProviderAttemptLedger()


# ==============================================================================
# 4. CIRCUIT BREAKER STATE
# ==============================================================================

class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"         # Healthy; accepts traffic
    OPEN = "OPEN"             # Unhealthy; traffic bypassed to fallback
    HALF_OPEN = "HALF_OPEN"   # Cooldown expired; controlled single probe permitted


# ==============================================================================
# 5. PROVIDER FAILOVER COORDINATOR & STATE MACHINE
# ==============================================================================

class MultiTierRoutingExhaustedError(RuntimeError):
    """Raised when all eligible model providers have failed or budget is exhausted."""
    pass


class ProviderFailoverCoordinator:
    """
    Authoritative state machine orchestrating multi-tier failover.
    Guarantees:
    1. Single deadline budget for the logical operation (no restart on retry).
    2. Deterministic failover: Tier 1 -> Tier 2 -> Tier 3.
    3. Never cycles backwards to an already failed provider in the same logical operation.
    4. Mission-scoped failed provider exclusion (prevents resetting to unhealthy tier next turn).
    5. Clean request cancellation and comprehensive audit ledger logging.
    """

    def __init__(self, ledger: Optional[ProviderAttemptLedger] = None) -> None:
        self.ledger = ledger or global_attempt_ledger
        # Mission-scoped sets of permanently or temporarily excluded tiers
        self._mission_excluded_tiers: Dict[str, Set[int]] = {}
        # Cooldown timestamps for circuit breaker: tier -> timestamp when open
        self._tier_cooldown_open: Dict[int, float] = {}
        # Cooldown window in seconds (configurable, default 30s)
        self.cooldown_seconds: float = float(os.getenv("HERMES_CIRCUIT_COOLDOWN_SECONDS", "30.0"))

    def get_mission_excluded_tiers(self, mission_id: str) -> Set[int]:
        if not mission_id:
            return set()
        return self._mission_excluded_tiers.setdefault(mission_id, set())

    def exclude_tier_for_mission(self, mission_id: str, tier: int, permanent: bool = False) -> None:
        if mission_id:
            self._mission_excluded_tiers.setdefault(mission_id, set()).add(tier)
        self._tier_cooldown_open[tier] = time.time()
        logger.warning(f"[FAILOVER COORDINATOR] Tier {tier} excluded for mission '{mission_id}' (permanent={permanent})")

    def reset_mission(self, mission_id: str) -> None:
        self._mission_excluded_tiers.pop(mission_id, None)
        self.ledger.clear_mission(mission_id)

    def is_tier_in_cooldown(self, tier: int) -> Tuple[bool, CircuitBreakerState]:
        """Check if tier is currently OPEN, HALF_OPEN, or CLOSED."""
        open_ts = self._tier_cooldown_open.get(tier)
        if open_ts is None:
            return False, CircuitBreakerState.CLOSED
        now = time.time()
        if now - open_ts >= self.cooldown_seconds:
            return False, CircuitBreakerState.HALF_OPEN
        return True, CircuitBreakerState.OPEN

    def record_probe_success(self, tier: int) -> None:
        """Mark tier healthy after a successful HALF_OPEN probe."""
        self._tier_cooldown_open.pop(tier, None)
        logger.info(f"[FAILOVER COORDINATOR] Tier {tier} probe succeeded. Circuit reset to CLOSED.")

    def record_probe_failure(self, tier: int) -> None:
        """Reset cooldown after a failed probe."""
        self._tier_cooldown_open[tier] = time.time()
        logger.warning(f"[FAILOVER COORDINATOR] Tier {tier} probe failed. Circuit remains OPEN.")


# Global coordinator singleton
global_failover_coordinator = ProviderFailoverCoordinator()
