"""
tests/test_t3_identity_attribution.py
HERMES Gate 20: T3 Identity Attribution & Fallback Detection Test Suite.

Validates:
- Requested model vs actual serving model.
- Requested provider vs actual serving provider.
- Model fallback detection.
- Provider failover detection.
- Both fallback detection.
- Independent cost validator checks.
- Tamper detection on primary summary.
"""

import copy
import pytest
from benchmarks.cost_accounting import evaluate_t3_identity_and_fallback, aggregate_t3_cost_metrics
from benchmarks.independent_cost_validator import validate_cost_independence


def test_identity_exact_match_no_fallback():
    """Case 1: Requested and actual match perfectly -> No fallback, no failover."""
    record = {
        "requested_model": "stealth/ox-alpha",
        "requested_provider": "openrouter",
        "actual_model": "stealth/ox-alpha",
        "actual_provider": "openrouter",
        "status": "SUCCESS"
    }
    res = evaluate_t3_identity_and_fallback(record)
    assert res["model_fallback"] is False
    assert res["provider_failover"] is False
    assert res["fallback_type"] == "NONE"
    assert res["identity_status"] == "KNOWN"


def test_model_fallback_detection():
    """Case 2: Requested model differs from actual serving model."""
    record = {
        "requested_model": "stealth/ox-alpha",
        "requested_provider": "openrouter",
        "actual_model": "anthropic/claude-3.5-sonnet",
        "actual_provider": "openrouter",
        "status": "SUCCESS"
    }
    res = evaluate_t3_identity_and_fallback(record)
    assert res["model_fallback"] is True
    assert res["provider_failover"] is False
    assert res["fallback_type"] == "MODEL_FALLBACK"


def test_provider_failover_detection():
    """Case 3: Requested provider differs from actual serving provider."""
    record = {
        "requested_model": "stealth/ox-alpha",
        "requested_provider": "openrouter",
        "actual_model": "stealth/ox-alpha",
        "actual_provider": "openrouter_backup_cluster",
        "status": "SUCCESS"
    }
    res = evaluate_t3_identity_and_fallback(record)
    assert res["model_fallback"] is False
    assert res["provider_failover"] is True
    assert res["fallback_type"] == "PROVIDER_FAILOVER"


def test_both_model_and_provider_fallback_detection():
    """Case 4: Both model and provider differ from requested."""
    record = {
        "requested_model": "stealth/ox-alpha",
        "requested_provider": "openrouter",
        "actual_model": "meta-llama/llama-3.1-70b",
        "actual_provider": "together",
        "status": "SUCCESS"
    }
    res = evaluate_t3_identity_and_fallback(record)
    assert res["model_fallback"] is True
    assert res["provider_failover"] is True
    assert res["fallback_type"] == "BOTH"


def test_independent_cost_validator():
    """Validates that independent cost validator recomputes and matches primary summary."""
    t3_records = [
        {
            "mission_id": "m1",
            "task_id": "A01",
            "requested_model": "stealth/ox-alpha",
            "requested_provider": "openrouter",
            "actual_model": "stealth/ox-alpha",
            "actual_provider": "openrouter",
            "status": "SUCCESS",
            "provider_attempts": 1,
            "input_tokens": 1000,
            "output_tokens": 300,
            "reported_cost_usd": 0.007500
        }
    ]
    missions = [{"mission_id": "m1", "category": "simple", "objective_status": "PASS"}]
    primary_summary = aggregate_t3_cost_metrics(t3_records, missions)

    val_res = validate_cost_independence(t3_records, missions, primary_summary)
    assert val_res["validation_status"] == "PASS"
    assert val_res["independence_verified"] is True


def test_independent_cost_validator_detects_tampering():
    """Validates that modifying primary summary causes validator assertion failure."""
    t3_records = [
        {
            "mission_id": "m1",
            "task_id": "A01",
            "reported_cost_usd": 0.007500,
            "input_tokens": 1000,
            "output_tokens": 300
        }
    ]
    missions = [{"mission_id": "m1", "category": "simple", "objective_status": "PASS"}]
    primary_summary = aggregate_t3_cost_metrics(t3_records, missions)

    tampered_summary = copy.deepcopy(primary_summary)
    tampered_summary["t3"]["total_cost_usd"] = 999.99

    with pytest.raises(AssertionError):
        validate_cost_independence(t3_records, missions, tampered_summary)
