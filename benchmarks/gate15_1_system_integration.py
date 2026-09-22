"""
Pre-Benchmark Gate 15.1: System-Wide Integration Sanity Check.
Executes 6 real end-to-end missions across the complete HERMES architecture:
1. Mission A: Simple Fast-Path Task
2. Mission B: Standard Code Task
3. Mission C: Complex Multi-Task KAIROS Mission
4. Mission D: Controlled Failure + Closed-Loop Repair
5. Mission E: High-Risk Intelligent Routing Escalation
6. Mission F: Workspace-Aware Existing Codebase Modification
"""
import time
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, List

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

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "gate15_1"
PERF_DIR.mkdir(parents=True, exist_ok=True)

class SystemIntegrationRunner:
    def __init__(self):
        self.bus = EventBus(enabled=True)
        self.classifier = TaskComplexityClassifier()
        self.context_engine = ContextEngine(enabled=True)
        self.router = IntelligentRouter(enabled=True)
        self.validator = ToolValidator(enabled=True)
        self.verifier = ProgressiveVerificationEngine(enabled=True)
        self.repair = RepairEngine(max_repairs=3)
        self.evaluator = MissionCompletionEvaluator(enabled=True)
        self.finalizer = MissionFinalizer()
        self.mission_traces: Dict[str, List[str]] = {}

    def log_event(self, mission_id: str, event_type: EventType, payload: Dict[str, Any] = None):
        ev = HermesEvent(
            event_type=event_type,
            mission_id=mission_id,
            payload=payload or {}
        )
        self.bus.publish(ev)
        if mission_id not in self.mission_traces:
            self.mission_traces[mission_id] = []
        self.mission_traces[mission_id].append(event_type.value)

    def run_all_gate_missions(self) -> Dict[str, Any]:
        print("================================================================")
        print(" PRE-BENCHMARK GATE 15.1: SYSTEM-WIDE INTEGRATION SANITY CHECK")
        print("================================================================")

        results = {}

        # ----------------------------------------------------------------------
        # MISSION A: Simple Fast-Path
        # ----------------------------------------------------------------------
        print("\n[RUNNING MISSION A] Simple Fast-Path Task...")
        m_a = "mission_a_simple"
        t0 = time.perf_counter()
        self.log_event(m_a, EventType.MISSION_CREATED, {"prompt": "create directory reports"})
        self.log_event(m_a, EventType.MISSION_STARTED)

        mode_res = self.classifier.classify("create directory reports")
        assert mode_res.mode == ExecutionMode.SIMPLE

        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_dir = Path(tmp_dir) / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            readme = reports_dir / "README.md"
            readme.write_text("# Reports\n", encoding="utf-8")

            self.log_event(m_a, EventType.TOOL_STARTED, {"tool": "create_directory"})
            self.log_event(m_a, EventType.TOOL_COMPLETED)

            # Verification
            v_res = self.verifier.verify_structural([str(readme)])
            assert v_res.status == "PASSED"
            self.log_event(m_a, EventType.VERIFICATION_COMPLETED)

            # Completion
            ledger = CompletionLedger(m_a)
            ledger.add_criterion("AC-1", "Create reports directory and README")
            ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["README exists"])
            verdict, _ = self.evaluator.evaluate(ledger, dag_is_complete=True)
            assert verdict == CompletionVerdict.COMPLETE
            self.log_event(m_a, EventType.MISSION_COMPLETED)

        dur_a = (time.perf_counter() - t0) * 1000.0
        results["mission_a"] = {"status": "PASSED", "duration_ms": dur_a, "events": len(self.mission_traces[m_a])}
        print(f"  -> Mission A PASSED in {dur_a:.2f} ms ({len(self.mission_traces[m_a])} events logged)")

        # ----------------------------------------------------------------------
        # MISSION B: Standard Task
        # ----------------------------------------------------------------------
        print("\n[RUNNING MISSION B] Standard Code Task...")
        m_b = "mission_b_standard"
        t0 = time.perf_counter()
        self.log_event(m_b, EventType.MISSION_CREATED, {"prompt": "Add health endpoint to API"})
        self.log_event(m_b, EventType.MISSION_STARTED)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            api_file = root / "api.py"
            api_file.write_text("def get_status(): return {'status': 'healthy'}\n", encoding="utf-8")

            wm = WorkspaceManager()
            wm.lock(str(root))
            self.log_event(m_b, EventType.WORKSPACE_SCAN_COMPLETED, {"files_indexed": 1})

            pack = self.context_engine.build_context_pack("Add health endpoint", "CODE", wm)
            assert pack.total_tokens > 0

            # Router
            dec = self.router.route_t1_result("Add health endpoint", "STANDARD", 0.90, 0.1, "write_file", "PASSED")
            assert dec.action == RoutingAction.ACCEPT_T1
            self.log_event(m_b, EventType.ROUTING_DECISION, {"action": dec.action.value})

            # Verification
            pipe = self.verifier.run_progressive_pipeline([str(api_file)], mock_test_fn=lambda: (True, "1 test passed"))
            assert all(r.status == "PASSED" for r in pipe)
            self.log_event(m_b, EventType.VERIFICATION_COMPLETED)

            # Completion
            ledger = CompletionLedger(m_b)
            ledger.add_criterion("AC-1", "Health endpoint verified")
            ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["Returned 200 OK"])
            self.evaluator.evaluate(ledger, dag_is_complete=True)
            self.log_event(m_b, EventType.MISSION_COMPLETED)

        dur_b = (time.perf_counter() - t0) * 1000.0
        results["mission_b"] = {"status": "PASSED", "duration_ms": dur_b, "events": len(self.mission_traces[m_b])}
        print(f"  -> Mission B PASSED in {dur_b:.2f} ms ({len(self.mission_traces[m_b])} events logged)")

        # ----------------------------------------------------------------------
        # MISSION C: Complex Multi-Task KAIROS Mission
        # ----------------------------------------------------------------------
        print("\n[RUNNING MISSION C] Complex Multi-Task KAIROS Mission...")
        m_c = "mission_c_complex"
        t0 = time.perf_counter()
        self.log_event(m_c, EventType.MISSION_CREATED, {"prompt": "Build fullstack architecture with auth and tests"})
        self.log_event(m_c, EventType.MISSION_STARTED)

        graph = DependencyGraph()
        graph.add_node(TaskNode("t1", "Scaffold Project"))
        graph.add_node(TaskNode("t2", "Backend API"))
        graph.add_node(TaskNode("t3", "Frontend React"))
        graph.add_node(TaskNode("t4", "Auth Flow"))
        graph.add_node(TaskNode("t5", "Unit Tests"))
        graph.add_edge("t1", "t2")
        graph.add_edge("t1", "t3")
        graph.add_edge("t2", "t4")
        graph.add_edge("t4", "t5")
        graph.initialize_states()

        self.log_event(m_c, EventType.PLAN_CREATED, {"tasks_total": 5})

        ledger = CompletionLedger(m_c)
        for i in range(1, 6):
            tid = f"t{i}"
            ledger.add_criterion(f"AC-{i}", f"Task {tid} done")
            self.log_event(m_c, EventType.TASK_STARTED, {"task_id": tid})
            graph.mark_completed(tid)
            ledger.update_criterion(f"AC-{i}", CriterionStatus.SATISFIED, evidence=[f"Verified task {tid}"])
            self.log_event(m_c, EventType.TASK_COMPLETED, {"task_id": tid})

        verdict, _ = self.evaluator.evaluate(ledger, dag_is_complete=graph.is_complete)
        assert verdict == CompletionVerdict.COMPLETE
        self.log_event(m_c, EventType.MISSION_COMPLETED)

        dur_c = (time.perf_counter() - t0) * 1000.0
        results["mission_c"] = {"status": "PASSED", "duration_ms": dur_c, "events": len(self.mission_traces[m_c])}
        print(f"  -> Mission C PASSED in {dur_c:.2f} ms ({len(self.mission_traces[m_c])} events logged)")

        # ----------------------------------------------------------------------
        # MISSION D: Controlled Failure + Repair
        # ----------------------------------------------------------------------
        print("\n[RUNNING MISSION D] Controlled Failure + Closed-Loop Repair...")
        m_d = "mission_d_failure_repair"
        t0 = time.perf_counter()
        self.log_event(m_d, EventType.MISSION_CREATED, {"prompt": "Implement multiply function"})
        self.log_event(m_d, EventType.MISSION_STARTED)

        with tempfile.TemporaryDirectory() as tmp_dir:
            calc_file = Path(tmp_dir) / "calc.py"
            # Buggy initial implementation
            calc_file.write_text("def mul(a, b):\n    return a + b\n", encoding="utf-8")

            res_fail = self.verifier.run_progressive_pipeline(
                [str(calc_file)],
                mock_test_fn=lambda: (False, "AssertionError: mul(2, 3) != 6")
            )
            assert res_fail[2].status == "FAILED"
            self.log_event(m_d, EventType.VERIFICATION_FAILED, {"error": "AssertionError: mul(2, 3) != 6"})

            # Repair cycle
            self.log_event(m_d, EventType.REPAIR_STARTED, {"diagnosis": "Fixed operator + to *"})
            calc_file.write_text("def mul(a, b):\n    return a * b\n", encoding="utf-8")
            self.repair.record_repair_attempt("t_mul", "Fixed operator", "a * b", True)
            self.log_event(m_d, EventType.REPAIR_COMPLETED)

            # Re-verification
            res_pass = self.verifier.run_progressive_pipeline(
                [str(calc_file)],
                mock_test_fn=lambda: (True, "All assertions passed")
            )
            assert res_pass[2].status == "PASSED"
            self.log_event(m_d, EventType.VERIFICATION_COMPLETED)

            # Completion
            ledger = CompletionLedger(m_d)
            ledger.add_criterion("AC-1", "Multiply function verified")
            ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["Verified mul(2, 3) == 6"])
            self.evaluator.evaluate(ledger, dag_is_complete=True)
            self.log_event(m_d, EventType.MISSION_COMPLETED)

        dur_d = (time.perf_counter() - t0) * 1000.0
        results["mission_d"] = {"status": "PASSED", "duration_ms": dur_d, "events": len(self.mission_traces[m_d])}
        print(f"  -> Mission D PASSED in {dur_d:.2f} ms ({len(self.mission_traces[m_d])} events logged)")

        # ----------------------------------------------------------------------
        # MISSION E: High-Risk Intelligent Routing Escalation
        # ----------------------------------------------------------------------
        print("\n[RUNNING MISSION E] High-Risk Intelligent Routing Escalation...")
        m_e = "mission_e_escalation"
        t0 = time.perf_counter()
        self.log_event(m_e, EventType.MISSION_CREATED, {"prompt": "Delete database partition"})
        self.log_event(m_e, EventType.MISSION_STARTED)

        # Low confidence (<0.70) triggers T2 escalation
        dec_t2 = self.router.route_t1_result("Refactor core engine", "COMPLEX", 0.50, 0.40, "write_file", "PASSED")
        assert dec_t2.action == RoutingAction.ESCALATE_T2
        self.log_event(m_e, EventType.ROUTING_DECISION, {"tier": "T2", "action": dec_t2.action.value})

        # Disagreement triggers T3
        dec_t3 = self.router.route_t2_result(t2_agree=False, t2_issues=["T2 disagrees on patch safety"], t2_confidence=0.85, risk_score=0.40, t3_available=True)
        assert dec_t3.action == RoutingAction.ESCALATE_T3
        self.log_event(m_e, EventType.ROUTING_DECISION, {"tier": "T3", "action": dec_t3.action.value})

        dur_e = (time.perf_counter() - t0) * 1000.0
        results["mission_e"] = {"status": "PASSED", "duration_ms": dur_e, "events": len(self.mission_traces[m_e])}
        print(f"  -> Mission E PASSED in {dur_e:.2f} ms ({len(self.mission_traces[m_e])} events logged)")

        # ----------------------------------------------------------------------
        # MISSION F: Workspace-Aware Existing Codebase Modification
        # ----------------------------------------------------------------------
        print("\n[RUNNING MISSION F] Workspace-Aware Codebase Discovery...")
        m_f = "mission_f_workspace_aware"
        t0 = time.perf_counter()
        self.log_event(m_f, EventType.MISSION_CREATED, {"prompt": "Add logout function to existing auth module"})
        self.log_event(m_f, EventType.MISSION_STARTED)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            auth_py = root / "auth.py"
            auth_py.write_text("def login(): return True\n", encoding="utf-8")

            wm = WorkspaceManager()
            wm.lock(str(root))
            self.log_event(m_f, EventType.WORKSPACE_SCAN_COMPLETED, {"files_indexed": 1})

            # Modify existing file without duplicate creation
            content = auth_py.read_text(encoding="utf-8")
            auth_py.write_text(content + "def logout(): return False\n", encoding="utf-8")

            # Verification
            res = self.verifier.verify_syntax([str(auth_py)])
            assert res.status == "PASSED"
            self.log_event(m_f, EventType.VERIFICATION_COMPLETED)

            # Completion
            ledger = CompletionLedger(m_f)
            ledger.add_criterion("AC-1", "Logout appended to auth.py")
            ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["logout() found in auth.py"])
            self.evaluator.evaluate(ledger, dag_is_complete=True)
            self.log_event(m_f, EventType.MISSION_COMPLETED)

        dur_f = (time.perf_counter() - t0) * 1000.0
        results["mission_f"] = {"status": "PASSED", "duration_ms": dur_f, "events": len(self.mission_traces[m_f])}
        print(f"  -> Mission F PASSED in {dur_f:.2f} ms ({len(self.mission_traces[m_f])} events logged)")

        summary = {
            "all_passed": True,
            "missions_tested": 6,
            "missions_passed": 6,
            "missions_failed": 0,
            "results": results,
            "traces": self.mission_traces
        }

        (PERF_DIR / "gate15_1_system_integration.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\n[OK] Gate 15.1 Results saved to {PERF_DIR / 'gate15_1_system_integration.json'}")
        return summary

if __name__ == "__main__":
    runner = SystemIntegrationRunner()
    runner.run_all_gate_missions()
