# core/transport/retry_coordinator.py
"""
HERMES Phase 6: Bounded Retry and Explicit Fallback Coordinator.
Provides:
1. Monotonic elapsed-time deadline accounting across attempts and tiers.
2. Bounded backoff with jitter and Retry-After header enforcement.
3. Explicit Tier 1 -> Tier 2 -> Tier 3 ordered fallback policy.
4. Immediate abort on mission cancellation (Phase 4).
5. Observability of routing history, final responding model, and fallback rationale.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger
from config.model_config import (
    TIER1_MODEL,
    TIER1_PROVIDER,
    TIER2_MODEL,
    TIER2_PROVIDER,
    TIER3_MODEL,
    TIER3_PROVIDER,
)
from core.transport.circuit_breaker import circuit_breaker_registry
from core.transport.types import ErrorCategory, StructuredTransportError
from models.provider import NormalizedModelResponse


@dataclass
class RouteAttemptRecord:
    tier: int
    provider: str
    model: str
    attempt: int
    success: bool
    latency_ms: float = 0.0
    error_category: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class TransportExecutionResult:
    response: Optional[NormalizedModelResponse]
    final_tier: int
    final_provider: str
    final_model: str
    total_attempts: int
    total_latency_ms: float
    history: List[RouteAttemptRecord] = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    error: Optional[StructuredTransportError] = None


@dataclass
class FallbackPolicyConfig:
    enabled: bool = True
    max_fallback_depth: int = 3
    primary_max_retries: int = 2
    fallback_max_retries: int = 1
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 5.0
    total_request_deadline_seconds: float = 120.0


class RetryCoordinator:
    """
    Coordinates bounded retries and explicit tier fallback for one logical model request.
    """

    def __init__(
        self,
        config: Optional[FallbackPolicyConfig] = None,
        time_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], Any] = asyncio.sleep,
        circuit_breaker: Optional[CircuitBreakerRegistry] = None,
        routes: Optional[List[Tuple[int, str, str]]] = None,
    ) -> None:
        self.config = config or FallbackPolicyConfig()
        self._time = time_func
        self._sleep = sleep_func
        self.circuit_breaker = circuit_breaker or circuit_breaker_registry
        self.routes = routes or [
            (1, TIER1_PROVIDER, TIER1_MODEL),
            (2, TIER2_PROVIDER, TIER2_MODEL),
            (3, TIER3_PROVIDER, TIER3_MODEL),
        ]

    async def execute_with_resilience(
        self,
        invoker_fn: Callable[[int, str, str, int, float], Any],
        abort_event: Optional[asyncio.Event] = None,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> TransportExecutionResult:
        """
        Execute request across configured tiers (T1 -> T2 -> T3) with bounded retries.
        invoker_fn signature:
            async def invoker_fn(tier: int, provider: str, model: str, attempt: int, timeout_remaining: float) -> NormalizedModelResponse
        """
        start_mono = self._time()
        overall_deadline = start_mono + self.config.total_request_deadline_seconds

        routes = self.routes

        history: List[RouteAttemptRecord] = []
        fallback_used = False
        fallback_reason: Optional[str] = None
        last_error: Optional[StructuredTransportError] = None

        for route_idx, (tier, provider, model) in enumerate(routes):
            if route_idx >= self.config.max_fallback_depth:
                break

            if route_idx > 0:
                if not self.config.enabled:
                    logger.info("Fallback disabled by policy; stopping at primary tier.")
                    break
                fallback_used = True

            max_attempts = self.config.primary_max_retries if tier == 1 else self.config.fallback_max_retries

            for attempt in range(1, max_attempts + 1):
                now = self._time()
                timeout_remaining = overall_deadline - now
                if timeout_remaining <= 0.5:
                    err = StructuredTransportError(
                        category=ErrorCategory.OVERALL_DEADLINE_EXCEEDED,
                        message=f"Logical request overall deadline ({self.config.total_request_deadline_seconds}s) exceeded.",
                        provider=provider,
                        model=model,
                        retryable=False,
                        attempt=attempt,
                        mission_id=mission_id,
                        run_id=run_id,
                    )
                    return TransportExecutionResult(
                        response=None,
                        final_tier=tier,
                        final_provider=provider,
                        final_model=model,
                        total_attempts=len(history) + 1,
                        total_latency_ms=(now - start_mono) * 1000.0,
                        history=history,
                        fallback_used=fallback_used,
                        fallback_reason=fallback_reason,
                        error=err,
                    )

                # 1. Mission cancellation check
                if abort_event and abort_event.is_set():
                    err = StructuredTransportError(
                        category=ErrorCategory.CANCELLED_BY_STOP,
                        message="Request cancelled by mission abort signal.",
                        provider=provider,
                        model=model,
                        retryable=False,
                        attempt=attempt,
                        mission_id=mission_id,
                        run_id=run_id,
                    )
                    return TransportExecutionResult(
                        response=None,
                        final_tier=tier,
                        final_provider=provider,
                        final_model=model,
                        total_attempts=len(history),
                        total_latency_ms=(now - start_mono) * 1000.0,
                        history=history,
                        fallback_used=fallback_used,
                        fallback_reason=fallback_reason,
                        error=err,
                    )

                # 2. Circuit breaker check
                can_proceed, cb_err = await self.circuit_breaker.check_can_proceed(provider, model)
                if not can_proceed and cb_err is not None:
                    history.append(
                        RouteAttemptRecord(
                            tier=tier,
                            provider=provider,
                            model=model,
                            attempt=attempt,
                            success=False,
                            error_category=cb_err.category.value,
                            error_message=cb_err.message,
                        )
                    )
                    last_error = cb_err
                    if fallback_reason is None:
                        fallback_reason = cb_err.message
                    # Break out of retry loop for this tier to allow fallback
                    break

                # 3. Invoke provider attempt
                attempt_start = self._time()
                try:
                    res = await invoker_fn(tier, provider, model, attempt, timeout_remaining)
                    attempt_lat_ms = (self._time() - attempt_start) * 1000.0

                    if isinstance(res, NormalizedModelResponse) and res.success:
                        # Success! Record success with circuit breaker
                        await self.circuit_breaker.record_success(provider, model)
                        history.append(
                            RouteAttemptRecord(
                                tier=tier,
                                provider=provider,
                                model=model,
                                attempt=attempt,
                                success=True,
                                latency_ms=attempt_lat_ms,
                            )
                        )
                        res.provider = provider
                        res.model = model
                        return TransportExecutionResult(
                            response=res,
                            final_tier=tier,
                            final_provider=provider,
                            final_model=model,
                            total_attempts=len(history),
                            total_latency_ms=(self._time() - start_mono) * 1000.0,
                            history=history,
                            fallback_used=fallback_used,
                            fallback_reason=fallback_reason,
                            error=None,
                        )
                    else:
                        err_text = getattr(res, "error", "Provider returned unflagged failure")
                        struct_err = StructuredTransportError(
                            category=ErrorCategory.UNKNOWN_ERROR,
                            message=err_text,
                            provider=provider,
                            model=model,
                            retryable=True,
                            attempt=attempt,
                        )
                        raise struct_err

                except StructuredTransportError as te:
                    attempt_lat_ms = (self._time() - attempt_start) * 1000.0
                    await self.circuit_breaker.record_failure(provider, model, te)
                    history.append(
                        RouteAttemptRecord(
                            tier=tier,
                            provider=provider,
                            model=model,
                            attempt=attempt,
                            success=False,
                            latency_ms=attempt_lat_ms,
                            error_category=te.category.value,
                            error_message=te.sanitized_message,
                        )
                    )
                    last_error = te
                    if fallback_reason is None:
                        fallback_reason = te.sanitized_message

                    # If not retryable within tier, break attempt loop to allow fallback
                    if not te.retryable:
                        break

                    # Backoff before next attempt if more attempts remain
                    if attempt < max_attempts:
                        delay = self._calculate_backoff(attempt, te.retry_after)
                        if (self._time() + delay) > overall_deadline:
                            break
                        if abort_event and abort_event.is_set():
                            break
                        await self._sleep(delay)

                except Exception as unk_exc:
                    attempt_lat_ms = (self._time() - attempt_start) * 1000.0
                    struct_err = StructuredTransportError(
                        category=ErrorCategory.UNKNOWN_ERROR,
                        message=str(unk_exc),
                        provider=provider,
                        model=model,
                        retryable=True,
                        attempt=attempt,
                    )
                    await circuit_breaker_registry.record_failure(provider, model, struct_err)
                    history.append(
                        RouteAttemptRecord(
                            tier=tier,
                            provider=provider,
                            model=model,
                            attempt=attempt,
                            success=False,
                            latency_ms=attempt_lat_ms,
                            error_category=ErrorCategory.UNKNOWN_ERROR.value,
                            error_message=str(unk_exc),
                        )
                    )
                    last_error = struct_err
                    if fallback_reason is None:
                        fallback_reason = str(unk_exc)

                    if attempt < max_attempts:
                        delay = self._calculate_backoff(attempt)
                        await self._sleep(delay)

        # All eligible routes exhausted
        final_err = last_error or StructuredTransportError(
            category=ErrorCategory.UNKNOWN_ERROR,
            message="All configured model tiers and attempts exhausted.",
            provider=routes[-1][1],
            model=routes[-1][2],
            retryable=False,
            mission_id=mission_id,
            run_id=run_id,
        )

        return TransportExecutionResult(
            response=None,
            final_tier=routes[-1][0],
            final_provider=routes[-1][1],
            final_model=routes[-1][2],
            total_attempts=len(history),
            total_latency_ms=(self._time() - start_mono) * 1000.0,
            history=history,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            error=final_err,
        )

    def _calculate_backoff(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None and retry_after > 0:
            return min(float(retry_after), self.config.max_backoff_seconds)
        delay = self.config.base_backoff_seconds * (2 ** (attempt - 1))
        # Add up to 25% jitter
        jitter = random.uniform(0.0, delay * 0.25)
        return min(delay + jitter, self.config.max_backoff_seconds)
