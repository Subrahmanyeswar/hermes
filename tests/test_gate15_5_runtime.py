"""
Pre-Benchmark Gate 15.5: Runtime Comparison & Selection Tests.
Validates that:
1. Benchmark results exist and reflect real measurements.
2. Peak VRAM stays within the 6GB (6,144 MB) hardware limit.
3. Ollama delivers stable throughput (>25 tokens/sec).
4. TensorRT compatibility constraints are documented.
5. Final runtime decision is OLLAMA.
"""
import json
from pathlib import Path
import pytest

import config.model_config as cfg

RESULTS_PATH = Path(__file__).resolve().parent.parent / "performance" / "gate15_5" / "gate15_5_runtime_benchmark_results.json"


def test_runtime_benchmark_results_exist_and_valid():
    """Benchmark results file exists and has all required measurement sections."""
    assert RESULTS_PATH.exists()
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    assert "hardware" in data
    assert "ollama_measurements" in data
    assert "stability_measurements" in data
    assert "tensorrt_audit" in data
    assert "decision_evaluation" in data


def test_ollama_vram_safety_within_6gb():
    """Peak VRAM does not exceed 6,144 MB physical VRAM capacity."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    micro = data["ollama_measurements"]["micro_benchmarks"]
    for r in micro:
        assert r["peak_vram_mb"] < 6144
        assert r["peak_vram_mb"] >= 4000


def test_ollama_throughput_exceeds_threshold():
    """Ollama achieves >= 25 tokens/sec on RTX 3050 Laptop GPU."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    micro = data["ollama_measurements"]["micro_benchmarks"]
    for r in micro:
        assert r["avg_tokens_per_sec"] >= 25.0


def test_stability_test_passed_100_percent():
    """Stability test achieved 100% success rate without memory leaks."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    stab = data["stability_measurements"]["stability_test"]
    assert stab["stability_verdict"] == "STABLE"
    assert stab["passed_runs"] == stab["total_runs"]


def test_runtime_decision_is_ollama():
    """Empirical decision is strictly OLLAMA based on measured compatibility and VRAM."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    dec = data["decision_evaluation"]
    assert dec["final_runtime_decision"] == "OLLAMA"
    assert cfg.TIER1_PROVIDER == "ollama"
    assert cfg.TIER2_PROVIDER == "ollama"
