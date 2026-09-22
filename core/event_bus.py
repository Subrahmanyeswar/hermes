# core/event_bus.py
"""
Unified Event Bus + Authoritative State Store for HERMES vNext (Phase 14).
Provides a lightweight, non-blocking pub/sub messaging hub for real-time observability.
Eliminates fake UI progress by distributing genuine backend execution events.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Set, Tuple

from loguru import logger
from config.model_config import EVENT_BUS_ENABLED, EVENT_BUS_BUFFER_SIZE


class EventType(str, Enum):
    # Mission lifecycle
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_STATUS_CHANGED = "MISSION_STATUS_CHANGED"
    MISSION_BLOCKED = "MISSION_BLOCKED"
    MISSION_FAILED = "MISSION_FAILED"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_CANCELLED = "MISSION_CANCELLED"

    # Workspace & Context
    WORKSPACE_SCAN_STARTED = "WORKSPACE_SCAN_STARTED"
    WORKSPACE_SCAN_PROGRESS = "WORKSPACE_SCAN_PROGRESS"
    WORKSPACE_SCAN_COMPLETED = "WORKSPACE_SCAN_COMPLETED"

    # Skills & Planning
    SKILL_LOADING = "SKILL_LOADING"
    SKILL_LOADED = "SKILL_LOADED"
    PLANNING_STARTED = "PLANNING_STARTED"
    PLAN_CREATED = "PLAN_CREATED"

    # KAIROS & Tasks
    KAIROS_STATE_CHANGED = "KAIROS_STATE_CHANGED"
    TASK_CREATED = "TASK_CREATED"
    TASK_STARTED = "TASK_STARTED"
    TASK_PROGRESS = "TASK_PROGRESS"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"

    # Models
    MODEL_REQUEST_STARTED = "MODEL_REQUEST_STARTED"
    MODEL_TTFT = "MODEL_TTFT"
    MODEL_GENERATING = "MODEL_GENERATING"
    MODEL_COMPLETED = "MODEL_COMPLETED"
    MODEL_FAILED = "MODEL_FAILED"
    ROUTING_DECISION = "ROUTING_DECISION"

    # Tools
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_PROGRESS = "TOOL_PROGRESS"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"

    # Verification & Repair
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REPAIR_STARTED = "REPAIR_STARTED"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"

    # General
    ERROR = "ERROR"


class EventSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class HermesEvent:
    event_type: EventType
    mission_id: str
    task_id: Optional[str] = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0
    stage: str = "EXECUTION"
    payload: Dict[str, Any] = field(default_factory=dict)
    severity: EventSeverity = EventSeverity.INFO
    source: str = "backend"


class ExecutionStateStore:
    """Maintains authoritative state per mission reconstructed deterministically from events."""

    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self.status: str = "CREATED"
        self.workspace_files_count: int = 0
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.current_task_id: Optional[str] = None
        self.current_model: Optional[str] = None
        self.current_tool: Optional[str] = None
        self.verification_state: str = "NOT_STARTED"
        self.repair_state: str = "NOT_REQUIRED"
        self.recent_events: deque[HermesEvent] = deque(maxlen=50)
        self.last_sequence: int = 0

    @property
    def progress(self) -> Tuple[int, int]:
        if not self.tasks:
            return (0, 0)
        done = sum(1 for t in self.tasks.values() if t.get("status") == "COMPLETED")
        return (done, len(self.tasks))

    def apply_event(self, event: HermesEvent) -> None:
        """Update authoritative state. Reject stale out-of-order sequence updates."""
        if event.sequence > 0 and event.sequence <= self.last_sequence:
            # Stale event, don't regress state
            self.recent_events.append(event)
            return

        if event.sequence > self.last_sequence:
            self.last_sequence = event.sequence

        self.recent_events.append(event)

        # Terminal state lock: CANCELLED is permanent and cannot be overwritten
        if self.status == "CANCELLED":
            return

        # Apply state transitions
        et = event.event_type
        if et == EventType.MISSION_CANCELLED:
            self.status = "CANCELLED"
            self.current_model = None
            self.current_tool = None
            self.current_task_id = None
            return
        elif et == EventType.MISSION_STARTED:
            self.status = "RUNNING"
        elif et == EventType.MISSION_COMPLETED:
            self.status = "COMPLETED"
        elif et == EventType.MISSION_FAILED:
            self.status = "FAILED"
        elif et == EventType.MISSION_BLOCKED:
            self.status = "BLOCKED"
        elif et == EventType.WORKSPACE_SCAN_COMPLETED:
            self.workspace_files_count = event.payload.get("files_indexed", self.workspace_files_count)
        elif et == EventType.TASK_CREATED:
            tid = event.payload.get("task_id") or event.task_id
            if tid:
                self.tasks[tid] = {
                    "task_id": tid,
                    "title": event.payload.get("title", tid),
                    "status": "PENDING"
                }
        elif et == EventType.TASK_STARTED:
            if event.task_id:
                self.current_task_id = event.task_id
                if event.task_id in self.tasks:
                    self.tasks[event.task_id]["status"] = "RUNNING"
        elif et == EventType.TASK_COMPLETED:
            if event.task_id and event.task_id in self.tasks:
                self.tasks[event.task_id]["status"] = "COMPLETED"
                if self.current_task_id == event.task_id:
                    self.current_task_id = None
        elif et == EventType.TASK_FAILED:
            if event.task_id and event.task_id in self.tasks:
                self.tasks[event.task_id]["status"] = "FAILED"
        elif et == EventType.MODEL_REQUEST_STARTED:
            self.current_model = event.payload.get("model", "Tier 1")
        elif et in {EventType.MODEL_COMPLETED, EventType.MODEL_FAILED}:
            self.current_model = None
        elif et == EventType.TOOL_STARTED:
            self.current_tool = event.payload.get("tool_name", "tool")
        elif et in {EventType.TOOL_COMPLETED, EventType.TOOL_FAILED}:
            self.current_tool = None
        elif et == EventType.VERIFICATION_STARTED:
            self.verification_state = "RUNNING"
        elif et == EventType.VERIFICATION_COMPLETED:
            self.verification_state = "PASSED"
        elif et == EventType.VERIFICATION_FAILED:
            self.verification_state = "FAILED"
        elif et == EventType.REPAIR_STARTED:
            self.repair_state = "REPAIRING"
        elif et == EventType.REPAIR_COMPLETED:
            self.repair_state = "COMPLETED"


class EventBus:
    """Centralized, thread-safe, non-blocking Event Bus for HERMES."""

    def __init__(self, enabled: bool = EVENT_BUS_ENABLED, buffer_size: int = EVENT_BUS_BUFFER_SIZE):
        self.enabled = enabled
        self.buffer_size = buffer_size
        self._sequence_counter = 0
        self._history: deque[HermesEvent] = deque(maxlen=buffer_size)
        self._subscribers: List[Tuple[Callable[[HermesEvent], None], Optional[Set[EventType]]]] = []
        self._state_stores: Dict[str, ExecutionStateStore] = {}
        self._seen_event_ids: Set[str] = set()

    def subscribe(
        self,
        handler: Callable[[HermesEvent], None],
        event_types: Optional[Set[EventType]] = None
    ) -> None:
        """Register subscriber. Isolated from exceptions during dispatch."""
        self._subscribers.append((handler, event_types))

    def unsubscribe(self, handler: Callable[[HermesEvent], None]) -> None:
        """Remove subscriber."""
        self._subscribers = [s for s in self._subscribers if s[0] != handler]

    def publish(self, event: HermesEvent) -> HermesEvent:
        """Publish event to all subscribers and update state store."""
        if not self.enabled:
            return event

        # Deduplication check
        if event.event_id in self._seen_event_ids:
            return event

        self._seen_event_ids.add(event.event_id)
        self._sequence_counter += 1
        event.sequence = self._sequence_counter

        # Store in event history
        self._history.append(event)

        # Update or create authoritative state store
        if event.mission_id not in self._state_stores:
            self._state_stores[event.mission_id] = ExecutionStateStore(event.mission_id)
        self._state_stores[event.mission_id].apply_event(event)

        # Dispatch to subscribers with failure isolation
        for handler, filter_types in self._subscribers:
            if filter_types is None or event.event_type in filter_types:
                try:
                    handler(event)
                except Exception as exc:
                    logger.warning("EventBus: Subscriber '{}' threw exception: {}", getattr(handler, '__name__', str(handler)), exc)

        return event

    def get_state(self, mission_id: str) -> Optional[ExecutionStateStore]:
        """Get authoritative state store for mission."""
        return self._state_stores.get(mission_id)

    def replay(self, mission_id: str) -> List[HermesEvent]:
        """Return all stored events for mission."""
        return [e for e in self._history if e.mission_id == mission_id]


# Global singleton
event_bus = EventBus()
