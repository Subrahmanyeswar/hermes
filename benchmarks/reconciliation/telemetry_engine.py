"""
Unified Hierarchical Telemetry & Latency Reconciliation Engine.
Provides nanosecond monotonic timing, strict parent-child span trees,
model switch tracking, timeout tracking, gap detection, and waterfall generation.
"""
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

@dataclass
class ReconciledSpan:
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    mission_id: str = ""
    parent_id: Optional[str] = None
    name: str = ""
    category: str = "OTHER"  # MISSION, PLANNING, TASK, ATTEMPT, STAGE, MODEL, MODEL_SWITCH, TOOL, VERIFICATION, MEMORY, REPAIR, ACCEPTANCE, SUMMARY, WAITING
    start_ns: int = 0
    end_ns: int = 0
    duration_ms: float = 0.0
    status: str = "success"
    metadata: Dict[str, Any] = field(default_factory=dict)
    children: List['ReconciledSpan'] = field(default_factory=list)

    def finish(self, status: str = "success", **extra):
        self.end_ns = time.perf_counter_ns()
        self.duration_ms = max(0.0, (self.end_ns - self.start_ns) / 1_000_000.0)
        self.status = status
        if extra:
            self.metadata.update(extra)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["children"] = [c.to_dict() for c in self.children]
        return d

@dataclass
class ModelSwitchEvent:
    switch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    mission_id: str = ""
    from_model: str = ""
    to_model: str = ""
    start_ns: int = 0
    end_ns: int = 0
    duration_ms: float = 0.0
    reason: str = ""

    def finish(self):
        self.end_ns = time.perf_counter_ns()
        self.duration_ms = max(0.0, (self.end_ns - self.start_ns) / 1_000_000.0)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class HierarchicalMissionProfiler:
    def __init__(self, mission_id: str, prompt: str = ""):
        self.mission_id = mission_id
        self.prompt = prompt
        self.root_spans: List[ReconciledSpan] = []
        self.all_spans: List[ReconciledSpan] = []
        self.model_switches: List[ModelSwitchEvent] = []
        self._span_stack: List[ReconciledSpan] = []
        self.start_ns = time.perf_counter_ns()
        self.end_ns = 0
        self.wall_clock_ms = 0.0
        self._last_active_model: Optional[str] = None

    @contextmanager
    def span(self, name: str, category: str = "OTHER", **metadata):
        parent_id = self._span_stack[-1].span_id if self._span_stack else None
        s = ReconciledSpan(
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

    def record_model_switch(self, from_model: str, to_model: str, duration_ms: float, reason: str = ""):
        now_ns = time.perf_counter_ns()
        dur_ns = int(duration_ms * 1_000_000)
        sw = ModelSwitchEvent(
            mission_id=self.mission_id,
            from_model=from_model,
            to_model=to_model,
            start_ns=now_ns - dur_ns,
            end_ns=now_ns,
            duration_ms=duration_ms,
            reason=reason
        )
        self.model_switches.append(sw)

    def finish(self):
        self.end_ns = time.perf_counter_ns()
        self.wall_clock_ms = (self.end_ns - self.start_ns) / 1_000_000.0

    def compute_gap_reconciliation(self) -> Dict[str, Any]:
        """
        Compute gap analysis verifying:
        WallClock = Sum(Sequential Spans) + Waiting + Unaccounted Gaps (Z)
        """
        leaves = [s for s in self.all_spans if not s.children]
        sorted_leaves = sorted(leaves, key=lambda x: x.start_ns)

        category_times = {}
        total_leaf_dur_ms = sum(s.duration_ms for s in leaves)

        # Detect gaps between consecutive leaf spans
        gaps = []
        for i in range(len(sorted_leaves) - 1):
            s1 = sorted_leaves[i]
            s2 = sorted_leaves[i + 1]
            gap_ns = s2.start_ns - s1.end_ns
            gap_ms = gap_ns / 1_000_000.0
            if gap_ms > 5.0:  # Gaps > 5ms
                gaps.append({
                    "after_span": s1.name,
                    "before_span": s2.name,
                    "gap_duration_ms": round(gap_ms, 2)
                })

        for s in leaves:
            category_times[s.category] = category_times.get(s.category, 0.0) + s.duration_ms

        unaccounted_z_ms = max(0.0, self.wall_clock_ms - total_leaf_dur_ms)

        return {
            "mission_id": self.mission_id,
            "wall_clock_ms": round(self.wall_clock_ms, 2),
            "wall_clock_seconds": round(self.wall_clock_ms / 1000.0, 2),
            "instrumented_duration_ms": round(total_leaf_dur_ms, 2),
            "unaccounted_gap_z_ms": round(unaccounted_z_ms, 2),
            "unaccounted_percent": round((unaccounted_z_ms / max(1.0, self.wall_clock_ms)) * 100.0, 2),
            "category_times_ms": {k: round(v, 2) for k, v in sorted(category_times.items(), key=lambda x: x[1], reverse=True)},
            "category_times_seconds": {k: round(v / 1000.0, 2) for k, v in sorted(category_times.items(), key=lambda x: x[1], reverse=True)},
            "detected_gaps": gaps,
            "span_count": len(self.all_spans),
            "model_switches_count": len(self.model_switches),
            "total_model_switch_ms": round(sum(sw.duration_ms for sw in self.model_switches), 2)
        }

    def generate_waterfall(self) -> str:
        """Produce text-based ASCII waterfall timeline from timestamps."""
        lines = [f"=== MISSION WATERFALL: {self.mission_id} (Total: {self.wall_clock_ms/1000.0:.2f}s) ==="]
        t0 = self.start_ns
        for s in self.all_spans:
            rel_start_s = (s.start_ns - t0) / 1_000_000_000.0
            rel_end_s = (s.end_ns - t0) / 1_000_000_000.0
            indent = "  " * (1 if s.parent_id else 0)
            lines.append(f"  {rel_start_s:6.2f}s - {rel_end_s:6.2f}s ({s.duration_ms/1000.0:5.2f}s) | {indent}[{s.category:^10}] {s.name}")
        return "\n".join(lines)
