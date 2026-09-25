# core/event_bus.py
"""
Unified Event Bus + Authoritative State Management for HERMES 2.x.
Integrates the canonical EventBus with the authoritative StateStore, providing:
- Monotonic sequence numbering
- Deduplication by event_id
- Strict subscriber failure isolation
- Monotonically versioned state reduction
- Complete backward compatibility with Phase 14 / Gate 15 contracts
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, Any, List, Optional, Callable, Set, Tuple, Union

from loguru import logger
from config.model_config import EVENT_BUS_ENABLED, EVENT_BUS_BUFFER_SIZE

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionState,
    MissionStatus,
    TaskState,
    TaskStatus,
    ToolExecutionState,
    ModelExecutionState,
    VerificationState,
    NetworkState,
    PermissionState,
)
from core.runtime_state.events import (
    HermesEvent,
    Event,
    EventType,
    EventSeverity,
    redact_sensitive_payload,
)
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore, ExecutionStateStore
from core.runtime_state.selectors import ViewModelBuilder, HermesViewModelBundle


class EventBus:
    """
    Centralized, thread-safe, non-blocking Event Bus for HERMES.
    Connects runtime execution to the authoritative StateStore and distributed observers.
    """

    def __init__(self, enabled: bool = EVENT_BUS_ENABLED, buffer_size: int = EVENT_BUS_BUFFER_SIZE):
        self.enabled = enabled
        self.buffer_size = buffer_size
        self._lock = threading.Lock()
        self._sequence_counter = 0
        self._history: deque[HermesEvent] = deque(maxlen=buffer_size)
        self._subscribers: List[Tuple[Callable[[HermesEvent], None], Optional[Set[EventType]]]] = []
        self._state_stores: Dict[str, StateStore] = {}
        self._seen_event_ids: Set[str] = set()

    def subscribe(
        self,
        handler: Callable[[HermesEvent], None],
        event_types: Optional[Set[EventType]] = None
    ) -> None:
        """Register subscriber. Isolated from exceptions during dispatch."""
        with self._lock:
            self._subscribers.append((handler, event_types))

    def unsubscribe(self, handler: Callable[[HermesEvent], None]) -> None:
        """Remove subscriber."""
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s[0] != handler]

    def publish(
        self,
        event_or_type: Union[HermesEvent, EventType, str],
        payload: Optional[Dict[str, Any]] = None,
        mission_id: Optional[str] = None,
    ) -> HermesEvent:
        """
        Publish event to state store and all subscribers.
        Supports both canonical HermesEvent objects and legacy (event_type, payload) calls.
        """
        if not self.enabled:
            if isinstance(event_or_type, HermesEvent):
                return event_or_type
            et = EventType(event_or_type) if isinstance(event_or_type, str) else event_or_type
            return HermesEvent(event_type=et, mission_id=mission_id or "default", payload=payload or {})

        # Normalize to canonical HermesEvent
        if isinstance(event_or_type, HermesEvent):
            event = event_or_type
        else:
            et = EventType(event_or_type) if isinstance(event_or_type, str) else event_or_type
            m_id = mission_id or (payload.get("mission_id") if payload else "default") or "default"
            t_id = payload.get("task_id") if payload else None
            event = HermesEvent(
                event_type=et,
                mission_id=m_id,
                task_id=t_id,
                payload=payload or {},
            )

        with self._lock:
            # Deduplication check
            if event.event_id in self._seen_event_ids:
                return event

            self._seen_event_ids.add(event.event_id)
            if len(self._seen_event_ids) > 10000:
                # Prune oldest seen event IDs to bound memory
                self._seen_event_ids.clear()

            self._sequence_counter += 1
            event.sequence = self._sequence_counter

            # Store in event history
            self._history.append(event)

            # Get or create authoritative state store
            if event.mission_id not in self._state_stores:
                self._state_stores[event.mission_id] = StateStore(event.mission_id)
            store = self._state_stores[event.mission_id]

            subscribers_snapshot = list(self._subscribers)

        # Apply to authoritative state store
        store.apply_event(event)

        # Dispatch to subscribers with failure isolation
        for handler, filter_types in subscribers_snapshot:
            if filter_types is None or event.event_type in filter_types:
                try:
                    handler(event)
                except Exception as exc:
                    logger.warning(
                        "EventBus: Subscriber '{}' threw exception: {}",
                        getattr(handler, '__name__', str(handler)),
                        exc
                    )

        return event

    def get_state(self, mission_id: str) -> Optional[StateStore]:
        """Get authoritative StateStore for mission (satisfies ExecutionStateStore interface)."""
        with self._lock:
            return self._state_stores.get(mission_id)

    def get_or_create_state(self, mission_id: str) -> StateStore:
        """Get or initialize authoritative StateStore for mission."""
        with self._lock:
            if mission_id not in self._state_stores:
                self._state_stores[mission_id] = StateStore(mission_id)
            return self._state_stores[mission_id]

    def replay(self, mission_id: str) -> List[HermesEvent]:
        """Return all stored events for mission."""
        with self._lock:
            return [e for e in self._history if e.mission_id == mission_id]


# Global singleton
event_bus = EventBus()

__all__ = [
    "HermesEvent",
    "Event",
    "EventType",
    "EventSeverity",
    "ExecutionStateStore",
    "StateStore",
    "StateReducer",
    "HermesRuntimeState",
    "ViewModelBuilder",
    "HermesViewModelBundle",
    "EventBus",
    "event_bus",
]
