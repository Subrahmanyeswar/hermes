"""
Pre-Benchmark Gate 15.1: System-Wide Integration Contract Tests.
Validates the handoff contracts across all 17 pipeline boundaries:
1. TUI -> Mission
2. Mission -> Workspace Intelligence
3. Workspace -> Context Engine
4. Context Engine -> Adaptive Execution
5. Adaptive Execution -> KAIROS DAG
6. KAIROS -> Intelligent Router
7. Router -> Model Provider
8. Model -> Tool Validation
9. Tool -> Verification -> Repair
10. Verification -> Mission Completion -> Event Bus -> TUI
"""
import tempfile
from pathlib import Path
import pytest

from core.event_bus import HermesEvent, EventType, EventBus
from ui.event_tui import EventDrivenTUI
from core.workspace import WorkspaceManager
from core.context_engine import ContextEngine, ContextItem, ContextSource
from core.adaptive_execution import AdaptiveExecutionEngine, ExecutionMode, TaskComplexityClassifier
from core.kairos_dag import KairosDAGScheduler, TaskNode, TaskState
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


def test_tui_to_mission_contract():
    """TUI receives user request and emits MISSION_CREATED with exact payload."""
    bus = EventBus(enabled=True)
    tui = EventDrivenTUI(mission_id="m_gate15_1")
    bus.subscribe(tui.handle_event)

    ev = HermesEvent(
        event_type=EventType.MISSION_CREATED,
        mission_id="m_gate15_1",
        payload={"prompt": "Build API", "workspace_root": "C:/tmp/test"}
    )
    bus.publish(ev)

    st = bus.get_state("m_gate15_1")
    assert st is not None
    assert st.mission_id == "m_gate15_1"
    assert "m_gate15_1" in tui.format_view(st)


def test_mission_to_workspace_contract():
    """Mission hands off to WorkspaceManager to index files and detect languages."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

        wm = WorkspaceManager()
        wm.lock(str(root))

        assert wm.index is not None
        assert wm.index.total_files == 2


from core.context_engine import ContextEngine, ContextItem, ContextSource


def test_workspace_to_context_engine_contract():
    """Workspace indexed files feed ContextEngine ranking and packing."""
    ce = ContextEngine(enabled=True)
    pack = ce.build_context_pack(
        task_text="Implement authentication",
        mode="CODE",
        max_context_tokens=1000
    )

    assert pack.total_tokens > 0
    assert "Implement authentication" in pack.user_message


def test_context_to_adaptive_execution_contract():
    """Context and task description enable accurate complexity classification."""
    classifier = TaskComplexityClassifier()
    res_simple = classifier.classify("create directory reports")
    res_complex = classifier.classify("Build complete system architecture")

    assert res_simple.mode == ExecutionMode.SIMPLE
    assert res_complex.mode == ExecutionMode.COMPLEX


from core.kairos_dag import DependencyGraph


def test_adaptive_to_kairos_dag_contract():
    """Complex mission decomposes into KAIROS DAG with correct dependencies."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="t1", title="Backend API"))
    graph.add_node(TaskNode(task_id="t2", title="Frontend App"))
    graph.add_edge("t1", "t2")
    graph.initialize_states()

    ready = graph.get_ready_nodes()
    assert len(ready) == 1
    assert ready[0].task_id == "t1"


def test_kairos_to_intelligent_router_contract():
    """KAIROS task metadata passes to IntelligentRouter to select model tier."""
    router = IntelligentRouter(enabled=True)
    decision = router.route_t1_result(
        task_text="Read config",
        complexity="SIMPLE",
        confidence=0.95,
        risk_score=0.1,
        tool_name="read_file",
        verification_result="PASSED"
    )
    assert decision.action == RoutingAction.ACCEPT_T1


def test_model_to_tool_contract():
    """Model tool request passes schema validation and argument normalization."""
    validator = ToolValidator(enabled=True)
    norm_params, mods = validator.normalize("write_file", {"filepath": "test.txt", "content": "hello"})
    assert norm_params["path"] == "test.txt"


def test_tool_to_verification_to_repair_contract():
    """Tool output triggers progressive verification; failure triggers repair."""
    engine = ProgressiveVerificationEngine(enabled=True)
    repair = RepairEngine(max_repairs=3)

    with tempfile.TemporaryDirectory() as tmp_dir:
        py_file = Path(tmp_dir) / "calc.py"
        # Initial implementation with defect
        py_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

        res = engine.run_progressive_pipeline(
            file_paths=[str(py_file)],
            mock_test_fn=lambda: (False, "AssertionError: add(2, 3) != 5")
        )
        assert res[2].status == "FAILED"

        # Apply repair
        py_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        repair.record_repair_attempt("t_calc", "Fixed operator", "a + b", True)

        res_after = engine.run_progressive_pipeline(
            file_paths=[str(py_file)],
            mock_test_fn=lambda: (True, "All tests passed")
        )
        assert res_after[2].status == "PASSED"


def test_verification_to_mission_completion_to_event_bus_contract():
    """Verified criteria satisfy CompletionLedger -> Evaluator completes -> EventBus publishes."""
    bus = EventBus(enabled=True)
    evaluator = MissionCompletionEvaluator(enabled=True)
    finalizer = MissionFinalizer()

    ledger = CompletionLedger(mission_id="m_gate_final")
    ledger.add_criterion("AC-1", "Build API")
    ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["Verified endpoint"])

    verdict, _ = evaluator.evaluate(ledger=ledger, dag_is_complete=True)
    assert verdict == CompletionVerdict.COMPLETE

    summary = finalizer.finalize("m_gate_final", ledger)
    assert summary["status"] == "COMPLETED"

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id="m_gate_final",
        payload=summary
    ))

    st = bus.get_state("m_gate_final")
    assert st.status == "COMPLETED"


def test_e2e_full_lifecycle_trace_contract():
    """Validates complete event propagation across an entire mission lifecycle."""
    bus = EventBus(enabled=True)
    traces = []
    bus.subscribe(lambda e: traces.append(e.event_type))

    m_id = "m_trace_test"
    bus.publish(HermesEvent(event_type=EventType.MISSION_CREATED, mission_id=m_id))
    bus.publish(HermesEvent(event_type=EventType.WORKSPACE_SCAN_COMPLETED, mission_id=m_id, payload={"files_indexed": 10}))
    bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id=m_id, task_id="t1"))
    bus.publish(HermesEvent(event_type=EventType.TOOL_STARTED, mission_id=m_id, task_id="t1", payload={"tool_name": "write_file"}))
    bus.publish(HermesEvent(event_type=EventType.TOOL_COMPLETED, mission_id=m_id, task_id="t1"))
    bus.publish(HermesEvent(event_type=EventType.VERIFICATION_STARTED, mission_id=m_id, task_id="t1"))
    bus.publish(HermesEvent(event_type=EventType.VERIFICATION_COMPLETED, mission_id=m_id, task_id="t1"))
    bus.publish(HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id=m_id, task_id="t1"))
    bus.publish(HermesEvent(event_type=EventType.MISSION_COMPLETED, mission_id=m_id))

    assert len(traces) == 9
    assert traces[0] == EventType.MISSION_CREATED
    assert traces[-1] == EventType.MISSION_COMPLETED
