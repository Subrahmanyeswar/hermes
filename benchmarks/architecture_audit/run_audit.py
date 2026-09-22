"""
Phase 4/5 Architecture Latency Audit Runner.
Executes the 10-mission benchmark suite through the real HERMES Orchestrator pipeline,
measuring exact nanosecond latency at every stage.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from core.orchestrator import Orchestrator
from benchmarks.architecture_audit.profiler import MissionProfiler
from benchmarks.inference_runtime_benchmark.system_info import get_system_snapshot

WORKSPACE = Path(__file__).resolve().parent.parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase4"
MISSIONS_FILE = WORKSPACE / "benchmarks" / "architecture_audit" / "missions.json"

async def run_single_mission(mission_item: Dict[str, Any], cold: bool = False, repetition: int = 1) -> Dict[str, Any]:
    mission_id = f"{mission_item['id']}_rep{repetition}_{'cold' if cold else 'warm'}"
    profiler = MissionProfiler(mission_id)
    orch = Orchestrator(mode="auto")

    if cold:
        # Evict any resident model to measure genuine cold start
        await orch.ollama.unload_all()
        await asyncio.sleep(1.0)

    prompt = mission_item["prompt"]
    print(f"\n[AUDIT] Running {mission_item['id']} ({'COLD' if cold else 'WARM'} rep {repetition}): {mission_item['name']}")

    start_perf = time.perf_counter()
    with profiler.span("TOTAL_MISSION", category="MISSION", mission_id=mission_id):
        # Instrument orchestrator run
        orch_res = await orch.run(prompt)
    profiler.finish()

    elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
    crit_path = profiler.compute_critical_path()

    print(f"  -> Wall Clock: {elapsed_ms:.1f}ms | Success: {orch_res.success} | Tool: {orch_res.tool_name} | Stage: {orch_res.pipeline_stage_reached}/12")

    record = {
        "mission_id": mission_id,
        "base_id": mission_item["id"],
        "name": mission_item["name"],
        "type": mission_item["type"],
        "cold": cold,
        "repetition": repetition,
        "wall_clock_ms": round(elapsed_ms, 2),
        "success": orch_res.success,
        "tool_name": orch_res.tool_name,
        "pipeline_stage_reached": orch_res.pipeline_stage_reached,
        "tier3_was_called": orch_res.tier3_was_called,
        "critical_path": crit_path,
        "spans": [s.to_dict() for s in profiler.root_spans]
    }
    return record

async def main_async():
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    missions_dir = PERF_DIR / "missions"
    missions_dir.mkdir(parents=True, exist_ok=True)

    with open(MISSIONS_FILE, "r", encoding="utf-8") as f:
        missions_suite = json.load(f)["missions"]

    # System snapshot
    sys_snap = get_system_snapshot()
    (PERF_DIR / "system_info.json").write_text(json.dumps(sys_snap, indent=2), encoding="utf-8")

    all_records = []

    print("============================================================")
    print(" STARTING HERMES COMPLETE ARCHITECTURE LATENCY AUDIT")
    print(f" Suite: {len(missions_suite)} representative missions (Cold + Warm)")
    print("============================================================")

    # 1. Cold Run on Mission 1 (System baseline cold start)
    m1_cold = await run_single_mission(missions_suite[0], cold=True, repetition=0)
    all_records.append(m1_cold)
    (missions_dir / f"{m1_cold['mission_id']}.json").write_text(json.dumps(m1_cold, indent=2), encoding="utf-8")

    # 2. Warm Runs for all 10 Missions (3 reps each)
    for m_item in missions_suite:
        for rep in range(1, 4):
            rec = await run_single_mission(m_item, cold=False, repetition=rep)
            all_records.append(rec)
            (missions_dir / f"{rec['mission_id']}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")

    # Save aggregated raw audit dataset
    (PERF_DIR / "audit_records.json").write_text(json.dumps(all_records, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved all raw records to {PERF_DIR / 'audit_records.json'}")

    # Run analysis
    from benchmarks.architecture_audit.analyze_audit import generate_audit_analysis
    generate_audit_analysis(all_records)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
