# core/runtime_state/store.py
"""
Authoritative State Store for HERMES 2.x.
Owns the canonical HermesRuntimeState for a mission session.
Serializes concurrent event applications, maintains monotonic state versioning,
and generates coherent, immutable snapshots.

Maintains complete backward compatibility with the legacy ExecutionStateStore contract.
"""

from __future__ import annotations

import copy
import threading
from collections import deque
from typing import Dict, Any, List, Optional, Callable, Tuple

from loguru import logger
from core.runtime_state.models import HermesRuntimeState, MissionStatus, TaskStatus
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.reducer import StateReducer


class StateStore:
    """
    Authoritative owner of runtime state for a single mission.
    Provides thread-safe atomic event application and versioned snapshotting.
    """

    def __init__(self, mission_id: str, session_id: Optional[str] = None):
        self._lock = threading.Lock()
        self._state: HermesRuntimeState = HermesRuntimeState.create_empty(mission_id, session_id)
        self._subscribers: List[Callable[[HermesRuntimeState, HermesEvent], None]] = []
        self._recent_events: deque[HermesEvent] = deque(maxlen=50)
        self.workspace_files_count: int = 0

    # ── State Store Core API ──────────────────────────────────────────────────

    def apply_event(self, event: HermesEvent) -> HermesRuntimeState:
        """
        Atomically apply event via pure StateReducer.
        Increments state_version, updates causal sequences, and dispatches to observers.
        """
        with self._lock:
            # Record in recent events
            self._recent_events.append(event)

            # Special case for legacy workspace_scan_completed
            if event.event_type == EventType.WORKSPACE_SCAN_COMPLETED:
                self.workspace_files_count = event.payload.get("files_indexed", self.workspace_files_count)

            # Pure reduction
            self._state = StateReducer.reduce(self._state, event)

        # Notify observers outside the lock with failure isolation
        if self._subscribers:
            snapshot = copy.deepcopy(self._state)
            for subscriber in self._subscribers:
                try:
                    subscriber(snapshot, event)
                except Exception as exc:
                    logger.warning("StateStore subscriber exception: {}", exc)

        return self._state

    def get_state(self) -> HermesRuntimeState:
        """Return the current authoritative runtime state."""
        with self._lock:
            return self._state

    def get_snapshot(self) -> HermesRuntimeState:
        """Return an immutable, isolated deep copy of the authoritative state."""
        with self._lock:
            return copy.deepcopy(self._state)

    def subscribe(self, callback: Callable[[HermesRuntimeState, HermesEvent], None]) -> None:
        """Register an observer for state mutations."""
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[HermesRuntimeState, HermesEvent], None]) -> None:
        """Unregister an observer."""
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s != callback]

    def replay(self, events: List[HermesEvent], initial_state: Optional[HermesRuntimeState] = None) -> HermesRuntimeState:
        """
        Replay an ordered list of events deterministically.
        Guarantees identical outcomes given the same initial state and event sequence.
        """
        with self._lock:
            current = copy.deepcopy(initial_state) if initial_state else HermesRuntimeState.create_empty(self._state.mission.mission_id)
            for ev in events:
                current = StateReducer.reduce(current, ev)
            self._state = current
            return copy.deepcopy(self._state)

    # ── Backward Compatibility with ExecutionStateStore ───────────────────────

    @property
    def mission_id(self) -> str:
        return self._state.mission.mission_id

    @property
    def status(self) -> str:
        return self._state.mission.status.value

    @status.setter
    def status(self, val: str) -> None:
        with self._lock:
            try:
                self._state.mission.status = MissionStatus(val)
            except ValueError:
                pass

    @property
    def current_task_id(self) -> Optional[str]:
        return self._state.mission.current_task_id

    @current_task_id.setter
    def current_task_id(self, val: Optional[str]) -> None:
        with self._lock:
            self._state.mission.current_task_id = val

    @property
    def current_model(self) -> Optional[str]:
        m = self._state.model_execution.model
        return m if m else None

    @current_model.setter
    def current_model(self, val: Optional[str]) -> None:
        with self._lock:
            self._state.model_execution.model = val or ""

    @property
    def current_tool(self) -> Optional[str]:
        t = self._state.tool_execution.tool_name
        return t if t else None

    @current_tool.setter
    def current_tool(self, val: Optional[str]) -> None:
        with self._lock:
            self._state.tool_execution.tool_name = val

    @property
    def verification_state(self) -> str:
        return self._state.verification.status.value

    @verification_state.setter
    def verification_state(self, val: str) -> None:
        pass

    @property
    def repair_state(self) -> str:
        cid = self._state.mission.current_task_id
        if cid and cid in self._state.tasks:
            return self._state.tasks[cid].repair_state
        return "NOT_REQUIRED"

    @repair_state.setter
    def repair_state(self, val: str) -> None:
        pass

    @property
    def last_sequence(self) -> int:
        return self._state.last_event_sequence

    @last_sequence.setter
    def last_sequence(self, val: int) -> None:
        with self._lock:
            self._state.last_event_sequence = val

    @property
    def recent_events(self) -> deque[HermesEvent]:
        return self._recent_events

    @property
    def progress(self) -> Tuple[int, int]:
        with self._lock:
            return (self._state.progress.completed_tasks, self._state.progress.total_tasks)

    @property
    def tasks(self) -> Dict[str, Dict[str, Any]]:
        """Legacy dictionary representation of tasks."""
        with self._lock:
            out = {}
            for tid, t in self._state.tasks.items():
                out[tid] = {
                    "task_id": t.task_id,
                    "title": t.title,
                    "status": t.status.value,
                    "dependencies": t.dependencies,
                    "current_iteration": t.current_iteration,
                }
            return out


# Legacy alias
ExecutionStateStore = StateStore
