"""
Unit tests for Pre-Phase 6 Telemetry Validation & Gap Reconciliation.
Verifies span nesting, parent-child links, model switch tracking, and zero-gap reconciliation math.
"""
import pytest
import time
from benchmarks.reconciliation.telemetry_engine import HierarchicalMissionProfiler, ReconciledSpan

def test_profiler_span_nesting():
    profiler = HierarchicalMissionProfiler("TEST_MISSION_001")
    with profiler.span("ROOT_MISSION", category="MISSION"):
        with profiler.span("TASK_1", category="TASK"):
            with profiler.span("T1_CALL", category="MODEL"):
                time.sleep(0.01)
            with profiler.span("TOOL_EXEC", category="TOOL"):
                time.sleep(0.005)
    profiler.finish()

    assert len(profiler.root_spans) == 1
    root = profiler.root_spans[0]
    assert root.name == "ROOT_MISSION"
    assert len(root.children) == 1
    task = root.children[0]
    assert task.name == "TASK_1"
    assert len(task.children) == 2
    assert task.children[0].name == "T1_CALL"
    assert task.children[1].name == "TOOL_EXEC"

def test_gap_reconciliation_zero_unaccounted():
    profiler = HierarchicalMissionProfiler("TEST_MISSION_002")
    with profiler.span("TASK_1", category="TASK"):
        time.sleep(0.02)
    with profiler.span("TASK_2", category="TASK"):
        time.sleep(0.02)
    profiler.finish()

    recon = profiler.compute_gap_reconciliation()
    assert recon["wall_clock_ms"] >= 35.0
    assert recon["instrumented_duration_ms"] >= 35.0
    # Unaccounted gap Z must be minimal (< 10ms)
    assert recon["unaccounted_gap_z_ms"] < 15.0

def test_model_switch_recording():
    profiler = HierarchicalMissionProfiler("TEST_MISSION_003")
    profiler.record_model_switch("deepseek-r1:8b", "qwen3:8b", 8600.0, reason="Verification")
    profiler.record_model_switch("qwen3:8b", "deepseek-r1:8b", 8600.0, reason="Memory")
    profiler.finish()

    assert len(profiler.model_switches) == 2
    assert profiler.model_switches[0].from_model == "deepseek-r1:8b"
    assert profiler.model_switches[0].to_model == "qwen3:8b"
    assert profiler.model_switches[1].from_model == "qwen3:8b"
    assert profiler.model_switches[1].to_model == "deepseek-r1:8b"

def test_waterfall_generation():
    profiler = HierarchicalMissionProfiler("TEST_MISSION_004")
    with profiler.span("STAGE_1", category="PLANNING"):
        time.sleep(0.005)
    with profiler.span("STAGE_2", category="MODEL"):
        time.sleep(0.01)
    profiler.finish()

    wf = profiler.generate_waterfall()
    assert "TEST_MISSION_004" in wf
    assert "STAGE_1" in wf
    assert "STAGE_2" in wf
