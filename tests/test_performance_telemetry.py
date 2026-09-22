# tests/test_performance_telemetry.py
import json
import time
from pathlib import Path
import pytest

from core.telemetry import (
    telemetry,
    ModelCallTelemetry,
    ModelSwitchTelemetry,
    ToolTelemetry,
    VerificationTelemetry,
    RepairTelemetry,
    StageSpan,
    ContextBreakdown,
)

def test_1_model_call_telemetry_fields():
    mc = ModelCallTelemetry(
        request_id="req_123",
        mission_id="mission_123",
        task_id="task_123",
        stage="Tier 1",
        model="deepseek-r1:8b",
        provider="ollama",
        start_time_monotonic=10.0,
        end_time_monotonic=12.5,
        start_timestamp="2026-09-13T12:00:00Z",
        end_timestamp="2026-09-13T12:00:02Z",
        total_latency_ms=2500.0,
        total_duration=2500.0,
        load_duration=100.0,
        prompt_eval_count=200,
        prompt_eval_duration=400.0,
        eval_count=150,
        eval_duration=2000.0,
        ttft_ms=500.0,
        tokens_per_second=75.0,
        think_enabled=False,
        thinking_present=True,
        thinking_available=False,
        thinking_length=120,
        final_response_length=80,
        tool_call_count=1,
        warm_cold_state="WARM",
        model_switch_state="SAME",
        previous_model="deepseek-r1:8b",
        requested_model="deepseek-r1:8b",
        raw_timing_metadata={"total_duration": 2500000000},
    )
    assert mc.request_id == "req_123"
    assert mc.model == "deepseek-r1:8b"
    assert mc.thinking_available is False
    assert mc.eval_count == 150
    assert mc.raw_timing_metadata["total_duration"] == 2500000000

def test_2_stage_spans_monotonic_and_positive():
    telemetry.clear()
    req = telemetry.start_request("test stage timing")
    req_id = req.request_id

    with telemetry.span("Stage 1: Test Span", request_id=req_id, stage_number=1) as s:
        time.sleep(0.01)

    req_retrieved = telemetry.get_request(req_id)
    assert req_retrieved is not None
    assert len(req_retrieved.spans) == 1
    span = req_retrieved.spans[0]
    assert span.name == "Stage 1: Test Span"
    assert span.start_time_monotonic <= span.end_time_monotonic
    assert span.duration_ms > 0
    telemetry.finish_request(req_id, success=True)

def test_3_tool_telemetry_recording():
    telemetry.clear()
    req = telemetry.start_request("test tool timing")
    req_id = req.request_id

    t_start = time.monotonic()
    time.sleep(0.01)
    t_end = time.monotonic()

    tool = ToolTelemetry(
        tool_name="write_file",
        category="filesystem",
        start_time_monotonic=t_start,
        duration_ms=(t_end - t_start) * 1000.0,
        filesystem_duration_ms=(t_end - t_start) * 1000.0,
        subprocess_duration_ms=0.0,
        success=True,
        exit_code=0,
        args_size_bytes=128,
        output_size_bytes=64,
        retry_count=0,
        mission_id="m_1",
        task_id="t_1",
        start=t_start,
        end=t_end,
    )
    telemetry.record_tool(tool, request_id=req_id)

    req_retrieved = telemetry.get_request(req_id)
    assert req_retrieved is not None
    assert len(req_retrieved.tools) == 1
    t_rec = req_retrieved.tools[0]
    assert t_rec.tool_name == "write_file"
    assert t_rec.success is True
    assert t_rec.exit_code == 0
    assert t_rec.duration_ms > 0
    assert t_rec.mission_id == "m_1"
    telemetry.finish_request(req_id, success=True)

def test_4_verification_telemetry_recording():
    telemetry.clear()
    req = telemetry.start_request("test verification telemetry")
    req_id = req.request_id

    v_start = time.perf_counter()
    time.sleep(0.01)
    v_end = time.perf_counter()

    ver = VerificationTelemetry(
        request_id=req_id,
        mission_id="m_2",
        task_id="t_2",
        method="deterministic",
        start_time_monotonic=v_start,
        end_time_monotonic=v_end,
        duration_ms=(v_end - v_start) * 1000.0,
        verdict="AGREE",
        escalated=False,
        issues_count=0,
        issues=[],
    )
    telemetry.record_verification(ver, request_id=req_id)

    req_retrieved = telemetry.get_request(req_id)
    assert req_retrieved is not None
    assert len(req_retrieved.verification_calls) == 1
    v_rec = req_retrieved.verification_calls[0]
    assert v_rec.verdict == "AGREE"
    assert v_rec.method == "deterministic"
    assert v_rec.duration_ms > 0
    telemetry.finish_request(req_id, success=True)

def test_5_repair_telemetry_recording():
    telemetry.clear()
    req = telemetry.start_request("test repair telemetry")
    req_id = req.request_id

    r_start = time.perf_counter()
    time.sleep(0.01)
    r_end = time.perf_counter()

    rep = RepairTelemetry(
        request_id=req_id,
        mission_id="m_3",
        task_id="t_3",
        attempt_number=1,
        trigger="FileNotFoundError",
        affected_files=["app.py"],
        start_time_monotonic=r_start,
        end_time_monotonic=r_end,
        duration_ms=(r_end - r_start) * 1000.0,
        model="deepseek-r1:8b",
        success=True,
    )
    telemetry.record_repair(rep, request_id=req_id)

    req_retrieved = telemetry.get_request(req_id)
    assert req_retrieved is not None
    assert len(req_retrieved.repair_attempts) == 1
    r_rec = req_retrieved.repair_attempts[0]
    assert r_rec.attempt_number == 1
    assert r_rec.trigger == "FileNotFoundError"
    assert r_rec.success is True
    telemetry.finish_request(req_id, success=True)

def test_6_no_duplicate_telemetry_records():
    telemetry.clear()
    req = telemetry.start_request("test deduplication")
    req_id = req.request_id

    with telemetry.span("Unique Span", request_id=req_id):
        pass

    req_retrieved = telemetry.get_request(req_id)
    assert len(req_retrieved.spans) == 1
    telemetry.finish_request(req_id, success=True)

def test_7_exported_trace_schema_and_accounting(tmp_path):
    telemetry.clear()
    req = telemetry.start_request("test trace export", mission_id="golden_probe_mission")
    req_id = req.request_id

    span = StageSpan(
        name="Stage 1",
        stage_number=1,
        request_id=req_id,
        start_time_monotonic=time.perf_counter(),
        end_time_monotonic=time.perf_counter() + 0.01,
        duration_ms=10.0,
        success=True,
    )
    telemetry.record_span(span, request_id=req_id)

    trace_path = tmp_path / "mission_trace.json"
    finished = telemetry.finish_request(req_id, success=True)
    exported = telemetry.export_performance_trace(req_id, filepath=str(trace_path))

    assert exported is not None
    assert trace_path.exists()

    with open(trace_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["mission_id"] == "golden_probe_mission"
    assert "mission" in data
    assert "duration_ms" in data["mission"]
    assert "accounted_time_ms" in data["mission"]
    assert "unaccounted_time_ms" in data["mission"]
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "Stage 1"
    assert "model_calls" in data
    assert "tool_calls" in data
    assert "verification_calls" in data
    assert "repair_attempts" in data
    assert "model_switches" in data
