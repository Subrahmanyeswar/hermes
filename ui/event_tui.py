# ui/event_tui.py
"""
Event-Driven TUI Subscriber for HERMES vNext (Prompt 7).
Renders truthful, real-time backend state from the Unified Event Bus.
Eliminates vague spinner verbs with concrete observability and sub-millisecond
initial acknowledgement latency.
Tracks perceived vs actual latency metrics using high-resolution monotonic clocks.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from core.event_bus import HermesEvent, EventType, ExecutionStateStore, event_bus


@dataclass
class TUIResponsivenessTelemetry:
    """Prompt 7 responsiveness and perceived latency telemetry structure."""
    mission_id: str
    task_id: Optional[str] = None
    time_submit_mono: float = field(default_factory=time.perf_counter)
    time_first_event_ms: Optional[float] = None
    time_first_real_status_ms: Optional[float] = None
    time_first_token_ms: Optional[float] = None
    time_to_tool_dispatch_ms: Optional[float] = None
    time_to_first_verification_ms: Optional[float] = None
    time_to_completion_ms: Optional[float] = None
    total_wall_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "task_id": self.task_id or "N/A",
            "time_first_event_ms": round(self.time_first_event_ms, 3) if self.time_first_event_ms is not None else "N/A",
            "time_first_real_status_ms": round(self.time_first_real_status_ms, 3) if self.time_first_real_status_ms is not None else "N/A",
            "time_first_token_ms": round(self.time_first_token_ms, 3) if self.time_first_token_ms is not None else "N/A",
            "time_to_tool_dispatch_ms": round(self.time_to_tool_dispatch_ms, 3) if self.time_to_tool_dispatch_ms is not None else "N/A",
            "time_to_first_verification_ms": round(self.time_to_first_verification_ms, 3) if self.time_to_first_verification_ms is not None else "N/A",
            "time_to_completion_ms": round(self.time_to_completion_ms, 3) if self.time_to_completion_ms is not None else "N/A",
            "total_wall_ms": round(self.total_wall_ms, 3)
        }


class EventDrivenTUI:
    """Observer subscriber that renders clean truthful console state from the Event Bus."""

    def __init__(self, mission_id: str = ""):
        self.mission_id = mission_id
        self.last_rendered_text: str = ""
        self.telemetry = TUIResponsivenessTelemetry(mission_id=mission_id)
        self.lifecycle_stages: List[str] = []

    def start_mission_observation(self, mission_id: str) -> None:
        """Explicitly start observing a submitted mission and record submission monotonic mark."""
        self.mission_id = mission_id
        self.telemetry = TUIResponsivenessTelemetry(mission_id=mission_id)
        self.lifecycle_stages = ["MISSION RECEIVED"]
        self.render()

    def handle_event(self, event: HermesEvent) -> None:
        """Receive live event from event bus and update UI + responsiveness telemetry."""
        now_mono = time.perf_counter()
        elapsed_since_submit = (now_mono - self.telemetry.time_submit_mono) * 1000.0

        if not self.mission_id:
            self.mission_id = event.mission_id
            self.telemetry.mission_id = event.mission_id

        if event.mission_id == self.mission_id:
            # 1. First event latency
            if self.telemetry.time_first_event_ms is None:
                self.telemetry.time_first_event_ms = elapsed_since_submit

            # 2. First real status
            if self.telemetry.time_first_real_status_ms is None and event.event_type in {
                EventType.WORKSPACE_SCAN_COMPLETED,
                EventType.PLANNING_STARTED,
                EventType.TASK_STARTED
            }:
                self.telemetry.time_first_real_status_ms = elapsed_since_submit
                self.lifecycle_stages.append(event.event_type.value)

            # 3. Model first token / TTFT
            if self.telemetry.time_first_token_ms is None and event.event_type in {
                EventType.MODEL_TTFT,
                EventType.MODEL_GENERATING
            }:
                self.telemetry.time_first_token_ms = elapsed_since_submit

            # 4. Tool dispatch
            if self.telemetry.time_to_tool_dispatch_ms is None and event.event_type == EventType.TOOL_STARTED:
                self.telemetry.time_to_tool_dispatch_ms = elapsed_since_submit

            # 5. Verification
            if self.telemetry.time_to_first_verification_ms is None and event.event_type in {
                EventType.VERIFICATION_STARTED,
                EventType.VERIFICATION_COMPLETED
            }:
                self.telemetry.time_to_first_verification_ms = elapsed_since_submit

            # 6. Completion
            if event.event_type in {EventType.MISSION_COMPLETED, EventType.MISSION_FAILED, EventType.MISSION_CANCELLED}:
                self.telemetry.time_to_completion_ms = elapsed_since_submit
                self.telemetry.total_wall_ms = elapsed_since_submit
                self.lifecycle_stages.append(event.event_type.value)

            self.render()

    def redact_sensitive(self, text: str) -> str:
        """Redact API keys, tokens, and passwords from UI output."""
        text = re.sub(r"(sk-[a-zA-Z0-9_-]{12})[a-zA-Z0-9_-]+", r"\1***", text)
        text = re.sub(r'(password[:=\s]+)[^\s,]+', r'\1***', text, flags=re.IGNORECASE)
        # Strip any accidental chain-of-thought traces
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text

    def format_view(self, state: Optional[ExecutionStateStore] = None) -> str:
        """Format the complete live TUI representation."""
        if not state:
            state = event_bus.get_state(self.mission_id)
        if not state:
            return "HERMES: Waiting for mission events..."

        done, total = state.progress
        pct = int((done / total * 100)) if total > 0 else 0
        bar_len = 20
        filled = int(bar_len * (done / total)) if total > 0 else 0
        bar_str = "[" + ("#" * filled) + ("-" * (bar_len - filled)) + "]"

        lines = [
            "================================================================",
            f" HERMES MISSION OBSERVER | Status: {state.status}",
            "================================================================",
            f"Mission:   {state.mission_id}",
            f"Progress:  {bar_str} {done}/{total} tasks ({pct}%)",
            f"Workspace: {state.workspace_files_count} files indexed",
            "----------------------------------------------------------------",
            "KAIROS DAG Tasks:"
        ]

        for tid, tinfo in state.tasks.items():
            st = tinfo.get("status", "PENDING")
            icon = "[OK]" if st == "COMPLETED" else "[*]" if st == "RUNNING" else "[X]" if st == "FAILED" else "[ ]"
            lines.append(f"  {icon} {tid}: {tinfo.get('title', tid)}")

        lines.extend([
            "----------------------------------------------------------------",
            f"Active Model:        {state.current_model or 'Idle'}",
            f"Active Tool:         {state.current_tool or 'None'}",
            f"Verification State:  {state.verification_state}",
            f"Repair State:        {state.repair_state}",
            "----------------------------------------------------------------",
            "Recent Events:"
        ])

        for ev in list(state.recent_events)[-4:]:
            ts = time.strftime("%H:%M:%S", time.localtime(ev.timestamp))
            lines.append(f"  {ts} [{ev.event_type.value}] {ev.payload.get('title', '')}")

        lines.append("================================================================")
        return self.redact_sensitive("\n".join(lines))

    def render(self) -> str:
        """Generate and cache the formatted view."""
        self.last_rendered_text = self.format_view()
        return self.last_rendered_text
