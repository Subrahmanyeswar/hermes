# tools/platform/output.py
"""
Output Shaping and External Storage Engine for HERMES 2.x Tool Platform.
Provides high-signal, context-efficient observations while retaining full output references.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from tools.platform.specs import ResponseFormat


@dataclass
class ShapedOutput:
    """Structured representation of shaped tool output."""
    content: str
    truncated: bool = False
    total_lines: int = 0
    shown_lines: int = 0
    total_chars: int = 0
    shown_chars: int = 0
    full_output_ref: Optional[str] = None
    summary: str = ""

    def to_observation_text(self) -> str:
        """Render shaped content with truncation banner if applicable."""
        text = self.content
        if self.truncated:
            banner = (
                f"\n[TRUNCATED: Showing {self.shown_lines}/{self.total_lines} lines "
                f"({self.shown_chars}/{self.total_chars} chars). "
            )
            if self.full_output_ref:
                banner += f"Full output stored at ref='{self.full_output_ref}'. Use fs.read or output slice to inspect.]"
            else:
                banner += "Narrow your search or query to inspect more.]"
            text += banner
        return text


@dataclass
class OutputRecord:
    """Stored raw output record."""
    output_id: str
    tool_name: str
    tool_call_id: str
    raw_content: str
    content_type: str = "text/plain"
    size_bytes: int = 0
    line_count: int = 0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class OutputStore:
    """
    Thread-safe storage for oversized tool execution outputs.
    Retains complete outputs outside model context for subsequent retrieval.
    """

    def __init__(self, max_records: int = 500) -> None:
        self._records: Dict[str, OutputRecord] = {}
        self._lock = threading.Lock()
        self._max_records = max_records

    def put(
        self,
        raw_content: str,
        tool_name: str = "",
        tool_call_id: str = "",
        content_type: str = "text/plain",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store raw content and return a unique reference ID."""
        output_id = f"out-{uuid.uuid4().hex[:12]}"
        lines = raw_content.splitlines()
        record = OutputRecord(
            output_id=output_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            raw_content=raw_content,
            content_type=content_type,
            size_bytes=len(raw_content.encode("utf-8", errors="replace")),
            line_count=len(lines),
            metadata=metadata or {},
        )
        with self._lock:
            # Enforce max record retention
            if len(self._records) >= self._max_records:
                # Remove oldest entry
                oldest_id = next(iter(self._records))
                del self._records[oldest_id]
            self._records[output_id] = record

        # Also mirror to file-backed ExternalizedOutputStore for persistent retrievability
        try:
            from core.context.external_store import externalized_output_store
            externalized_output_store.put(
                raw_content=raw_content,
                tool_call_id=tool_call_id or output_id,
                tool_name=tool_name,
                metadata=metadata,
            )
        except Exception:
            pass

        return output_id

    def get(self, output_id: str) -> Optional[OutputRecord]:
        """Retrieve stored output by ID."""
        with self._lock:
            rec = self._records.get(output_id)
            if rec:
                return rec
        # Fallback to persistent file-backed store
        try:
            from core.context.external_store import externalized_output_store
            content = externalized_output_store.get(output_id)
            if content is not None:
                lines = content.splitlines()
                return OutputRecord(
                    output_id=output_id,
                    tool_name="",
                    tool_call_id="",
                    raw_content=content,
                    size_bytes=len(content.encode("utf-8", errors="replace")),
                    line_count=len(lines),
                )
        except Exception:
            pass
        return None

    def get_slice(
        self,
        output_id: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> Tuple[Optional[str], bool, int]:
        """
        Retrieve line slice from stored output.
        Returns: (content, has_more, total_lines)
        """
        rec = self.get(output_id)
        if not rec:
            try:
                from core.context.external_store import externalized_output_store
                return externalized_output_store.get_slice(output_id, start_line, end_line)
            except Exception:
                return None, False, 0

        lines = rec.raw_content.splitlines()
        total = len(lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total, end_line) if end_line is not None else total

        sliced = lines[start_idx:end_idx]
        has_more = end_idx < total
        return "\n".join(sliced), has_more, total

    def search(self, output_id: str, query: str, max_results: int = 20) -> List[Tuple[int, str]]:
        """Search stored output for query, returning list of (1-based line_number, line_text)."""
        rec = self.get(output_id)
        if not rec:
            return []

        q_lower = query.lower()
        results = []
        for idx, line in enumerate(rec.raw_content.splitlines(), start=1):
            if q_lower in line.lower():
                results.append((idx, line))
                if len(results) >= max_results:
                    break
        return results

    def clear(self) -> None:
        """Clear all stored output records."""
        with self._lock:
            self._records.clear()


# Global canonical OutputStore singleton
output_store = OutputStore()


class OutputShaper:
    """
    Shapes tool outputs for optimal context efficiency based on requested format,
    line limits, and truncation thresholds.
    """

    DEFAULT_CONCISE_MAX_CHARS = 2_000
    DEFAULT_NORMAL_MAX_CHARS = 10_000
    DEFAULT_DETAILED_MAX_CHARS = 40_000

    DEFAULT_CONCISE_MAX_LINES = 50
    DEFAULT_NORMAL_MAX_LINES = 250
    DEFAULT_DETAILED_MAX_LINES = 1_000

    @classmethod
    def shape(
        cls,
        raw_output: str,
        response_format: ResponseFormat = ResponseFormat.NORMAL,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None,
        max_chars: Optional[int] = None,
        tool_name: str = "",
        tool_call_id: str = "",
        auto_store_large: bool = True,
    ) -> ShapedOutput:
        """Shape raw tool output into a context-safe observation."""
        if not raw_output:
            return ShapedOutput(content="", total_lines=0, shown_lines=0, total_chars=0, shown_chars=0)

        lines = raw_output.splitlines()
        total_lines = len(lines)
        total_chars = len(raw_output)

        # 1. Apply line range slicing if specified
        if start_line is not None or end_line is not None:
            s_idx = max(0, (start_line or 1) - 1)
            e_idx = min(total_lines, end_line) if end_line is not None else total_lines
            lines = lines[s_idx:e_idx]

        # 2. Determine thresholds based on format
        if max_chars is None:
            if response_format == ResponseFormat.CONCISE:
                char_limit = cls.DEFAULT_CONCISE_MAX_CHARS
                line_limit = max_lines or cls.DEFAULT_CONCISE_MAX_LINES
            elif response_format == ResponseFormat.DETAILED:
                char_limit = cls.DEFAULT_DETAILED_MAX_CHARS
                line_limit = max_lines or cls.DEFAULT_DETAILED_MAX_LINES
            else:
                char_limit = cls.DEFAULT_NORMAL_MAX_CHARS
                line_limit = max_lines or cls.DEFAULT_NORMAL_MAX_LINES
        else:
            char_limit = max_chars
            line_limit = max_lines or cls.DEFAULT_NORMAL_MAX_LINES

        # 3. Apply line cap
        truncated = False
        if len(lines) > line_limit:
            lines = lines[:line_limit]
            truncated = True

        joined = "\n".join(lines)

        # 4. Apply character cap
        if len(joined) > char_limit:
            joined = joined[:char_limit]
            truncated = True

        # 5. Externalize large output if truncated
        full_ref = None
        if truncated and auto_store_large and total_chars > char_limit:
            full_ref = output_store.put(
                raw_content=raw_output,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )

        shown_lines = len(joined.splitlines())
        shown_chars = len(joined)

        first_line = raw_output.splitlines()[0][:100] if raw_output else ""
        summary = first_line if (not truncated and first_line) else f"{shown_lines}/{total_lines} lines"

        return ShapedOutput(
            content=joined,
            truncated=truncated,
            total_lines=total_lines,
            shown_lines=shown_lines,
            total_chars=total_chars,
            shown_chars=shown_chars,
            full_output_ref=full_ref,
            summary=summary,
        )
