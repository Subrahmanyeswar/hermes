# core/persistence/journal.py
"""
Append-only event journal and deterministic replay engine for HERMES 2.x.

Core Invariants:
1. STRICT MONOTONICITY: Every persisted event receives a strictly increasing sequence.
2. IMMUTABLE COMMITS: Events cannot be modified once appended.
3. REPLAY NEVER EXECUTES TOOLS: State reconstruction is a pure mathematical state reduction.
4. CORRUPTED TAIL SAFETY: Truncated or corrupt event tails are detected safely.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from core.persistence.database import SQLiteDatabase
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore

logger = logging.getLogger("hermes.persistence.journal")


class EventJournal:
    """
    Durable append-only event journal.
    Supports causal tracking, monotonic event sequencing, and side-effect-free replay.
    """

    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def append(self, session_id: str, event: HermesEvent) -> int:
        """
        Append an event to the session journal.
        Assigns the next monotonic sequence number and commits atomically.
        """
        max_seq = self.db.get_max_journal_sequence(session_id)
        next_seq = max_seq + 1
        event.sequence = next_seq

        payload_bytes = json.dumps(event.payload, sort_keys=True).encode("utf-8")
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        self.db.append_journal_entry(
            session_id=session_id,
            sequence=next_seq,
            event_id=event.event_id,
            event_type=event.event_type.value,
            payload_hash=payload_hash,
            payload_json=json.dumps(event.payload, sort_keys=True),
            timestamp=event.timestamp,
        )
        return next_seq

    def get_events(
        self,
        session_id: str,
        from_seq: int = 1,
        to_seq: Optional[int] = None,
    ) -> List[HermesEvent]:
        """Load journal events into typed HermesEvent objects."""
        rows = self.db.get_journal_entries(session_id, from_seq=from_seq, to_seq=to_seq)
        events: List[HermesEvent] = []

        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                ev = HermesEvent(
                    event_type=EventType(row["event_type"]),
                    mission_id="",
                    event_id=row["event_id"],
                    timestamp=row["timestamp"],
                    sequence=row["sequence"],
                    session_id=session_id,
                    payload=payload,
                )
                events.append(ev)
            except Exception as exc:
                logger.warning("Corrupted journal entry sequence={} in session={}: {}", row.get("sequence"), session_id, exc)
                # Fail-safe: stop reading at the first corrupt tail entry
                break

        return events

    def replay(
        self,
        session_id: str,
        initial_state: HermesRuntimeState,
        from_seq: int = 1,
        to_seq: Optional[int] = None,
    ) -> HermesRuntimeState:
        """
        Deterministically reconstruct HermesRuntimeState by replaying journal events.
        CRITICAL INVARIANT: ZERO side-effects or tool calls executed during replay.
        """
        events = self.get_events(session_id, from_seq=from_seq, to_seq=to_seq)
        state = initial_state

        for ev in events:
            state = StateReducer.reduce(state, ev)

        return state
