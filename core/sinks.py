# core/sinks.py
"""
Reusable Presentation Event Sinks for HERMES 2.x (Prompt 16).

Central Invariants:
1. OUTPUT SEPARATION: Clean separation of stdout (machine/agent data) and stderr (diagnostics).
2. STRUCTURED FORMATS: Valid JSON and Stream-JSON (NDJSON) without stray tracebacks or ANSI escapes.
3. BOUNDED BUFFERING: Swallows BrokenPipeError and handles terminal disconnects without corrupting runtime state.
"""

from __future__ import annotations

import io
import json
import sys
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TextIO

from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState
from ui.rendering.text_safety import sanitize_terminal_text


class EventSink(ABC):
    """Abstract interface for receiving runtime events and formatting output."""

    @abstractmethod
    def on_event(self, event: HermesEvent, state: Optional[HermesRuntimeState] = None) -> None:
        """Process an individual runtime event."""
        pass

    @abstractmethod
    def on_completed(
        self,
        final_state: HermesRuntimeState,
        exit_code: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Handle mission or command completion and render final presentation."""
        pass


class TextSink(EventSink):
    """Human-readable streaming text sink for terminal and CLI run."""

    def __init__(
        self,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
        quiet: bool = False,
    ):
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.quiet = quiet

    def on_event(self, event: HermesEvent, state: Optional[HermesRuntimeState] = None) -> None:
        if self.quiet:
            return

        et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        payload = event.payload or {}

        try:
            if et == "MISSION_STARTED":
                prompt = payload.get("prompt", "")
                self._safe_write(self.stdout, f"\n[HERMES] Mission Started: {prompt}\n")

            elif et == "MODEL_STREAM_CHUNK":
                chunk = payload.get("delta", "") or payload.get("text", "")
                self._safe_write(self.stdout, sanitize_terminal_text(chunk, allow_newlines=True))

            elif et == "TOOL_STARTED":
                tool = payload.get("tool_name", "tool")
                self._safe_write(self.stderr, f"\n-> Executing tool: {tool}...\n")

            elif et == "TOOL_COMPLETED":
                tool = payload.get("tool_name", "tool")
                exit_code = payload.get("exit_code", 0)
                dur = payload.get("duration_seconds", 0.0)
                self._safe_write(self.stderr, f"<- Tool {tool} completed (exit={exit_code}, {dur:.2f}s)\n")

            elif et == "SECURITY_DENIED":
                action = payload.get("action", "")
                self._safe_write(self.stderr, f"\n[SECURITY] Action DENIED: {action}\n")

            elif et == "MISSION_COMPLETED":
                self._safe_write(self.stdout, "\n[HERMES] Mission Completed Successfully.\n")

            elif et == "MISSION_FAILED":
                err = payload.get("error", "Unknown error")
                self._safe_write(self.stderr, f"\n[HERMES] Mission Failed: {err}\n")

        except Exception:
            pass

    def on_completed(
        self,
        final_state: HermesRuntimeState,
        exit_code: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        m = final_state.mission
        status_str = m.status.value if hasattr(m.status, "value") else str(m.status)
        summary = (
            f"\n"
            f"============================================================\n"
            f"Status:     {status_str}\n"
            f"Mission ID: {m.mission_id}\n"
            f"Exit Code:  {exit_code}\n"
        )
        if error_message:
            summary += f"Error:      {error_message}\n"
        summary += "============================================================\n"
        self._safe_write(self.stdout if exit_code == 0 else self.stderr, summary)

    def _safe_write(self, stream: TextIO, text: str) -> None:
        try:
            stream.write(text)
            stream.flush()
        except (BrokenPipeError, OSError):
            pass


class JsonSink(EventSink):
    """Machine-readable JSON sink for automation, scripting, and CI."""

    def __init__(self, stdout: Optional[TextIO] = None, stderr: Optional[TextIO] = None):
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.events_collected: List[Dict[str, Any]] = []
        self._start_time = time.monotonic()

    def on_event(self, event: HermesEvent, state: Optional[HermesRuntimeState] = None) -> None:
        et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        self.events_collected.append({
            "type": et,
            "timestamp": event.timestamp,
            "payload": event.payload or {},
        })

    def on_completed(
        self,
        final_state: HermesRuntimeState,
        exit_code: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        m = final_state.mission
        s = final_state.session
        elapsed = time.monotonic() - self._start_time

        tasks_summary = [
            {"id": t.task_id, "title": t.title, "status": t.status.value}
            for t in final_state.tasks.values()
        ]

        result_obj = {
            "status": m.status.value if hasattr(m.status, "value") else str(m.status),
            "mission_id": m.mission_id,
            "session_id": s.session_id,
            "exit_code": exit_code,
            "duration_seconds": round(elapsed, 3),
            "goal": final_state.goal.description if (hasattr(final_state, "goal") and final_state.goal) else "",
            "tasks": tasks_summary,
            "events_count": len(self.events_collected),
            "checkpoint_id": s.last_checkpoint_id,
            "error": error_message or m.abort_reason,
        }

        json_text = json.dumps(result_obj, indent=2)
        try:
            self.stdout.write(json_text + "\n")
            self.stdout.flush()
        except (BrokenPipeError, OSError):
            pass


class StreamJsonSink(EventSink):
    """Newline-delimited JSON (NDJSON) streaming sink."""

    def __init__(self, stdout: Optional[TextIO] = None):
        self.stdout = stdout or sys.stdout

    def on_event(self, event: HermesEvent, state: Optional[HermesRuntimeState] = None) -> None:
        et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        record = {
            "event": et,
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "session_id": event.session_id,
            "mission_id": event.mission_id,
            "payload": event.payload or {},
        }
        line = json.dumps(record) + "\n"
        try:
            self.stdout.write(line)
            self.stdout.flush()
        except (BrokenPipeError, OSError):
            pass

    def on_completed(
        self,
        final_state: HermesRuntimeState,
        exit_code: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        record = {
            "event": "TERMINATION",
            "status": final_state.mission.status.value if hasattr(final_state.mission.status, "value") else str(final_state.mission.status),
            "exit_code": exit_code,
            "error": error_message,
        }
        try:
            self.stdout.write(json.dumps(record) + "\n")
            self.stdout.flush()
        except (BrokenPipeError, OSError):
            pass


class NullSink(EventSink):
    """Discards all output (useful for benchmarking and tests)."""

    def on_event(self, event: HermesEvent, state: Optional[HermesRuntimeState] = None) -> None:
        pass

    def on_completed(
        self,
        final_state: HermesRuntimeState,
        exit_code: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        pass
