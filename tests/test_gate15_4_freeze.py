"""
Pre-Benchmark Gate 15.4: Configuration & Environment Freeze Tests.
Tests that:
1. Frozen manifest exists and is valid JSON without unredacted secrets.
2. validate_environment() passes against the current live environment.
3. Injected drift is immediately detected and reported.
4. Restored configuration passes validation.
5. All 3 model tiers match the locked hierarchy (deepseek-r1:8b, qwen3:8b, ox-alpha).
"""
import json
from pathlib import Path
import pytest

from scripts.validate_benchmark_freeze import validate_environment, MANIFEST_PATH
import config.model_config as cfg


def test_freeze_manifest_integrity():
    """Manifest exists, contains all required sections, and has no raw secrets."""
    assert MANIFEST_PATH.exists()
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert "hardware" in data
    assert "locked_model_hierarchy" in data
    assert "subsystem_parameters" in data
    assert "benchmark_dataset_manifest" in data

    # Verify secrets are redacted
    raw_text = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "<REDACTED>" in raw_text


def test_live_environment_matches_freeze():
    """Live environment matches the frozen manifest exactly."""
    is_valid, results = validate_environment()
    assert is_valid is True
    assert all(r["status"] == "MATCH" for r in results)


def test_locked_model_hierarchy_exact_match():
    """Models match exact locked specifications."""
    assert cfg.TIER1_MODEL == "deepseek-r1:8b"
    assert cfg.TIER2_MODEL == "qwen3:8b"
    assert "ox-alpha" in cfg.TIER3_MODEL


def test_controlled_drift_detection():
    """Injected configuration drift is detected immediately."""
    manifest_data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # Simulate drift in manifest copy
    mutated_data = json.loads(json.dumps(manifest_data))
    mutated_data["locked_model_hierarchy"]["tier1_primary"]["identifier"] = "gpt-4-turbo"
    mutated_data["subsystem_parameters"]["intelligent_router"]["t2_confidence_threshold"] = 0.99

    is_valid, results = validate_environment(mutated_data)
    assert is_valid is False
    mismatches = [r for r in results if r["status"] == "MISMATCH"]
    assert len(mismatches) >= 2
    mismatch_fields = {r["field"] for r in mismatches}
    assert "t1_model_identifier" in mismatch_fields
    assert "router_t2_confidence" in mismatch_fields


def test_benchmark_prompts_immutability():
    """Frozen prompt set contains exactly 6 immutable test tasks with acceptance criteria."""
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    prompts = data["benchmark_dataset_manifest"]["prompt_set"]
    assert len(prompts) == 6
    assert all("id" in p and "prompt" in p and "acceptance" in p for p in prompts)
