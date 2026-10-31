# core/server/events.py
"""
Typed SSE Event Contract and Formatter for HERMES 2.x.
Ensures versioned, sequentially ordered, sanitized events for SSE streaming.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, Optional
from core.runtime_state.events import HermesEvent, redact_sensitive_payload
from utils.logging import redact_secrets


class ServerSentEvent:
    """Represents a formatted Server-Sent Event (SSE)."""

    def __init__(
        self,
        event: str,
        data: Dict[str, Any],
        event_id: Optional[str] = None,
        retry: Optional[int] = 3000,
    ):
        self.event = event
        self.data = data
        self.event_id = event_id
        self.retry = retry

    def format(self) -> str:
        """Format event into standard SSE text frame."""
        lines = []
        if self.event_id is not None:
            lines.append(f"id: {self.event_id}")
        if self.event:
            lines.append(f"event: {self.event}")
        if self.retry is not None:
            lines.append(f"retry: {self.retry}")

        payload_json = json.dumps(self.data, ensure_ascii=False)
        lines.append(f"data: {payload_json}")
        return "\n".join(lines) + "\n\n"


def format_hermes_event_to_sse(event: HermesEvent) -> str:
    """Convert canonical HermesEvent to SSE text frame with strict secret scrubbing."""
    # Ensure event dict
    raw_dict = event.to_dict()
    # Extra layer of secret scrubbing
    safe_payload = redact_sensitive_payload(raw_dict.get("payload", {}))
    raw_dict["payload"] = safe_payload

    # Scrape string representation for any rogue tokens
    clean_dict = json.loads(redact_secrets(json.dumps(raw_dict, ensure_ascii=False)))

    sse = ServerSentEvent(
        event=str(clean_dict.get("event_type", "GENERIC_EVENT")),
        data=clean_dict,
        event_id=str(event.sequence),  # Monotonic sequence ID for Last-Event-ID cursor
    )
    return sse.format()
