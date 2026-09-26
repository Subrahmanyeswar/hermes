# core/context/tool_results.py
"""
Tool Result Store for HERMES 2.x Context Engine.
Maintains the complete logical history of tool executions across turns,
supporting independent tool-result clearing, externalization references, and surgical slice retrieval.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.context.external_store import ExternalizedOutputStore, externalized_output_store


class ToolResultClearState(str, Enum):
    """Lifecycle state of a tool result representation."""
    INLINE = "INLINE"               # Full or shaped result in active context
    EXTERNALIZED = "EXTERNALIZED"   # Stored externally with reference in context
    CLEARED = "CLEARED"             # Bulky inline content cleared; metadata/ref preserved
    SUMMARIZED = "SUMMARIZED"       # Compressed to high-level semantic summary


@dataclass
class ToolResultRecord:
    """Complete logical record of a tool execution."""
    tool_call_id: str
    tool_name: str
    turn_id: str
    mission_id: str
    status: str                     # "success", "error"
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    inline_payload: Optional[str] = None
    external_ref: Optional[str] = None
    clear_state: ToolResultClearState = ToolResultClearState.INLINE
    truncation_state: bool = False
    evidence_ref: Optional[str] = None
    size_bytes: int = 0
    token_estimate: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "turn_id": self.turn_id,
            "mission_id": self.mission_id,
            "status": self.status,
            "summary": self.summary,
            "inline_payload_len": len(self.inline_payload) if self.inline_payload else 0,
            "external_ref": self.external_ref,
            "clear_state": self.clear_state.value,
            "truncation_state": self.truncation_state,
            "evidence_ref": self.evidence_ref,
            "size_bytes": self.size_bytes,
            "token_estimate": self.token_estimate,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class ToolResultStore:
    """
    Thread-safe repository for tool execution history.
    Decoupled from runtime event flow and primary model context window.
    """

    def __init__(self, external_store: Optional[ExternalizedOutputStore] = None) -> None:
        self._records: Dict[str, ToolResultRecord] = {}
        self._lock = threading.Lock()
        self.external_store = external_store or externalized_output_store

    def record_result(
        self,
        tool_call_id: str,
        tool_name: str,
        turn_id: str,
        mission_id: str,
        output_text: str,
        status: str = "success",
        summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        external_ref: Optional[str] = None,
        evidence_ref: Optional[str] = None,
        auto_externalize_threshold_chars: int = 4000,
    ) -> ToolResultRecord:
        """Record a tool execution result, externalizing if payload is oversized."""
        size_bytes = len(output_text.encode("utf-8", errors="replace"))
        token_estimate = max(1, len(output_text) // 4)

        if not summary:
            first_line = output_text.splitlines()[0][:120] if output_text else "Empty output"
            summary = first_line

        # Auto-externalize large outputs if not already externalized
        clear_state = ToolResultClearState.INLINE
        inline_payload = output_text

        if len(output_text) > auto_externalize_threshold_chars and not external_ref:
            artifact = self.external_store.put(
                raw_content=output_text,
                mission_id=mission_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                metadata=metadata,
            )
            external_ref = artifact.artifact_id
            clear_state = ToolResultClearState.EXTERNALIZED

        record = ToolResultRecord(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            turn_id=turn_id,
            mission_id=mission_id,
            status=status,
            summary=summary,
            metadata=metadata or {},
            inline_payload=inline_payload,
            external_ref=external_ref,
            clear_state=clear_state,
            truncation_state=len(output_text) > auto_externalize_threshold_chars,
            evidence_ref=evidence_ref,
            size_bytes=size_bytes,
            token_estimate=token_estimate,
        )

        with self._lock:
            self._records[tool_call_id] = record

        return record

    def clear_result(self, tool_call_id: str, summary_override: Optional[str] = None) -> bool:
        """
        Lightweight clearing of bulky inline content.
        Preserves metadata, external reference, and summary.
        Full content remains retrievable via external_store.
        """
        with self._lock:
            record = self._records.get(tool_call_id)
            if not record:
                return False

            # If not yet externalized, make sure full content is preserved in external_store before clearing
            if not record.external_ref and record.inline_payload:
                art = self.external_store.put(
                    raw_content=record.inline_payload,
                    mission_id=record.mission_id,
                    tool_call_id=record.tool_call_id,
                    tool_name=record.tool_name,
                )
                record.external_ref = art.artifact_id

            if summary_override:
                record.summary = summary_override

            record.inline_payload = None
            record.clear_state = ToolResultClearState.CLEARED
            record.token_estimate = max(1, len(record.summary) // 4)
            return True

    def get(self, tool_call_id: str) -> Optional[ToolResultRecord]:
        """Retrieve tool result record by tool_call_id."""
        with self._lock:
            return self._records.get(tool_call_id)

    def get_full_content(self, tool_call_id: str) -> Optional[str]:
        """Retrieve full original output (from inline payload or external store)."""
        record = self.get(tool_call_id)
        if not record:
            return None
        if record.inline_payload is not None:
            return record.inline_payload
        if record.external_ref:
            return self.external_store.get(record.external_ref)
        return None

    def get_slice(
        self,
        tool_call_id: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> Tuple[Optional[str], bool, int]:
        """Retrieve line-addressed slice of tool output."""
        record = self.get(tool_call_id)
        if not record:
            return None, False, 0

        if record.inline_payload is not None:
            lines = record.inline_payload.splitlines()
            total = len(lines)
            s_idx = max(0, start_line - 1)
            e_idx = min(total, end_line) if end_line is not None else total
            sliced = lines[s_idx:e_idx]
            return "\n".join(sliced), e_idx < total, total

        if record.external_ref:
            return self.external_store.get_slice(record.external_ref, start_line, end_line)

        return None, False, 0

    def get_summary(self, tool_call_id: str) -> Optional[str]:
        """Retrieve summary for a tool execution."""
        record = self.get(tool_call_id)
        return record.summary if record else None

    def list_for_mission(self, mission_id: str) -> List[ToolResultRecord]:
        """List all tool execution records for a specific mission."""
        with self._lock:
            return [r for r in self._records.values() if r.mission_id == mission_id]

    def find_by_artifact(self, artifact_id: str) -> Optional[ToolResultRecord]:
        """Find tool record associated with an externalized artifact ID."""
        with self._lock:
            for r in self._records.values():
                if r.external_ref == artifact_id:
                    return r
            return None

    def detect_duplicate_call(self, tool_name: str, args_repr: str, mission_id: str) -> Optional[ToolResultRecord]:
        """Detect identical repeated calls within the same mission."""
        with self._lock:
            for r in reversed(list(self._records.values())):
                if r.mission_id == mission_id and r.tool_name == tool_name:
                    if r.metadata.get("args_repr") == args_repr:
                        return r
            return None

    def clear(self) -> None:
        """Clear in-memory records."""
        with self._lock:
            self._records.clear()


# Global singleton
tool_result_store = ToolResultStore()
