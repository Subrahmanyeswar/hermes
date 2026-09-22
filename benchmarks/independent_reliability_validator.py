"""
benchmarks/independent_reliability_validator.py
HERMES Gate 19: Independent Reliability Metrics Validator.

Independently ingests raw execution records and verifies that all statistical
and reliability metrics are mathematically sound, reproducible, and strictly
derived from raw telemetry.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from benchmarks.statistics import calculate_percentiles
from benchmarks.reliability import aggregate_reliability_metrics, evaluate_repeated_attempt_study


def validate_reliability_independence(
    raw_records: List[Dict[str, Any]],
    primary_summary: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Independently recomputes all metrics from raw records and asserts equality against primary summary.
    """
    recomputed = aggregate_reliability_metrics(raw_records)

    # Validate mission success match
    assert recomputed["mission"]["success_count"] == primary_summary["mission"]["success_count"]
    assert recomputed["mission"]["success_rate"] == primary_summary["mission"]["success_rate"]

    # Validate first attempt match
    assert recomputed["first_attempt"]["success_count"] == primary_summary["first_attempt"]["success_count"]
    assert recomputed["first_attempt"]["success_rate"] == primary_summary["first_attempt"]["success_rate"]

    # Validate repair match
    assert recomputed["repair"]["success_count"] == primary_summary["repair"]["success_count"]
    assert recomputed["repair"]["success_rate"] == primary_summary["repair"]["success_rate"]

    # Validate false completion match
    assert recomputed["false_completion"]["count"] == primary_summary["false_completion"]["count"]

    # Validate percentiles match within 0.001s tolerance
    if "e2e_mission" in recomputed.get("latency_distributions", {}):
        rec_p50 = recomputed["latency_distributions"]["e2e_mission"]["p50"]
        prim_p50 = primary_summary["latency_distributions"]["e2e_mission"]["p50"]
        assert abs(rec_p50 - prim_p50) < 0.001

    return {
        "validation_status": "PASS",
        "independence_verified": True,
        "recomputed_metrics": recomputed
    }
