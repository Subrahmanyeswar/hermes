# core/network/health.py
"""
Provider health tracking, circuit breaker, and bounded health probes for HERMES 2.x
Network Resilience layer.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional
from loguru import logger

from core.network.models import FailureClassification


class CircuitState:
    CLOSED = "CLOSED"      # Normal operation, traffic allowed
    OPEN = "OPEN"          # Failing, fast-fail without network call
    HALF_OPEN = "HALF_OPEN"  # Testing recovery with single probe/request


class ProviderHealthState:
    """
    Maintains per-provider health metrics, circuit breaker state, and hysteresis.
    Independent instances exist for NVIDIA NIM and Ollama.
    """

    def __init__(
        self,
        provider_name: str,
        failure_threshold: int = 3,
        recovery_threshold: int = 2,
        cooldown_seconds: float = 10.0,
    ) -> None:
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.cooldown_seconds = cooldown_seconds

        self.circuit_state: str = CircuitState.CLOSED
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self.total_requests: int = 0
        self.total_failures: int = 0

        self.last_success_at: Optional[float] = None
        self.last_failure_at: Optional[float] = None
        self.last_failure_reason: Optional[str] = None
        self.last_failure_classification: Optional[FailureClassification] = None
        self.tripped_at: Optional[float] = None

    @property
    def is_healthy(self) -> bool:
        return self.circuit_state == CircuitState.CLOSED

    def can_attempt(self, now: Optional[float] = None) -> bool:
        """
        Check if a request to this provider is permitted.
        If circuit is OPEN:
          - If cooldown expired -> transitions to HALF_OPEN and returns True (probe attempt).
          - If cooldown not expired -> returns False (circuit tripped).
        """
        now_ts = now if now is not None else time.monotonic()

        if self.circuit_state == CircuitState.CLOSED:
            return True

        if self.circuit_state == CircuitState.OPEN:
            if self.tripped_at is not None and (now_ts - self.tripped_at) >= self.cooldown_seconds:
                logger.info(
                    f"ProviderHealthState [{self.provider_name}]: Cooldown expired, transitioning OPEN -> HALF_OPEN"
                )
                self.circuit_state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN allows single probe attempt
        return True

    def record_success(self) -> None:
        """Record successful request or probe."""
        self.total_requests += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_at = time.monotonic()

        if self.circuit_state == CircuitState.HALF_OPEN:
            if self.consecutive_successes >= self.recovery_threshold:
                logger.info(
                    f"ProviderHealthState [{self.provider_name}]: Recovery verified, transitioning HALF_OPEN -> CLOSED"
                )
                self.circuit_state = CircuitState.CLOSED
                self.tripped_at = None
        elif self.circuit_state == CircuitState.OPEN:
            # Direct recovery if external probe succeeded
            self.circuit_state = CircuitState.CLOSED
            self.tripped_at = None

    def record_failure(
        self,
        reason: str,
        classification: Optional[FailureClassification] = None,
    ) -> None:
        """Record failed request or probe."""
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_at = time.monotonic()
        self.last_failure_reason = reason
        self.last_failure_classification = classification

        if self.circuit_state == CircuitState.HALF_OPEN:
            # Immediate trip back to OPEN
            logger.warning(
                f"ProviderHealthState [{self.provider_name}]: Half-open probe failed, tripping back to OPEN: {reason}"
            )
            self.circuit_state = CircuitState.OPEN
            self.tripped_at = time.monotonic()

        elif self.circuit_state == CircuitState.CLOSED:
            if self.consecutive_failures >= self.failure_threshold:
                logger.warning(
                    f"ProviderHealthState [{self.provider_name}]: Failure threshold ({self.failure_threshold}) reached, tripping circuit to OPEN: {reason}"
                )
                self.circuit_state = CircuitState.OPEN
                self.tripped_at = time.monotonic()

    def reset(self) -> None:
        """Force reset health state to healthy/CLOSED."""
        self.circuit_state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.tripped_at = None

    def get_summary(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "circuit_state": self.circuit_state,
            "is_healthy": self.is_healthy,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "last_failure_reason": self.last_failure_reason,
            "last_failure_classification": (
                self.last_failure_classification.value if self.last_failure_classification else None
            ),
        }


async def bounded_health_probe(
    probe_fn: Any,
    timeout_seconds: float = 2.0,
) -> bool:
    """
    Execute a provider health check with a guaranteed hard timeout.
    Guarantees probe never hangs under any circumstance.
    """
    try:
        coro = probe_fn() if callable(probe_fn) else probe_fn
        result = await asyncio.wait_for(coro, timeout=timeout_seconds)
        return bool(result)
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning(f"Health probe failed or timed out ({exc})")
        return False
