# core/observability/spans.py
"""
High-Resolution Timing Spans and Duration Attribution for HERMES 2.x.
Ensures every thinking interval, network operation, and local phase is measurable and attributable.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Any, Optional
from core.observability.schemas import TimingPhase


class TimingSpan:
    """Represents a measured span of execution with monotonic precision."""

    def __init__(
        self,
        name: str,
        category: TimingPhase = TimingPhase.LOCAL_PROCESSING_LATENCY,
        parent_span_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.span_id: str = f"sp_{uuid.uuid4().hex[:8]}"
        self.name: str = name
        self.category: TimingPhase = category
        self.parent_span_id: Optional[str] = parent_span_id
        self.metadata: Dict[str, Any] = metadata or {}
        self.start_ns: int = time.monotonic_ns()
        self.end_ns: Optional[int] = None
        self.duration_ms: Optional[float] = None
        self.is_completed: bool = False

    def finish(self, status: str = "COMPLETED", extra_metadata: Optional[Dict[str, Any]] = None) -> float:
        """Complete the span, compute duration in ms, and attach final metadata."""
        self.end_ns = time.monotonic_ns()
        self.duration_ms = (self.end_ns - self.start_ns) / 1_000_000.0
        self.is_completed = True
        self.metadata["status"] = status
        if extra_metadata:
            self.metadata.update(extra_metadata)
        return self.duration_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "category": self.category.value if isinstance(self.category, TimingPhase) else str(self.category),
            "parent_span_id": self.parent_span_id,
            "duration_ms": self.duration_ms,
            "is_completed": self.is_completed,
            "metadata": self.metadata,
        }


def classify_thinking_duration(
    total_duration_ms: float,
    ttft_ms: Optional[float],
    streaming_duration_ms: Optional[float],
    parse_duration_ms: Optional[float] = None,
    queue_wait_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Deconstruct total thinking/model latency into verifiable constituent phases.
    Avoids unexplained latency blocks.
    """
    breakdown = {}
    if queue_wait_ms is not None:
        breakdown["queue_wait_ms"] = round(queue_wait_ms, 2)
    if ttft_ms is not None:
        breakdown["time_to_first_token_ms"] = round(ttft_ms, 2)
    if streaming_duration_ms is not None:
        breakdown["streaming_generation_ms"] = round(streaming_duration_ms, 2)
    if parse_duration_ms is not None:
        breakdown["response_parsing_ms"] = round(parse_duration_ms, 2)

    accounted_ms = sum(breakdown.values())
    unaccounted_ms = max(0.0, total_duration_ms - accounted_ms)
    breakdown["local_or_network_overhead_ms"] = round(unaccounted_ms, 2)
    breakdown["total_duration_ms"] = round(total_duration_ms, 2)

    # Classify latency anomaly
    anomaly = None
    if ttft_ms is not None and ttft_ms > 30000.0:
        anomaly = "MODEL_TTFT_LATENCY_EXCESSIVE"
    elif total_duration_ms > 60000.0:
        anomaly = "MODEL_TOTAL_LATENCY_EXCESSIVE"
    elif unaccounted_ms > 5000.0:
        anomaly = "LOCAL_PROCESSING_OVERHEAD_HIGH"

    return {
        "phases": breakdown,
        "anomaly": anomaly,
    }
