"""
tests/test_gate18_objective_evaluator.py
HERMES Gate 18: Objective Success Contract & Evaluator Validation Test Suite.

Validates that:
1. Success contracts exist for all 80 frozen tasks (A01-H10).
2. Success contract SHA-256 matches manifest exactly.
3. Every task has expected files, expected behavior, expected tests, acceptance criteria, constraints, and verification procedures.
4. ObjectiveEvaluator is deterministic and independent of HERMES's self-reported completion status.
5. False completion is explicitly caught when agent reports COMPLETED but verification fails.
6. False negative is explicitly caught when agent reports FAILED but verification passes.
7. Evaluator self-tests pass (correct implementation -> PASS, missing file -> FAIL, syntax error -> FAIL, test failure -> FAIL).
8. Benchmark execution remains explicitly blocked (`benchmark_execution_allowed: false`).
"""

import hashlib
import json
import tempfile
from pathlib import Path
import pytest

from benchmarks.objective_evaluator import ObjectiveEvaluator, ObjectiveEvaluationResult

WORKSPACE = Path(__file__).resolve().parent.parent
DATASET_PATH = WORKSPACE / "artifacts" / "final_benchmark_dataset.json"
CONTRACT_PATH = WORKSPACE / "artifacts" / "final_benchmark_success_contract.json"
MANIFEST_PATH = WORKSPACE / "artifacts" / "final_benchmark_success_contract_manifest.json"


def test_success_contract_files_exist():
    """Validates that contract JSON and manifest exist."""
    assert CONTRACT_PATH.exists()
    assert MANIFEST_PATH.exists()


def test_success_contract_80_tasks_coverage():
    """Validates that all 80 tasks have complete success contracts."""
    contracts = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert len(contracts) == 80

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    dataset_ids = [d["task_id"] for d in dataset]
    contract_ids = [c["task_id"] for c in contracts]

    assert contract_ids == dataset_ids


def test_success_contract_schema_completeness():
    """Validates that each contract contains all required specification sections."""
    contracts = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    required_keys = [
        "task_id", "dataset_version", "success_contract_version", "category",
        "difficulty", "workspace", "expected_files", "expected_behavior",
        "expected_tests", "acceptance_criteria", "constraints", "verification",
        "pass_conditions", "fail_conditions"
    ]
    for c in contracts:
        for k in required_keys:
            assert k in c, f"Contract {c.get('task_id')} missing required key {k}"
        assert len(c["expected_behavior"]) > 0
        assert len(c["expected_tests"]) > 0
        assert len(c["acceptance_criteria"]) > 0
        assert len(c["constraints"]) > 0


def test_success_contract_sha256_matches_manifest():
    """Validates exact byte SHA-256 hash match against manifest."""
    raw_bytes = CONTRACT_PATH.read_bytes()
    actual_hash = hashlib.sha256(raw_bytes).hexdigest()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["dataset_version"] == "1.0.0"
    assert manifest["success_contract_version"] == "1.0.0"
    assert manifest["task_count"] == 80
    assert manifest["sha256"] == actual_hash
    assert manifest["frozen"] is True
    assert manifest["benchmark_execution_allowed"] is False


def test_evaluator_self_test_pass_case():
    """Self-Test 1: Correct implementation with passing tests evaluates to PASS."""
    evaluator = ObjectiveEvaluator(CONTRACT_PATH)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Create expected files with valid Python syntax
        target_file = tmp_path / "utils" / "string_helpers.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("def truncate_text(t, m, s='...'): return t[:m] + s\n", encoding="utf-8")

        test_file = tmp_path / "tests" / "test_string_helpers.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_truncate(): pass\n", encoding="utf-8")

        # Mock test runner returning exit code 0
        def mock_runner(cmd, cwd):
            return 0, "PASSED 1 test", ""

        res = evaluator.evaluate(
            task_id="A01",
            workspace_dir=tmp_path,
            hermes_reported_status="COMPLETED",
            mock_command_runner=mock_runner
        )

        assert res.objective_status == "PASS"
        assert res.false_completion is False
        assert res.constraints_satisfied is True


def test_evaluator_self_test_missing_file_fails():
    """Self-Test 2: Missing expected file evaluates to FAIL."""
    evaluator = ObjectiveEvaluator(CONTRACT_PATH)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # File not created

        def mock_runner(cmd, cwd):
            return 0, "", ""

        res = evaluator.evaluate(
            task_id="A01",
            workspace_dir=tmp_path,
            hermes_reported_status="COMPLETED",
            mock_command_runner=mock_runner
        )

        assert res.objective_status == "FAIL"
        assert res.false_completion is True  # Agent said COMPLETED but file missing!
        assert any("missing" in r.lower() for r in res.failure_reasons)


def test_evaluator_self_test_syntax_error_fails():
    """Self-Test 3: Syntax error in created file evaluates to FAIL."""
    evaluator = ObjectiveEvaluator(CONTRACT_PATH)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target_file = tmp_path / "utils" / "string_helpers.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("def broken_syntax(:\n", encoding="utf-8")

        test_file = tmp_path / "tests" / "test_string_helpers.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_truncate(): pass\n", encoding="utf-8")

        def mock_runner(cmd, cwd):
            return 0, "", ""

        res = evaluator.evaluate(
            task_id="A01",
            workspace_dir=tmp_path,
            hermes_reported_status="COMPLETED",
            mock_command_runner=mock_runner
        )

        assert res.objective_status == "FAIL"
        assert res.false_completion is True
        assert any("syntax error" in r.lower() for r in res.failure_reasons)


def test_evaluator_self_test_command_failure_fails():
    """Self-Test 4: Verification test failure evaluates to FAIL."""
    evaluator = ObjectiveEvaluator(CONTRACT_PATH)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target_file = tmp_path / "utils" / "string_helpers.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("def truncate_text(t, m): pass\n", encoding="utf-8")

        test_file = tmp_path / "tests" / "test_string_helpers.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_truncate(): pass\n", encoding="utf-8")

        # Mock runner returning exit code 1
        def mock_runner(cmd, cwd):
            return 1, "", "AssertionError: expected '...' but got None"

        res = evaluator.evaluate(
            task_id="A01",
            workspace_dir=tmp_path,
            hermes_reported_status="COMPLETED",
            mock_command_runner=mock_runner
        )

        assert res.objective_status == "FAIL"
        assert res.false_completion is True


def test_evaluator_self_test_false_negative_detection():
    """Self-Test 5: Agent reports FAILED but objective tests pass -> FALSE_NEGATIVE."""
    evaluator = ObjectiveEvaluator(CONTRACT_PATH)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target_file = tmp_path / "utils" / "string_helpers.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("def truncate_text(t, m): return t\n", encoding="utf-8")

        test_file = tmp_path / "tests" / "test_string_helpers.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_truncate(): pass\n", encoding="utf-8")

        def mock_runner(cmd, cwd):
            return 0, "PASSED", ""

        res = evaluator.evaluate(
            task_id="A01",
            workspace_dir=tmp_path,
            hermes_reported_status="FAILED",
            mock_command_runner=mock_runner
        )

        assert res.objective_status == "PASS"
        assert res.false_negative is True
        assert res.false_completion is False


def test_evaluator_determinism():
    """Validates that running evaluator 10 times produces identical result."""
    evaluator = ObjectiveEvaluator(CONTRACT_PATH)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target_file = tmp_path / "utils" / "string_helpers.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("def truncate_text(t, m): return t\n", encoding="utf-8")

        test_file = tmp_path / "tests" / "test_string_helpers.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_truncate(): pass\n", encoding="utf-8")

        def mock_runner(cmd, cwd):
            return 0, "PASSED", ""

        results = [
            evaluator.evaluate(
                task_id="A01",
                workspace_dir=tmp_path,
                hermes_reported_status="COMPLETED",
                mock_command_runner=mock_runner
            ).objective_status
            for _ in range(10)
        ]

        assert all(r == "PASS" for r in results)
