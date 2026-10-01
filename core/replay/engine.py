# core/replay/engine.py
"""
Historical Replay Engine for HERMES 2.x (Prompt 16).

Central Invariants:
1. REPLAY IS NOT EXECUTION:
   - ZERO model calls
   - ZERO tool executions
   - ZERO shell executions
   - ZERO network requests
   - ZERO filesystem mutations
   - ZERO database writes
2. PURE RECONSTRUCTION: Uses StateReducer to rebuild authoritative runtime state deterministically from event history.
3. OUTPUT AGNOSTIC: Can project to Text, JSON, Stream-JSON, or TUI presentation sinks.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.runtime_state.reducer import StateReducer

logger = logging.getLogger("hermes.replay.engine")


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of historical event journal replay."""
    session_id: str
    events_replayed: int
    final_state: HermesRuntimeState
    success: bool
    duration_seconds: float
    error: Optional[str] = None


class ReplayEngine:
    """Reconstructs historical runtime state from persisted event journals without side effects."""

    def __init__(self, session_manager: Optional[Any] = None) -> None:
        self.session_manager = session_manager
        self.reducer = StateReducer()

    def replay_events(
        self,
        events: Sequence[HermesEvent],
        initial_mission_id: str = "replay_mission",
        sink: Optional[Callable[[HermesEvent, HermesRuntimeState], None]] = None,
    ) -> ReplayResult:
        """
        Deterministically reduce a sequence of historical events into authoritative state.
        Zero side effects.
        """
        start_time = time.monotonic()
        if not events:
            dummy_state = HermesRuntimeState(mission=MissionState(mission_id=initial_mission_id))
            return ReplayResult(
                session_id=initial_mission_id,
                events_replayed=0,
                final_state=dummy_state,
                success=True,
                duration_seconds=0.0,
            )

        # Initialize base state with first event's mission or fallback
        first_event = events[0]
        mission_id = first_event.mission_id or initial_mission_id
        session_id = first_event.session_id or "replay_session"

        state = HermesRuntimeState(
            mission=MissionState(
                mission_id=mission_id,
                session_id=session_id,
                title="Historical Replay",
            )
        )

        replayed_count = 0
        try:
            for event in events:
                # Pure state reduction
                state = self.reducer.reduce(state, event)
                replayed_count += 1

                # Notify presentation sink if provided
                if sink:
                    try:
                        sink(event, state)
                    except Exception as sink_err:
                        logger.warning(f"Replay presentation sink warning: {sink_err}")

            elapsed = time.monotonic() - start_time
            return ReplayResult(
                session_id=session_id,
                events_replayed=replayed_count,
                final_state=state,
                success=True,
                duration_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.exception(f"Error during replay reconstruction: {e}")
            return ReplayResult(
                session_id=session_id,
                events_replayed=replayed_count,
                final_state=state,
                success=False,
                duration_seconds=elapsed,
                error=str(e),
            )

    def replay_session(
        self,
        session_id: str,
        sink: Optional[Callable[[HermesEvent, HermesRuntimeState], None]] = None,
    ) -> ReplayResult:
        """Load and replay events for a session from the persistent SessionManager journal."""
        if not self.session_manager:
            dummy_state = HermesRuntimeState(mission=MissionState(mission_id=session_id))
            return ReplayResult(
                session_id=session_id,
                events_replayed=0,
                final_state=dummy_state,
                success=False,
                duration_seconds=0.0,
                error="SessionManager not configured on ReplayEngine.",
            )

        try:
            events = self.session_manager.journal.get_events(session_id)
            if not events:
                dummy_state = HermesRuntimeState(mission=MissionState(mission_id=session_id))
                return ReplayResult(
                    session_id=session_id,
                    events_replayed=0,
                    final_state=dummy_state,
                    success=False,
                    duration_seconds=0.0,
                    error=f"No recorded events found for session '{session_id}'.",
                )
            return self.replay_events(events, initial_mission_id=session_id, sink=sink)
        except Exception as e:
            dummy_state = HermesRuntimeState(mission=MissionState(mission_id=session_id))
            return ReplayResult(
                session_id=session_id,
                events_replayed=0,
                final_state=dummy_state,
                success=False,
                duration_seconds=0.0,
                error=f"Failed to read session journal: {e}",
            )

    def replay_trace_file(
        self,
        trace_path: Path | str,
        sink: Optional[Callable[[HermesEvent, HermesRuntimeState], None]] = None,
    ) -> ReplayResult:
        """Load and replay events from an export JSON / JSONL trace file."""
        path = Path(trace_path).resolve()
        if not path.exists():
            dummy_state = HermesRuntimeState(mission=MissionState(mission_id="unknown"))
            return ReplayResult(
                session_id="unknown",
                events_replayed=0,
                final_state=dummy_state,
                success=False,
                duration_seconds=0.0,
                error=f"Trace file not found: '{trace_path}'",
            )

        events: List[HermesEvent] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            if content.startswith("["):
                # JSON array
                records = json.loads(content)
            else:
                # JSONL lines
                records = [json.loads(line) for line in content.splitlines() if line.strip()]

            from core.runtime_state.events import EventType

            for r in records:
                evt_type_val = r.get("event_type") or r.get("type", "UNKNOWN")
                try:
                    et = EventType(evt_type_val)
                except ValueError:
                    et = EventType.GENERIC_EVENT

                events.append(
                    HermesEvent(
                        event_type=et,
                        event_id=r.get("event_id", ""),
                        session_id=r.get("session_id", "trace_session"),
                        mission_id=r.get("mission_id", "trace_mission"),
                        task_id=r.get("task_id"),
                        sequence=r.get("sequence", 0),
                        timestamp=r.get("timestamp", time.time()),
                        payload=r.get("payload", {}),
                    )
                )

            return self.replay_events(events, initial_mission_id=path.stem, sink=sink)

        except Exception as e:
            dummy_state = HermesRuntimeState(mission=MissionState(mission_id=path.stem))
            return ReplayResult(
                session_id=path.stem,
                events_replayed=0,
                final_state=dummy_state,
                success=False,
                duration_seconds=0.0,
                error=f"Corrupt or invalid trace file: {e}",
            )
