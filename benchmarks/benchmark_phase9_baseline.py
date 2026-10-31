# benchmarks/benchmark_phase9_baseline.py
"""
HERMES Phase 9 — Comprehensive Performance Baseline & Optimization Benchmark Harness.

Measures:
1. Mission Startup & Initialization Latency
2. Event Bus Publish, Dispatch & High-Throughput Burst Performance
3. Authoritative Snapshot Assembly & Checks Extraction Latency (10, 100, 500 events)
4. Workspace Indexing & Incremental Change Detection Latency
5. Workspace File Snapshotting & CAS Deduplication Latency (Cold vs Warm Checkpoint)
6. Persistence Latency (SQLite Mission, Snapshot, Event Journal)
7. Mission Control Latency (Pause Request, Stop Signal Dispatch)
"""

import asyncio
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List

def calc_median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0

def calc_p95(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = int(math.ceil(0.95 * len(s))) - 1
    return s[max(0, min(idx, len(s) - 1))]

def calc_mean(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0

# Canonical environment check
REPO_ROOT = Path(r"C:\Users\SUBBU\Downloads\hermes").resolve()
CANONICAL_PYTHON = REPO_ROOT / "venv" / "Scripts" / "python.exe"

active_exe = Path(sys.executable).resolve()
if active_exe != CANONICAL_PYTHON.resolve():
    print(f"FATAL: Must execute with canonical Python! Active: {active_exe}, Expected: {CANONICAL_PYTHON}")
    sys.exit(1)

sys.path.insert(0, str(REPO_ROOT))

from core.event_bus import EventBus, HermesEvent, EventType
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionState,
    MissionStatus,
    TaskState,
    TaskStatus,
    MissionControlContext,
)
from core.checkpoints.file_snapshot import WorkspaceSnapshotter
from core.server.runtime_adapter import RuntimeAdapter
from core.server.checks_service import extract_mission_checks
from core.workspace import WorkspaceManager


def benchmark_event_bus() -> Dict[str, Any]:
    """Measure single-event dispatch latency, burst throughput, and replay speed."""
    db_file = Path(tempfile.mktemp(suffix=".db"))
    try:
        db = SQLiteDatabase(db_file)
        bus = EventBus(enabled=True, buffer_size=2000, db=db)
        received_events = []
        bus.subscribe(lambda e: received_events.append(e.event_id))

        # 1. Single-event publish latency (100 iterations)
        single_latencies_ms: List[float] = []
        for i in range(100):
            ev = HermesEvent(
                event_type=EventType.TASK_PROGRESS,
                mission_id="m_bench_bus",
                task_id=f"t_{i % 5}",
                payload={"progress": i, "step": f"step_{i}"},
            )
            t0 = time.perf_counter()
            bus.publish(ev)
            t1 = time.perf_counter()
            single_latencies_ms.append((t1 - t0) * 1000.0)

        # 2. High-throughput burst (5,000 events)
        t_burst_start = time.perf_counter()
        burst_count = 5000
        for i in range(burst_count):
            bus.publish(
                HermesEvent(
                    event_type=EventType.MODEL_GENERATING if i % 2 == 0 else EventType.TOOL_PROGRESS,
                    mission_id="m_bench_burst",
                    payload={"chunk": i, "token": f"tok_{i}"},
                )
            )
        t_burst_end = time.perf_counter()
        burst_total_ms = (t_burst_end - t_burst_start) * 1000.0
        burst_ops_per_sec = burst_count / (burst_total_ms / 1000.0)

        # 3. In-memory replay latency
        t_replay_start = time.perf_counter()
        replayed = bus.replay("m_bench_burst", from_seq=1, to_seq=500)
        t_replay_end = time.perf_counter()
        replay_ms = (t_replay_end - t_replay_start) * 1000.0

        bus.flush(timeout=5.0)

        return {
            "single_publish_p50_ms": round(calc_median(single_latencies_ms), 4),
            "single_publish_p95_ms": round(calc_p95(single_latencies_ms), 4),
            "single_publish_avg_ms": round(calc_mean(single_latencies_ms), 4),
            "burst_total_ms": round(burst_total_ms, 2),
            "burst_throughput_events_per_sec": round(burst_ops_per_sec, 1),
            "replay_500_events_ms": round(replay_ms, 4),
        }
    finally:
        if db_file.exists():
            try:
                db_file.unlink()
            except Exception:
                pass


def benchmark_snapshot_assembly() -> Dict[str, Any]:
    """Measure snapshot assembly and verification checks extraction across event scales."""
    db_file = Path(tempfile.mktemp(suffix=".db"))
    try:
        db = SQLiteDatabase(db_file)
        adapter = RuntimeAdapter(event_bus=EventBus(enabled=True, db=db))

        # Helper to generate test mission with N events
        def setup_mission_with_events(m_id: str, num_events: int) -> None:
            db.save_mission(mission_id=m_id, workspace_path="/test/ws", status="RUNNING", prompt="Test mission for benchmarking")
            adapter.event_bus.publish(HermesEvent(
                event_type=EventType.MISSION_STARTED,
                mission_id=m_id,
                payload={"prompt": "Test mission for benchmarking", "workspace_root": "/test/ws"}
            ))
            for i in range(num_events):
                if i % 10 == 0:
                    ev_type = EventType.VERIFICATION_COMPLETED
                    payload = {"check_name": f"Check {i}", "verdict": "passed", "exit_code": 0}
                elif i % 5 == 0:
                    ev_type = EventType.TOOL_COMPLETED
                    payload = {"tool_name": "edit_file", "path": f"src/module_{i}.py", "files_modified": [f"src/module_{i}.py"]}
                elif i % 7 == 0:
                    ev_type = EventType.TOOL_COMPLETED
                    payload = {"tool_name": "create_file", "path": f"src/new_file_{i}.py", "files_created": [f"src/new_file_{i}.py"]}
                else:
                    ev_type = EventType.TASK_PROGRESS
                    payload = {"task_id": f"task_{i % 3}", "progress": i}
                adapter.event_bus.publish(HermesEvent(
                    event_type=ev_type,
                    mission_id=m_id,
                    task_id=f"task_{i % 3}",
                    payload=payload
                ))
            adapter.event_bus.publish(HermesEvent(
                event_type=EventType.MISSION_COMPLETED,
                mission_id=m_id,
                payload={"final_output": "Mission completed successfully.", "output": "Done"}
            ))

        # Benchmark snapshot assembly at 10, 100, and 500 events
        scales = [10, 100, 500]
        assembly_results = {}

        for scale in scales:
            m_id = f"m_snap_{scale}"
            setup_mission_with_events(m_id, scale)

            durations_ms = []
            for _ in range(50):
                t0 = time.perf_counter()
                state = adapter.get_mission_snapshot(m_id)
                events = adapter.get_events_since(m_id, 0)
                checks = extract_mission_checks(m_id, state, events)
                # simulate endpoint gathering
                t1 = time.perf_counter()
                durations_ms.append((t1 - t0) * 1000.0)

            assembly_results[f"snapshot_{scale}_events_p50_ms"] = round(calc_median(durations_ms), 3)
            assembly_results[f"snapshot_{scale}_events_p95_ms"] = round(calc_p95(durations_ms), 3)
            assembly_results[f"snapshot_{scale}_events_avg_ms"] = round(calc_mean(durations_ms), 3)

        return assembly_results
    finally:
        if db_file.exists():
            try:
                db_file.unlink()
            except Exception:
                pass


def benchmark_workspace_and_checkpoints() -> Dict[str, Any]:
    """Measure workspace indexing and FileSnapshotter cold vs warm checkpoint latency."""
    ws_dir = Path(tempfile.mkdtemp(prefix="hermes_bench_ws_"))
    blob_dir = Path(tempfile.mkdtemp(prefix="hermes_bench_blobs_"))
    try:
        # Create a realistic project workspace with 50 files
        subdirs = ["src", "src/core", "src/utils", "tests", "docs"]
        for sd in subdirs:
            (ws_dir / sd).mkdir(parents=True, exist_ok=True)

        for i in range(50):
            if i < 25:
                p = ws_dir / "src" / f"module_{i}.py"
                p.write_text(f"class Service{i}:\n    def process_{i}(self):\n        return {i * 10}\n", encoding="utf-8")
            elif i < 40:
                p = ws_dir / "tests" / f"test_{i}.py"
                p.write_text(f"def test_{i}():\n    assert {i} > 0\n", encoding="utf-8")
            else:
                p = ws_dir / "docs" / f"doc_{i}.md"
                p.write_text(f"# Documentation {i}\nDetails here.\n", encoding="utf-8")

        # 1. Cold workspace indexing
        wm = WorkspaceManager()
        t0 = time.perf_counter()
        wm.lock(str(ws_dir))
        t1 = time.perf_counter()
        cold_index_ms = (t1 - t0) * 1000.0

        # 2. Warm workspace refresh (no files modified)
        t2 = time.perf_counter()
        wm.refresh_index()
        t3 = time.perf_counter()
        warm_refresh_ms = (t3 - t2) * 1000.0

        # 3. Cold file checkpoint snapshot
        blob_store = BlobStore(blob_dir)
        snapshotter = WorkspaceSnapshotter(workspace_root=ws_dir, blob_store=blob_store)
        t4 = time.perf_counter()
        manifest1 = snapshotter.create_snapshot()
        t5 = time.perf_counter()
        cold_snapshot_ms = (t5 - t4) * 1000.0

        # 4. Warm file checkpoint snapshot (prior_manifest provided, 0 files changed)
        warm_snapshot_latencies = []
        for _ in range(10):
            t6 = time.perf_counter()
            manifest2 = snapshotter.create_snapshot(prior_manifest=manifest1)
            t7 = time.perf_counter()
            warm_snapshot_latencies.append((t7 - t6) * 1000.0)
        warm_snapshot_ms = calc_median(warm_snapshot_latencies)

        # 5. Incremental snapshot (1 file modified out of 50)
        (ws_dir / "src" / "module_0.py").write_text("class Service0:\n    # modified\n    pass\n", encoding="utf-8")
        t8 = time.perf_counter()
        manifest3 = snapshotter.create_snapshot(prior_manifest=manifest1)
        t9 = time.perf_counter()
        single_mod_snapshot_ms = (t9 - t8) * 1000.0

        return {
            "workspace_files_count": 50,
            "cold_workspace_index_ms": round(cold_index_ms, 3),
            "warm_workspace_refresh_ms": round(warm_refresh_ms, 3),
            "cold_checkpoint_snapshot_ms": round(cold_snapshot_ms, 3),
            "warm_checkpoint_snapshot_p50_ms": round(warm_snapshot_ms, 3),
            "single_file_mod_snapshot_ms": round(single_mod_snapshot_ms, 3),
        }
    finally:
        shutil.rmtree(ws_dir, ignore_errors=True)
        shutil.rmtree(blob_dir, ignore_errors=True)


def benchmark_persistence_layer() -> Dict[str, Any]:
    """Measure SQLite database operations latency (mission insert, snapshot, journal append)."""
    db_file = Path(tempfile.mktemp(suffix=".db"))
    try:
        db = SQLiteDatabase(db_file)

        # 1. Mission creation latency (50 iterations)
        m_create_times = []
        for i in range(50):
            t0 = time.perf_counter()
            db.save_mission(f"m_persist_{i}", workspace_path="/test/ws", status="RUNNING", prompt=f"Mission {i}")
            t1 = time.perf_counter()
            m_create_times.append((t1 - t0) * 1000.0)

        # 2. Event journal write latency (100 individual appends)
        evt_append_times = []
        for i in range(100):
            ev = HermesEvent(
                event_type=EventType.TASK_PROGRESS,
                mission_id="m_persist_0",
                sequence=i + 1,
                payload={"step": i},
            )
            t0 = time.perf_counter()
            db.append_mission_event(ev)
            t1 = time.perf_counter()
            evt_append_times.append((t1 - t0) * 1000.0)

        # 3. Snapshot save latency (20 iterations)
        state = HermesRuntimeState.create_empty("m_persist_0")
        from core.persistence.serializer import serialize_runtime_state
        state_dict, state_hash = serialize_runtime_state(state)
        snap_save_times = []
        for _ in range(20):
            t0 = time.perf_counter()
            db.save_snapshot("m_persist_0", "/test/ws", "RUNNING", state_dict, state_hash)
            t1 = time.perf_counter()
            snap_save_times.append((t1 - t0) * 1000.0)

        # 4. Snapshot read latency (50 iterations)
        snap_read_times = []
        for _ in range(50):
            t0 = time.perf_counter()
            _ = db.get_snapshot("m_persist_0")
            t1 = time.perf_counter()
            snap_read_times.append((t1 - t0) * 1000.0)

        return {
            "mission_create_avg_ms": round(calc_mean(m_create_times), 3),
            "mission_create_p50_ms": round(calc_median(m_create_times), 3),
            "event_journal_append_avg_ms": round(calc_mean(evt_append_times), 3),
            "event_journal_append_p50_ms": round(calc_median(evt_append_times), 3),
            "snapshot_save_avg_ms": round(calc_mean(snap_save_times), 3),
            "snapshot_save_p50_ms": round(calc_median(snap_save_times), 3),
            "snapshot_read_avg_ms": round(calc_mean(snap_read_times), 3),
            "snapshot_read_p50_ms": round(calc_median(snap_read_times), 3),
        }
    finally:
        if db_file.exists():
            try:
                db_file.unlink()
            except Exception:
                pass


def benchmark_mission_controls() -> Dict[str, Any]:
    """Measure latency of pause request and stop control actions."""
    db_file = Path(tempfile.mktemp(suffix=".db"))
    try:
        db = SQLiteDatabase(db_file)
        adapter = RuntimeAdapter(event_bus=EventBus(enabled=True, db=db))

        m_id = "m_ctrl_bench"
        db.save_mission(m_id, workspace_path="/test/ws", status="RUNNING")
        ctrl = MissionControlContext(
            mission_id=m_id,
            run_id="run_1",
            abort_event=asyncio.Event(),
            pause_event=asyncio.Event(),
        )
        adapter._mission_controls[m_id] = ctrl
        adapter._abort_events[m_id] = ctrl.abort_event
        adapter.event_bus.publish(HermesEvent(
            event_type=EventType.MISSION_STARTED,
            mission_id=m_id,
            payload={"prompt": "Control test"}
        ))

        # Pause request latency (20 iterations)
        pause_times = []
        for _ in range(20):
            t0 = time.perf_counter()
            adapter.request_pause(m_id)
            t1 = time.perf_counter()
            pause_times.append((t1 - t0) * 1000.0)
            ctrl.is_paused = False
            ctrl.pause_requested = False

        # Stop request latency (20 iterations)
        stop_times = []
        for _ in range(20):
            t0 = time.perf_counter()
            adapter.request_cancellation(m_id)
            t1 = time.perf_counter()
            stop_times.append((t1 - t0) * 1000.0)

        return {
            "pause_request_p50_ms": round(calc_median(pause_times), 4),
            "pause_request_avg_ms": round(calc_mean(pause_times), 4),
            "stop_request_p50_ms": round(calc_median(stop_times), 4),
            "stop_request_avg_ms": round(calc_mean(stop_times), 4),
        }
    finally:
        if db_file.exists():
            try:
                db_file.unlink()
            except Exception:
                pass


def run_full_phase9_benchmark() -> Dict[str, Any]:
    print("=" * 70)
    print(" HERMES PHASE 9 — PERFORMANCE BASELINE BENCHMARK HARNESS")
    print("=" * 70)

    print("\n[1/5] Measuring Event Bus performance...")
    bus_metrics = benchmark_event_bus()
    print(f"  -> Single publish p50: {bus_metrics['single_publish_p50_ms']} ms")
    print(f"  -> Burst throughput: {bus_metrics['burst_throughput_events_per_sec']:,.0f} events/sec")
    print(f"  -> Replay 500 events: {bus_metrics['replay_500_events_ms']} ms")

    print("\n[2/5] Measuring Snapshot assembly & checks extraction...")
    snap_metrics = benchmark_snapshot_assembly()
    print(f"  -> 10 events snapshot p50: {snap_metrics['snapshot_10_events_p50_ms']} ms")
    print(f"  -> 100 events snapshot p50: {snap_metrics['snapshot_100_events_p50_ms']} ms")
    print(f"  -> 500 events snapshot p50: {snap_metrics['snapshot_500_events_p50_ms']} ms")

    print("\n[3/5] Measuring Workspace indexing & Checkpoint snapshotting...")
    ws_metrics = benchmark_workspace_and_checkpoints()
    print(f"  -> Cold workspace index (50 files): {ws_metrics['cold_workspace_index_ms']} ms")
    print(f"  -> Warm workspace refresh: {ws_metrics['warm_workspace_refresh_ms']} ms")
    print(f"  -> Cold checkpoint snapshot (50 files): {ws_metrics['cold_checkpoint_snapshot_ms']} ms")
    print(f"  -> Warm checkpoint snapshot (0 changes): {ws_metrics['warm_checkpoint_snapshot_p50_ms']} ms")
    print(f"  -> 1-file modified checkpoint snapshot: {ws_metrics['single_file_mod_snapshot_ms']} ms")

    print("\n[4/5] Measuring Persistence layer latency...")
    persist_metrics = benchmark_persistence_layer()
    print(f"  -> Mission create p50: {persist_metrics['mission_create_p50_ms']} ms")
    print(f"  -> Event journal append p50: {persist_metrics['event_journal_append_p50_ms']} ms")
    print(f"  -> Snapshot save p50: {persist_metrics['snapshot_save_p50_ms']} ms")
    print(f"  -> Snapshot read p50: {persist_metrics['snapshot_read_p50_ms']} ms")

    print("\n[5/5] Measuring Mission control latency...")
    ctrl_metrics = benchmark_mission_controls()
    print(f"  -> Pause request p50: {ctrl_metrics['pause_request_p50_ms']} ms")
    print(f"  -> Stop request p50: {ctrl_metrics['stop_request_p50_ms']} ms")

    full_results = {
        "timestamp": time.time(),
        "python_version": sys.version,
        "event_bus": bus_metrics,
        "snapshot_assembly": snap_metrics,
        "workspace_and_checkpoints": ws_metrics,
        "persistence": persist_metrics,
        "controls": ctrl_metrics,
    }

    out_file = REPO_ROOT / "artifacts" / "phase9" / "baseline_metrics.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(full_results, indent=2), encoding="utf-8")
    print(f"\n[OK] Full benchmark metrics saved to: {out_file}")
    return full_results


if __name__ == "__main__":
    run_full_phase9_benchmark()
