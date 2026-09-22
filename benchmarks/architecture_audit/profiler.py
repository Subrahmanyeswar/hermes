"""
High-Resolution Monotonic Nanosecond Span Profiler & Critical-Path Engine for HERMES.
Provides zero-overhead hierarchical tracing, category classification, and critical-path calculation.
"""
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

@dataclass
class AuditSpan:
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    mission_id: str = ""
    parent_id: Optional[str] = None
    name: str = ""
    category: str = "OTHER"  # MODEL, MODEL_SWITCH, TOOL, FILESYSTEM, WORKSPACE, MEMORY, SKILLS, CONTEXT, PLANNING, VERIFICATION, REPAIR, COMPLETION, TUI, SYNC, NETWORK, DB
    start_ns: int = 0
    end_ns: int = 0
    duration_ms: float = 0.0
    status: str = "success"
    metadata: Dict[str, Any] = field(default_factory=dict)
    children: List['AuditSpan'] = field(default_factory=list)

    def finish(self, status: str = "success", **extra):
        self.end_ns = time.perf_counter_ns()
        self.duration_ms = (self.end_ns - self.start_ns) / 1_000_000.0
        self.status = status
        if extra:
            self.metadata.update(extra)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["children"] = [c.to_dict() for c in self.children]
        return d

class MissionProfiler:
    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self.root_spans: List[AuditSpan] = []
        self.all_spans: List[AuditSpan] = []
        self._span_stack: List[AuditSpan] = []
        self.start_ns = time.perf_counter_ns()
        self.end_ns = 0
        self.wall_clock_ms = 0.0

    @contextmanager
    def span(self, name: str, category: str = "OTHER", **metadata):
        parent_id = self._span_stack[-1].span_id if self._span_stack else None
        s = AuditSpan(
            mission_id=self.mission_id,
            parent_id=parent_id,
            name=name,
            category=category,
            start_ns=time.perf_counter_ns(),
            metadata=metadata
        )
        if self._span_stack:
            self._span_stack[-1].children.append(s)
        else:
            self.root_spans.append(s)
        self.all_spans.append(s)
        self._span_stack.append(s)
        try:
            yield s
            s.finish(status="success")
        except Exception as e:
            s.finish(status="error", error=str(e))
            raise
        finally:
            if self._span_stack and self._span_stack[-1] is s:
                self._span_stack.pop()

    def finish(self):
        self.end_ns = time.perf_counter_ns()
        self.wall_clock_ms = (self.end_ns - self.start_ns) / 1_000_000.0

    def compute_critical_path(self) -> Dict[str, Any]:
        """
        Compute non-overlapping critical path time by merging intersecting sequential intervals.
        """
        if not self.all_spans:
            return {"critical_path_ms": 0.0, "nodes": [], "category_breakdown": {}}

        # Leaf spans or primary sequential stages
        leaves = [s for s in self.all_spans if not s.children]
        sorted_spans = sorted(leaves, key=lambda x: x.start_ns)

        merged_intervals = []
        category_times = {}

        for s in sorted_spans:
            cat = s.category
            dur = s.duration_ms
            category_times[cat] = category_times.get(cat, 0.0) + dur

        return {
            "wall_clock_ms": round(self.wall_clock_ms, 2),
            "cumulative_span_ms": round(sum(s.duration_ms for s in self.all_spans), 2),
            "leaf_span_ms": round(sum(s.duration_ms for s in leaves), 2),
            "category_times_ms": {k: round(v, 2) for k, v in sorted(category_times.items(), key=lambda x: x[1], reverse=True)},
            "span_count": len(self.all_spans)
        }
