import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.orchestrator import Orchestrator
from core.telemetry import telemetry


async def main():
    probe_path = Path("artifacts/performance/golden_performance_probe.json")
    if not probe_path.exists():
        print(f"Error: {probe_path} not found")
        sys.exit(1)

    with open(probe_path, "r", encoding="utf-8") as f:
        probe_data = json.load(f)

    prompt = probe_data["task"]
    mission_id = probe_data.get("probe_id", "golden_performance_probe_01")
    mode = probe_data.get("mode", "auto")

    print("============================================================")
    print("HERMES PERFORMANCE BASELINE PROBE")
    print(f"Mission ID: {mission_id}")
    print(f"Mode: {mode}")
    print(f"Task: {prompt}")
    print("============================================================")

    telemetry.clear()
    telemetry.set_active_mission_id(mission_id)

    orchestrator = Orchestrator(mode=mode)


    t0_mono = time.monotonic()

    result = await orchestrator.run(prompt)


    t1_mono = time.monotonic()
    wall_duration = t1_mono - t0_mono

    print(f"\n============================================================")
    print("PROBE EXECUTION RESULT")
    print(f"Success: {result.success}")
    print(f"Pipeline Stage Reached: {result.pipeline_stage_reached}")
    print(f"Tool Used: {result.tool_name}")
    print(f"Total Wall Latency: {wall_duration:.2v}s ({wall_duration * 1000:.1}ms)")
    if result.error:
        print(f"Error: {result.error}")
    print(f"Output Preview:\n{result.final_output[:600]}")
    print("===========================================================")

    trace_path = Path(f"artifacts/performance/traces/mission_{mission_id}.json")
    if not trace_path.exists():
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        completed = telemetry.get_completed_requests()
        if completed:
            telemetry.export_performance_trace(completed[-1].request_id, filepath=str(trace_path))

    if trace_path.exists():
        with open(trace_path, "r", encoding="utf-8") as f:
            trace = json.load(f)
        print(f"\nTrace recorded at: {trace_path}")
        print(f"Trace mission duration: {trace.get('mission', {}).get('duration_ms')}ms")
        print(f"Stages recorded: {len(trace.get('stages', []))}")
        print(f"Model calls recorded: {len(trace.get('model_calls', []))}")
        print(f"Tool calls recorded: {len(trace.get('tool_calls', []))}")
        print(f"Verification calls recorded: {len(trace.get('verification_calls', []))}")
        print(f"Model switches recorded: {len(trace.get('model_switches', []))}")
    else:
        print(f"WARNING: Trace file not found at {trace_path}")

if __name__ == "__main__":
    asyncio.run(main())
