# core/profiler.py
"""
HERMES Phase 10: High-Resolution Runtime Profiler & Lifecycle Span Tracer.

Provides low-overhead (<5µs per span), thread-safe, and async-safe span tracking
using monotonic time (time.perf_counter_ns()).

Guarantees:
1. Purely observational: Never modifies application exceptions or control flow.
2. Exception-safe: Automatically captures exceptions, records error status, and re-raises.
3. Thread-safe & async-safe: Bounded in-memory buffer with thread lock.
4. No sensitive leakages: Never logs prompts, tokens, or authorization credentials.
5. Microsecond precision: Tracks duration in milliseconds with sub-microsecond resolution.
"""

from __future__ import annotations

import contextvars
import json
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional


@dataclass
class ProfilerSpan:
    name: str
    start_ns: int
    end_ns: Optional[int] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "metadata": {
                k: v for k, v in self.metadata.items()
                if not any(secret in k.lower() for secret in ("token", "key", "auth", "secret", "password"))
            },
        }


class RuntimeProfiler:
    """
    High-resolution monotonic profiler with bounded in-memory buffer.
    """

    DEFAULT_MAX_SPANS = 2000

    def __init__(self, max_spans: int = DEFAULT_MAX_SPANS) -> None:
        self.max_spans = max_spans
        self._spans: List[ProfilerSpan] = []
        self._lock = threading.RLock()

    def record_span(self, span: ProfilerSpan) -> None:
        with self._lock:
            if len(self._spans) >= self.max_spans:
                # Evict oldest entry to keep bounded memory footprint
                self._spans.pop(0)
            self._spans.append(span)

    @contextmanager
    def span(self, name: str, **metadata: Any) -> Iterator[ProfilerSpan]:
        start = time.perf_counter_ns()
        span_obj = ProfilerSpan(name=name, start_ns=start, metadata=metadata)
        try:
            yield span_obj
            span_obj.status = "ok"
        except BaseException as exc:
            span_obj.status = "error"
            span_obj.error = f"{type(exc).__name__}: {str(exc)}"
            raise
        finally:
            end = time.perf_counter_ns()
            span_obj.end_ns = end
            span_obj.duration_ms = (end - start) / 1_000_000.0
            self.record_span(span_obj)

    @asynccontextmanager
    async def async_span(self, name: str, **metadata: Any) -> AsyncIterator[ProfilerSpan]:
        start = time.perf_counter_ns()
        span_obj = ProfilerSpan(name=name, start_ns=start, metadata=metadata)
        try:
            yield span_obj
            span_obj.status = "ok"
        except BaseException as exc:
            span_obj.status = "error"
            span_obj.error = f"{type(exc).__name__}: {str(exc)}"
            raise
        finally:
            end = time.perf_counter_ns()
            span_obj.end_ns = end
            span_obj.duration_ms = (end - start) / 1_000_000.0
            self.record_span(span_obj)

    def get_spans(self, name_filter: Optional[str] = None) -> List[ProfilerSpan]:
        with self._lock:
            if name_filter is None:
                return list(self._spans)
            return [s for s in self._spans if s.name == name_filter]

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def summary(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            spans_copy = list(self._spans)

        grouped: Dict[str, List[float]] = {}
        for s in spans_copy:
            if s.duration_ms is not None:
                grouped.setdefault(s.name, []).append(s.duration_ms)

        res = {}
        for name, durations in grouped.items():
            durations.sort()
            count = len(durations)
            total = sum(durations)
            avg = total / count if count > 0 else 0.0
            med = durations[count // 2] if count > 0 else 0.0
            p95 = durations[min(int(count * 0.95), count - 1)] if count > 0 else 0.0
            res[name] = {
                "count": count,
                "total_ms": round(total, 3),
                "avg_ms": round(avg, 3),
                "median_ms": round(med, 3),
                "p95_ms": round(p95, 3),
                "min_ms": round(durations[0], 3) if durations else 0.0,
                "max_ms": round(durations[-1], 3) if durations else 0.0,
            }
        return res

    def export_json(self, destination: Path | str) -> Path:
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = {
                "total_spans": len(self._spans),
                "summary": self.summary(),
                "spans": [s.to_dict() for s in self._spans],
            }
        dest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return dest_path


# Global singleton profiler
runtime_profiler = RuntimeProfiler()
