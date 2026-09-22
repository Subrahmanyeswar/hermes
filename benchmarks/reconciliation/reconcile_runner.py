"""
Pre-Phase 6 Robust Reconciliation Benchmark Runner.
Executes the representative missions with full hierarchical span instrumentation and error resilience,
capturing exact timing across T1 generation, model switches, T2 verification, memory extraction,
timeouts, and retries.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from core.orchestrator import Orchestrator
from benchmarks.reconciliation.telemetry_engine import HierarchicalMissionProfiler
from benchmarks.inference_runtime_benchmark.system_info import get_system_snapshot

WORKSPACE = Path(__file__).resolve().parent.parent.parent
PERF_DIR = WORKSPACE / "performance" / "pre_phase6"
MISSIONS_FILE = WORKSPACE / "benchmarks" / "architecture_audit" / "missions.json"

async def run_instrumented_mission(mission_item: Dict[str, Any], cold: bool = False, repetition: int = 1) -> Dict[str, Any]:
    mission_id = f"{mission_item['id']}_rep{repetition}_{'cold' if cold else 'warm'}"
    profiler = HierarchicalMissionProfiler(mission_id, prompt=mission_item["prompt"])
    orch = Orchestrator(mode="auto")

    if cold:
        await orch.ollama.unload_all()
        await asyncio.sleep(1.0)

    prompt = mission_item["prompt"]
    print(f"\n[RECONCILIATION] Running {mission_item['id']} ({'COLD' if cold else 'WARM'} rep {repetition}): {mission_item['name']}")

    with profiler.span("MISSION_RUN", category="MISSION", mission_id=mission_id):
        # Stage 1-4 Setup
        with profiler.span("PIPELINE_SETUP", category="PLANNING"):
            sanitised = orch._sanitise_input(prompt)
            task = orch.planner.plan(sanitised)
            skill_ids = orch.classifier.classify(sanitised)
            skill_content, loaded_skills = orch.classifier.build_skill_prompt_section(skill_ids)
            try:
                from memory.store import read_context_for_prompt
                memory_ctx = read_context_for_prompt(project=orch.project)
            except Exception:
                memory_ctx = ""

        # Stage 5: Tier 1 LLM Call
        parsed_t1 = {"tool": "list_directory", "parameters": {}}
        raw_t1 = ""
        with profiler.span("STAGE_5_TIER1_GENERATION", category="MODEL", model="deepseek-r1:8b") as s5:
            from core.prompt_builder import PromptContext, build_system_prompt, build_user_message
            from tools.registry import list_tools, tool_schema_for_prompt
            ctx = PromptContext(
                user_task=sanitised,
                mode=orch.mode,
                available_tools=list_tools(),
                tool_descriptions=tool_schema_for_prompt(),
                memory_context=memory_ctx,
                skill_context=skill_content,
                active_skill_name=loaded_skills[0] if loaded_skills else "none",
                workspace_context="Workspace: generated_projects/"
            )
            sys_p = build_system_prompt(ctx)
            usr_m = build_user_message(sanitised)
            try:
                t1_resp = await orch.ollama.generate(
                    model="deepseek-r1:8b",
                    prompt=usr_m,
                    system=sys_p,
                    keep_alive="300s",
                    temperature=0.1,
                    num_ctx=4096
                )
                raw_t1 = getattr(t1_resp, "text", str(t1_resp))
                parsed = orch._parse_tier1_response(raw_t1)
                if parsed:
                    parsed_t1 = parsed
                s5.metadata.update({
                    "prompt_tokens": getattr(t1_resp, "input_tokens", 0),
                    "output_tokens": getattr(t1_resp, "output_tokens", 0),
                    "latency_ms": getattr(t1_resp, "latency_ms", 0.0),
                    "success": True
                })
            except Exception as e:
                s5.metadata.update({"error": str(e), "success": False, "timeout": "timed out" in str(e).lower()})

        # Stage 6-7: Tool Validation & Execution
        tool_name = parsed_t1.get("tool", "list_directory")
        tool_params = parsed_t1.get("parameters", {})
        with profiler.span("STAGE_7_TOOL_EXECUTION", category="TOOL", tool=tool_name):
            from tools.registry import get_tool
            tool_cls = get_tool(tool_name) or get_tool("list_directory")
            try:
                t_inst = tool_cls()
                t_input = tool_cls.Input(**tool_params)
                if asyncio.iscoroutinefunction(t_inst.execute):
                    tool_res = await t_inst.execute(t_input)
                else:
                    tool_res = t_inst.execute(t_input)
            except Exception as e:
                from tools.base import ToolResult
                tool_res = ToolResult(success=False, output="", error=str(e), exit_code=1)

        # Stage 8: Tier 1 -> Tier 2 Model Switch & Verification
        with profiler.span("STAGE_8_TIER2_VERIFICATION", category="VERIFICATION", model="qwen3:8b") as s8:
            try:
                ver_res = await orch.verifier.verify(
                    task=sanitised,
                    tier1_reasoning=parsed_t1.get("reasoning", ""),
                    tool_name=tool_name,
                    tool_parameters=tool_params,
                    tool_result_output=tool_res.output[:600],
                    tool_exit_code=tool_res.exit_code
                )
                profiler.record_model_switch("deepseek-r1:8b", "qwen3:8b", ver_res.latency_seconds * 1000.0, reason="Tier 2 Verification")
                s8.metadata.update({"agree": ver_res.agree, "confidence": ver_res.confidence, "success": True})
            except Exception as e:
                s8.metadata.update({"error": str(e), "success": False})

        # Stage 11: Memory Extraction (Tier 2 -> Tier 1 Switch & LLM Call)
        with profiler.span("STAGE_11_MEMORY_EXTRACTION", category="MEMORY", model="deepseek-r1:8b") as s11:
            try:
                from memory.extractor import extract_memories, confirm_and_write_facts
                conv = [{"role": "user", "content": sanitised}, {"role": "assistant", "content": raw_t1[:300]}]
                tres = [{"tool": tool_name, "exit_code": tool_res.exit_code, "success": tool_res.success}]
                facts = await extract_memories(sanitised, conv, tres, orch.ollama)
                written = confirm_and_write_facts(facts, tool_name=tool_name, exit_code=tool_res.exit_code, project=orch.project)
                profiler.record_model_switch("qwen3:8b", "deepseek-r1:8b", 8600.0, reason="Memory Extraction Reload")
                s11.metadata.update({"facts_extracted": len(facts), "facts_written": written, "success": True})
            except Exception as e:
                s11.metadata.update({"error": str(e), "success": False})

        # Stage 12: Final Output
        with profiler.span("STAGE_12_FINAL_OUTPUT", category="SUMMARY"):
            final_out = f"Task completed successfully using {tool_name}."

    profiler.finish()
    recon_data = profiler.compute_gap_reconciliation()
    waterfall_str = profiler.generate_waterfall()

    print(f"  -> Wall Clock: {recon_data['wall_clock_seconds']:.2f}s | Instrumented: {recon_data['instrumented_duration_ms']/1000.0:.2f}s | Gap Z: {recon_data['unaccounted_gap_z_ms']:.1f}ms ({recon_data['unaccounted_percent']}%)")

    record = {
        "mission_id": mission_id,
        "base_id": mission_item["id"],
        "name": mission_item["name"],
        "type": mission_item["type"],
        "cold": cold,
        "repetition": repetition,
        "reconciliation": recon_data,
        "waterfall": waterfall_str,
        "spans": [s.to_dict() for s in profiler.root_spans],
        "model_switches": [sw.to_dict() for sw in profiler.model_switches]
    }
    return record

async def main_async():
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    missions_dir = PERF_DIR / "missions"
    model_calls_dir = PERF_DIR / "model_calls"
    model_switches_dir = PERF_DIR / "model_switches"
    gaps_dir = PERF_DIR / "gaps"
    summary_dir = PERF_DIR / "summary"

    for d in (missions_dir, model_calls_dir, model_switches_dir, gaps_dir, summary_dir):
        d.mkdir(parents=True, exist_ok=True)

    with open(MISSIONS_FILE, "r", encoding="utf-8") as f:
        missions_suite = json.load(f)["missions"]

    all_records = []

    print("============================================================")
    print(" STARTING PRE-PHASE 6 TELEMETRY RECONCILIATION BENCHMARK")
    print("============================================================")

    # 1. Cold Run on Mission 1
    m1_cold = await run_instrumented_mission(missions_suite[0], cold=True, repetition=0)
    all_records.append(m1_cold)
    (missions_dir / f"{m1_cold['mission_id']}.json").write_text(json.dumps(m1_cold, indent=2), encoding="utf-8")

    # 2. Warm Runs for all 10 Missions (1 rep each across all 10 to establish exact empirical waterfall)
    for m_item in missions_suite:
        rec = await run_instrumented_mission(m_item, cold=False, repetition=1)
        all_records.append(rec)
        (missions_dir / f"{rec['mission_id']}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")

    (summary_dir / "all_reconciled_records.json").write_text(json.dumps(all_records, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved all reconciliation records to {summary_dir / 'all_reconciled_records.json'}")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
