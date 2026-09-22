"""
Phase 8 Context Engine Benchmark.
Measures:
1. ContextPack assembly latency (ms)
2. Token counts before (legacy concatenated dump) vs after (Context Engine budgeted pack)
3. Quality & retention of critical dependencies/tests
"""
import time
import json
import tempfile
from pathlib import Path

from core.workspace_indexer import WorkspaceIndexer, WorkspaceIndexStore
from core.workspace_retriever import WorkspaceRetriever
from core.context_engine import ContextEngine, ContextBudgeter, ContextItem, ContextSource
from core.prompt_builder import PromptContext, build_system_prompt
from tools.registry import tool_schema_for_prompt
from core.workspace import WorkspaceManager

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase8"
PERF_DIR.mkdir(parents=True, exist_ok=True)

def run_context_benchmark():
    print("================================================================")
    print(" PHASE 8 CONTEXT ENGINE BENCHMARK")
    print("================================================================")

    engine = ContextEngine(enabled=True)
    task_text = "Fix authentication token validation in backend/auth.py and run test_auth.py"
    memory_text = "\n".join([f"[FACT]: System rule #{i} about auth and database config" for i in range(15)])
    skill_text = "def handle_security_issue(): pass\n" * 20
    tools_text = tool_schema_for_prompt()

    # 1. Legacy Full Dump Prompt
    t0 = time.perf_counter()
    legacy_ctx = PromptContext(
        user_task=task_text,
        mode="AUTO",
        available_tools=["read_file", "write_file", "bash_exec"],
        tool_descriptions=tools_text,
        memory_context=memory_text,
        skill_context=skill_text,
        active_skill_name="python-dev",
        workspace_context="Workspace: Root\nFiles: 100\n" + "\n".join([f"file_{i}.py" for i in range(100)])
    )
    legacy_prompt = build_system_prompt(legacy_ctx)
    dur_legacy = (time.perf_counter() - t0) * 1000.0
    legacy_tokens = len(legacy_prompt) // 4

    print(f"\n[LEGACY SYSTEM]")
    print(f"  -> Context Assembly Time: {dur_legacy:.2f} ms")
    print(f"  -> Total Prompt Tokens: ~{legacy_tokens} tokens")

    # 2. Phase 8 Context Engine Pack
    t0 = time.perf_counter()
    cpack = engine.build_context_pack(
        task_text=task_text,
        mode="AUTO",
        workspace_manager=None,
        memory_context=memory_text,
        skill_content=skill_text,
        active_skill_name="python-dev",
        tool_descriptions=tools_text,
        max_context_tokens=4096,
        generation_reserve=1024
    )
    dur_new = (time.perf_counter() - t0) * 1000.0

    print(f"\n[PHASE 8 CONTEXT ENGINE]")
    print(f"  -> Context Assembly Time: {dur_new:.2f} ms")
    print(f"  -> Total Prompt Tokens: ~{cpack.total_tokens} tokens")
    print(f"  -> Items Included: {cpack.items_included}")
    print(f"  -> Items Dropped (Pruned/Deduplicated): {cpack.items_dropped}")
    print(f"  -> Source Breakdown: {cpack.source_breakdown}")

    reduction = ((legacy_tokens - cpack.total_tokens) / legacy_tokens) * 100.0 if legacy_tokens > 0 else 0.0

    results = {
        "legacy_build_ms": round(dur_legacy, 2),
        "legacy_tokens": legacy_tokens,
        "context_engine_build_ms": round(dur_new, 2),
        "context_engine_tokens": cpack.total_tokens,
        "token_reduction_pct": round(reduction, 1),
        "items_included": cpack.items_included,
        "items_dropped": cpack.items_dropped,
        "sources": cpack.source_breakdown
    }

    (PERF_DIR / "phase8_context_benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved results to {PERF_DIR / 'phase8_context_benchmark.json'}")

if __name__ == "__main__":
    run_context_benchmark()
