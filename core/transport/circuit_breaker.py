# core/transport/circuit_breaker.py
"""
HERMES Phase 6: Circuit Breaker Implementation.
Three-state machine: CLOSED -> OPEN -> HALF_OPEN.
Per-route state tracking (provider + model).
Features:
- Concurrency-safe probe limitation.
- Separation of transient transport errors vs user cancellation vs configuration errors.
- Configuration failure suppression (auth/billing fails fast without storming).
- Explicit reset and testing hooks with injected monotonic clocks.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Set, Tuple

from loguru import logger
from core.transport.types import ErrorCategory, StructuredTransportError


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class RouteCircuitRecord:
    route_key: str
    provider: str
    model: str
    state: CircuitState = CircuitState.CLOSED
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    half_open_max_probes: int = 1
    
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    circuit_opened_time: Optional[float] = None
    half_open_probes_in_flight: int = 0

    # Permanent / config suppression state
    config_blocked: bool = False
    config_blocked_reason: Optional[str] = None


class CircuitBreakerRegistry:
    """
    Registry of circuit breakers keyed by route (e.g. 'nvidia_nim:z-ai/glm-5.3-flash').
    """

    def __init__(self, time_func: Callable[[], float] = time.monotonic) -> None:
        self._circuits: Dict[str, RouteCircuitRecord] = {}
        self._time_func = time_func
        self._lock = asyncio.Lock()
        self._listeners: Set[Callable[[str, CircuitState, Optional[CircuitState]], Any]] = set()

    def add_listener(self, cb: Callable[[str, CircuitState, Optional[CircuitState]], Any]) -> None:
        """Register a listener called when a circuit breaker state changes."""
        self._listeners.add(cb)

    def remove_listener(self, cb: Callable[[str, CircuitState, Optional[CircuitState]], Any]) -> None:
        """Unregister a route state listener."""
        self._listeners.discard(cb)

    def _notify_listeners(self, route_key: str, new_state: CircuitState, old_state: Optional[CircuitState]) -> None:
        for cb in list(self._listeners):
            try:
                res = cb(route_key, new_state, old_state)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as e:
                logger.warning(f"CircuitBreaker listener error: {e}")

    def notify_route_recovered(self, provider: str, model: str) -> None:
        """Explicitly notify listeners that a route has recovered (e.g. via successful health check)."""
        route_key = f"{provider}:{model}"
        rec = self._circuits.get(route_key)
        old_state = rec.state if rec else None
        if rec:
            rec.state = CircuitState.CLOSED
            rec.consecutive_failures = 0
            rec.circuit_opened_time = None
        self._notify_listeners(route_key, CircuitState.CLOSED, old_state)

    def get_record(
        self,
        provider: str,
        model: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> RouteCircuitRecord:
        route_key = f"{provider}:{model}"
        if route_key not in self._circuits:
            self._circuits[route_key] = RouteCircuitRecord(
                route_key=route_key,
                provider=provider,
                model=model,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )
        return self._circuits[route_key]

    async def check_can_proceed(
        self,
        provider: str,
        model: str,
    ) -> Tuple[bool, Optional[StructuredTransportError]]:
        """
        Check if request can proceed. If OPEN, checks if cooldown expired to enter HALF_OPEN.
        Returns (can_proceed, optional_rejection_error).
        """
        now = self._time_func()
        async with self._lock:
            rec = self.get_record(provider, model)

            # Check config suppression
            if rec.config_blocked:
                return False, StructuredTransportError(
                    category=ErrorCategory.AUTHENTICATION_FAILURE,
                    message=f"Provider route '{rec.route_key}' is configuration-blocked: {rec.config_blocked_reason}",
                    provider=provider,
                    model=model,
                    retryable=False,
                    fallback_eligible=True,
                )

            if rec.state == CircuitState.CLOSED:
                return True, None

            if rec.state == CircuitState.OPEN:
                # Check cooldown expiry
                opened_at = rec.circuit_opened_time or 0.0
                if (now - opened_at) >= rec.cooldown_seconds:
                    rec.state = CircuitState.HALF_OPEN
                    rec.half_open_probes_in_flight = 1
                    logger.info(f"CircuitBreaker [{rec.route_key}]: OPEN -> HALF_OPEN (probing)")
                    return True, None
                else:
                    remain = rec.cooldown_seconds - (now - opened_at)
                    return False, StructuredTransportError(
                        category=ErrorCategory.CIRCUIT_BREAKER_OPEN,
                        message=f"Circuit breaker OPEN for route '{rec.route_key}' (cooldown remaining: {remain:.1f}s)",
                        provider=provider,
                        model=model,
                        retryable=False,
                        fallback_eligible=True,
                        details={"cooldown_remaining": remain},
                    )

            if rec.state == CircuitState.HALF_OPEN:
                if rec.half_open_probes_in_flight < rec.half_open_max_probes:
                    rec.half_open_probes_in_flight += 1
                    return True, None
                return False, StructuredTransportError(
                    category=ErrorCategory.CIRCUIT_BREAKER_OPEN,
                    message=f"Circuit breaker HALF_OPEN probe in flight for '{rec.route_key}'",
                    provider=provider,
                    model=model,
                    retryable=False,
                    fallback_eligible=True,
                )

        return True, None

    async def record_success(self, provider: str, model: str) -> None:
        """Record successful response; resets failures and closes HALF_OPEN circuits."""
        now = self._time_func()
        async with self._lock:
            rec = self.get_record(provider, model)
            rec.last_success_time = now
            rec.consecutive_successes += 1
            rec.consecutive_failures = 0
            rec.half_open_probes_in_flight = 0

            if rec.state != CircuitState.CLOSED:
                old_state = rec.state
                logger.info(f"CircuitBreaker [{rec.route_key}]: {rec.state.value} -> CLOSED (healthy)")
                rec.state = CircuitState.CLOSED
                rec.circuit_opened_time = None
                self._notify_listeners(rec.route_key, CircuitState.CLOSED, old_state)

    async def record_failure(
        self,
        provider: str,
        model: str,
        error: StructuredTransportError,
    ) -> None:
        """
        Record failure.
        - Intentional cancellation (STOP) does NOT increment failure count.
        - Permanent auth/billing failures activate config suppression.
        - Reaching failure_threshold trips circuit to OPEN.
        """
        now = self._time_func()

        # Cancellation by Stop must never count as provider failure
        if error.category in (ErrorCategory.CANCELLED_BY_STOP, ErrorCategory.CANCELLED_BY_SHUTDOWN):
            return

        async with self._lock:
            rec = self.get_record(provider, model)
            rec.last_failure_time = now
            rec.half_open_probes_in_flight = 0

            # Check config suppression trigger
            if error.category in (
                ErrorCategory.AUTHENTICATION_FAILURE,
                ErrorCategory.AUTHORIZATION_RESTRICTION,
                ErrorCategory.BILLING_FAILURE,
            ):
                rec.config_blocked = True
                rec.config_blocked_reason = error.message
                rec.state = CircuitState.OPEN
                rec.circuit_opened_time = now
                logger.warning(f"CircuitBreaker [{rec.route_key}]: config-blocked due to {error.category.value}")
                return

            rec.consecutive_failures += 1
            rec.consecutive_successes = 0

            if rec.state == CircuitState.HALF_OPEN:
                # Failed probe reopens circuit immediately
                rec.state = CircuitState.OPEN
                rec.circuit_opened_time = now
                logger.warning(f"CircuitBreaker [{rec.route_key}]: probe failed, HALF_OPEN -> OPEN")
            elif rec.state == CircuitState.CLOSED:
                if rec.consecutive_failures >= rec.failure_threshold:
                    rec.state = CircuitState.OPEN
                    rec.circuit_opened_time = now
                    logger.warning(
                        f"CircuitBreaker [{rec.route_key}]: threshold {rec.failure_threshold} exceeded, CLOSED -> OPEN"
                    )

    async def reset(self) -> None:
        """Reset all circuit breakers (for testing and manual reset)."""
        async with self._lock:
            self._circuits.clear()


# Process-wide singleton
circuit_breaker_registry = CircuitBreakerRegistry()
