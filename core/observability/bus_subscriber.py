# core/observability/bus_subscriber.py
"""
EventBus Subscriber for the Forensic Telemetry System in HERMES 2.x.
Ensures every canonical HermesEvent published through EventBus is recorded
in the active run's structured JSONL streams.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from typing import Optional

from core.event_bus import EventBus
from core.observability.logger import get_telemetry_logger, MissionTelemetryLogger, validate_run_id
from core.runtime_state.events import HermesEvent, EventType

logger = logging.getLogger(__name__)


class ObservabilityBusSubscriber:
    """Subscribes to EventBus and fans out events to MissionTelemetryLogger."""

    SUBSCRIPTION_KEY = "hermes.observability.global_subscriber"

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.subscriber_id: str = uuid.uuid4().hex
        self._is_owner: bool = False
        self._lock = threading.Lock()

    @property
    def is_attached(self) -> bool:
        """True if and only if this specific subscriber instance owns an active registration."""
        with self._lock:
            return self._is_owner

    def attach(self) -> bool:
        """
        Register subscriber with EventBus safely, atomically, and with ownership awareness.
        Returns True if this instance successfully acquired/holds the subscription,
        or False if another instance already owns the global subscription.
        """
        with self._lock:
            if self._is_owner:
                return True
            if hasattr(self.event_bus, "subscribe_keyed"):
                registered = self.event_bus.subscribe_keyed(
                    key=self.SUBSCRIPTION_KEY,
                    handler=self.handle_event,
                    event_types=None,
                    owner_id=self.subscriber_id,
                )
                if registered:
                    self._is_owner = True
                    return True
                return False
            else:
                self.event_bus.subscribe(self.handle_event)
                self._is_owner = True
                return True

    def detach(self) -> bool:
        """
        Unregister subscriber from EventBus safely and thoroughly.
        Only the instance that owns the subscription can detach it.
        Returns True if detached, False otherwise.
        """
        with self._lock:
            if not self._is_owner:
                return False
            if hasattr(self.event_bus, "unsubscribe_keyed"):
                removed = self.event_bus.unsubscribe_keyed(
                    key=self.SUBSCRIPTION_KEY,
                    owner_id=self.subscriber_id,
                )
                if removed:
                    self._is_owner = False
                    return True
                return False
            else:
                self.event_bus.unsubscribe(self.handle_event)
                self._is_owner = False
                return True

    def handle_event(self, event: HermesEvent) -> None:
        """Dispatch EventBus events to the appropriate run telemetry logger."""
        try:
            run_id = event.run_id
            if not run_id and event.mission_id:
                # Authoritative Run ID lookup from state store or database
                try:
                    state_store = self.event_bus.get_or_create_state(event.mission_id)
                    snap = state_store.get_snapshot()
                    if snap and getattr(snap, "mission", None) and getattr(snap.mission, "run_id", None):
                        run_id = snap.mission.run_id
                except Exception:
                    pass
                if not run_id:
                    try:
                        db = self.event_bus.get_database()
                        if db:
                            m_row = db.get_mission(event.mission_id)
                            if m_row and m_row.get("run_id"):
                                run_id = m_row.get("run_id")
                    except Exception:
                        pass
            if not run_id:
                run_id = f"run_1_{event.mission_id}" if event.mission_id else "run_default"

            # Validate and normalize run_id to prevent path injection
            try:
                validate_run_id(run_id)
            except Exception:
                clean_m = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(event.mission_id or "default")).strip("_") or "default"
                run_id = f"run_1_{clean_m}"

            telemetry = get_telemetry_logger(run_id=run_id, mission_id=event.mission_id)

            # Determine specialized stream destinations based on EventType and payload
            dests = ["events"]
            et_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)

            tool_name = str(event.payload.get("tool_name") or event.payload.get("requested_tool_name") or "")

            if "MODEL" in et_str or "ROUTING" in et_str or "TIER" in et_str:
                dests.append("models")
            if "TOOL" in et_str:
                dests.append("tools")
            if "RECOVERY" in et_str or "REPAIR" in et_str or "ESCALATION" in et_str or "CIRCUIT" in et_str or "FAILOVER" in et_str:
                dests.append("recovery")
            if "FILE" in et_str or (tool_name in ("fs.write", "fs.edit", "write_file", "edit_file")):
                dests.append("files")
            if "VALIDATION" in et_str or "SYNTAX" in et_str or "HTML" in et_str or "CSS" in et_str or "BROWSER" in et_str or "CHECK" in et_str:
                dests.append("validation")
            cmd = str(event.payload.get("command") or event.payload.get("cmd_to_run") or "")
            if any(k in cmd for k in ("node -c", "node --check", "pytest", "npm test", "python -m pytest")):
                dests.append("validation")
            if "RUNTIME" in et_str or "SERVER" in et_str:
                dests.append("runtime")
            if event.severity.value in ("ERROR", "CRITICAL") or "FAIL" in et_str or "ERROR" in et_str:
                dests.append("errors")

            p_copy = dict(event.payload or {})
            if event.tool_call_id and "tool_call_id" not in p_copy:
                p_copy["tool_call_id"] = event.tool_call_id

            telemetry.log_event(
                event_type=et_str,
                component=event.source or "event_bus",
                severity=event.severity.value,
                message=p_copy.get("message") or p_copy.get("error") or et_str,
                turn=p_copy.get("turn") or (int(event.turn_id.split("_")[1]) if (event.turn_id and "_" in event.turn_id and event.turn_id.split("_")[1].isdigit()) else None),
                tier=p_copy.get("tier"),
                provider=p_copy.get("provider"),
                model=p_copy.get("model"),
                duration_ms=p_copy.get("duration_ms") or (p_copy.get("duration_seconds", 0.0) * 1000.0 if "duration_seconds" in p_copy else None),
                status=p_copy.get("status"),
                trace_id=event.trace_id,
                span_id=event.span_id,
                parent_span_id=event.parent_span_id,
                payload=p_copy,
                destinations=dests,
            )
        except Exception as e:
            # Observability subscriber should never crash EventBus execution
            logger.debug(f"ObservabilityBusSubscriber dispatch notice: {e}")
