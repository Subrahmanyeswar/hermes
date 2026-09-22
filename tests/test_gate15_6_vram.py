"""
Pre-Benchmark Gate 15.6: Real Workload VRAM & Residency Tests.
Validates that:
1. gate_15_6_vram_results.json and gate_15_6_vram_samples.jsonl exist.
2. Overall peak VRAM does not exceed 6,144 MB physical capacity.
3. Minimum headroom is >= 400 MB.
4. Warm residency provides significant speedup over cold start.
5. Zero OOM errors, zero CUDA errors, and zero CPU fallbacks across V1-V12.
"""
import json
from pathlib import Path
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
RESULTS_PATH = WORKSPACE / "artifacts" / "gate_15_6_vram_results.json"
SAMPLES_PATH = WORKSPACE / "artifacts" / "gate_15_6_vram_samples.jsonl"


def test_vram_results_and_samples_exist():
    """VRAM summary results and time-series sample files exist."""
    assert RESULTS_PATH.exists()
    assert SAMPLES_PATH.exists()
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    assert "hardware_baseline" in data
    assert "test_matrix" in data
    assert len(data["test_matrix"]) == 12


def test_vram_ceiling_and_headroom():
    """Overall peak VRAM stays within 6,144 MB and maintains headroom."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    hw = data["hardware_baseline"]
    assert hw["overall_peak_vram_mb"] <= 6144
    assert hw["overall_peak_vram_mb"] >= 5000
    assert hw["min_headroom_mb"] >= 400
    assert hw["min_headroom_mb"] <= 1000


def test_warm_residency_speedup():
    """Warm inference latency is significantly faster than cold start."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    matrix = {row["test_id"]: row for row in data["test_matrix"]}
    cold_lat = matrix["V1"]["latency_ms"]
    warm_lat = matrix["V2"]["latency_ms"]
    assert cold_lat > warm_lat * 2.0


def test_zero_oom_and_zero_cuda_errors():
    """All 12 workload scenarios ran with 0 OOM, 0 CUDA errors, and 0 CPU fallbacks."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    for row in data["test_matrix"]:
        assert row["oom"] is False
        assert row["cuda_error"] is False
        assert row["cpu_fallback"] is False
        assert row["result"] == "PASS"


def test_no_vram_accumulation_in_repeated_runs():
    """Repeated runs and model switches show no uncontrolled VRAM growth."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    res = data["residency_findings"]
    assert res["vram_accumulation_observed"] is False
    assert res["model_reload_count"] == 0
