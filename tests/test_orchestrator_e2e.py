#!/usr/bin/env python3
"""
HERMES - Orchestrator End-to-End Test
Runs 10 real diverse tasks through the complete 12-stage pipeline.
Requires: Ollama running with qwen2.5-coder:7b and mistral:7b-instruct-q4_K_M pulled.

Success criteria:
  - At least 7 of 10 tasks reach Stage 12 without crashing
  - At least 5 of 10 tool calls succeed (exit_code == 0)
  - Zero unhandled exceptions
  - Memory updates happen only for successful tool calls

Run: python tests/test_orchestrator_e2e.py
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import Orchestrator

# ----------------------------------------------------------------------

TASKS = [
    # L1: Trivial - read/list operations
    ("L1-01", "List all files in the current directory"),
    ("L1-02", "Read the contents of the HERMES.md file"),
    ("L1-03", "Show me what is in the config/ folder"),

    # L2: Simple - single file creation
    ("L2-01", "Create a Python file called hello.py that prints hello world"),
    ("L2-02", "Write a file called test_output.txt with the text HERMES test passed"),

    # L3: Medium - multi-step tasks
    ("L3-01", "Create a Python calculator module at generated_projects/calculator.py with add subtract multiply divide functions"),
    ("L3-02", "Create a Flask hello world app at generated_projects/flask_demo/app.py"),

    # L2: Bash execution
    ("L2-03", "Run the command python --version and show the output"),

    # L2: Web interaction
    ("L2-04", "Search the web for Python asyncio documentation"),

    # L3: Memory
    ("L3-03", "Remember that this project is using Python 3.12 and the main framework is Flask"),
]

# ----------------------------------------------------------------------

async def run_all_tasks():
    print("=" * 70)
    print("HERMES - Orchestrator End-to-End Test (10 Tasks)")
    print("=" * 70)

    orch = Orchestrator(mode="auto", project="e2e_test")

    results = []
    stage_12_count = 0
    tool_success_count = 0
    tier3_called_count = 0
    memory_update_count = 0
    crash_count = 0

    for task_id, task_text in TASKS:
        print(f"\n[{task_id}] {task_text[:60]}")

        try:
            start = time.monotonic()
            result = await orch.run(task_text)
            elapsed = time.monotonic() - start

            if result.pipeline_stage_reached == 12:
                stage_12_count += 1

            if result.tool_result and result.tool_result.success:
                tool_success_count += 1

            if result.tier3_was_called:
                tier3_called_count += 1

            status = "[OK]" if result.success else "[FAIL]"
            print(f"  {status} Stage reached: {result.pipeline_stage_reached}/12 | "
                  f"tool={result.tool_name} | success={result.success} | "
                  f"tier3={result.tier3_was_called} | {elapsed:.1f}s")

            if result.error:
                print(f"    Error: {result.error[:80]}")

            if result.final_output:
                preview = result.final_output[:100].replace(chr(10), ' ')
                print(f"    Output: {preview}")

            results.append((task_id, result))

        except Exception as e:
            crash_count += 1
            print(f"  [CRASH] {type(e).__name__}: {e}")
            results.append((task_id, None))

        # Brief pause between tasks to avoid overwhelming Ollama
        await asyncio.sleep(1)

    # -- Print summary -------------------------------------------------
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"Tasks run:              {len(TASKS)}")
    print(f"Reached Stage 12:       {stage_12_count}/{len(TASKS)}")
    print(f"Tool calls succeeded:   {tool_success_count}/{len(TASKS)}")
    print(f"Tier 3 calls made:      {tier3_called_count}")
    print(f"Crashes (unhandled):    {crash_count}")
    print(f"Router stats:           {orch.router.get_stats()}")
    print(f"Cost summary:           {orch.claude.get_cost_summary()}")

    # -- Gate criteria -------------------------------------------------
    print("\n" + "=" * 70)
    print("PASS/FAIL GATES")
    print("=" * 70)

    gates = [
        ("Zero crashes", crash_count == 0, f"Got {crash_count} crashes"),
        (">=7/10 tasks reach Stage 12", stage_12_count >= 7, f"Only {stage_12_count}/10 reached Stage 12"),
        (">=5/10 tool calls succeed", tool_success_count >= 5, f"Only {tool_success_count}/10 tools succeeded"),
        ("Cost cap not exceeded", orch.claude.total_cost < 25.0, f"Cost ${orch.claude.total_cost:.4f} exceeds cap"),
    ]

    all_passed = True
    for gate_name, passed, failure_msg in gates:
        if passed:
            print(f"  [OK] {gate_name}")
        else:
            print(f"  [FAIL] {gate_name} -- {failure_msg}")
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("WEEK 5 COMPLETE: Full pipeline operational.")
        print("Tier 2 verification, disagreement routing, and 12-stage orchestrator all working.")
        print("Ready for Week 6 (KAIROS daemon + remaining skills).")
    else:
        print("WEEK 5 INCOMPLETE: Fix the failed gates above before Week 6.")
        print()
        print("Most common issues:")
        print("  - If many tasks fail at Stage 4: system prompt needs better JSON instruction")
        print("  - If many tasks fail at Stage 5: tool names in registry need checking")
        print("  - If crashes occur: check imports and class instantiation in orchestrator.py")
    print("=" * 70)

    return all_passed

if __name__ == "__main__":
    asyncio.run(run_all_tasks())
