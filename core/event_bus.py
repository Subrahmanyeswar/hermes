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

import queue
import threading
import time
from collections import deque
from typing import Dict, Any, List, Optional, Callable, Set, Tuple, Union

from loguru import logger
from config.model_config import EVENT_BUS_ENABLED, EVENT_BUS_BUFFER_SIZE

from core.persistence.database import SQLiteDatabase, get_canonical_database_path
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
    Connects runtime execution to the authoritative StateStore, distributed observers,
    and durable SQLite persistence journal.
    """

    def __init__(
        self,
        enabled: bool = EVENT_BUS_ENABLED,
        buffer_size: int = EVENT_BUS_BUFFER_SIZE,
        db: Optional[SQLiteDatabase] = None,
    ):
        self.enabled = enabled
        self.buffer_size = buffer_size
        self._lock = threading.Lock()
        self._sequence_counter = 0
        self._db = db
        if self._db is not None:
            try:
                self._sequence_counter = self._db.get_max_event_sequence()
            except Exception:
                pass
        self._history: deque[HermesEvent] = deque(maxlen=buffer_size)
        self._subscribers: List[Tuple[Callable[[HermesEvent], None], Optional[Set[EventType]]]] = []
        self._state_stores: Dict[str, StateStore] = {}
        self._seen_event_ids: Set[str] = set()

        # Phase 2 Durable Persistence Engine
        self._persist_queue: queue.Queue = queue.Queue()
        self._persist_stop_event = threading.Event()
        self._persist_thread: Optional[threading.Thread] = None
        self._persistence_failures: deque = deque(maxlen=1000)
        self._start_persistence_worker()

    def set_database(self, db: SQLiteDatabase) -> None:
        """Bind or rebind canonical database store."""
        with self._lock:
            self._db = db
            try:
                max_s = db.get_max_event_sequence()
                if max_s > self._sequence_counter:
                    self._sequence_counter = max_s
            except Exception:
                pass

    def get_database(self) -> Optional[SQLiteDatabase]:
        """Return canonical database store."""
        if self._db is None:
            try:
                self._db = SQLiteDatabase()
                with self._lock:
                    max_s = self._db.get_max_event_sequence()
                    if max_s > self._sequence_counter:
                        self._sequence_counter = max_s
            except Exception as e:
                logger.warning(f"EventBus: lazy SQLite initialization warning: {e}")
        return self._db

    def _start_persistence_worker(self) -> None:
        """Start daemon background thread to write journal events in strict monotonic order."""
        self._persist_thread = threading.Thread(
            target=self._persistence_worker_loop,
            name="HermesEventBusJournalWorker",
            daemon=True,
        )
        self._persist_thread.start()

    def _persistence_worker_loop(self) -> None:
        """Background thread writing queued events to SQLiteDatabase with atomic micro-batching."""
        while not self._persist_stop_event.is_set() or not self._persist_queue.empty():
            try:
                first_item = self._persist_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            batch_items = [first_item]
            while len(batch_items) < 100:
                try:
                    batch_items.append(self._persist_queue.get_nowait())
                except queue.Empty:
                    break

            # Group events by target database instance
            db_groups: Dict[Any, List[Any]] = {}
            for event, db_instance in batch_items:
                target_db = db_instance or self.get_database()
                if target_db not in db_groups:
                    db_groups[target_db] = []
                db_groups[target_db].append(event)

            try:
                for target_db, events in db_groups.items():
                    if target_db:
                        try:
                            if hasattr(target_db, "append_mission_events_batch"):
                                target_db.append_mission_events_batch(events)
                            else:
                                for ev in events:
                                    target_db.append_mission_event(ev)
                        except Exception as exc:
                            logger.warning(f"EventBus: batch persistence failed ({exc}), falling back to individual inserts with retry...")
                            for ev in events:
                                persisted = False
                                for attempt in range(3):
                                    try:
                                        target_db.append_mission_event(ev)
                                        persisted = True
                                        break
                                    except Exception as ind_exc:
                                        time.sleep(0.01 * (attempt + 1))
                                if not persisted:
                                    logger.error(f"EventBus: event {getattr(ev, 'event_id', str(ev))} failed durable journal commit after retries")
                                    self._persistence_failures.append((ev, str(exc)))
            finally:
                for _ in batch_items:
                    self._persist_queue.task_done()

    def flush(self, timeout: float = 5.0) -> None:
        """Wait for all pending journal writes to commit to disk."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._persist_queue.all_tasks_done:
                if self._persist_queue.unfinished_tasks == 0:
                    return
                remaining = max(0.001, deadline - time.time())
                self._persist_queue.all_tasks_done.wait(timeout=min(0.05, remaining))

    def shutdown(self, timeout: float = 5.0) -> None:
        """Gracefully stop background persistence worker after flushing queue."""
        self.flush(timeout=timeout)
        self._persist_stop_event.set()
        if self._persist_thread and self._persist_thread.is_alive():
            self._persist_thread.join(timeout=timeout)

    def get_persistence_failures(self) -> List[Tuple[Any, str]]:
        """Return list of events that failed durable SQLite persistence."""
        return list(self._persistence_failures)

    def clear_persistence_failures(self) -> None:
        """Clear recorded persistence failures."""
        self._persistence_failures.clear()

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

            # Store in in-memory event ring buffer
            self._history.append(event)

            # Get or create authoritative state store
            if event.mission_id not in self._state_stores:
                self._state_stores[event.mission_id] = StateStore(event.mission_id)
            store = self._state_stores[event.mission_id]

            # Enqueue to background journal writer for durable persistence
            db_inst = self._db
            self._persist_queue.put((event, db_inst))

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

    def publish_durable(
        self,
        event_or_type: Union[HermesEvent, EventType, str],
        payload: Optional[Dict[str, Any]] = None,
        mission_id: Optional[str] = None,
    ) -> HermesEvent:
        """
        Publish event and synchronously commit to SQLite database BEFORE returning.
        Guarantees write-ahead durability for operations, state transitions, and checkpoints.
        Raises ToolPersistenceError if the database commit fails.
        """
        from core.persistence.models import ToolPersistenceError

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

        target_db = self.get_database()
        if target_db is None:
            raise ToolPersistenceError("Database is not configured; durable commit impossible.")

        with self._lock:
            # Deduplication check
            if event.event_id in self._seen_event_ids:
                return event

            self._seen_event_ids.add(event.event_id)
            if len(self._seen_event_ids) > 10000:
                self._seen_event_ids.clear()

            self._sequence_counter += 1
            event.sequence = self._sequence_counter

            if event.mission_id not in self._state_stores:
                self._state_stores[event.mission_id] = StateStore(event.mission_id)
            store = self._state_stores[event.mission_id]

            subscribers_snapshot = list(self._subscribers)

        # Synchronously write and commit directly to SQLite outside lock BEFORE adding to history or broadcasting
        try:
            target_db.append_mission_event(event)
        except Exception as exc:
            with self._lock:
                self._seen_event_ids.discard(event.event_id)
            logger.error(f"EventBus: synchronous durable commit failed for event {event.event_id}: {exc}")
            raise ToolPersistenceError(f"Failed to durably commit event {event.event_id}: {exc}") from exc

        # Once durably committed to SQLite, record in memory ring buffer
        with self._lock:
            self._history.append(event)

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

    def replay(self, mission_id: str, from_seq: int = 0, to_seq: Optional[int] = None) -> List[HermesEvent]:
        """
        Return stored events for mission.
        Checks in-memory history first; if the requested range extends beyond the in-memory
        ring buffer, queries the authoritative SQLite database journal.
        """
        with self._lock:
            mem_events = [
                e for e in self._history
                if e.mission_id == mission_id
                and e.sequence >= from_seq
                and (to_seq is None or e.sequence <= to_seq)
            ]
            oldest_mem_seq = self._history[0].sequence if self._history else float("inf")

        # If from_seq is older than the oldest event in memory buffer, or memory returned nothing,
        # fallback to querying the durable SQLite database journal
        if not mem_events or from_seq < oldest_mem_seq:
            db = self.get_database()
            if db:
                try:
                    # Flush pending writes first to ensure journal is up to date
                    self.flush(timeout=0.2)
                    raw_records = db.get_mission_events(mission_id, from_seq=from_seq, to_seq=to_seq)
                    db_events: List[HermesEvent] = []
                    for r in raw_records:
                        p = r.get("payload", {})
                        # If p was serialized from event.to_dict(), the actual event payload is inside p.get("payload")
                        actual_payload = p.get("payload") if isinstance(p.get("payload"), dict) else p
                        et_val = r.get("event_type", "GENERIC_EVENT")
                        try:
                            et = EventType(et_val)
                        except Exception:
                            et = EventType.GENERIC_EVENT
                        ev = HermesEvent(
                            event_type=et,
                            mission_id=r.get("mission_id", mission_id),
                            run_id=r.get("run_id"),
                            attempt_number=r.get("attempt_number", 1),
                            sequence=r.get("sequence", 0),
                            event_id=r.get("event_id", ""),
                            timestamp=r.get("timestamp", 0.0),
                            payload=actual_payload,
                        )
                        db_events.append(ev)
                    if db_events:
                        combined = {e.sequence: e for e in db_events}
                        for e in mem_events:
                            combined[e.sequence] = e
                        return sorted(combined.values(), key=lambda x: x.sequence)
                except Exception as exc:
                    logger.warning(f"EventBus: DB replay query fallback encountered error: {exc}")

        return mem_events


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
