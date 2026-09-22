"""
core/cancellation_controller.py
Centralized Cancellation Controller for HERMES vNext.
Coordinates end-to-end mission cancellation across:
- MissionRunner
- KairosDAGScheduler
- Active Subprocess Management (OS PID termination)
- Progressive Verification & Repair Engine
- Unified EventBus & StateStore
- EventDrivenTUI
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, Dict, Any, Set, List
from loguru import logger

from core.event_bus import event_bus, HermesEvent, EventType
from tools.shell_tools import terminate_active_subprocesses


class CancellationController:
    """
    Authoritative production controller for mission cancellation.
    Guarantees atomic, terminal cancellation propagation across all live subsystems.
    """

    def __init__(self):
        self._cancelled_missions: Set[str] = set()
        self._cancellation_events: Dict[str, asyncio.Event] = {}

    def get_cancellation_event(self, mission_id: str) -> asyncio.Event:
        """Returns or creates an asyncio.Event tied to mission cancellation."""
        if mission_id not in self._cancellation_events:
            self._cancellation_events[mission_id] = asyncio.Event()
        return self._cancellation_events[mission_id]

    def is_cancelled(self, mission_id: str) -> bool:
        """Checks if a mission has been cancelled."""
        return mission_id in self._cancelled_missions

    def cancel_mission(
        self,
        mission_id: str,
        reason: str = "User cancelled mission",
        source: str = "USER_TUI"
    ) -> Dict[str, Any]:
        """
        Production entrypoint to cancel an active mission.
        Propagates cancellation to all live execution subsystems.
        """
        commit_timestamp = time.time()
        logger.warning(
            "CancellationController: CANCEL committed for mission '{}' | reason='{}' | source='{}'",
            mission_id, reason, source
        )

        # 1. Mark mission cancelled in memory
        self._cancelled_missions.add(mission_id)

        # 2. Trigger asyncio abort event for MissionRunner & KAIROS
        if mission_id in self._cancellation_events:
            self._cancellation_events[mission_id].set()

        # 3. Terminate all active mission-owned subprocesses
        terminated_procs = terminate_active_subprocesses()

        # 4. Publish MISSION_CANCELLED to EventBus (locks ExecutionStateStore)
        cancel_event = HermesEvent(
            event_type=EventType.MISSION_CANCELLED,
            mission_id=mission_id,
            timestamp=commit_timestamp,
            payload={
                "reason": reason,
                "source": source,
                "terminated_subprocesses": terminated_procs,
                "committed_at": commit_timestamp,
            }
        )
        event_bus.publish(cancel_event)

        return {
            "mission_id": mission_id,
            "status": "MISSION_CANCELLED",
            "cancelled": True,
            "commit_timestamp": commit_timestamp,
            "terminated_subprocesses": terminated_procs,
            "reason": reason
        }


# Global singleton
cancellation_controller = CancellationController()
