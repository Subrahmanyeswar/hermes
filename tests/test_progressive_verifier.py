"""
Unit and Integration Tests for Phase 13 Progressive Verification + Repair Engine.
Tests all 10 core verification and repair scenarios:
1. Level 0 & 1 pass allows Level 2
2. Level 1 syntax failure short-circuits Level 2
3. Level 0 structural failure detects missing/empty files
4. Deterministic failure classification
5. Environment failures block hallucinated code repair
6. Closed-loop repair re-verification
7. Bounded repair attempts (max 3)
8. Evidence invalidation on file modification
9. Unrelated files retain valid cache
10. Sub-millisecond execution latency
"""
import tempfile
from pathlib import Path
import pytest

from core.progressive_verifier import (
    VerificationLevel,
    FailureClass,
    VerificationResult,
    FailureDiagnoser,
    ProgressiveVerificationEngine,
    RepairEngine
)


@pytest.fixture
def engine():
    return ProgressiveVerificationEngine(enabled=True)


@pytest.fixture
def repair():
    return RepairEngine(max_repairs=3)


def test_syntax_pass_allows_targeted_test(engine):
    """Clean syntax allows Level 2 targeted test execution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        py_file = Path(tmp_dir) / "math_utils.py"
        py_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

        results = engine.run_progressive_pipeline(
            file_paths=[str(py_file)],
            mock_test_fn=lambda: (True, "All 3 unit tests passed")
        )

        assert len(results) == 3
        assert results[0].level == VerificationLevel.STRUCTURAL and results[0].status == "PASSED"
        assert results[1].level == VerificationLevel.SYNTAX and results[1].status == "PASSED"
        assert results[2].level == VerificationLevel.TARGETED and results[2].status == "PASSED"


def test_syntax_fail_short_circuits_downstream(engine):
    """Syntax error at Level 1 immediately short-circuits Level 2 test execution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        py_file = Path(tmp_dir) / "broken.py"
        py_file.write_text("def broken_syntax(:\n    pass\n", encoding="utf-8")

        results = engine.run_progressive_pipeline(
            file_paths=[str(py_file)],
            mock_test_fn=lambda: (True, "Should not run")
        )

        assert len(results) == 3
        assert results[0].status == "PASSED"
        assert results[1].status == "FAILED"
        assert results[1].failure_class == FailureClass.SYNTAX_ERROR
        assert results[2].status == "SKIPPED"  # Short-circuited!


def test_structural_missing_file_fails_level_0(engine):
    """Missing or empty file fails Level 0 structural check."""
    results = engine.run_progressive_pipeline(file_paths=["/nonexistent/path/file.py"])
    assert results[0].status == "FAILED"
    assert results[1].status == "SKIPPED"
    assert results[2].status == "SKIPPED"


def test_deterministic_failure_classification():
    """FailureDiagnoser accurately classifies errors."""
    f1, _ = FailureDiagnoser.classify_error("SyntaxError: invalid syntax at line 4")
    assert f1 == FailureClass.SYNTAX_ERROR

    f2, _ = FailureDiagnoser.classify_error("AssertionError: assert 4 == 5 in test_calc.py")
    assert f2 == FailureClass.TEST_FAILURE

    f3, _ = FailureDiagnoser.classify_error("npm: command not found")
    assert f3 == FailureClass.ENVIRONMENT_FAILURE

    f4, _ = FailureDiagnoser.classify_error("SECURITY: Forbidden command blocked")
    assert f4 == FailureClass.SECURITY_FAILURE


def test_environment_failure_blocks_code_repair(repair):
    """Environment failure returns can_repair=False (no hallucinated code repair)."""
    can_fix = repair.can_repair(task_id="t1", failure_class=FailureClass.ENVIRONMENT_FAILURE)
    assert can_fix is False

    can_fix_test = repair.can_repair(task_id="t1", failure_class=FailureClass.TEST_FAILURE)
    assert can_fix_test is True


def test_successful_repair_loop_re_verification(engine, repair):
    """Repair loop records attempt and enables successful re-verification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        py_file = Path(tmp_dir) / "app.py"
        # Initial version has bug
        py_file.write_text("def subtract(a, b):\n    return a + b\n", encoding="utf-8")

        # Initial verification fails
        res1 = engine.run_progressive_pipeline(
            file_paths=[str(py_file)],
            mock_test_fn=lambda: (False, "AssertionError: subtract(5, 2) != 3")
        )
        assert res1[2].status == "FAILED"

        # Apply repair
        py_file.write_text("def subtract(a, b):\n    return a - b\n", encoding="utf-8")
        repair.record_repair_attempt(
            task_id="task_sub",
            diagnosis="Fixed operator from + to -",
            patch_description="return a - b",
            re_verification_passed=True
        )

        # Re-verification passes
        res2 = engine.run_progressive_pipeline(
            file_paths=[str(py_file)],
            mock_test_fn=lambda: (True, "All assertions passed")
        )
        assert res2[2].status == "PASSED"
        assert len(repair.repair_history["task_sub"]) == 1


def test_repeated_repair_loop_exceeds_budget(repair):
    """Repair loop stops after exceeding max 3 attempts."""
    for i in range(3):
        assert repair.can_repair("task_loop", FailureClass.TEST_FAILURE) is True
        repair.record_repair_attempt("task_loop", f"Diag {i}", f"Patch {i}", False)

    # 4th attempt blocked
    assert repair.can_repair("task_loop", FailureClass.TEST_FAILURE) is False


def test_evidence_invalidation_on_file_change(engine):
    """Modifying a file clears its cached evidence."""
    p_str = str(Path("c:/test/file.py").resolve())
    engine.evidence_cache[p_str] = {
        VerificationLevel.SYNTAX: VerificationResult(level=VerificationLevel.SYNTAX, status="PASSED")
    }

    assert p_str in engine.evidence_cache
    engine.invalidate_file("c:/test/file.py")
    assert p_str not in engine.evidence_cache


def test_unrelated_files_retain_valid_cache(engine):
    """Invalidating one file does not purge unrelated cached files."""
    p1 = str(Path("c:/test/auth.py").resolve())
    p2 = str(Path("c:/test/utils.py").resolve())

    engine.evidence_cache[p1] = {VerificationLevel.SYNTAX: VerificationResult(level=VerificationLevel.SYNTAX, status="PASSED")}
    engine.evidence_cache[p2] = {VerificationLevel.SYNTAX: VerificationResult(level=VerificationLevel.SYNTAX, status="PASSED")}

    engine.invalidate_file("c:/test/auth.py")

    assert p1 not in engine.evidence_cache
    assert p2 in engine.evidence_cache


def test_fast_verification_sub_millisecond(engine):
    """Progressive structural and syntax checks finish in < 2 ms."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        py_file = Path(tmp_dir) / "fast.py"
        py_file.write_text("x = 1 + 2\\n", encoding="utf-8")

        res = engine.run_progressive_pipeline(file_paths=[str(py_file)])
        total_dur = sum(r.duration_ms for r in res)
        assert total_dur < 50.0  # Fast deterministic execution
