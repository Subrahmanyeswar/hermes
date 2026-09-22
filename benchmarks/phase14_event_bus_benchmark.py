"""
Phase 14 Unified Event Bus & Event-Driven TUI Benchmark.
Measures:
1. Event publish and dispatch latency (<0.01ms)
2. High-throughput burst processing (events/sec)
3. State store reconstruction latency
4. TUI live view render latency (<0.5ms)
5. Zero memory leakage with bounded ring buffer
"""
import time
import json
from pathlib import Path

from core.event_bus import (
    HermesEvent,
    EventType,
    EventSeverity,
    ExecutionStateStore,
    EventBus
)
from ui.event_tui import EventDrivenTUI

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase14"
PERF_DIR.mkdir(parents=True, exist_ok=True)

def run_event_bus_benchmark():
    print("================================================================")
    print(" PHASE 14 UNIFIED EVENT BUS + EVENT-DRIVEN TUI BENCHMARK")
    print("================================================================")

    bus = EventBus(enabled=True, buffer_size=1000)
    tui = EventDrivenTUI(mission_id="m_bench")
    bus.subscribe(tui.handle_event)

    # 1. Single Event Dispatch Latency
    print("\n[TEST 1] Single Event Dispatch Latency...")
    latencies = []
    for i in range(100):
        ev = HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id="m_bench",
            task_id="t1",
            payload={"pct": i}
        )
        t0 = time.perf_counter()
        bus.publish(ev)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_publish_ms = sum(latencies) / len(latencies)
    print(f"  -> Average Publish + Dispatch Latency: {avg_publish_ms:.4f} ms (< 0.01 ms target)")

    # 2. High-Throughput Burst Test (10,000 events)
    print("\n[TEST 2] High-Throughput Event Burst (10,000 events)...")
    t0 = time.perf_counter()
    for i in range(10000):
        bus.publish(HermesEvent(
            event_type=EventType.MODEL_TTFT if i % 2 == 0 else EventType.TOOL_PROGRESS,
            mission_id="m_bench",
            payload={"iter": i}
        ))
    burst_total_ms = (time.perf_counter() - t0) * 1000.0
    throughput = 10000 / (burst_total_ms / 1000.0)
    print(f"  -> Processed 10,000 events in {burst_total_ms:.2f} ms ({throughput:,.0f} events/sec)")

    # 3. State Store Reconstruction Speed
    print("\n[TEST 3] State Store Reconstruction from Events...")
    t0 = time.perf_counter()
    st = bus.get_state("m_bench")
    reconstruct_ms = (time.perf_counter() - t0) * 1000.0
    print(f"  -> State Store Retrieval Latency: {reconstruct_ms:.4f} ms")

    # 4. TUI Render Formatting Latency
    print("\n[TEST 4] TUI Layout Formatting & Redaction Latency...")
    t0 = time.perf_counter()
    rendered_output = tui.format_view(st)
    render_ms = (time.perf_counter() - t0) * 1000.0
    print(f"  -> TUI View Format & Redact Latency: {render_ms:.4f} ms (< 0.5 ms target)")

    report = {
        "avg_publish_latency_ms": round(avg_publish_ms, 4),
        "burst_throughput_events_per_sec": round(throughput, 1),
        "state_retrieval_latency_ms": round(reconstruct_ms, 4),
        "tui_render_latency_ms": round(render_ms, 4),
        "buffer_bounded": len(bus._history) <= 1000
    }

    (PERF_DIR / "phase14_event_bus_benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved results to {PERF_DIR / 'phase14_event_bus_benchmark.json'}")

if __name__ == "__main__":
    run_event_bus_benchmark()
