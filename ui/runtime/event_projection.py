# ui/runtime/event_projection.py
"""
Event Projection Layer.

Translates live EventBus events into transient presentation updates:
- Formats streaming model tokens into coalesced partial content.
- Appends typed ChatMessageViewModels for completed steps.
- Accumulates user-facing notifications for critical events.
- Never mutates authoritative runtime state.
"""

from __future__ import annotations

import time
from typing import List, Optional

from core.runtime_state.events import EventType, HermesEvent
from ui.rendering.text_safety import sanitize_terminal_text
from ui.viewmodels.chat import ChatEntryKind, ChatMessageViewModel


class EventProjector:
    """Maintains transient presentation state derived from EventBus stream."""

    def __init__(self, max_messages: int = 1000):
        self.max_messages = max_messages
        self.messages: List[ChatMessageViewModel] = []
        self.notifications: List[str] = []
        self.is_streaming: bool = False
        self.streaming_content: str = ""
        self._msg_counter: int = 0

    def process_event(self, event: HermesEvent) -> bool:
        """
        Process an event and update presentation state.
        Returns True if presentation state changed, False otherwise.
        """
        et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        payload = event.payload or {}
        ts_str = time.strftime("%H:%M:%S", time.localtime(event.timestamp))

        # 1. Model streaming
        if et in (EventType.MODEL_TTFT.value, "MODEL_STREAMING_STARTED"):
            self.is_streaming = True
            self.streaming_content = ""
            return True

        elif et in ("MODEL_DELTA", "MODEL_STREAM_CHUNK", "MODEL_STREAMING_STALLED"):
            delta = payload.get("delta", "") or payload.get("text", "")
            self.streaming_content += delta
            return True

        elif et == EventType.MODEL_COMPLETED.value:
            self.is_streaming = False
            final_text = payload.get("final_output", "") or self.streaming_content
            self.streaming_content = ""
            self._add_message(
                author_role="Hermes",
                kind=ChatEntryKind.ASSISTANT,
                content=final_text or "(Empty response)",
                status="COMPLETED",
                timestamp_str=ts_str,
            )
            return True

        # 2. Tool events
        elif et == EventType.TOOL_COMPLETED.value:
            tool_name = payload.get("tool_name", "tool")
            out_preview = payload.get("output_preview", "")
            success = payload.get("success", True)
            self._add_message(
                author_role="Tool",
                kind=ChatEntryKind.TOOL,
                content=f"Executed {tool_name} -> {out_preview[:80]}",
                status="COMPLETED" if success else "FAILED",
                is_error=not success,
                timestamp_str=ts_str,
                tool_call_id=payload.get("tool_call_id"),
            )
            return True

        # 3. Verification events
        elif et == EventType.VERIFICATION_COMPLETED.value:
            verdict = payload.get("verdict", "INCONCLUSIVE")
            is_pass = verdict == "PASSED"
            self._add_message(
                author_role="Verifier",
                kind=ChatEntryKind.VERIFICATION,
                content=f"Verification {verdict}: {payload.get('summary', '')}",
                status=verdict,
                is_error=not is_pass,
                timestamp_str=ts_str,
            )
            if not is_pass:
                self.notifications.append(f"Verification Failed: {verdict}")
            return True

        # 4. Security events
        elif et == "SECURITY_DENIED":
            action = payload.get("action", "")
            self.notifications.append(f"Security Alert: Action '{action}' was DENIED.")
            self._add_message(
                author_role="Security",
                kind=ChatEntryKind.SECURITY,
                content=f"Action '{action}' was denied under active security policy.",
                status="DENIED",
                is_error=True,
                timestamp_str=ts_str,
            )
            return True

        # 5. Checkpoint events
        elif et in ("CHECKPOINT_COMMITTED", "CHECKPOINT_CREATED"):
            chk_id = payload.get("checkpoint_id", "")
            self._add_message(
                author_role="System",
                kind=ChatEntryKind.CHECKPOINT,
                content=f"Checkpoint {chk_id} saved successfully.",
                status="COMMITTED",
                timestamp_str=ts_str,
            )
            return True

        # 6. Session recovery events
        elif et in ("SESSION_RESUMED", "RECOVERY_COMPLETED"):
            sess_id = payload.get("session_id", "")
            self.notifications.append(f"Session {sess_id} resumed cleanly.")
            self._add_message(
                author_role="System",
                kind=ChatEntryKind.RECOVERY,
                content=f"Session {sess_id} recovered from persistent state.",
                status="RESUMED",
                timestamp_str=ts_str,
            )
            return True

        return False

    def add_user_message(self, text: str) -> None:
        """Record submitted user prompt."""
        self._add_message(
            author_role="User",
            kind=ChatEntryKind.USER,
            content=text,
            status="SUBMITTED",
            timestamp_str=time.strftime("%H:%M:%S"),
        )

    def _add_message(
        self,
        author_role: str,
        kind: ChatEntryKind,
        content: str,
        status: str = "DONE",
        is_error: bool = False,
        timestamp_str: str = "",
        tool_call_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> None:
        self._msg_counter += 1
        msg = ChatMessageViewModel(
            message_id=f"msg_{self._msg_counter}",
            sequence=self._msg_counter,
            timestamp_str=timestamp_str or time.strftime("%H:%M:%S"),
            kind=kind,
            author_role=author_role,
            content=sanitize_terminal_text(content),
            status=status,
            tool_call_id=tool_call_id,
            task_id=task_id,
            is_error=is_error,
        )
        self.messages.append(msg)
        if len(self.messages) > self.max_messages:
            self.messages.pop(0)
