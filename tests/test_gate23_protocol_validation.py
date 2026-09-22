"""
HERMES Gate 23 — Final Benchmark Execution Protocol Self-Validation Suite.
Validates all 20 pre-benchmark invariants and freeze guarantees before final execution.
"""
import hashlib
import json
from pathlib import Path
import pytest

DATASET_PATH = Path("artifacts/final_benchmark_dataset.json")
EXPECTED_DATASET_SHA = "f3475b6415364ccea70f4710bfe2137fe84d91cce5d1db822e8d156716cf4d72"

CONTRACT_PATH = Path("artifacts/final_benchmark_success_contract.json")
EXPECTED_CONTRACT_SHA = "4cf78a7dce0cfedfeb81e5e6929241fb7fd69d5eba0ba2b91888f6744834fff3"

PROTOCOL_DOC_PATH = Path("artifacts/FINAL_BENCHMARK_EXECUTION_PROTOCOL.md")
EXPECTED_PROTOCOL_SHA = "8740e0a6face5b1b4ce1b23839a97605cffb63045e289bda7b297fb83d8bfe15"

EXEC_MANIFEST_PATH = Path("artifacts/final_benchmark/final_benchmark_execution_manifest.json")
GATE23_MANIFEST_PATH = Path("artifacts/gate23_protocol_manifest.json")
GATE22_RESULTS_PATH = Path("artifacts/gate22_regression_results.json")


def test_1_dataset_sha256_matches_frozen_hash():
    """Invariant 1: Dataset SHA-256 matches frozen Gate 17 record."""
    assert DATASET_PATH.exists(), "Dataset artifact missing"
    sha = hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    assert sha == EXPECTED_DATASET_SHA, f"Dataset hash mismatch: {sha}"


def test_2_success_contract_sha256_matches_frozen_hash():
    """Invariant 2: Success contract SHA-256 matches frozen Gate 18 record."""
    assert CONTRACT_PATH.exists(), "Success contract artifact missing"
    sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    assert sha == EXPECTED_CONTRACT_SHA, f"Success contract hash mismatch: {sha}"


def test_3_protocol_document_sha256_matches_frozen_hash():
    """Invariant 3: Canonical protocol document SHA-256 matches frozen Gate 23 record."""
    assert PROTOCOL_DOC_PATH.exists(), "Protocol document missing"
    sha = hashlib.sha256(PROTOCOL_DOC_PATH.read_bytes()).hexdigest()
    assert sha == EXPECTED_PROTOCOL_SHA, f"Protocol hash mismatch: {sha}"


def test_4_dataset_contains_exactly_80_tasks():
    """Invariant 4: Dataset contains exactly 80 tasks across 8 categories."""
    tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert len(tasks) == 80, f"Expected 80 tasks, got {len(tasks)}"


def test_5_task_ids_are_unique_and_canonical():
    """Invariant 5: All 80 task IDs are unique, valid, and follow A01-H10 format."""
    tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    ids = [t["task_id"] for t in tasks]
    assert len(ids) == 80
    assert len(set(ids)) == 80
    for prefix in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        for num in range(1, 11):
            expected_id = f"{prefix}{num:02d}"
            assert expected_id in ids, f"Missing task ID {expected_id}"


def test_6_task_execution_order_is_deterministic():
    """Invariant 6: Task execution order in execution manifest matches canonical dataset order."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    canonical_ids = [t["task_id"] for t in tasks]
    assert manifest["task_order"] == canonical_ids
    assert manifest["randomization_enabled"] is False


def test_7_workspace_reset_is_configured():
    """Invariant 7: Workspace isolation and per-task clean reset is enforced."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["workspace_reset"] is True
    assert manifest["memory_policy"] == "task_isolated"
    assert manifest["cache_policy"] == "model_warm_app_reset"


def test_8_objective_evaluator_is_authoritative():
    """Invariant 8: Objective Evaluator is authoritative and HERMES completion is not."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["objective_evaluator_authoritative"] is True


def test_9_llm_as_primary_judge_is_disabled():
    """Invariant 9: LLM as primary judge is explicitly disabled."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["llm_as_primary_judge"] is False


def test_10_raw_telemetry_is_authoritative():
    """Invariant 10: Raw telemetry recording is enabled and authoritative."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["raw_telemetry_authoritative"] is True


def test_11_retry_policy_is_frozen():
    """Invariant 11: Production retry policy is frozen with separated attempt tracking."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "max_3_attempts" in manifest["retry_policy"]
    assert manifest["repair_policy"] == "progressive_verification_repair"


def test_12_timeout_policy_is_frozen():
    """Invariant 12: Hierarchical timeout policy (Gate 14) is frozen."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["timeout_policy"] == "gate14_hierarchical_deadline"


def test_13_cancellation_policy_is_frozen():
    """Invariant 13: Zero-zombie cancellation policy (Gate 13) is frozen."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["cancellation_policy"] == "gate13_zero_zombie_semantics"


def test_14_model_hierarchy_is_strictly_locked():
    """Invariant 14: Model hierarchy is locked to deepseek-r1:8b (T1), qwen3:8b (T2), stealth/ox-alpha (T3)."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    hierarchy = manifest["model_hierarchy"]
    assert hierarchy["tier1"] == "deepseek-r1:8b"
    assert hierarchy["tier2"] == "qwen3:8b"
    assert hierarchy["tier3"] == "stealth/ox-alpha"


def test_15_t3_cost_and_identity_attribution_is_configured():
    """Invariant 15: Gate 20 T3 cost accounting and actual provider attribution is configured."""
    manifest = json.loads(GATE23_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert any(g["gate"] == "20" and g["status"] == "LOCKED" for g in manifest["locked_gates"])


def test_16_thermal_sustained_load_protocol_is_configured():
    """Invariant 16: Gate 21 thermal and sustained-load protocol is locked."""
    manifest = json.loads(GATE23_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert any(g["gate"] == "21" and g["status"] == "LOCKED" for g in manifest["locked_gates"])


def test_17_full_regression_suite_health_is_verified():
    """Invariant 17: Gate 22 regression results verify 945 collected, 945 passed, 0 failures."""
    assert GATE22_RESULTS_PATH.exists(), "Gate 22 results missing"
    results = json.loads(GATE22_RESULTS_PATH.read_text(encoding="utf-8"))
    tests = results["tests"]
    assert tests["collected"] == 945
    assert tests["passed"] == 945
    assert tests["failed"] == 0
    assert tests["errors"] == 0
    assert results["status"] == "PASS"


def test_18_final_benchmark_is_not_executed():
    """Invariant 18: Final benchmark has NOT been executed yet."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["final_benchmark_executed"] is False


def test_19_benchmark_execution_allowed_flag_is_false():
    """Invariant 19: Benchmark execution allowed flag is explicitly false."""
    manifest = json.loads(EXEC_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["benchmark_execution_allowed"] is False
    assert manifest["frozen"] is True


def test_20_gate23_protocol_manifest_is_complete():
    """Invariant 20: Gate 23 protocol manifest is frozen and passes all lock checks."""
    manifest = json.loads(GATE23_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["gate"] == "23"
    assert manifest["status"] == "PASS"
    assert manifest["protocol_frozen"] is True
    assert manifest["task_count"] == 80
    assert manifest["protocol_sha256"] == EXPECTED_PROTOCOL_SHA
    assert manifest["dataset_sha256"] == EXPECTED_DATASET_SHA
    assert manifest["success_contract_sha256"] == EXPECTED_CONTRACT_SHA
    assert len(manifest["locked_gates"]) == 7
