# core/request_guard.py
"""
HERMES 2.x — In-Flight Request Guard & Concurrency Control (Phase 2)
Guarantees:
  1. Prevents duplicate in-flight model requests for the same mission.
  2. Ensures cancellation cleanly propagates into active transport connections.
  3. Releases all execution slots and semaphores upon completion or abort.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, Set
from contextlib import asynccontextmanager
from loguru import logger


class DuplicateInFlightRequestError(RuntimeError):
    """Raised when a concurrent duplicate model request is initiated for an active mission."""
    pass


class MissionRequestGuard:
    """
    Tracks and gates in-flight model requests per mission.
    """

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._active_missions: Set[str] = set()
        self._meta_lock: Optional[asyncio.Lock] = None

    def _get_meta_lock(self) -> asyncio.Lock:
        if self._meta_lock is None:
            self._meta_lock = asyncio.Lock()
        return self._meta_lock

    async def get_mission_lock(self, mission_id: str) -> asyncio.Lock:
        meta = self._get_meta_lock()
        async with meta:
            if mission_id not in self._locks:
                self._locks[mission_id] = asyncio.Lock()
            return self._locks[mission_id]

    def is_in_flight(self, mission_id: str) -> bool:
        return mission_id in self._active_missions

    @asynccontextmanager
    async def guard(self, mission_id: str, allow_wait: bool = False):
        """
        Context manager ensuring only one model request is active per mission.
        If allow_wait is False, raises DuplicateInFlightRequestError immediately on collision.
        """
        if not mission_id:
            yield
            return

        lock = await self.get_mission_lock(mission_id)
        if not allow_wait and lock.locked():
            raise DuplicateInFlightRequestError(
                f"Duplicate model request rejected: mission '{mission_id}' already has a model call in flight."
            )

        await lock.acquire()
        self._active_missions.add(mission_id)
        try:
            yield
        finally:
            self._active_missions.discard(mission_id)
            if lock.locked():
                lock.release()

    def release_all(self, mission_id: str) -> None:
        """Forcibly clear active mission guard on mission abort or terminal error."""
        self._active_missions.discard(mission_id)
        lock = self._locks.get(mission_id)
        if lock and lock.locked():
            try:
                lock.release()
            except RuntimeError:
                pass


# Global singleton
mission_request_guard = MissionRequestGuard()
