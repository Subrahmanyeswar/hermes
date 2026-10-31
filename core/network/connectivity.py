# core/network/connectivity.py
"""
HERMES Phase 7: Canonical Connectivity Monitor.
Distinguishes:
- Condition A: Browser-to-backend disconnection (handled by SSE replay & client reconnect)
- Condition B: Backend process/service unavailable (handled by persistence & restart recovery)
- Condition C: Model-provider failure (Internet is fine, provider is down/circuit-broken)
- Condition D: Actual Internet connectivity loss (DNS fails, neutral probe fails, socket unreachable)

Guarantees:
- Minimal shared monitor across all missions (never per-mission probing loops)
- Independent, lightweight probes to neutral endpoints (zero billable tokens used)
- Hysteresis and anti-flapping protection (configurable failure & recovery thresholds)
- Clean lifecycle management and background polling
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

import httpx
from loguru import logger


class ConnectivityStatus(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class ConnectivityCondition(str, Enum):
    CONDITION_A = "BROWSER_DISCONNECTED"
    CONDITION_B = "SERVICE_UNAVAILABLE"
    CONDITION_C = "PROVIDER_OUTAGE"
    CONDITION_D = "INTERNET_LOSS"


def classify_error_condition(exc: Exception, is_internet_online: bool) -> Optional[ConnectivityCondition]:
    """
    Classify whether an exception corresponds to Condition C (Provider Outage)
    or Condition D (Internet Loss).
    Returns None if the error is permanent or non-network.
    """
    from core.transport.types import ErrorCategory, StructuredTransportError
    if isinstance(exc, StructuredTransportError):
        # Permanent errors must not enter waiting state
        if exc.category in (
            ErrorCategory.AUTHENTICATION_FAILURE,
            ErrorCategory.AUTHORIZATION_RESTRICTION,
            ErrorCategory.BILLING_FAILURE,
            ErrorCategory.INVALID_REQUEST,
            ErrorCategory.UNSUPPORTED_MODEL,
        ):
            return None

        if exc.category in (
            ErrorCategory.CONNECT_TIMEOUT,
            ErrorCategory.CONNECTION_FAILURE,
            ErrorCategory.CONNECTION_RESET,
        ):
            return ConnectivityCondition.CONDITION_D if not is_internet_online else ConnectivityCondition.CONDITION_C

        if exc.category in (
            ErrorCategory.PROVIDER_SERVER_ERROR,
            ErrorCategory.PROVIDER_UNAVAILABLE,
            ErrorCategory.CIRCUIT_BREAKER_OPEN,
            ErrorCategory.RATE_LIMITED,
        ):
            return ConnectivityCondition.CONDITION_C

    # Socket / httpx / standard connection errors
    msg = str(exc).lower()
    net_err_keywords = [
        "connecterror", "connection refused", "network is unreachable",
        "name or service not known", "getaddrinfo failed", "nodename nor servname",
        "temporary failure in name resolution", "connection reset", "broken pipe",
        "connecttimeout", "timed out", "could not connect", "unable to connect",
        "connection error", "is the ollama server running", "failed to connect",
        "cannot connect", "failed to establish a new connection",
    ]
    if any(k in msg for k in net_err_keywords):
        return ConnectivityCondition.CONDITION_D if not is_internet_online else ConnectivityCondition.CONDITION_C

    if any(p in msg for p in ["503", "502", "504", "server error", "service unavailable", "circuit breaker"]):
        return ConnectivityCondition.CONDITION_C

    return None


@dataclass
class ProbeResult:
    target: str
    success: bool
    latency_ms: float = 0.0
    error: Optional[str] = None
    status_code: Optional[int] = None


@dataclass
class ConnectivityStateSnapshot:
    status: ConnectivityStatus
    is_connected: bool
    last_checked: float
    consecutive_failures: int
    consecutive_successes: int
    probe_targets: List[str]
    last_error: Optional[str] = None


# Default neutral, high-availability public probe endpoints that don't consume model tokens
DEFAULT_PROBE_URLS = [
    "https://1.1.1.1/cdn-cgi/trace",
    "https://dns.google/resolve?name=example.com",
    "https://cloudflare.com/cdn-cgi/trace",
    "https://icanhazip.com",
]


class ConnectivityMonitor:
    """
    Authoritative shared connectivity monitor for HERMES runtime.
    Maintains network status with hysteresis to prevent flapping and retry storms.
    """

    def __init__(
        self,
        probe_urls: Optional[List[str]] = None,
        failure_threshold: int = 2,
        recovery_threshold: int = 2,
        online_interval: float = 30.0,
        offline_interval: float = 3.0,
        probe_timeout: float = 2.0,
        custom_probe_func: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> None:
        self.probe_urls = probe_urls or list(DEFAULT_PROBE_URLS)
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_threshold = max(1, recovery_threshold)
        self.online_interval = online_interval
        self.offline_interval = offline_interval
        self.probe_timeout = probe_timeout
        self._custom_probe_func = custom_probe_func

        self._status: ConnectivityStatus = ConnectivityStatus.UNKNOWN
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._last_checked: float = 0.0
        self._last_error: Optional[str] = None
        self._recovered_at: Optional[float] = None

        self._listeners: Set[Callable[[ConnectivityStatus, ConnectivityStatus], Any]] = set()
        self._lock = asyncio.Lock()
        self._poll_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def status(self) -> ConnectivityStatus:
        return self._status

    @property
    def is_online(self) -> bool:
        return self._status == ConnectivityStatus.ONLINE

    @property
    def is_offline(self) -> bool:
        return self._status == ConnectivityStatus.OFFLINE

    def add_listener(self, callback: Callable[[ConnectivityStatus, ConnectivityStatus], Any]) -> None:
        """Register a callback notified when connectivity status changes."""
        self._listeners.add(callback)

    def remove_listener(self, callback: Callable[[ConnectivityStatus, ConnectivityStatus], Any]) -> None:
        """Unregister a listener callback."""
        self._listeners.discard(callback)

    def get_snapshot(self) -> ConnectivityStateSnapshot:
        return ConnectivityStateSnapshot(
            status=self._status,
            is_connected=(self._status == ConnectivityStatus.ONLINE),
            last_checked=self._last_checked,
            consecutive_failures=self._consecutive_failures,
            consecutive_successes=self._consecutive_successes,
            probe_targets=list(self.probe_urls),
            last_error=self._last_error,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.probe_timeout, connect=self.probe_timeout),
                follow_redirects=True,
                headers={"User-Agent": "HERMES-Connectivity-Monitor/1.0"},
            )
        return self._client

    async def _execute_single_probe(self, url: str) -> ProbeResult:
        start = time.monotonic()
        try:
            client = await self._get_client()
            res = await client.get(url)
            latency = (time.monotonic() - start) * 1000.0
            if res.status_code in (200, 204, 301, 302, 307, 308):
                # Bounded body reading (max 4KB) & captive portal detection
                sample = res.content[:4096].decode("utf-8", errors="ignore").lower()
                if "<html" in sample and any(term in sample for term in ("login", "captive", "portal", "access denied", "radius")):
                    return ProbeResult(
                        target=url,
                        success=False,
                        latency_ms=latency,
                        status_code=res.status_code,
                        error="Captive portal interception detected",
                    )
                return ProbeResult(target=url, success=True, latency_ms=latency, status_code=res.status_code)
            return ProbeResult(
                target=url,
                success=False,
                latency_ms=latency,
                status_code=res.status_code,
                error=f"Unexpected status: {res.status_code}",
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000.0
            return ProbeResult(target=url, success=False, latency_ms=latency, error=str(exc))

    async def probe_now(self) -> ConnectivityStatus:
        """
        Perform an immediate connectivity probe across neutral targets.
        Updates hysteresis and triggers listeners if status changed.
        Thread-safe under async lock.
        """
        async with self._lock:
            self._last_checked = time.time()

            # 1. Check custom probe function if injected
            if self._custom_probe_func is not None:
                try:
                    probe_success = await self._custom_probe_func()
                    error_msg = None if probe_success else "Custom probe returned False"
                except Exception as e:
                    probe_success = False
                    error_msg = str(e)
            else:
                # 2. Try neutral probe targets in sequence or parallel until success
                probe_success = False
                error_msg = None
                for url in self.probe_urls:
                    res = await self._execute_single_probe(url)
                    if res.success:
                        probe_success = True
                        break
                    else:
                        error_msg = res.error

            old_status = self._status

            if probe_success:
                self._consecutive_successes += 1
                self._consecutive_failures = 0
                self._last_error = None

                # Transition to ONLINE requires recovery_threshold consecutive successes
                if self._status != ConnectivityStatus.ONLINE:
                    if self._consecutive_successes >= self.recovery_threshold:
                        self._status = ConnectivityStatus.ONLINE
                        self._recovered_at = time.time()
                        logger.info(
                            f"ConnectivityMonitor: Status transitioned {old_status.value} -> ONLINE "
                            f"(recovery threshold {self.recovery_threshold} reached)."
                        )
                        self._notify_listeners(old_status, ConnectivityStatus.ONLINE)
                    else:
                        # In the process of recovering
                        self._status = ConnectivityStatus.DEGRADED
                        if old_status != ConnectivityStatus.DEGRADED:
                            self._notify_listeners(old_status, ConnectivityStatus.DEGRADED)
            else:
                self._consecutive_failures += 1
                self._consecutive_successes = 0
                self._last_error = error_msg or "Probe failed"

                # Transition to OFFLINE requires failure_threshold consecutive failures
                if self._status != ConnectivityStatus.OFFLINE:
                    if self._consecutive_failures >= self.failure_threshold:
                        self._status = ConnectivityStatus.OFFLINE
                        logger.warning(
                            f"ConnectivityMonitor: Status transitioned {old_status.value} -> OFFLINE "
                            f"(failure threshold {self.failure_threshold} reached: {self._last_error})."
                        )
                        self._notify_listeners(old_status, ConnectivityStatus.OFFLINE)
                    else:
                        # Transient blip: mark DEGRADED
                        self._status = ConnectivityStatus.DEGRADED
                        if old_status != ConnectivityStatus.DEGRADED:
                            self._notify_listeners(old_status, ConnectivityStatus.DEGRADED)

            return self._status

    def _notify_listeners(self, old_status: ConnectivityStatus, new_status: ConnectivityStatus) -> None:
        for listener in list(self._listeners):
            try:
                res = listener(old_status, new_status)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as exc:
                logger.warning(f"ConnectivityMonitor: Error in listener {listener}: {exc}")

    async def _polling_loop(self) -> None:
        """Background non-blocking polling loop."""
        while self._running:
            try:
                await self.probe_now()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug(f"ConnectivityMonitor: error during polling check: {exc}")

            interval = self.offline_interval if self._status != ConnectivityStatus.ONLINE else self.online_interval
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    def start(self) -> None:
        """Start the background monitor loop if not already running."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._polling_loop())
        logger.info("ConnectivityMonitor: background polling loop started.")

    async def stop(self) -> None:
        """Stop background monitor loop and close HTTP probe client."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None

        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        logger.info("ConnectivityMonitor: background polling stopped.")

    async def aclose(self) -> None:
        await self.stop()


# Singleton monitor instance
shared_connectivity_monitor = ConnectivityMonitor()
