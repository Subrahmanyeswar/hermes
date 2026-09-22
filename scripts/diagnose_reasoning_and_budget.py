import asyncio
import json
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from core.prompt_builder import PromptContext, build_system_prompt, build_user_message
from core.response_parser import ResponseParser
from tools.registry import list_tools, tool_schema_for_prompt
from config.model_config import TIER1_MODEL, MODEL_KEEP_ALIVE

async def run_experiments():
    task_text = "Create performance_reasoning_probe.py containing: def answer(): return 42"
    
    ctx = PromptContext(
        user_task=task_text,
        mode="auto",
        available_tools=list_tools(),
        tool_descriptions=tool_schema_for_prompt(),
        memory_context="",
        skill_context="",
        active_skill_name="none",
        workspace_context="Workspace: generated_projects/ (default)",
    )
    system_prompt = build_system_prompt(ctx)
    user_message = build_user_message(task_text)
    parser = ResponseParser()
    client = httpx.AsyncClient(timeout=300.0)
    url = "http://127.0.0.1:11434/api/generate"

    results = {
        "task": task_text,
        "system_prompt_chars": len(system_prompt),
        "user_message_chars": len(user_message),
        "budget_experiments": {},
        "think_experiments": {}
    }

    # Warm up model first
    print("Warming up T1...")
    await client.post(url, json={"model": TIER1_MODEL, "prompt": "hi", "stream": False, "options": {"num_predict": 10}})

    # Part 9: Controlled reasoning budget experiments
    budgets = [
        ("Config_A_1536", 1536),
        ("Config_B_512", 512),
        ("Config_C_1024", 1024),
    ]

    for config_name, num_predict in budgets:
        print(f"\n--- Running Part 9: {config_name} (num_predict={num_predict}) ---", flush=True)
        t0 = time.perf_counter()
        resp = await client.post(url, json={
            "model": TIER1_MODEL,
            "system": system_prompt,
            "prompt": user_message,
            "stream": False,
            "keep_alive": MODEL_KEEP_ALIVE,
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
                "num_predict": num_predict
            }
        })
        wall_s = time.perf_counter() - t0
        data = resp.json()
        raw_text = data.get("response", "")
        
        load_ms = data.get("load_duration", 0) / 1e6
        prefill_ms = data.get("prompt_eval_duration", 0) / 1e6
        eval_ms = data.get("eval_duration", 0) / 1e6
        prompt_tokens = data.get("prompt_eval_count", 0)
        eval_tokens = data.get("eval_count", 0)
        
        has_think_tag = "<think>" in raw_text
        has_close_think = "</think>" in raw_text
        think_text = ""
        if has_think_tag and has_close_think:
            think_text = raw_text.split("</think>")[0].replace("<think>", "").strip()
            final_text = raw_text.split("</think>")[1].strip()
        elif has_think_tag and not has_close_think:
            think_text = raw_text.replace("<think>", "").strip()
            final_text = ""
        else:
            final_text = raw_text.strip()
            
        parsed = parser.parse(raw_text)
        parse_success = hasattr(parsed, "to_dict")
        tool_name = parsed.tool if parse_success else None
        method_used = parsed.method_used if parse_success else getattr(parsed, "failure_reason", "unknown")
        
        results["budget_experiments"][config_name] = {
            "num_predict": num_predict,
            "wall_s": wall_s,
            "load_ms": load_ms,
            "prefill_ms": prefill_ms,
            "eval_ms": eval_ms,
            "prompt_tokens": prompt_tokens,
            "eval_tokens": eval_tokens,
            "tok_per_sec": (eval_tokens / (eval_ms / 1000.0)) if eval_ms > 0 else 0,
            "has_think_tag": has_think_tag,
            "has_close_think": has_close_think,
            "thinking_char_len": len(think_text),
            "final_text_char_len": len(final_text),
            "parse_success": parse_success,
            "parsed_tool": tool_name,
            "method_used": method_used,
            "raw_preview": raw_text[:200]
        }
        print(f"{config_name}: Wall={wall_s:.2f}s | EvalTokens={eval_tokens} | ThinkClosed={has_close_think} | ParseSuccess={parse_success} ({method_used})", flush=True)

    # Part 10: Thinking disable experiment (diagnostic only)
    print("\n--- Running Part 10: Think Enabled vs Think Disabled ---", flush=True)
    for think_val in [True, False]:
        lbl = "think_true" if think_val else "think_false"
        print(f"Testing {lbl}...", flush=True)
        t0 = time.perf_counter()
        payload = {
            "model": TIER1_MODEL,
            "system": system_prompt,
            "prompt": user_message,
            "stream": False,
            "keep_alive": MODEL_KEEP_ALIVE,
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
                "num_predict": 1024
            }
        }
        if not think_val:
            payload["think"] = False
        
        resp = await client.post(url, json=payload)
        wall_s = time.perf_counter() - t0
        data = resp.json()
        raw_text = data.get("response", "")
        
        load_ms = data.get("load_duration", 0) / 1e6
        prefill_ms = data.get("prompt_eval_duration", 0) / 1e6
        eval_ms = data.get("eval_duration", 0) / 1e6
        prompt_tokens = data.get("prompt_eval_count", 0)
        eval_tokens = data.get("eval_count", 0)
        
        has_think_tag = "<think>" in raw_text
        has_close_think = "</think>" in raw_text
        
        parsed = parser.parse(raw_text)
        parse_success = hasattr(parsed, "to_dict")
        tool_name = parsed.tool if parse_success else None
        method_used = parsed.method_used if parse_success else getattr(parsed, "failure_reason", "unknown")
        
        results["think_experiments"][lbl] = {
            "think_flag": think_val,
            "wall_s": wall_s,
            "load_ms": load_ms,
            "prefill_ms": prefill_ms,
            "eval_ms": eval_ms,
            "prompt_tokens": prompt_tokens,
            "eval_tokens": eval_tokens,
            "tok_per_sec": (eval_tokens / (eval_ms / 1000.0)) if eval_ms > 0 else 0,
            "has_think_tag": has_think_tag,
            "has_close_think": has_close_think,
            "raw_len": len(raw_text),
            "parse_success": parse_success,
            "parsed_tool": tool_name,
            "method_used": method_used,
            "raw_preview": raw_text[:200]
        }
        print(f"{lbl}: Wall={wall_s:.2f}s | EvalTokens={eval_tokens} | HasThink={has_think_tag} | ParseSuccess={parse_success} ({method_used})", flush=True)

    out_path = Path("artifacts/performance/reasoning_budget_experiments.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved experiments to {out_path}", flush=True)

if __name__ == "__main__":
    asyncio.run(run_experiments())
