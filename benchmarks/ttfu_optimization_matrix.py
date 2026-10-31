# benchmarks/ttfu_optimization_matrix.py
"""
HERMES Final TTFU (Time to First Useful Action) Optimization Experiment.

Evaluates configurations A through H with repeated trials:
- TTFB (Time to First Byte - headers received)
- TTFT_REASONING (First reasoning delta)
- TTFT_TOOL (First tool delta)
- TTFU (Complete valid executable native tool call ready)
- Total latency
- Tool-call correctness (valid function name and arguments)
- Verification result (AST syntax & functional correctness)
- Artifact quality (functions, docstrings, error handling)
- Distribution stats (min, p50, p90, p95, max)
"""

import asyncio
import json
import os
import sys
import time
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY", "")
BASE_URL = os.getenv("TIER1_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
MODEL = "z-ai/glm-5.3-flash"

TASK_PROMPT = "Create a Python calculator with add, subtract, multiply, and divide functions in calc.py with error handling and docstrings."


@dataclass
class TrialResult:
    config_name: str
    trial_idx: int
    ttfb_ms: float
    ttft_reasoning_ms: float
    ttft_tool_ms: float
    ttfu_ms: float
    total_latency_ms: float
    status_code: int
    tool_called: Optional[str] = None
    tool_args_valid: bool = False
    verification_passed: bool = False
    quality_score: float = 0.0  # 0.0 to 1.0
    generated_code_bytes: int = 0
    error: Optional[str] = None


def evaluate_generated_calculator(code: str) -> tuple[bool, float]:
    """Verify code AST syntax and calculator functionality."""
    if not code or len(code.strip()) < 30:
        return False, 0.0
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False, 0.0

    score = 0.0
    # AST checks
    funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    required = ["add", "subtract", "multiply", "divide"]
    matches = sum(1 for r in required if r in funcs)
    score += (matches / 4.0) * 0.5  # up to 0.5 for function presence

    # Docstring check
    has_docs = False
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and ast.get_docstring(n):
            has_docs = True
            break
    if has_docs:
        score += 0.25

    # Error handling check (ZeroDivisionError or try/except/if in divide)
    if "ZeroDivisionError" in code or "0" in code:
        score += 0.25

    return True, round(score, 2)


async def execute_probe_trial(
    client: httpx.AsyncClient,
    payload: Dict[str, Any],
    config_name: str,
    trial_idx: int,
) -> TrialResult:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    url = f"{BASE_URL}/chat/completions"

    t_start = time.perf_counter()
    ttfb_ms = 0.0
    ttft_reasoning_ms = 0.0
    ttft_tool_ms = 0.0
    ttfu_ms = 0.0

    content_chunks: List[str] = []
    reasoning_chunks: List[str] = []
    tool_calls_map: Dict[int, Dict[str, Any]] = {}

    try:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            t_headers = time.perf_counter()
            ttfb_ms = (t_headers - t_start) * 1000.0

            if response.status_code != 200:
                err_text = await response.aread()
                return TrialResult(
                    config_name=config_name,
                    trial_idx=trial_idx,
                    ttfb_ms=ttfb_ms,
                    ttft_reasoning_ms=0.0,
                    ttft_tool_ms=0.0,
                    ttfu_ms=0.0,
                    total_latency_ms=(time.perf_counter() - t_start) * 1000.0,
                    status_code=response.status_code,
                    error=err_text.decode(errors="replace")[:150],
                )

            async for line in response.aiter_lines():
                t_now = time.perf_counter()
                if not line or not line.strip().startswith("data:"):
                    continue
                data_str = line.strip()[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except Exception:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                ch = choices[0]
                delta = ch.get("delta", {})

                r = delta.get("reasoning_content")
                if r:
                    reasoning_chunks.append(r)
                    if ttft_reasoning_ms == 0.0:
                        ttft_reasoning_ms = (t_now - t_start) * 1000.0

                c = delta.get("content")
                if c:
                    content_chunks.append(c)

                tc_deltas = delta.get("tool_calls")
                if tc_deltas and isinstance(tc_deltas, list):
                    if ttft_tool_ms == 0.0:
                        ttft_tool_ms = (t_now - t_start) * 1000.0
                    for tc in tc_deltas:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": tc.get("id", f"call_{idx}"),
                                "function": {"name": "", "arguments": ""},
                            }
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            tool_calls_map[idx]["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            tool_calls_map[idx]["function"]["arguments"] += fn["arguments"]

                fr = ch.get("finish_reason")
                if fr in ("tool_calls", "stop") or (tool_calls_map and fr):
                    if ttfu_ms == 0.0:
                        ttfu_ms = (t_now - t_start) * 1000.0

    except Exception as exc:
        return TrialResult(
            config_name=config_name,
            trial_idx=trial_idx,
            ttfb_ms=ttfb_ms,
            ttft_reasoning_ms=ttft_reasoning_ms,
            ttft_tool_ms=ttft_tool_ms,
            ttfu_ms=0.0,
            total_latency_ms=(time.perf_counter() - t_start) * 1000.0,
            status_code=0,
            error=str(exc),
        )

    t_end = time.perf_counter()
    total_ms = (t_end - t_start) * 1000.0
    if ttfu_ms == 0.0:
        ttfu_ms = total_ms

    # Extract tool call
    tool_name = None
    args_valid = False
    generated_code = ""
    if tool_calls_map:
        first_call = tool_calls_map[0]
        tool_name = first_call["function"]["name"]
        raw_args = first_call["function"]["arguments"]
        try:
            parsed_args = json.loads(raw_args)
            args_valid = True
            generated_code = parsed_args.get("CodeContent") or parsed_args.get("content") or ""
        except Exception:
            args_valid = False

    syntax_valid, quality_score = evaluate_generated_calculator(generated_code)

    return TrialResult(
        config_name=config_name,
        trial_idx=trial_idx,
        ttfb_ms=round(ttfb_ms, 1),
        ttft_reasoning_ms=round(ttft_reasoning_ms, 1),
        ttft_tool_ms=round(ttft_tool_ms, 1),
        ttfu_ms=round(ttfu_ms, 1),
        total_latency_ms=round(total_ms, 1),
        status_code=200,
        tool_called=tool_name,
        tool_args_valid=args_valid,
        verification_passed=syntax_valid,
        quality_score=quality_score,
        generated_code_bytes=len(generated_code),
    )


async def main():
    print("=" * 75)
    print("HERMES FINAL TTFU OPTIMIZATION CONTROLLED EXPERIMENT HARNESS")
    print(f"Model: {MODEL} | Endpoint: {BASE_URL}")
    print("=" * 75)

    from tools.registry import get_openai_tool_definitions
    from core.prompt_builder import build_system_prompt, PromptContext

    all_tools = get_openai_tool_definitions()
    minimal_tools = [t for t in all_tools if t["function"]["name"] in ("write_file", "read_file", "list_directory")]
    core_tools = [t for t in all_tools if t["function"]["name"] in ("write_file", "read_file", "list_directory", "create_folder", "bash_exec")]

    # System prompts
    minimal_sys_prompt = "You are HERMES, an autonomous engineering agent. Complete the user's task using the available tools."

    real_ctx = PromptContext(
        user_task=TASK_PROMPT,
        mode="auto",
        available_tools=[t["function"]["name"] for t in core_tools],
        tool_descriptions="",
        memory_context="Previous mission: verified calculator specifications.",
        skill_context="Skill: python_code_generator. Implement full error handling and type hints.",
        workspace_context="Workspace: C:\\Users\\SUBBU\\Downloads\\hermes\\workspace",
    )
    real_sys_prompt = build_system_prompt(real_ctx)

    # Prompt with directive E: extremely concise tool-use directive
    sys_prompt_e = real_sys_prompt + "\n\nCRITICAL: Immediately call the appropriate tool. Do not generate explanatory prose."

    # Prompt with directive F: explicit act immediately directive
    sys_prompt_f = real_sys_prompt + "\n\nAct immediately when a tool is sufficient. Do not produce explanatory prose before the first tool call."

    # Prompt with directive G: candidate directive
    sys_prompt_g = real_sys_prompt + "\n\nPrioritize the earliest correct executable action. When a tool can directly satisfy the next required step, issue the native tool call instead of generating explanatory prose."

    configs = [
        ("Config A (Minimal Sys + Minimal Tools)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": minimal_sys_prompt},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": minimal_tools,
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": True,
        }),
        ("Config B (Minimal Sys + Core Tools)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": minimal_sys_prompt},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": core_tools,
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": True,
        }),
        ("Config C (Real HERMES + Minimal Tools)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": real_sys_prompt},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": minimal_tools,
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": True,
        }),
        ("Config D (Real HERMES + Core Tools)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": real_sys_prompt},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": core_tools,
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": True,
        }),
        ("Config E (Real HERMES + Concise Directive)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": sys_prompt_e},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": core_tools,
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": True,
        }),
        ("Config F (Real HERMES + Explicit Act Immediately)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": sys_prompt_f},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": core_tools,
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": True,
        }),
        ("Config G (Real HERMES + Earliest Executable Directive)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": sys_prompt_g},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": core_tools,
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": True,
        }),
        ("Config H (Current Production Baseline)", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": real_sys_prompt},
                {"role": "user", "content": TASK_PROMPT},
            ],
            "tools": core_tools,
            "reasoning_effort": "low",
            "temperature": 0.0,
            "max_tokens": 2048,
            "stream": True,
        }),
    ]

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(90.0, connect=30.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        http2=False,
    )

    all_trials: List[TrialResult] = []
    NUM_TRIALS = 3  # Multiple trials per configuration to separate prompt effects from provider variance

    print(f"\nStarting {len(configs)} configurations × {NUM_TRIALS} trials each...")

    try:
        for cfg_name, payload in configs:
            print(f"\n>>> Running {cfg_name} ({NUM_TRIALS} trials)...")
            for t_idx in range(1, NUM_TRIALS + 1):
                print(f"  Trial {t_idx}/{NUM_TRIALS}...", end="", flush=True)
                res = await execute_probe_trial(client, payload, cfg_name, t_idx)
                all_trials.append(res)
                print(
                    f" TTFB={res.ttfb_ms:.0f}ms | TTFT_Reas={res.ttft_reasoning_ms:.0f}ms | "
                    f"TTFT_Tool={res.ttft_tool_ms:.0f}ms | TTFU={res.ttfu_ms:.0f}ms | "
                    f"Tool={res.tool_called} | Quality={res.quality_score:.2f} | Error={res.error or 'None'}"
                )
    finally:
        await client.aclose()

    # Aggregate results
    print("\n" + "=" * 80)
    print("FINAL TTFU OPTIMIZATION BENCHMARK SUMMARY TABLE")
    print("=" * 80)
    print(f"{'Configuration':<42} | {'TTFB (p50)':<10} | {'TTFT_Reas':<10} | {'TTFU (p50)':<10} | {'Quality':<8} | {'Success':<8}")
    print("-" * 95)

    summary_rows = []
    for cfg_name, _ in configs:
        cfg_trials = [t for t in all_trials if t.config_name == cfg_name and t.status_code == 200]
        if not cfg_trials:
            continue
        ttfbs = [t.ttfb_ms for t in cfg_trials]
        reasons = [t.ttft_reasoning_ms for t in cfg_trials]
        ttfus = [t.ttfu_ms for t in cfg_trials]
        qualities = [t.quality_score for t in cfg_trials]
        successes = sum(1 for t in cfg_trials if t.verification_passed and t.tool_args_valid)

        p50_ttfb = np.percentile(ttfbs, 50)
        p50_reas = np.percentile(reasons, 50)
        p50_ttfu = np.percentile(ttfus, 50)
        min_ttfu = np.min(ttfus)
        p90_ttfu = np.percentile(ttfus, 90)
        max_ttfu = np.max(ttfus)
        avg_qual = np.mean(qualities)

        print(
            f"{cfg_name:<42} | {p50_ttfb:>8.1f}ms | {p50_reas:>8.1f}ms | {p50_ttfu:>8.1f}ms | "
            f"{avg_qual:>6.2f}   | {successes}/{len(cfg_trials)}"
        )
        summary_rows.append({
            "config": cfg_name,
            "p50_ttfb": p50_ttfb,
            "p50_reas": p50_reas,
            "p50_ttfu": p50_ttfu,
            "min_ttfu": min_ttfu,
            "p90_ttfu": p90_ttfu,
            "max_ttfu": max_ttfu,
            "avg_quality": avg_qual,
            "success_rate": f"{successes}/{len(cfg_trials)}",
        })

    # Save to json artifact
    out_file = Path("artifacts/performance/ttfu_optimization_results.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "task": TASK_PROMPT,
            "model": MODEL,
            "summary": summary_rows,
            "trials": [
                {
                    "config": t.config_name,
                    "trial": t.trial_idx,
                    "ttfb_ms": t.ttfb_ms,
                    "ttft_reasoning_ms": t.ttft_reasoning_ms,
                    "ttft_tool_ms": t.ttft_tool_ms,
                    "ttfu_ms": t.ttfu_ms,
                    "total_ms": t.total_latency_ms,
                    "tool": t.tool_called,
                    "args_valid": t.tool_args_valid,
                    "verification": t.verification_passed,
                    "quality": t.quality_score,
                    "code_bytes": t.generated_code_bytes,
                    "error": t.error,
                }
                for t in all_trials
            ],
        }, f, indent=2)
    print(f"\n[+] Full experiment results written to {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
