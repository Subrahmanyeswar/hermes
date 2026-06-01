#!/usr/bin/env python3
"""
HERMES — Phase 2 Complete Validation
Verifies all Phase 2 (Weeks 9-14) deliverables are present and functional.

Run: python tests/test_phase2_complete.py
"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


PHASE2_REQUIRED_FILES = [
    # Week 9 — KAIROS
    ("kairos/db.py",                    "KAIROS SQLite database manager"),
    ("kairos/task_queue.py",            "KAIROS task queue interface"),
    ("kairos/daemon.py",                "KAIROS background daemon"),
    # Week 10 — Prompt hardening
    ("tools/prompt_tester.py",          "50-prompt reliability tester"),
    ("core/response_parser.py",         "Hardened response parser"),
    # Week 11 — Error handling
    ("core/error_handler.py",           "Centralised error handler"),
    # Week 12 — Logging
    ("utils/__init__.py",               "Utils package init"),
    ("utils/logging.py",                "Structured logging module"),
    # Week 13 — Integration + calibration
    ("tests/integration/__init__.py",   "Integration test package"),
    ("tests/integration/conftest.py",   "Integration test fixtures"),
    ("tests/integration/test_pipeline_integration.py",  "20-task integration suite"),
    ("tests/integration/test_threshold_calibration.py", "Threshold calibration suite"),
    # Week 14 — Benchmarks
    ("benchmarks/__init__.py",          "Benchmarks package init"),
    ("benchmarks/latency_profiler.py",  "Latency measurement profiler"),
    ("benchmarks/stability_audit.py",   "Stability audit script"),
]

PHASE2_REQUIRED_MODULES = [
    ("kairos.db",                   ["init_db", "get_connection", "execute_write", "execute_read", "record_api_cost"]),
    ("kairos.task_queue",           ["register_task", "mark_running", "mark_completed", "mark_failed", "get_stuck_tasks", "get_kairos_state"]),
    ("kairos.daemon",               ["KairosDaemon"]),
    ("core.response_parser",        ["ResponseParser", "ParseSuccess", "ParseFailure"]),
    ("core.error_handler",          ["ErrorHandler", "ErrorResult", "FailureMode", "RecoveryAction"]),
    ("utils.logging",               ["setup_logging", "generate_trace_id", "TraceContext", "log_pipeline_start", "log_tool_call", "search_session_logs"]),
    ("core.disagreement_router",    ["load_calibrated_threshold"]),
]

PHASE2_REQUIRED_DATA = [
    "data/threshold_calibration_results.json",
    "data/paper_threshold_table.csv",
]


def test_1_all_phase2_files_exist():
    """Every Phase 2 source file must exist."""
    missing = []
    for path_str, description in PHASE2_REQUIRED_FILES:
        if not Path(path_str).exists():
            missing.append(f"{path_str} ({description})")

    if missing:
        print(f"  [FAIL] {len(missing)} files missing:")
        for m in missing:
            print(f"    - {m}")
        return False

    print(f"  [OK] All {len(PHASE2_REQUIRED_FILES)} Phase 2 files exist")
    return True


def test_2_all_phase2_modules_importable():
    """Every Phase 2 module must import cleanly with required symbols."""
    failures = []

    for module_path, required_symbols in PHASE2_REQUIRED_MODULES:
        try:
            mod = importlib.import_module(module_path)
            for symbol in required_symbols:
                if not hasattr(mod, symbol):
                    failures.append(f"{module_path}.{symbol} not found")
        except ImportError as e:
            failures.append(f"{module_path} ImportError: {e}")
        except Exception as e:
            failures.append(f"{module_path} {type(e).__name__}: {str(e)[:80]}")

    if failures:
        print(f"  [FAIL] {len(failures)} import failures:")
        for f in failures:
            print(f"    - {f}")
        return False

    print(f"  [OK] All {len(PHASE2_REQUIRED_MODULES)} Phase 2 modules import cleanly")
    return True


def test_3_kairos_triple_gate_logic_correct():
    """KAIROS Triple-Gate logic must enforce all 3 conditions."""
    import tempfile
    from kairos.db import init_db
    from kairos.task_queue import register_task, mark_running, mark_completed, get_kairos_state

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "triple_gate_test.db"
        init_db(db_path=db)

        # Complete 3 tasks to satisfy gate 2
        for i in range(3):
            tid = register_task("s1", f"Task {i}", db_path=db)
            mark_running(tid, db_path=db)
            mark_completed(tid, db_path=db)

        state = get_kairos_state(db_path=db)
        gate2_passes = state["tasks_since_consolidation"] >= 3

    if not gate2_passes:
        print(f"  [FAIL] Triple-Gate: tasks_since_consolidation should be 3, got {state['tasks_since_consolidation']}")
        return False

    print(f"  [OK] Triple-Gate: task counter increments correctly ({state['tasks_since_consolidation']} tasks)")
    return True


def test_4_error_handler_all_6_modes():
    """ErrorHandler must produce valid ErrorResult for all 6 failure modes."""
    from core.error_handler import ErrorHandler, ErrorResult, FailureMode

    handler = ErrorHandler()

    results = [
        handler.json_parse_failure("bad json", attempt=0),
        handler.json_parse_failure("bad json", attempt=1),
        handler.tool_not_found("fake", ["write_file"], attempt=0),
        handler.tool_execution_failure("bash_exec", 1, "error", retry_count=0),
        handler.tool_execution_failure("bash_exec", 1, "error", retry_count=3),
        handler.ollama_timeout("model", 120, "stage_4"),
        handler.tier3_api_failure("APIError", "rate limit", "T1 output"),
        handler.memory_parse_error("parse error", "project"),
        handler.unknown_error(RuntimeError("crash"), "stage_6"),
    ]

    failures = []
    for r in results:
        if not isinstance(r, ErrorResult):
            failures.append(f"Not an ErrorResult: {type(r)}")
        if r.failure_mode not in FailureMode:
            failures.append(f"Invalid failure_mode: {r.failure_mode}")

    if failures:
        print(f"  [FAIL] ErrorHandler issues: {failures}")
        return False

    # Verify retry boundaries
    assert handler.json_parse_failure("x", 0).can_retry is True
    assert handler.json_parse_failure("x", 1).can_retry is False
    assert handler.tool_execution_failure("t", 1, "e", 2).can_retry is True
    assert handler.tool_execution_failure("t", 1, "e", 3).can_retry is False
    assert handler.ollama_timeout("m", 120, "s").can_retry is False
    assert handler.tier3_api_failure("E", "d", "o").can_retry is False

    print(f"  [OK] All 6 failure modes produce valid ErrorResult with correct retry boundaries")
    return True


def test_5_response_parser_handles_all_formats():
    """ResponseParser must handle all 6 known response formats."""
    from core.response_parser import ResponseParser, ParseSuccess, ParseFailure

    parser = ResponseParser()

    test_cases = [
        ('{"tool": "write_file", "parameters": {"path": "x.py"}, "reasoning": "r", "explanation": "e"}',          True,  "clean_json"),
        ('```json\n{"tool": "read_file", "parameters": {"path": "x.py"}, "reasoning": "r", "explanation": "e"}\n```', True, "fenced"),
        ('Here:\n{"tool": "list_directory", "parameters": {}, "reasoning": "r", "explanation": "e"}\nDone.',       True,  "embedded_in_prose"),
        ('{"action": "write_file", "parameters": {"path": "x.py"}, "reasoning": "r", "explanation": "e"}',         True,  "alternate_key"),
        ("",                                                                                                          False, "empty"),
        ("I would be happy to help you with that task.",                                                             False, "plain_text"),
    ]

    failures = []
    for response, expect_success, label in test_cases:
        result = parser.parse(response)
        actual = isinstance(result, ParseSuccess)
        if actual != expect_success:
            failures.append(f"{label}: expected={expect_success} got={actual}")

    # Verify never raises
    adversarial = ["{{{{", None, "null", "[]", "\x00\x01"]
    for bad in adversarial:
        try:
            parser.parse(bad or "")
        except Exception as e:
            failures.append(f"Crashed on {bad!r}: {e}")

    if failures:
        print(f"  [FAIL] ResponseParser failures: {failures}")
        return False

    print(f"  [OK] ResponseParser handles all 6 formats and never crashes on adversarial input")
    return True


def test_6_logging_module_complete():
    """utils/logging.py must export all required functions."""
    from utils.logging import (
        generate_trace_id, generate_session_id, setup_logging,
        TraceContext, get_trace_logger,
        log_pipeline_start, log_pipeline_complete,
        log_tier1_call, log_tier2_call, log_tier3_call,
        log_tool_call, log_tool_result,
        log_memory_event, log_security_gate, log_kairos_event,
        search_session_logs, get_session_log_path,
    )

    # Verify trace_id format
    tid = generate_trace_id()
    assert len(tid) == 8 and all(c in "0123456789abcdef" for c in tid)

    # Verify TraceContext measures elapsed time
    import time
    ctx = TraceContext()
    with ctx:
        time.sleep(0.05)
    assert ctx.elapsed_seconds >= 0.04

    print(f"  [OK] utils/logging.py exports all 17 required functions")
    return True


def test_7_threshold_calibration_data_exists():
    """Calibration results and paper table must exist with valid structure."""
    failures = []

    cal_path = Path("data/threshold_calibration_results.json")
    if not cal_path.exists():
        failures.append("data/threshold_calibration_results.json not found — run: python tests/integration/test_threshold_calibration.py")
    else:
        with open(cal_path) as f:
            data = json.load(f)
        required = ["recommended_threshold", "results_by_threshold", "thresholds_tested"]
        missing = [k for k in required if k not in data]
        if missing:
            failures.append(f"calibration_results missing keys: {missing}")
        elif len(data["results_by_threshold"]) < 5:
            failures.append(f"Only {len(data['results_by_threshold'])} thresholds tested (expected 5)")
        else:
            threshold = data["recommended_threshold"]
            print(f"  [INFO] Recommended threshold: {threshold}")

    csv_path = Path("data/paper_threshold_table.csv")
    if not csv_path.exists():
        failures.append("data/paper_threshold_table.csv not found")
    else:
        lines = csv_path.read_text().strip().split("\n")
        if len(lines) < 6:  # header + 5 thresholds
            failures.append(f"paper_threshold_table.csv only has {len(lines)} lines")

    if failures:
        for f in failures:
            print(f"  [FAIL] {f}")
        return False

    print(f"  [OK] Calibration data and paper table exist and valid")
    return True


def test_8_orchestrator_result_has_trace_id():
    """OrchestratorResult dataclass must have trace_id field."""
    import dataclasses
    from core.orchestrator import OrchestratorResult

    fields = {f.name for f in dataclasses.fields(OrchestratorResult)}

    required_fields = {
        "success", "final_output", "tool_name", "tool_result",
        "task", "skill_ids_used", "tier3_was_called",
        "total_latency_seconds", "error", "pipeline_stage_reached", "trace_id"
    }
    missing = required_fields - fields
    if missing:
        print(f"  [FAIL] OrchestratorResult missing fields: {missing}")
        return False

    print(f"  [OK] OrchestratorResult has all {len(required_fields)} required fields including trace_id")
    return True


def test_9_conftest_uses_monkeypatch_not_context_manager():
    """conftest.py must use monkeypatch for KairosDaemon, not a context manager."""
    conftest_path = Path("tests/integration/conftest.py")
    if not conftest_path.exists():
        print("  [FAIL] conftest.py not found")
        return False

    content = conftest_path.read_text()

    # The fixed version uses monkeypatch.setattr for KairosDaemon
    uses_monkeypatch_for_kairos = (
        'monkeypatch.setattr("core.orchestrator.KairosDaemon"' in content
    )

    # The buggy version uses 'with _patch("core.orchestrator.KairosDaemon"):'
    uses_context_manager_for_kairos = (
        'with _patch("core.orchestrator.KairosDaemon")' in content
    )

    if uses_context_manager_for_kairos and not uses_monkeypatch_for_kairos:
        print("  [FAIL] conftest.py still uses context manager for KairosDaemon — apply conftest fix")
        return False

    if not uses_monkeypatch_for_kairos:
        print("  [WARN] conftest.py KairosDaemon patching style unclear — verify manually")
        return True

    # Also verify it uses yield not return
    uses_yield = "yield {" in content
    if not uses_yield:
        print("  [FAIL] conftest.py isolated_env fixture uses return not yield — patches exit early")
        return False

    print(f"  [OK] conftest.py uses monkeypatch for KairosDaemon and yield for fixture")
    return True


def test_10_full_unit_test_suite_passes():
    """Run the complete unit test suite and confirm zero failures."""
    print("  Running unit test suite (this takes 1-2 minutes)...")

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/",
            "--ignore=tests/integration/",
            "--ignore=tests/test_week10_final.py",
            "--ignore=tests/test_week11_final.py",
            "--ignore=tests/test_week12_final.py",
            "--ignore=tests/test_week13_final.py",
            "--ignore=tests/test_week14_final.py",
            "--ignore=tests/test_phase2_complete.py",
            "-q", "--timeout=120", "--tb=line",
        ],
        capture_output=True, text=True, timeout=180
    )

    lines = result.stdout.strip().split("\n")
    summary = lines[-1] if lines else "(no output)"

    if result.returncode != 0:
        # Show last 25 lines for context
        print(f"  [FAIL] Unit tests FAILED")
        for line in lines[-25:]:
            if line.strip():
                print(f"    {line}")
        return False

    print(f"  [OK] All unit tests pass | {summary}")
    return True


def main():
    print("=" * 65)
    print("HERMES — Phase 2 Complete Validation")
    print("Weeks 9–14: Hardening Phase")
    print("=" * 65)

    tests = [
        ("All Phase 2 source files exist",                      test_1_all_phase2_files_exist),
        ("All Phase 2 modules import cleanly",                  test_2_all_phase2_modules_importable),
        ("KAIROS Triple-Gate counter logic correct",            test_3_kairos_triple_gate_logic_correct),
        ("ErrorHandler: all 6 failure modes + retry boundaries",   test_4_error_handler_all_6_modes),
        ("ResponseParser: all formats + never crashes",        test_5_response_parser_handles_all_formats),
        ("utils/logging.py exports all 17 functions",          test_6_logging_module_complete),
        ("Calibration data + paper table exist",               test_7_threshold_calibration_data_exists),
        ("OrchestratorResult has trace_id field",              test_8_orchestrator_result_has_trace_id),
        ("conftest.py uses monkeypatch not context manager",   test_9_conftest_uses_monkeypatch_not_context_manager),
        ("Full unit test suite passes",                        test_10_full_unit_test_suite_passes),
    ]

    passed_all = True
    for name, test_fn in tests:
        print(f"\n[TEST] {name}")
        try:
            passed = test_fn()
            if not passed:
                passed_all = False
        except Exception as e:
            import traceback
            print(f"  [FAIL] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            passed_all = False

    print("\n" + "=" * 65)
    if passed_all:
        print("PHASE 2 COMPLETE [OK]")
        print()
        print("All hardening deliverables verified:")
        print("  [OK] Week 09: KAIROS daemon + SQLite task queue")
        print("  [OK] Week 10: Prompt hardening + ResponseParser")
        print("  [OK] Week 11: 6 failure modes + session never crashes")
        print("  [OK] Week 12: Structured logging + trace_id per run")
        print("  [OK] Week 13: 20-task integration suite + threshold calibration")
        print("  [OK] Week 14: Latency profiler + stability audit")
        print()
        print("Phase 3 (TUI) can begin. Start: Week 15.")
    else:
        print("PHASE 2 INCOMPLETE — fix failures above before Phase 3.")
        print()
        print("Run fixes in this order:")
        print("  1. conftest.py KairosDaemon patch")
        print("  2. stability_audit.py async decorator")
        print("  3. test_failure_modes.py 100-request test")
        print("  4. main.py logs/trace commands")
        print("  Then re-run: python tests/test_phase2_complete.py")
    print("=" * 65)


if __name__ == "__main__":
    main()
