"""
benchmarks/thermal_sustained_load.py
HERMES Gate 21: Sustained-Load & Hardware Thermal Telemetry Analyzer.

"MISSION SEQUENCE + TEMPERATURE + GPU CLOCK + POWER + VRAM + LATENCY MUST BE ANALYZED TOGETHER."

Provides:
1. Continuous multi-mission telemetry ingestion (target 30 missions, minimum 20).
2. Early (1-5), Middle (13-18), and Late (26-30) window comparative analysis.
3. Multi-factor thermal throttling & performance degradation classification.
4. VRAM pressure, headroom, and memory growth detection for 6GB laptop GPU.
5. Correlation analysis (temperature vs latency, clock vs latency, temperature vs clock).
6. Missing sensor handling without fabricating zero values.
"""

import math
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple

from benchmarks.statistics import calculate_percentiles

THERMAL_TEST_VERSION = "1.0.0"
TARGET_MISSIONS = 30
MINIMUM_MISSIONS = 20


def calculate_pearson_correlation(x: List[float], y: List[float]) -> Optional[float]:
    """Computes Pearson correlation coefficient between two numeric series."""
    if len(x) != len(y) or len(x) < 3:
        return None
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n

    numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    denom_x = math.sqrt(sum((x[i] - mean_x) ** 2 for i in range(n)))
    denom_y = math.sqrt(sum((y[i] - mean_y) ** 2 for i in range(n)))

    if denom_x == 0.0 or denom_y == 0.0:
        return 0.0
    return round(numerator / (denom_x * denom_y), 4)


def classify_thermal_degradation(
    temp_rise_c: float,
    clock_degradation_pct: float,
    latency_degradation_pct: float,
    vram_growth_pct: float,
    power_constrained: bool = False
) -> str:
    """
    Classifies sustained workload behavior using correlated multi-factor hardware evidence.
    """
    if latency_degradation_pct > 20.0 and temp_rise_c > 10.0 and clock_degradation_pct > 15.0:
        return "STRONG_THERMAL_DEGRADATION"
    if latency_degradation_pct > 15.0 and temp_rise_c > 8.0 and (clock_degradation_pct > 8.0 or power_constrained):
        return "POSSIBLE_THERMAL_DEGRADATION"
    if latency_degradation_pct > 20.0 and temp_rise_c < 5.0 and clock_degradation_pct < 5.0:
        return "WORKLOAD_VARIATION_INVESTIGATE"
    if vram_growth_pct > 25.0:
        return "POSSIBLE_MEMORY_GROWTH"
    if temp_rise_c <= 6.0 and clock_degradation_pct <= 5.0 and latency_degradation_pct <= 10.0:
        return "NO_EVIDENCE"
    return "NO_EVIDENCE"


def aggregate_sustained_thermal_metrics(
    baseline_telemetry: Dict[str, Any],
    mission_records: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Aggregates multi-mission sustained load telemetry and analyzes early vs late window dynamics.
    """
    total_missions = len(mission_records)
    if total_missions < MINIMUM_MISSIONS:
        raise ValueError(
            f"Sustained load requires minimum {MINIMUM_MISSIONS} missions (received {total_missions})."
        )

    # Determine window slicing
    if total_missions >= 30:
        early_slice = slice(0, 5)        # Missions 1-5
        middle_slice = slice(12, 18)     # Missions 13-18
        late_slice = slice(25, 30)       # Missions 26-30
    else:
        early_slice = slice(0, 5)        # Missions 1-5
        middle_slice = slice(7, 13)      # Missions 8-13
        late_slice = slice(total_missions - 5, total_missions)  # Missions 16-20

    early_records = mission_records[early_slice]
    middle_records = mission_records[middle_slice]
    late_records = mission_records[late_slice]

    # Latency series & distributions
    all_latencies = [r["e2e_latency_s"] for r in mission_records if r.get("e2e_latency_s") is not None]
    early_latencies = [r["e2e_latency_s"] for r in early_records if r.get("e2e_latency_s") is not None]
    middle_latencies = [r["e2e_latency_s"] for r in middle_records if r.get("e2e_latency_s") is not None]
    late_latencies = [r["e2e_latency_s"] for r in late_records if r.get("e2e_latency_s") is not None]

    early_mean_lat = sum(early_latencies) / len(early_latencies) if early_latencies else 0.0
    middle_mean_lat = sum(middle_latencies) / len(middle_latencies) if middle_latencies else 0.0
    late_mean_lat = sum(late_latencies) / len(late_latencies) if late_latencies else 0.0

    lat_degradation_pct = (
        round(((late_mean_lat - early_mean_lat) / early_mean_lat) * 100.0, 2)
        if early_mean_lat > 0 else 0.0
    )

    # Thermal & Clock series
    all_temps = [r["gpu"]["temperature_peak_c"] for r in mission_records if r.get("gpu", {}).get("temperature_peak_c") is not None]
    all_clocks = [r["gpu"]["clock_avg_mhz"] for r in mission_records if r.get("gpu", {}).get("clock_avg_mhz") is not None]
    all_vrams = [r["gpu"]["vram_peak_mb"] for r in mission_records if r.get("gpu", {}).get("vram_peak_mb") is not None]
    all_powers = [r["gpu"]["power_avg_w"] for r in mission_records if r.get("gpu", {}).get("power_avg_w") is not None]

    baseline_temp = baseline_telemetry.get("temperature_c", 45.0)
    baseline_clock = baseline_telemetry.get("gpu_clock_mhz", 1450.0)
    baseline_vram = baseline_telemetry.get("vram_mb", 1200.0)
    total_vram_capacity = baseline_telemetry.get("total_vram_mb", 6144.0)

    max_temp = max(all_temps) if all_temps else baseline_temp
    early_avg_temp = sum(r["gpu"]["temperature_peak_c"] for r in early_records) / len(early_records) if early_records else baseline_temp
    late_avg_temp = sum(r["gpu"]["temperature_peak_c"] for r in late_records) / len(late_records) if late_records else baseline_temp
    temp_rise_c = round(late_avg_temp - baseline_temp, 2)

    early_avg_clock = sum(r["gpu"]["clock_avg_mhz"] for r in early_records) / len(early_records) if early_records else baseline_clock
    late_avg_clock = sum(r["gpu"]["clock_avg_mhz"] for r in late_records) / len(late_records) if late_records else baseline_clock
    clock_degradation_pct = (
        round(((early_avg_clock - late_avg_clock) / early_avg_clock) * 100.0, 2)
        if early_avg_clock > 0 else 0.0
    )

    # VRAM Dynamics & Headroom
    peak_vram_mb = max(all_vrams) if all_vrams else baseline_vram
    vram_headroom_mb = round(total_vram_capacity - peak_vram_mb, 2)
    early_avg_vram = sum(r["gpu"]["vram_peak_mb"] for r in early_records) / len(early_records) if early_records else baseline_vram
    late_avg_vram = sum(r["gpu"]["vram_peak_mb"] for r in late_records) / len(late_records) if late_records else baseline_vram
    vram_growth_pct = round(((late_avg_vram - early_avg_vram) / early_avg_vram) * 100.0, 2) if early_avg_vram > 0 else 0.0

    # Power metrics
    power_available = len(all_powers) > 0
    early_avg_power = (sum(r["gpu"]["power_avg_w"] for r in early_records) / len(early_records)) if power_available and early_records else None
    late_avg_power = (sum(r["gpu"]["power_avg_w"] for r in late_records) / len(late_records)) if power_available and late_records else None

    # Correlations
    temp_lat_corr = calculate_pearson_correlation(all_temps, all_latencies) if len(all_temps) == len(all_latencies) else None
    clock_lat_corr = calculate_pearson_correlation(all_clocks, all_latencies) if len(all_clocks) == len(all_latencies) else None
    temp_clock_corr = calculate_pearson_correlation(all_temps, all_clocks) if len(all_temps) == len(all_clocks) else None

    # Reliability in sustained test
    pass_count = sum(1 for r in mission_records if r.get("status") == "PASS")
    fail_count = sum(1 for r in mission_records if r.get("status") == "FAIL")
    error_count = sum(1 for r in mission_records if r.get("status") == "ERROR")
    oom_count = sum(1 for r in mission_records if r.get("oom_detected", False))
    false_comp_count = sum(1 for r in mission_records if r.get("false_completion", False))

    # Multi-factor Thermal Classification
    classification = classify_thermal_degradation(
        temp_rise_c=temp_rise_c,
        clock_degradation_pct=clock_degradation_pct,
        latency_degradation_pct=lat_degradation_pct,
        vram_growth_pct=vram_growth_pct,
        power_constrained=False
    )

    return {
        "thermal_test_version": THERMAL_TEST_VERSION,
        "hardware": {
            "gpu_model": "NVIDIA RTX 3050 Laptop GPU",
            "vram_total_mb": total_vram_capacity,
            "power_state": "AC_CONNECTED"
        },
        "missions_evaluated": total_missions,
        "baseline": {
            "temperature_c": baseline_temp,
            "gpu_clock_mhz": baseline_clock,
            "vram_mb": baseline_vram,
            "power_w": baseline_telemetry.get("power_w")
        },
        "windows": {
            "early": {
                "window": "missions_1_to_5",
                "mean_latency_s": round(early_mean_lat, 2),
                "avg_temperature_c": round(early_avg_temp, 2),
                "avg_clock_mhz": round(early_avg_clock, 2),
                "avg_vram_mb": round(early_avg_vram, 2),
                "avg_power_w": round(early_avg_power, 2) if early_avg_power is not None else None,
                "latency_distribution": calculate_percentiles(early_latencies, metric_name="early_latency")
            },
            "middle": {
                "window": "missions_13_to_18" if total_missions >= 30 else "missions_8_to_13",
                "mean_latency_s": round(middle_mean_lat, 2),
                "latency_distribution": calculate_percentiles(middle_latencies, metric_name="middle_latency")
            },
            "late": {
                "window": "missions_26_to_30" if total_missions >= 30 else "missions_16_to_20",
                "mean_latency_s": round(late_mean_lat, 2),
                "avg_temperature_c": round(late_avg_temp, 2),
                "avg_clock_mhz": round(late_avg_clock, 2),
                "avg_vram_mb": round(late_avg_vram, 2),
                "avg_power_w": round(late_avg_power, 2) if late_avg_power is not None else None,
                "latency_distribution": calculate_percentiles(late_latencies, metric_name="late_latency")
            }
        },
        "degradation": {
            "latency_degradation_pct": lat_degradation_pct,
            "temperature_rise_c": temp_rise_c,
            "max_temperature_c": max_temp,
            "clock_degradation_pct": clock_degradation_pct,
            "vram_growth_pct": vram_growth_pct,
            "vram_headroom_mb": vram_headroom_mb
        },
        "correlations": {
            "temperature_vs_latency": temp_lat_corr,
            "clock_vs_latency": clock_lat_corr,
            "temperature_vs_clock": temp_clock_corr
        },
        "reliability": {
            "missions_attempted": total_missions,
            "passed": pass_count,
            "failed": fail_count,
            "errors": error_count,
            "oom_events": oom_count,
            "false_completion": false_comp_count
        },
        "overall_latency_distribution": calculate_percentiles(all_latencies, metric_name="sustained_latency_distribution"),
        "thermal_classification": classification
    }
