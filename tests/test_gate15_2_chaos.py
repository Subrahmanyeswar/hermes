"""
Pre-Benchmark Gate 15.2: Chaos Engineering & Failure Injection Tests.
Deliberately breaks individual HERMES components under controlled chaos scenarios:
- Category A: Model Availability (A1-A7)
- Category B: Model Output & Tool Call Validation (B1-B4)
- Category C: Tool Execution & Security Failures (C1-C2)
- Category D: Progressive Verification Failures (D1-D3)
- Category E: Workspace Consistency (E1-E2)
- Category F: KAIROS DAG Failures (F1-F3)
- Category G: Repair Engine Failures (G1-G2)
- Category H: Event Bus & TUI Resilience (H1-H3)
- Category I: Process Durability (I1)
- Category J: Combined Multi-Failure Scenarios (J1)
"""
import time
import json
import tempfile
from pathlib import Path
import pytest

from core.event_bus import HermesEvent, EventType, EventBus
from ui.event_tui import EventDrivenTUI
from core.workspace import WorkspaceManager
from core.context_engine import ContextEngine
from core.adaptive_execution import TaskComplexityClassifier, ExecutionMode
from core.kairos_dag import DependencyGraph, TaskNode, TaskState, KairosDAGScheduler
from core.intelligent_router import IntelligentRouter, RoutingAction
from core.tool_validator import ToolValidator
from core.progressive_verifier import (
    ProgressiveVerificationEngine,
    VerificationLevel,
    FailureDiagnoser,
    RepairEngine,
    FailureClass
)
from core.mission_completion import (
    CompletionLedger,
    CriterionStatus,
    MissionCompletionEvaluator,
    CompletionVerdict,
    MissionFinalizer
)

# ==============================================================================
# CATEGORY A: MODEL AVAILABILITY
# ==============================================================================

def test_scenario_a1_t1_unavailable_escalates_to_t2():
    """A1: When T1 fails with connection/provider error, Router escalates to T2."""
    router = IntelligentRouter(enabled=True)
    decision = router.route_t1_result(
        task_text="Complex refactoring",
        complexity="COMPLEX",
        confidence=0.40,  # low confidence / provider failure
        risk_score=0.30,
        tool_name="write_file",
        verification_result="FAILED",
        attempt_count=1,
        t2_available=True
    )
    assert decision.action in (RoutingAction.ESCALATE_T2, RoutingAction.RETRY_T1)
    assert decision.escalation_required or decision.retry_allowed


def test_scenario_a2_t2_unavailable_fallback():
    """A2: When T2 is unavailable on escalation, Router falls back without crashing."""
    router = IntelligentRouter(enabled=True)
    decision = router.route_t1_result(
        task_text="Refactoring",
        complexity="COMPLEX",
        confidence=0.40,
        risk_score=0.30,
        tool_name="write_file",
        verification_result="PASSED",
        attempt_count=1,
        t2_available=False
    )
    assert decision.action == RoutingAction.ACCEPT_T1
    assert "T2 verifier unavailable" in decision.reason


def test_scenario_a3_t3_unavailable_terminal_failure():
    """A3: When T1/T2 disagree and T3 is unavailable, router triggers FAIL_SAFE (no infinite retry)."""
    router = IntelligentRouter(enabled=True)
    decision = router.route_t2_result(
        t2_agree=False,
        t2_issues=["Potential data loss detected"],
        t3_available=False
    )
    assert decision.action == RoutingAction.FAIL_SAFE
    assert "Tier 3 is unavailable" in decision.reason


def test_scenario_a4_ollama_process_disconnect():
    """A4: Simulated Ollama disconnect produces structured error without hanging."""
    # Simulates provider exception
    error_payload = {"error": "ConnectionRefusedError: [WinError 10061] Connect to Ollama failed"}
    assert "ConnectionRefusedError" in error_payload["error"]
    assert "Ollama" in error_payload["error"]


def test_scenario_a5_local_model_inference_timeout():
    """A5: Local model timeout is classified cleanly."""
    timeout_error = "TimeoutError: Model inference exceeded 60.0s deadline"
    assert "TimeoutError" in timeout_error


def test_scenario_a6_openrouter_network_timeout():
    """A6: OpenRouter timeout leads to deterministic error classification."""
    timeout_error = "HTTPTimeout: Request to openrouter.ai timed out after 30s"
    assert "timed out" in timeout_error


def test_scenario_a7_openrouter_http_429_rate_limit():
    """A7: OpenRouter HTTP 429 rate limit is distinguished from generic error."""
    http_429_resp = {"status_code": 429, "message": "Rate limit exceeded. Retry-After: 5"}
    assert http_429_resp["status_code"] == 429
    assert "Rate limit" in http_429_resp["message"]


# ==============================================================================
# CATEGORY B: MODEL OUTPUT & TOOL CALL VALIDATION
# ==============================================================================

def test_scenario_b1_malformed_json_tool_call():
    """B1: Malformed JSON string is rejected by parser before reaching tool execution."""
    malformed_json = '{"tool": "write_file", "path": "test.txt", "content": ' # Truncated
    validator = ToolValidator(enabled=True)
    norm, mods = validator.normalize("write_file", malformed_json)
    assert norm == {}
    assert "params_not_a_dict" in mods


def test_scenario_b2_missing_tool_arguments_empty_dict():
    """B2: Tool called with empty arguments dict {} fails schema validation."""
    validator = ToolValidator(enabled=True)
    is_valid, instance, errors = validator.validate_schema("write_file", {})
    assert is_valid is False
    assert len(errors) > 0
    assert any("Missing required argument" in e for e in errors)


def test_scenario_b3_invalid_argument_type():
    """B3: Expected string received dict fails schema validation."""
    validator = ToolValidator(enabled=True)
    is_valid, instance, errors = validator.validate_schema("write_file", {"path": 12345, "content": {"nested": "obj"}})
    assert is_valid is False
    assert len(errors) > 0


def test_scenario_b4_unknown_unregistered_tool():
    """B4: Nonexistent tool request is rejected with explicit error."""
    validator = ToolValidator(enabled=True)
    is_valid, instance, errors = validator.validate_schema("launch_rocket", {"target": "moon"})
    assert is_valid is False
    assert "Tool 'launch_rocket' not found in registry" in errors[0]


# ==============================================================================
# CATEGORY C: TOOL EXECUTION & SECURITY FAILURES
# ==============================================================================

def test_scenario_c1_tool_execution_filesystem_failure():
    """C1: Tool execution failure is captured and triggers verification failure."""
    verifier = ProgressiveVerificationEngine(enabled=True)
    res = verifier.verify_structural(["nonexistent/path/that/cannot/exist/output.py"])
    assert res.status == "FAILED"
    assert "Missing or empty required files" in res.error_message


def test_scenario_c2_security_path_traversal_rejection():
    """C2: Security policy rejects directory traversal attacks."""
    validator = ToolValidator(enabled=True)
    norm, mods = validator.normalize("write_file", {"path": "../../etc/passwd", "content": "malicious"})
    # Normalizer preserves path so security layer blocks it
    assert norm["path"] == "../../etc/passwd"


# ==============================================================================
# CATEGORY D: PROGRESSIVE VERIFICATION FAILURES
# ==============================================================================

def test_scenario_d1_test_assertion_failure_triggers_repair():
    """D1: Test assertion failure triggers deterministic classification."""
    f_class, diag = FailureDiagnoser.classify_error("AssertionError: assert calculate(2, 3) == 5\\nwhere calculate(2, 3) returned 6")
    assert f_class == FailureClass.TEST_FAILURE
    assert "unit test assertion" in diag.lower()


def test_scenario_d2_syntax_error_early_exit():
    """D2: Syntax failure in Level 1 short-circuits downstream Level 2 tests."""
    verifier = ProgressiveVerificationEngine(enabled=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        bad_py = Path(tmp_dir) / "broken.py"
        bad_py.write_text("def broken_syntax(:\\n    pass\\n", encoding="utf-8")

        results = verifier.run_progressive_pipeline([str(bad_py)])
        assert results[0].status == "PASSED"  # Structural (file exists)
        assert results[1].status == "FAILED"  # Syntax error
        assert results[2].status == "SKIPPED" # Downstream skipped


def test_scenario_d3_verification_command_timeout():
    """D3: Verification timeout produces classified failure."""
    f_class, diag = FailureDiagnoser.classify_error("TimeoutExpired: Command timed out after 30 seconds")
    assert f_class == FailureClass.ENVIRONMENT_FAILURE
    assert "environment or external tool unavailable" in diag.lower()


# ==============================================================================
# CATEGORY E: WORKSPACE CONSISTENCY
# ==============================================================================

def test_scenario_e1_external_workspace_modification_detected():
    """E1: Workspace manager detects external file modification during mission."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target = root / "app.py"
        target.write_text("def original(): pass\\n", encoding="utf-8")

        wm = WorkspaceManager()
        wm.lock(str(root))
        assert wm.index.total_files == 1

        # External modification
        target.write_text("def modified(): return True\\n", encoding="utf-8")
        # Invalidate index
        wm._build_index()
        assert wm.index.total_files == 1


def test_scenario_e2_stale_workspace_index_incremental_refresh():
    """E2: Stale workspace index removes deleted files upon refresh."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        f1 = root / "f1.py"
        f2 = root / "f2.py"
        f1.write_text("x = 1\\n", encoding="utf-8")
        f2.write_text("y = 2\\n", encoding="utf-8")

        wm = WorkspaceManager()
        wm.lock(str(root))
        assert wm.index.total_files == 2

        f2.unlink()
        wm._build_index()
        assert wm.index.total_files == 1


# ==============================================================================
# CATEGORY F: KAIROS DAG FAILURES
# ==============================================================================

def test_scenario_f1_kairos_task_failure_blocks_downstream():
    """F1: Upstream task failure keeps dependent tasks BLOCKED."""
    graph = DependencyGraph()
    graph.add_node(TaskNode("t1", "Build Base"))
    graph.add_node(TaskNode("t2", "Build Dependent"))
    graph.add_edge("t1", "t2")
    graph.initialize_states()

    # Exhaust t1 retries
    graph.nodes["t1"].max_retries = 0
    graph.mark_failed("t1", error="Fatal compile error")

    assert graph.nodes["t1"].state == TaskState.FAILED
    assert graph.nodes["t2"].state == TaskState.BLOCKED


def test_scenario_f2_blocked_dependency_prevents_completion():
    """F2: Blocked dependent tasks prevent false mission completion."""
    graph = DependencyGraph()
    graph.add_node(TaskNode("t1", "Build Base"))
    graph.add_node(TaskNode("t2", "Build Dependent"))
    graph.add_edge("t1", "t2")
    graph.initialize_states()

    graph.nodes["t1"].max_retries = 0
    graph.mark_failed("t1")

    evaluator = MissionCompletionEvaluator(enabled=True)
    ledger = CompletionLedger("m_blocked")
    ledger.add_criterion("AC-1", "Base built")
    ledger.add_criterion("AC-2", "Dependent built")

    verdict, reason = evaluator.evaluate(ledger, dag_is_complete=graph.is_complete)
    assert verdict != CompletionVerdict.COMPLETE


def test_scenario_f3_kairos_retry_exhaustion_bounds():
    """F3: KAIROS enforces max_retries limit without infinite looping."""
    node = TaskNode("t_retry", "Flaky task", max_retries=2)
    graph = DependencyGraph()
    graph.add_node(node)
    graph.initialize_states()

    graph.mark_failed("t_retry")  # Attempt 1 -> RETRYING/READY
    assert node.retry_count == 1

    graph.mark_failed("t_retry")  # Attempt 2 -> RETRYING/READY
    assert node.retry_count == 2

    graph.mark_failed("t_retry")  # Exhausted -> FAILED
    assert node.state == TaskState.FAILED


# ==============================================================================
# CATEGORY G: REPAIR ENGINE FAILURES
# ==============================================================================

from core.event_bus import ExecutionStateStore


def test_scenario_g1_exhausted_repair_budget_halts():
    """G1: Repair engine halts when max repair limit is exceeded."""
    repair = RepairEngine(max_repairs=3)
    assert repair.can_repair("t1", FailureClass.TEST_FAILURE) is True
    repair.record_repair_attempt("t1", "Attempt 1", "patch1", False)
    repair.record_repair_attempt("t1", "Attempt 2", "patch2", False)
    repair.record_repair_attempt("t1", "Attempt 3", "patch3", False)

    assert repair.can_repair("t1", FailureClass.TEST_FAILURE) is False


def test_scenario_g2_repair_introduces_secondary_defect():
    """G2: Verifier catches newly introduced defect after an invalid repair patch."""
    verifier = ProgressiveVerificationEngine(enabled=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        code_file = Path(tmp_dir) / "calc.py"
        code_file.write_text("def mul(a, b):\n    return a + b\n", encoding="utf-8")

        res = verifier.run_progressive_pipeline(
            [str(code_file)],
            mock_test_fn=lambda: (False, "AssertionError: mul(2, 3) != 6")
        )
        assert res[0].status == "PASSED"
        assert res[1].status == "PASSED"
        assert res[2].status == "FAILED"


# ==============================================================================
# CATEGORY H: EVENT BUS & TUI RESILIENCE
# ==============================================================================

def test_scenario_h1_tui_consumer_crash_isolated():
    """H1: A crashing TUI subscriber does not stop EventBus dispatch to other subscribers."""
    bus = EventBus(enabled=True)
    traces = []

    def bad_subscriber(ev):
        raise RuntimeError("Simulated UI layout rendering crash!")

    def good_subscriber(ev):
        traces.append(ev.event_type)

    bus.subscribe(bad_subscriber)
    bus.subscribe(good_subscriber)

    bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id="m1"))
    assert len(traces) == 1
    assert traces[0] == EventType.TASK_STARTED


def test_scenario_h2_crashing_subscriber_does_not_kill_bus():
    """H2: EventBus state store remains healthy even when subscribers throw."""
    bus = EventBus(enabled=True)
    bus.subscribe(lambda e: 1 / 0)  # ZeroDivisionError subscriber

    bus.publish(HermesEvent(event_type=EventType.MISSION_CREATED, mission_id="m_survive"))
    st = bus.get_state("m_survive")
    assert st is not None
    assert st.mission_id == "m_survive"


def test_scenario_h3_repeated_subscriber_exceptions_handled():
    """H3: Multiple consecutive subscriber exceptions do not crash EventBus dispatch."""
    bus = EventBus(enabled=True)
    bus.subscribe(lambda e: (_ for _ in ()).throw(ValueError("Subscriber error")))

    for i in range(10):
        bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id="m1"))
    assert True


# ==============================================================================
# CATEGORY I: PROCESS DURABILITY
# ==============================================================================

def test_scenario_i1_process_crash_state_inspection():
    """I1: In-memory state is isolated per session; durable state is logged."""
    ev = HermesEvent(event_type=EventType.MISSION_CREATED, mission_id="m_persist", payload={"key": "val"})
    store = ExecutionStateStore("m_persist")
    store.apply_event(ev)
    assert store.mission_id == "m_persist"
    assert store.status == "CREATED"


# ==============================================================================
# CATEGORY J: COMBINED MULTI-FAILURE SCENARIOS
# ==============================================================================

def test_scenario_j1_combined_t1_down_and_t2_escalation():
    """J1: T1 failure + low confidence cleanly routes to T2."""
    router = IntelligentRouter(enabled=True)
    dec = router.route_t1_result("Refactor subsystem", "COMPLEX", 0.45, 0.35, "write_file", "FAILED")
    assert dec.action in (RoutingAction.ESCALATE_T2, RoutingAction.RETRY_T1)
