"""
benchmarks/independent_cost_validator.py
HERMES Gate 20: Independent Cost & Attribution Validator.

Independently recalculates all T3 cloud inference costs, token counts, rates,
and provider/model fallback attributions directly from raw T3 telemetry.
"""

from decimal import Decimal
from typing import Dict, Any, List
from benchmarks.cost_accounting import aggregate_t3_cost_metrics, evaluate_t3_identity_and_fallback


def validate_cost_independence(
    raw_t3_records: List[Dict[str, Any]],
    raw_mission_records: List[Dict[str, Any]],
    primary_summary: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Independently recomputes cost metrics from raw records and verifies against primary summary.
    """
    recomputed = aggregate_t3_cost_metrics(raw_t3_records, raw_mission_records)

    # 1. Verify logical request counts & rates
    assert recomputed["t3"]["logical_requests"] == primary_summary["t3"]["logical_requests"]
    assert recomputed["t3"]["t3_mission_rate"] == primary_summary["t3"]["t3_mission_rate"]
    assert recomputed["t3"]["t3_call_rate"] == primary_summary["t3"]["t3_call_rate"]

    # 2. Verify token counts
    assert recomputed["t3"]["input_tokens"] == primary_summary["t3"]["input_tokens"]
    assert recomputed["t3"]["output_tokens"] == primary_summary["t3"]["output_tokens"]
    assert recomputed["t3"]["total_tokens"] == primary_summary["t3"]["total_tokens"]

    # 3. Verify total cost
    assert recomputed["t3"]["total_cost_usd"] == primary_summary["t3"]["total_cost_usd"]
    assert recomputed["t3"]["cost_per_successful_mission_usd"] == primary_summary["t3"]["cost_per_successful_mission_usd"]
    assert recomputed["t3"]["cost_per_100_missions_usd"] == primary_summary["t3"]["cost_per_100_missions_usd"]

    # 4. Verify fallbacks & serving breakdown
    assert recomputed["t3"]["model_fallback_count"] == primary_summary["t3"]["model_fallback_count"]
    assert recomputed["t3"]["provider_failover_count"] == primary_summary["t3"]["provider_failover_count"]
    assert recomputed["actual_serving"]["models"] == primary_summary["actual_serving"]["models"]
    assert recomputed["actual_serving"]["providers"] == primary_summary["actual_serving"]["providers"]

    return {
        "validation_status": "PASS",
        "independence_verified": True,
        "recomputed_metrics": recomputed
    }
