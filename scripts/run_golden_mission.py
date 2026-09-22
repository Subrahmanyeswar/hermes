import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.orchestrator import Orchestrator
from core.workspace import workspace_manager
from core.telemetry import telemetry
from kairos.mission_driver import MissionDriver

async def main():
    print("============================================================")
    print("HERMES GOLDEN MISSION EXECUTION — RUN 01")
    print("============================================================")

    # 1. Load mission definition
    mission_file = ROOT / "artifacts" / "performance" / "golden_mission.json"
    with open(mission_file, "r", encoding="utf-8") as f:
        mdata = json.load(f)

    prompt = mdata["task"]
    print(f"Mission: {mdata.get('name')}")
    print(f"Prompt: {prompt}")

    # 2. Prepare workspace directory
    target_dir = ROOT / "generated_projects" / "edupath_mini"
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 3. Setup workspace & telemetry
    workspace_manager.lock(str(target_dir))
    telemetry.clear()
    mission_id = "golden_run_01"
    telemetry.set_active_mission_id(mission_id)

    # 4. Initialize Orchestrator and Driver
    orchestrator = Orchestrator(mode="auto")
    driver = MissionDriver(orchestrator)
    driver._workspace_initialised = True

    # Background task to drain event queue and print live updates
    async def drain_events():
        while True:
            try:
                event = await driver._event_queue.get()
                etype = getattr(event, "event_type", "unknown")
                payload = getattr(event, "payload", {})
                if etype == "task_start":
                    print(f"\n[TASK START] {payload.get('title')} ({payload.get('task_id')})", flush=True)
                elif etype == "task_complete":
                    print(f"[TASK COMPLETE] {payload.get('title')} ✓", flush=True)
                elif etype == "task_failed":
                    print(f"[TASK FAILED] {payload.get('title')} ✗ error={payload.get('error')}", flush=True)
                elif etype == "pipeline_stage":
                    print(f"  -> Stage {payload.get('stage')}: {payload.get('stage_name')} ({payload.get('status')})", flush=True)
                elif etype == "quality_check":
                    print(f"  -> Quality verdict: {payload.get('verdict')} (passed={payload.get('passed')})", flush=True)
                elif etype == "thought":
                    print(f"  [Thought] {payload.get('text')}", flush=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                pass

    event_task = asyncio.create_task(drain_events())

    t0_wall = time.perf_counter()
    try:
        res = await driver.run_mission(prompt)
    finally:
        event_task.cancel()
    t1_wall = time.perf_counter()
    total_wall_s = t1_wall - t0_wall

    print("\n============================================================")
    print("MISSION EXECUTION FINISHED")
    print(f"Success: {res.success}")
    print(f"Tasks Completed: {res.tasks_completed}/{res.tasks_total}")
    print(f"Total Wall Latency: {total_wall_s:.2f}s ({total_wall_s/60.0:.2f} min)")
    print(f"Files Created: {res.files_created}")
    print("============================================================")

    # 5. Export comprehensive telemetry
    golden_dir = ROOT / "artifacts" / "performance" / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    out_trace_path = golden_dir / "golden_run_01.json"

    # Compile all completed requests into structured golden trace
    completed = telemetry.get_completed_requests()
    all_model_calls = []
    all_tool_calls = []
    all_ver_calls = []
    all_repair_calls = []
    all_switches = []
    all_stages = []

    for req in completed:
        for mc in req.model_calls:
            all_model_calls.append(mc.to_dict() if hasattr(mc, "to_dict") else mc)
        for tc in req.tools:
            all_tool_calls.append(tc.to_dict() if hasattr(tc, "to_dict") else tc)
        for vc in req.verification_calls:
            all_ver_calls.append(vc.to_dict() if hasattr(vc, "to_dict") else vc)
        for rc in req.repair_attempts:
            all_repair_calls.append(rc.to_dict() if hasattr(rc, "to_dict") else rc)
        for ms in req.model_switches:
            all_switches.append(ms.to_dict() if hasattr(ms, "to_dict") else ms)
        for s in req.spans:
            all_stages.append({
                "name": s.name,
                "stage_number": s.stage_number,
                "duration_ms": s.duration_ms,
                "success": s.success
            })

    total_model_duration_ms = sum(mc.get("total_latency_ms", 0.0) for mc in all_model_calls)
    total_tool_duration_ms = sum(tc.get("duration_ms", 0.0) for tc in all_tool_calls)
    total_ver_duration_ms = sum(vc.get("duration_ms", 0.0) for vc in all_ver_calls)
    total_stage_duration_ms = sum(s.get("duration_ms", 0.0) for s in all_stages)

    accounted_ms = total_model_duration_ms + total_tool_duration_ms + total_ver_duration_ms
    unaccounted_ms = max(0.0, (total_wall_s * 1000.0) - accounted_ms)

    trace_doc = {
        "mission_id": "golden_run_01",
        "mission_name": "EduPath Mini Career Guidance Webpage",
        "wall_time_seconds": total_wall_s,
        "wall_time_minutes": total_wall_s / 60.0,
        "tasks_completed": res.tasks_completed,
        "tasks_total": res.tasks_total,
        "success": res.success,
        "error": res.error,
        "files_created": res.files_created,
        "files_modified": res.files_modified,
        "accounting": {
            "total_wall_ms": total_wall_s * 1000.0,
            "accounted_ms": accounted_ms,
            "unaccounted_ms": unaccounted_ms,
            "model_time_ms": total_model_duration_ms,
            "tool_time_ms": total_tool_duration_ms,
            "verification_time_ms": total_ver_duration_ms,
            "stage_spans_ms": total_stage_duration_ms
        },
        "model_calls": all_model_calls,
        "tool_calls": all_tool_calls,
        "verification_calls": all_ver_calls,
        "repair_attempts": all_repair_calls,
        "model_switches": all_switches,
        "stages": all_stages
    }

    with open(out_trace_path, "w", encoding="utf-8") as f:
        json.dump(trace_doc, f, indent=2)

    print(f"Trace saved to {out_trace_path} ({len(all_model_calls)} model calls, {len(all_tool_calls)} tool calls)")

if __name__ == "__main__":
    asyncio.run(main())
