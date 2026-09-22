"""
Pre-Benchmark Gate 15.4: Frozen Environment Execution Dry-Run.
Verifies that all components of the frozen environment are executable
without recording or publishing final benchmark performance numbers.
"""
import sys
import json
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from core.event_bus import HermesEvent, EventType, EventBus
from core.context_engine import ContextEngine
from core.intelligent_router import IntelligentRouter, RoutingAction
from core.progressive_verifier import ProgressiveVerificationEngine
from core.mission_completion import CompletionLedger, CriterionStatus, MissionCompletionEvaluator

WORKSPACE = Path(__file__).resolve().parent.parent
MANIFEST_PATH = WORKSPACE / "benchmarks" / "HERMES_BENCHMARK_FREEZE.json"


def run_environment_dry_run():
    print("================================================================")
    print(" PRE-BENCHMARK GATE 15.4: FROZEN ENVIRONMENT DRY-RUN")
    print("================================================================")

    assert MANIFEST_PATH.exists()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    prompts = manifest["benchmark_dataset_manifest"]["prompt_set"]

    bus = EventBus(enabled=True)
    ce = ContextEngine(enabled=True)
    router = IntelligentRouter(enabled=True)
    verifier = ProgressiveVerificationEngine(enabled=True)
    evaluator = MissionCompletionEvaluator(enabled=True)

    print(f"\nLoaded {len(prompts)} frozen benchmark tasks from manifest:")
    for task in prompts:
        print(f"  * [{task['id']}] {task['prompt']} -> Expected Mode: {task['expected_mode']}")

    # Dry-run execution on Task 1
    m_id = "m_dry_run_01"
    bus.publish(HermesEvent(event_type=EventType.MISSION_CREATED, mission_id=m_id))

    # Context Pack
    pack = ce.build_context_pack(prompts[0]["prompt"], "CODE")
    assert pack.total_tokens > 0

    # Routing
    dec = router.route_t1_result(prompts[0]["prompt"], "SIMPLE", 0.95, 0.1, "read_file", "PASSED")
    assert dec.action == RoutingAction.ACCEPT_T1

    # Ledger
    ledger = CompletionLedger(m_id)
    ledger.add_criterion("AC-1", prompts[0]["acceptance"])
    ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["Dry-run simulated"])

    verdict, _ = evaluator.evaluate(ledger, dag_is_complete=True)
    assert verdict.value == "COMPLETE"
    bus.publish(HermesEvent(event_type=EventType.MISSION_COMPLETED, mission_id=m_id))

    print("\n[SUCCESS] Frozen environment dry-run completed successfully.")
    print("  - Frozen Manifest Loaded: OK")
    print("  - Context Pack Assembly: OK")
    print("  - Intelligent Router Tier Selection: OK")
    print("  - Event Bus & State Store: OK")
    print("  - Mission Completion Ledger: OK")
    return True


if __name__ == "__main__":
    run_environment_dry_run()
