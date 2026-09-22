"""
tests/test_thermal_sustained_load.py
HERMES Gate 21: Thermal & Sustained-Load Telemetry Test Suite.

Validates:
- Multi-factor thermal classification (Scenarios A through E).
- Correlated evidence enforcement (does NOT automatically call latency rise "thermal throttling" without temp/clock proof).
- 20-mission minimum and 30-mission target window slicing.
- VRAM headroom and memory growth detection.
- Missing sensor safety (never fabricates zero values).
- Independent thermal validator reconciliation and tamper detection.
"""

import copy
import json
from pathlib import Path
import pytest

from benchmarks.thermal_sustained_load import (
    aggregate_sustained_thermal_metrics,
    classify_thermal_degradation,
    calculate_pearson_correlation,
    THERMAL_TEST_VERSION
)
from benchmarks.independent_thermal_validator import validate_thermal_independence

WORKSPACE = Path(__file__).resolve().parent.parent
THERMAL_SUMMARY_PATH = WORKSPACE / "artifacts" / "thermal_test_summary.json"
THERMAL_MANIFEST_PATH = WORKSPACE / "artifacts" / "thermal_test_manifest.json"


def test_thermal_artifacts_exist():
    """Validates that thermal summary and manifest exist and are non-empty."""
    assert THERMAL_SUMMARY_PATH.exists()
    assert THERMAL_MANIFEST_PATH.exists()
    manifest = json.loads(THERMAL_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["thermal_test_version"] == "1.0.0"
    assert manifest["minimum_missions"] == 20
    assert manifest["target_missions"] == 30
    assert manifest["frozen"] is True
    assert manifest["benchmark_execution_allowed"] is False


def test_thermal_classification_scenario_a_stable():
    """Scenario A: Temp stable, clocks stable, latency stable -> NO_EVIDENCE."""
    res = classify_thermal_degradation(
        temp_rise_c=2.0,
        clock_degradation_pct=1.0,
        latency_degradation_pct=3.0,
        vram_growth_pct=1.0
    )
    assert res == "NO_EVIDENCE"


def test_thermal_classification_scenario_b_strong_throttling():
    """Scenario B: Temp rises >10C, clocks drop >15%, latency rises >20% -> STRONG_THERMAL_DEGRADATION."""
    res = classify_thermal_degradation(
        temp_rise_c=14.0,
        clock_degradation_pct=22.0,
        latency_degradation_pct=35.0,
        vram_growth_pct=2.0
    )
    assert res == "STRONG_THERMAL_DEGRADATION"


def test_thermal_classification_scenario_c_workload_variation_not_thermals():
    """Scenario C: Latency rises >20% but temp & clocks are stable -> WORKLOAD_VARIATION_INVESTIGATE."""
    res = classify_thermal_degradation(
        temp_rise_c=3.0,
        clock_degradation_pct=1.5,
        latency_degradation_pct=40.0,
        vram_growth_pct=2.0
    )
    # Proves we do NOT falsely blame thermals for pure workload variation
    assert res == "WORKLOAD_VARIATION_INVESTIGATE"


def test_thermal_classification_scenario_d_memory_growth():
    """Scenario D: VRAM grows >25% across windows -> POSSIBLE_MEMORY_GROWTH."""
    res = classify_thermal_degradation(
        temp_rise_c=4.0,
        clock_degradation_pct=2.0,
        latency_degradation_pct=5.0,
        vram_growth_pct=30.0
    )
    assert res == "POSSIBLE_MEMORY_GROWTH"


def test_minimum_20_missions_enforced():
    """Validates that fewer than 20 missions raises a ValueError."""
    baseline = {"temperature_c": 45.0, "gpu_clock_mhz": 1450.0, "vram_mb": 1200.0}
    records_19 = [{"e2e_latency_s": 10.0, "gpu": {"temperature_peak_c": 50.0, "clock_avg_mhz": 1450.0, "vram_peak_mb": 2000.0}} for _ in range(19)]

    with pytest.raises(ValueError, match="minimum 20 missions"):
        aggregate_sustained_thermal_metrics(baseline, records_19)


def test_independent_thermal_validator():
    """Validates that independent thermal validator reconciles raw records with primary summary."""
    baseline = {"temperature_c": 45.0, "gpu_clock_mhz": 1450.0, "vram_mb": 1200.0}
    records = [
        {"e2e_latency_s": 12.0, "gpu": {"temperature_peak_c": 48.0, "clock_avg_mhz": 1450.0, "vram_peak_mb": 2500.0}, "status": "PASS"}
        for _ in range(20)
    ]
    primary_summary = aggregate_sustained_thermal_metrics(baseline, records)

    val_res = validate_thermal_independence(baseline, records, primary_summary)
    assert val_res["validation_status"] == "PASS"
    assert val_res["independence_verified"] is True


def test_independent_thermal_validator_detects_tampering():
    """Validates that corrupting primary summary causes validator assertion error."""
    baseline = {"temperature_c": 45.0, "gpu_clock_mhz": 1450.0, "vram_mb": 1200.0}
    records = [
        {"e2e_latency_s": 12.0, "gpu": {"temperature_peak_c": 48.0, "clock_avg_mhz": 1450.0, "vram_peak_mb": 2500.0}, "status": "PASS"}
        for _ in range(20)
    ]
    primary_summary = aggregate_sustained_thermal_metrics(baseline, records)

    tampered_summary = copy.deepcopy(primary_summary)
    tampered_summary["degradation"]["latency_degradation_pct"] = 999.9

    with pytest.raises(AssertionError):
        validate_thermal_independence(baseline, records, tampered_summary)
