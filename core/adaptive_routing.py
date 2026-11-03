# core/adaptive_routing.py
"""
HERMES Phase 4D — Adaptive Model Routing & Zero-Wait Circuit Breaker Engine
Provides provider-health awareness, circuit breaking for stalled providers,
background non-blocking recovery probing, and zero-wait failover.
"""

from __future__ import annotations

import os
import time
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
from loguru import logger

from config.model_config import (
    TIER1_PROVIDER, TIER1_MODEL,
    TIER2_PROVIDER, TIER2_MODEL,
    TIER3_PROVIDER, TIER3_MODEL,
    TIER4_PROVIDER, TIER4_MODEL,
    CIRCUIT_BREAKER_ENABLED,
    T1_CIRCUIT_BREAKER_FAILURES,
    T1_CIRCUIT_BREAKER_WINDOW,
    T1_PROBE_INTERVAL,
    T2_MAX_CONCURRENCY,
    MODEL_FIRST_TOKEN_TIMEOUT,
)


class ProviderHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OPEN_CIRCUIT = "OPEN_CIRCUIT"
    PROBING = "PROBING"
    RECOVERED = "RECOVERED"


@dataclass
class ProviderHealthRecord:
    tier: int
    provider: str
    model: str
    state: ProviderHealthState = ProviderHealthState.HEALTHY
    failure_count: int = 0
    consecutive_first_token_failures: int = 0
    consecutive_successes: int = 0
    last_failure_ts: Optional[float] = None
    last_success_ts: Optional[float] = None
    last_probe_ts: Optional[float] = None
    last_state_change_ts: float = field(default_factory=time.time)
    rolling_latency: List[float] = field(default_factory=list)
    rolling_first_token_latency: List[float] = field(default_factory=list)
    probe_in_flight: bool = False
    circuit_open_ts: Optional[float] = None
    circuit_close_ts: Optional[float] = None
    is_auth_failure: bool = False
    is_quota_exhausted: bool = False
    retry_after_ts: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "provider": self.provider,
            "model": self.model,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "consecutive_first_token_failures": self.consecutive_first_token_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_failure_ts": self.last_failure_ts,
            "last_success_ts": self.last_success_ts,
            "last_probe_ts": self.last_probe_ts,
            "last_state_change_ts": self.last_state_change_ts,
            "rolling_latency": self.rolling_latency[-5:] if self.rolling_latency else [],
            "probe_in_flight": self.probe_in_flight,
            "circuit_open_ts": self.circuit_open_ts,
            "circuit_close_ts": self.circuit_close_ts,
        }


@dataclass
class RouteDecision:
    tier: int
    provider: str
    model: str
    bypassed: bool
    reason: str
    avoided_timeout_ms: float = 0.0
    decision_latency_ms: float = 0.0


@dataclass
class AdaptiveRoutingTelemetry:
    avoided_timeout_count: int = 0
    avoided_timeout_ms: float = 0.0
    total_routing_decisions: int = 0
    t1_direct_dispatches: int = 0
    t2_fast_failovers: int = 0
    t2_circuit_bypass_dispatches: int = 0
    t3_arbitration_dispatches: int = 0
    probes_scheduled: int = 0
    probes_succeeded: int = 0
    probes_failed: int = 0
    state_transitions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avoided_timeout_count": self.avoided_timeout_count,
            "avoided_timeout_ms": self.avoided_timeout_ms,
            "total_routing_decisions": self.total_routing_decisions,
            "t1_direct_dispatches": self.t1_direct_dispatches,
            "t2_fast_failovers": self.t2_fast_failovers,
            "t2_circuit_bypass_dispatches": self.t2_circuit_bypass_dispatches,
            "t3_arbitration_dispatches": self.t3_arbitration_dispatches,
            "probes_scheduled": self.probes_scheduled,
            "probes_succeeded": self.probes_succeeded,
            "probes_failed": self.probes_failed,
            "state_transitions": self.state_transitions,
        }


class AdaptiveRouter:
    """
    Central provider-health aware router.
    Maintains health states for Tier 1, Tier 2, and Tier 3.
    Immediately bypasses stalled tiers when circuit is open, avoiding repeated timeout waiting.
    Restores Tier 1 when background health probes confirm responsiveness.
    """

    def __init__(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._lock = asyncio.Lock() if loop is not None else None
        self.providers: Dict[int, ProviderHealthRecord] = {
            1: ProviderHealthRecord(tier=1, provider=TIER1_PROVIDER, model=TIER1_MODEL),
            2: ProviderHealthRecord(tier=2, provider=TIER2_PROVIDER, model=TIER2_MODEL),
            3: ProviderHealthRecord(tier=3, provider=TIER3_PROVIDER, model=TIER3_MODEL),
            4: ProviderHealthRecord(tier=4, provider=TIER4_PROVIDER, model=TIER4_MODEL),
        }
        self.telemetry = AdaptiveRoutingTelemetry()
        self._t2_semaphore: Optional[asyncio.Semaphore] = None
        self._probe_callback: Optional[Callable[[], Any]] = None

    def _ensure_concurrency_guards(self) -> None:
        if self._t2_semaphore is None:
            self._t2_semaphore = asyncio.Semaphore(T2_MAX_CONCURRENCY)

    def set_probe_callback(self, cb: Callable[[], Any]) -> None:
        self._probe_callback = cb

    def get_health(self, tier: int) -> ProviderHealthRecord:
        record = self.providers[tier]
        if record.state in (ProviderHealthState.OPEN_CIRCUIT, ProviderHealthState.DEGRADED):
            now = time.time()
            # Permanent / unserviceable failure checks (do not auto-recover via generic cooldown)
            if getattr(record, "is_auth_failure", False):
                return record
            if getattr(record, "is_quota_exhausted", False):
                return record

            # Retry-After duration check: must respect explicit provider Retry-After duration
            if getattr(record, "retry_after_ts", None) is not None:
                if now < record.retry_after_ts:
                    return record
                else:
                    record.retry_after_ts = None

            reference_ts = record.circuit_open_ts or record.last_state_change_ts or record.last_failure_ts
            if reference_ts and (now - reference_ts >= T1_CIRCUIT_BREAKER_WINDOW):
                logger.info(
                    f"[ADAPTIVE ROUTING] Tier {tier} circuit breaker cooldown window expired ({now - reference_ts:.1f}s >= {T1_CIRCUIT_BREAKER_WINDOW}s). "
                    "Resetting state to HEALTHY."
                )
                record.state = ProviderHealthState.HEALTHY
                record.consecutive_first_token_failures = 0
                record.failure_count = 0
                record.circuit_open_ts = None
                record.circuit_close_ts = now
                record.last_state_change_ts = now
        return record

    def is_tier_healthy(self, tier: int) -> bool:
        record = self.get_health(tier) if tier in self.providers else None
        if not record:
            return False
        return record.state in (ProviderHealthState.HEALTHY, ProviderHealthState.RECOVERED)

    def reset_state(self) -> None:
        """Reset all provider health records to clean initial state."""
        now = time.time()
        for tier, rec in self.providers.items():
            rec.state = ProviderHealthState.HEALTHY
            rec.failure_count = 0
            rec.consecutive_first_token_failures = 0
            rec.consecutive_successes = 0
            rec.circuit_open_ts = None
            rec.circuit_close_ts = now
            rec.last_state_change_ts = now
            rec.probe_in_flight = False
            rec.is_auth_failure = False
            rec.is_quota_exhausted = False
            rec.retry_after_ts = None

    def route_primary(self, client_t1: Any = None) -> RouteDecision:
        """
        Evaluate provider health and return route decision.
        Target: <= 5ms local overhead.
        """
        t0 = time.perf_counter()
        self.telemetry.total_routing_decisions += 1
        t1 = self.providers[1]
        t2 = self.providers[2]

        if not CIRCUIT_BREAKER_ENABLED:
            dec_lat = (time.perf_counter() - t0) * 1000.0
            self.telemetry.t1_direct_dispatches += 1
            return RouteDecision(
                tier=1,
                provider=t1.provider,
                model=t1.model,
                bypassed=False,
                reason="Circuit breaker disabled, using T1 primary",
                decision_latency_ms=dec_lat,
            )

        # Evaluate T1 state
        if t1.state in (ProviderHealthState.HEALTHY, ProviderHealthState.RECOVERED):
            dec_lat = (time.perf_counter() - t0) * 1000.0
            self.telemetry.t1_direct_dispatches += 1
            return RouteDecision(
                tier=1,
                provider=t1.provider,
                model=t1.model,
                bypassed=False,
                reason="T1 is healthy, direct primary dispatch",
                decision_latency_ms=dec_lat,
            )

        # T1 is DEGRADED, OPEN_CIRCUIT, or PROBING
        # Check if probe should be triggered in background
        now = time.time()
        if (
            not t1.probe_in_flight
            and (t1.last_probe_ts is None or (now - t1.last_probe_ts) >= T1_PROBE_INTERVAL)
        ):
            self.schedule_background_probe(tier=1, client=client_t1)

        # Zero-wait bypass: evaluate T2 health, then T3 if T2 is also degraded/open
        expected_saved_ms = MODEL_FIRST_TOKEN_TIMEOUT * 1000.0
        self.telemetry.avoided_timeout_count += 1
        self.telemetry.avoided_timeout_ms += expected_saved_ms
        dec_lat = (time.perf_counter() - t0) * 1000.0

        t3 = self.providers.get(3)
        if t2.state in (ProviderHealthState.OPEN_CIRCUIT, ProviderHealthState.DEGRADED) and t3 and t3.model:
            self.telemetry.t3_arbitration_dispatches += 1
            logger.warning(
                f"[ADAPTIVE ROUTING] T1 circuit is {t1.state.value} and T2 circuit is {t2.state.value}. "
                f"Zero-wait failover directly to T3 ({t3.model}) in {dec_lat:.3f}ms"
            )
            return RouteDecision(
                tier=3,
                provider=t3.provider,
                model=t3.model,
                bypassed=True,
                reason=f"T1 circuit {t1.state.value} and T2 circuit {t2.state.value}, fast-failover to T3",
                avoided_timeout_ms=expected_saved_ms * 2,
                decision_latency_ms=dec_lat,
            )

        self.telemetry.t2_circuit_bypass_dispatches += 1
        logger.info(
            f"[ADAPTIVE ROUTING] T1 circuit is {t1.state.value}. Zero-wait failover to T2 ({t2.model}) "
            f"in {dec_lat:.3f}ms (avoided {expected_saved_ms/1000:.1f}s stall)"
        )

        return RouteDecision(
            tier=2,
            provider=t2.provider,
            model=t2.model,
            bypassed=True,
            reason=f"T1 circuit {t1.state.value}, fast-failover to T2",
            avoided_timeout_ms=expected_saved_ms,
            decision_latency_ms=dec_lat,
        )

    def record_success(
        self,
        tier: int,
        latency: float,
        first_token_latency: Optional[float] = None,
    ) -> None:
        """Update provider health following a successful generation."""
        record = self.providers.get(tier)
        if not record:
            return

        now = time.time()
        record.last_success_ts = now
        record.consecutive_successes += 1
        record.consecutive_first_token_failures = 0
        record.rolling_latency.append(latency)
        if len(record.rolling_latency) > 20:
            record.rolling_latency.pop(0)

        if first_token_latency is not None:
            record.rolling_first_token_latency.append(first_token_latency)
            if len(record.rolling_first_token_latency) > 20:
                record.rolling_first_token_latency.pop(0)

        # If tier was recovering or degraded, restore HEALTHY state
        if tier in (1, 2) and record.state != ProviderHealthState.HEALTHY:
            old_state = record.state.value
            record.state = ProviderHealthState.HEALTHY
            record.last_state_change_ts = now
            record.circuit_close_ts = now
            self.telemetry.state_transitions.append({
                "tier": tier,
                "from": old_state,
                "to": ProviderHealthState.HEALTHY.value,
                "timestamp": now,
                "reason": "generation_success",
            })
            logger.info(
                f"[ADAPTIVE ROUTING] Tier {tier} transitioned {old_state} -> HEALTHY after successful generation ({latency:.2f}s)"
            )

    def record_failure(
        self,
        tier: int,
        error: Exception,
        timeout_type: str = "",
        latency: float = 0.0,
        client: Any = None,
        retry_after: Optional[float] = None,
    ) -> None:
        """Update provider health following a failure, tripping circuit if threshold exceeded."""
        record = self.providers.get(tier)
        if not record:
            return

        now = time.time()
        record.last_failure_ts = now
        record.failure_count += 1
        record.consecutive_successes = 0

        err_str = str(error).lower()
        if "401" in err_str or "unauthorized" in err_str or "auth_failure" in err_str or "invalid api key" in err_str or "403" in err_str:
            record.is_auth_failure = True
            record.state = ProviderHealthState.OPEN_CIRCUIT
            record.circuit_open_ts = now
            return

        if "insufficient_quota" in err_str or "quota exceeded" in err_str or "out of credits" in err_str:
            record.is_quota_exhausted = True
            record.state = ProviderHealthState.OPEN_CIRCUIT
            record.circuit_open_ts = now
            return

        act_retry = retry_after
        if act_retry is None and hasattr(error, "retry_after"):
            try:
                act_retry = float(getattr(error, "retry_after"))
            except Exception:
                pass
        if act_retry is not None and act_retry > 0:
            record.retry_after_ts = now + act_retry
            record.state = ProviderHealthState.OPEN_CIRCUIT
            record.circuit_open_ts = now
            return

        is_severe_timeout = timeout_type in ("FIRST_TOKEN_TIMEOUT", "CONNECT_TIMEOUT", "TOTAL_GENERATION_TIMEOUT") or "timeout" in str(error).lower()

        if is_severe_timeout:
            record.consecutive_first_token_failures += 1
        else:
            record.consecutive_first_token_failures += 1

        if tier in (1, 2):
            old_state = record.state
            threshold = T1_CIRCUIT_BREAKER_FAILURES if tier == 1 else 2
            if record.consecutive_first_token_failures >= threshold:
                new_state = ProviderHealthState.OPEN_CIRCUIT
            else:
                new_state = ProviderHealthState.DEGRADED

            if old_state != new_state:
                record.state = new_state
                record.last_state_change_ts = now
                if new_state == ProviderHealthState.OPEN_CIRCUIT:
                    record.circuit_open_ts = now
                self.telemetry.state_transitions.append({
                    "tier": tier,
                    "from": old_state.value,
                    "to": new_state.value,
                    "timestamp": now,
                    "reason": f"{timeout_type or 'failure'}: {str(error)[:100]}",
                })
                logger.warning(
                    f"[ADAPTIVE ROUTING] Tier {tier} circuit transitioned {old_state.value} -> {new_state.value} "
                    f"(failures={record.consecutive_first_token_failures}/{threshold})"
                )

            # Enforce cooldown on probe
            record.last_probe_ts = now

    def schedule_background_probe(self, tier: int = 1, client: Any = None, force: bool = False) -> None:
        """Spawn a non-blocking background recovery probe if cooldown elapsed."""
        record = self.providers.get(tier)
        if not record or record.probe_in_flight:
            return

        now = time.time()
        if not force and record.last_probe_ts is not None and (now - record.last_probe_ts) < T1_PROBE_INTERVAL:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._run_probe(tier=tier, client=client))
        except RuntimeError:
            pass  # No running event loop

    async def _run_probe(self, tier: int, client: Any = None) -> bool:
        """Execute lightweight non-blocking health probe with active inference verification."""
        record = self.providers.get(tier)
        if not record or record.probe_in_flight:
            return False

        record.probe_in_flight = True
        record.last_probe_ts = time.time()
        self.telemetry.probes_scheduled += 1

        logger.debug(f"[ADAPTIVE ROUTING] Background probe starting for Tier {tier}...")
        success = False
        t_probe0 = time.monotonic()

        try:
            if self._probe_callback is not None:
                res = self._probe_callback()
                if asyncio.iscoroutine(res):
                    success = await res
                else:
                    success = bool(res)
            elif client is not None:
                if hasattr(client, "is_running"):
                    is_ok = await client.is_running(timeout=2.0)
                    if not is_ok:
                        success = False
                    elif hasattr(client, "generate"):
                        try:
                            resp = await asyncio.wait_for(
                                client.generate(prompt="ping", max_tokens=1, stream=False),
                                timeout=2.5
                            )
                            # Strictly distinguish model inference health from endpoint availability
                            success = bool(resp and getattr(resp, "success", False))
                        except Exception:
                            success = False
                    else:
                        # Endpoint responding without inference capability cannot mark provider healthy
                        success = False
                elif hasattr(client, "generate"):
                    try:
                        resp = await asyncio.wait_for(
                            client.generate(prompt="ping", max_tokens=1, stream=False),
                            timeout=2.5
                        )
                        success = bool(resp and getattr(resp, "success", False))
                    except Exception:
                        success = False
            elif tier in (1, 2, 3):
                from models.common_adapter import get_provider_adapter
                from config.model_config import (
                    TIER1_PROVIDER, TIER1_MODEL,
                    TIER2_PROVIDER, TIER2_MODEL,
                    TIER3_PROVIDER, TIER3_MODEL,
                )
                p_name = TIER1_PROVIDER if tier == 1 else (TIER2_PROVIDER if tier == 2 else TIER3_PROVIDER)
                m_name = TIER1_MODEL if tier == 1 else (TIER2_MODEL if tier == 2 else TIER3_MODEL)
                adapter = get_provider_adapter(p_name, m_name, tier=tier)
                try:
                    resp = await asyncio.wait_for(
                        adapter.generate(prompt="ping", max_tokens=1, stream=False),
                        timeout=3.0
                    )
                    success = bool(resp and getattr(resp, "success", False))
                except Exception:
                    success = False
        except Exception as e:
            logger.debug(f"[ADAPTIVE ROUTING] Background probe exception: {e}")
            success = False

        probe_dur = time.monotonic() - t_probe0
        now = time.time()

        if success:
            self.telemetry.probes_succeeded += 1
            old_state = record.state.value
            record.state = ProviderHealthState.HEALTHY
            record.last_state_change_ts = now
            record.circuit_close_ts = now
            record.consecutive_first_token_failures = 0
            self.telemetry.state_transitions.append({
                "tier": tier,
                "from": old_state,
                "to": ProviderHealthState.HEALTHY.value,
                "timestamp": now,
                "reason": f"probe_success ({probe_dur:.2f}s)",
            })
            logger.info(
                f"[ADAPTIVE ROUTING] Tier {tier} probe SUCCEEDED in {probe_dur:.2f}s! "
                f"State restored to HEALTHY. Primary routing reactivated."
            )
        else:
            self.telemetry.probes_failed += 1
            logger.debug(
                f"[ADAPTIVE ROUTING] Tier {tier} probe failed ({probe_dur:.2f}s). Circuit remains OPEN."
            )

        record.probe_in_flight = False
        return success

    def notify_provider_recovered(self, tier: int = 1) -> None:
        """Explicitly restore a tier to HEALTHY and reset its circuit breaker."""
        record = self.providers.get(tier)
        if not record:
            return
        now = time.time()
        old_state = record.state.value
        record.state = ProviderHealthState.HEALTHY
        record.last_state_change_ts = now
        record.circuit_close_ts = now
        record.consecutive_first_token_failures = 0
        record.probe_in_flight = False
        self.telemetry.state_transitions.append({
            "tier": tier,
            "from": old_state,
            "to": ProviderHealthState.HEALTHY.value,
            "timestamp": now,
            "reason": "external_recovery_notification",
        })
        logger.info(
            f"[ADAPTIVE ROUTING] Tier {tier} circuit restored {old_state} -> HEALTHY via recovery notification."
        )

    def reset(self) -> None:
        """Reset state for tests or fresh qualification."""
        self.providers = {
            1: ProviderHealthRecord(tier=1, provider=TIER1_PROVIDER, model=TIER1_MODEL),
            2: ProviderHealthRecord(tier=2, provider=TIER2_PROVIDER, model=TIER2_MODEL),
            3: ProviderHealthRecord(tier=3, provider=TIER3_PROVIDER, model=TIER3_MODEL),
        }
        self.telemetry = AdaptiveRoutingTelemetry()


# Global singleton
adaptive_router = AdaptiveRouter()


def get_adaptive_router() -> AdaptiveRouter:
    return adaptive_router
