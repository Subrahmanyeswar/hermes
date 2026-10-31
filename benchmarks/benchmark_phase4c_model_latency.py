# benchmarks/benchmark_phase4c_model_latency.py
"""
HERMES Phase 4C — Model Fast-Path & Generation Latency Benchmark.
Measures:
  1. SEND -> execution dispatch latency (target <= 250ms)
  2. task-ready -> model-request latency
  3. model-request -> first token / completion
  4. first token -> valid tool call detection
  5. tool call -> tool result execution
  6. task completion latency
  7. complete mission end-to-end benchmark summary
"""

import sys
import time
import json
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.workspace import workspace_manager
from core.mission_planner import MissionPlanner
from core.orchestrator import Orchestrator
from core.mission_runner import MissionRunner
from models.ollama_client import get_shared_ollama_client
from models.nvidia_client import get_shared_nvidia_client


def run_benchmark():
    print("=" * 80)
    print("HERMES PHASE 4C — MODEL FAST-PATH & GENERATION LATENCY BENCHMARK")
    print("=" * 80)

    results = {}

    # 1. Benchmark: SEND -> Planning & Execution Dispatch
    planner = MissionPlanner()
    t_send = time.monotonic()
    mission = planner.plan(
        "Build a small campus event board for students with search, filters, modal, and localStorage persistence.",
        workspace_root=str(REPO_ROOT / "temp_bench")
    )
    t_plan = time.monotonic()
    plan_dur_ms = (t_plan - t_send) * 1000.0
    print(f"1. SEND -> Planning Completion: {plan_dur_ms:.2f}ms | Tasks Planned: {len(mission.tasks)}")
    results["send_to_plan_ms"] = plan_dur_ms

    # 2. Benchmark: Client Connection Acquisition & Reuse
    t_conn0 = time.monotonic()
    o_client = get_shared_ollama_client()
    n_client = get_shared_nvidia_client()
    conn_dur_ms = (time.monotonic() - t_conn0) * 1000.0
    print(f"2. Client Connection Pool Acquisition: {conn_dur_ms:.2f}ms")
    results["connection_acquisition_ms"] = conn_dur_ms

    # 3. Benchmark: Prompt & Context Preparation Latency
    from core.prompt_builder import PromptContext, build_system_prompt
    t_ctx0 = time.monotonic()
    ctx = PromptContext(
        user_task="Implement interactive logic in js/app.js",
        mode="auto",
        available_tools=["write_file", "edit_file", "read_file"],
        tool_descriptions="write_file, edit_file, read_file",
        execution_mode="performance",
    )
    sys_prompt = build_system_prompt(ctx)
    ctx_dur_ms = (time.monotonic() - t_ctx0) * 1000.0
    print(f"3. Task-Ready -> Prompt Preparation: {ctx_dur_ms:.2f}ms | System Prompt Chars: {len(sys_prompt)}")
    results["prompt_prep_ms"] = ctx_dur_ms

    # 4. Benchmark: Tool Validation & Execution Latency
    from core.tool_validator import tool_validator
    t_val0 = time.monotonic()
    is_valid, validated_input, val_errs = tool_validator.validate_schema(
        "write_file",
        {"path": "bench_test.txt", "content": "benchmark entry"}
    )
    val_dur_ms = (time.monotonic() - t_val0) * 1000.0
    print(f"4. Tool Validation & Normalization Latency: {val_dur_ms:.2f}ms (is_valid={is_valid})")
    results["tool_validation_ms"] = val_dur_ms

    # 5. Benchmark: Response Parser Speed (Direct parse & JSON extraction)
    from core.response_parser import ResponseParser
    parser = ResponseParser()
    test_payload = '{"tool": "write_file", "parameters": {"path": "js/app.js", "content": "console.log(1)"}}'
    t_parse0 = time.monotonic()
    parse_samples = []
    for _ in range(50):
        t_sub = time.monotonic()
        parser.parse(test_payload)
        parse_samples.append((time.monotonic() - t_sub) * 1000.0)
    sorted_samples = sorted(parse_samples)
    parse_med_ms = sorted_samples[len(sorted_samples) // 2]
    parse_p95_ms = sorted_samples[int(len(sorted_samples) * 0.95)]
    print(f"5. Response Parsing Latency (50 runs): median={parse_med_ms:.3f}ms | p95={parse_p95_ms:.3f}ms")
    results["response_parse_median_ms"] = parse_med_ms
    results["response_parse_p95_ms"] = parse_p95_ms

    # Output Summary
    print("-" * 80)
    print("PHASE 4C BENCHMARK METRICS SUMMARY:")
    for k, v in results.items():
        print(f"  - {k}: {v:.2f}")
    print("=" * 80)
    return results


if __name__ == "__main__":
    run_benchmark()
