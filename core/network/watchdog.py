# core/network/watchdog.py
"""
StreamWatchdog for HERMES 2.x
Monitors streaming progress using monotonic clock, distinguishing
connection establishment from first-delta arrival and inter-delta streaming progress.
Detects hangs and stalls proactively even if the socket or async generator blocks.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional
from loguru import logger


class StreamWatchdog:
    """
    Tracks streaming progress and enforces both TTFT (time-to-first-delta)
    and idle inter-delta timeouts using monotonic clocks.
    """

    def __init__(
        self,
        first_delta_timeout: float = 15.0,
        idle_timeout: float = 15.0,
        on_stall: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.first_delta_timeout: float = float(first_delta_timeout)
        self.idle_timeout: float = float(idle_timeout)
        self.on_stall: Optional[Callable[[str], Any]] = on_stall

        self._started_at: Optional[float] = None
        self._first_delta_at: Optional[float] = None
        self._last_delta_at: Optional[float] = None
        self._deltas_count: int = 0
        self._is_running: bool = False
        self._watchdog_task: Optional[asyncio.Task] = None
        self._stall_detected: bool = False
        self._stall_reason: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def has_first_delta(self) -> bool:
        return self._first_delta_at is not None

    @property
    def deltas_count(self) -> int:
        return self._deltas_count

    @property
    def stall_reason(self) -> Optional[str]:
        return self._stall_reason

    def start(self, start_time: Optional[float] = None) -> None:
        """Start watchdog clock."""
        self._started_at = start_time if start_time is not None else time.monotonic()
        self._first_delta_at = None
        self._last_delta_at = None
        self._deltas_count = 0
        self._stall_detected = False
        self._stall_reason = None
        self._is_running = True

    def record_first_delta(self, now: Optional[float] = None) -> None:
        """Record the arrival of the first streaming delta."""
        now_ts = now if now is not None else time.monotonic()
        if self._first_delta_at is None:
            self._first_delta_at = now_ts
        self._last_delta_at = now_ts
        self._deltas_count += 1

    def record_delta(self, delta_len: int = 1, now: Optional[float] = None) -> None:
        """Record arrival of subsequent tokens / chunks."""
        now_ts = now if now is not None else time.monotonic()
        if self._first_delta_at is None:
            self._first_delta_at = now_ts
        self._last_delta_at = now_ts
        self._deltas_count += 1

    def check_stall(self, now: Optional[float] = None) -> Optional[str]:
        """
        Check if the stream is currently stalled.
        Returns stall reason string if stalled, or None if healthy.
        """
        if not self._is_running or self._started_at is None:
            return None

        now_ts = now if now is not None else time.monotonic()

        # Phase 1: Waiting for first delta
        if self._first_delta_at is None:
            elapsed = now_ts - self._started_at
            if elapsed > self.first_delta_timeout:
                self._stall_detected = True
                self._stall_reason = f"FIRST_DELTA_TIMEOUT ({elapsed:.2f}s > {self.first_delta_timeout:.2f}s)"
                return self._stall_reason
            return None

        # Phase 2: Streaming active, check inter-delta idle gap
        gap = now_ts - (self._last_delta_at or self._first_delta_at)
        if gap > self.idle_timeout:
            self._stall_detected = True
            self._stall_reason = f"INTER_DELTA_STALL ({gap:.2f}s idle > {self.idle_timeout:.2f}s)"
            return self._stall_reason

        return None

    def start_background_monitoring(self, poll_interval: float = 0.5) -> None:
        """Launch background monitoring task that triggers on_stall if a stall occurs."""
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()

        async def _monitor_loop() -> None:
            try:
                while self._is_running:
                    await asyncio.sleep(poll_interval)
                    if not self._is_running:
                        break
                    reason = self.check_stall()
                    if reason:
                        logger.warning(f"StreamWatchdog: Stall detected: {reason}")
                        if self.on_stall is not None:
                            try:
                                res = self.on_stall(reason)
                                if asyncio.iscoroutine(res):
                                    await res
                            except Exception as cb_err:
                                logger.error(f"StreamWatchdog: on_stall callback error: {cb_err}")
                        break
            except asyncio.CancelledError:
                pass

        try:
            loop = asyncio.get_running_loop()
            self._watchdog_task = loop.create_task(_monitor_loop())
        except RuntimeError:
            # If no running event loop, background monitoring is not started
            self._watchdog_task = None

    def stop(self) -> None:
        """Stop watchdog and cleanup background task."""
        self._is_running = False
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None
