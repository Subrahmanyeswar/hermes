# benchmarks/model_lifecycle_benchmark.py
# Dedicated Model Lifecycle & Residency Benchmark for HERMES Phase 2.
# Accurately measures:
# 1. Cold vs Warm load durations (reported in ns by Ollama API)
# 2. Time-To-First-Token (TTFT) / Prompt Eval duration
# 3. Generation (Eval) duration & tokens/second
# 4. Total request latency
# 5. Switching overhead (T1 -> T2, T2 -> T1)
# 6. Repeated same-model runs (T1x3, T2x3)
# 7. Alternating cycles (T1 -> T2 -> T1 -> T2)
# 8. VRAM usage & resident model state via /api/ps and nvidia-smi

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# Ensure workspace is in python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.model_config import (
    TIER1_MODEL,
    TIER2_MODEL,
    MODEL_KEEP_ALIVE,
)

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
CONTROLLED_PROMPT = "Respond with ONLY the JSON object: {\"status\": \"ok\", \"code\": 200}"
SYSTEM_PROMPT = "You are a concise JSON generator. Output only valid JSON."


def get_gpu_vram() -> Dict[str, float]:
    """Query nvidia-smi for VRAM usage."""
    res = {"vram_used_mb": 0.0, "vram_free_mb": 0.0, "vram_total_mb": 0.0, "gpu_util": 0.0}
    try:
        smi = shutil.which("nvidia-smi")
        if smi:
            out = subprocess.check_output(
                [
                    smi,
                    "--query-gpu=memory.used,memory.free,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                encoding="utf-8",
                timeout=2.0,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ).strip()
            if out:
                parts = [p.strip() for p in out.split(",")]
                if len(parts) >= 4:
                    res["vram_used_mb"] = float(parts[0])
                    res["vram_free_mb"] = float(parts[1])
                    res["vram_total_mb"] = float(parts[2])
                    res["gpu_util"] = float(parts[3])
    except Exception:
        pass
    return res


def get_resident_models() -> List[Dict[str, Any]]:
    """Query Ollama /api/ps for currently resident models."""
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{OLLAMA_BASE_URL}/api/ps")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("models", [])
    except Exception:
        pass
    return []


def unload_all_models():
    """Unload all models by sending keep_alive=0 to all active models."""
    try:
        active = get_resident_models()
        with httpx.Client(timeout=10.0) as client:
            for m in active:
                name = m.get("name", "")
                if name:
                    client.post(
                        f"{OLLAMA_BASE_URL}/api/generate",
                        json={"model": name, "keep_alive": 0}
                    )
            # Also explicitly ensure T1 and T2 are unloaded
            client.post(f"{OLLAMA_BASE_URL}/api/generate", json={"model": TIER1_MODEL, "keep_alive": 0})
            client.post(f"{OLLAMA_BASE_URL}/api/generate", json={"model": TIER2_MODEL, "keep_alive": 0})
    except Exception:
        pass
    time.sleep(1.0)


async def run_single_inference(
    model: str,
    prompt: str = CONTROLLED_PROMPT,
    system: str = SYSTEM_PROMPT,
    keep_alive: Any = MODEL_KEEP_ALIVE,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Execute a single inference and capture precise timing and VRAM metrics."""
    vram_before = get_gpu_vram()
    resident_before = [m.get("name") for m in get_resident_models()]

    body = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "keep_alive": keep_alive,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": 4096,
        },
    }

    start_perf = time.perf_counter()
    should_close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(180.0))
        should_close_client = True

    try:
        resp = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=body)
        elapsed_sec = time.perf_counter() - start_perf
        data = resp.json()
    finally:
        if should_close_client:
            await client.aclose()

    vram_after = get_gpu_vram()
    resident_after = [m.get("name") for m in get_resident_models()]

    # Extract nanosecond durations from Ollama API
    load_dur_ms = (data.get("load_duration", 0) or 0) / 1_000_000.0
    prompt_eval_dur_ms = (data.get("prompt_eval_duration", 0) or 0) / 1_000_000.0
    eval_dur_ms = (data.get("eval_duration", 0) or 0) / 1_000_000.0
    prompt_tokens = data.get("prompt_eval_count", 0) or 0
    eval_tokens = data.get("eval_count", 0) or 0
    total_tokens = prompt_tokens + eval_tokens

    tok_per_sec = 0.0
    if eval_dur_ms > 0:
        tok_per_sec = eval_tokens / (eval_dur_ms / 1000.0)

    # Determine residency state
    is_resident_before = any(model in str(r) for r in resident_before)
    is_resident_after = any(model in str(r) for r in resident_after)

    state = "WARM" if (is_resident_before and load_dur_ms < 50.0) else "COLD"
    if not is_resident_before and is_resident_after:
        state = "LOADED_COLD"
    elif is_resident_before and load_dur_ms >= 50.0:
        state = "RELOADED"

    return {
        "model": model,
        "state": state,
        "load_duration_ms": round(load_dur_ms, 2),
        "prompt_eval_duration_ms": round(prompt_eval_dur_ms, 2),
        "eval_duration_ms": round(eval_dur_ms, 2),
        "ttft_ms": round(load_dur_ms + prompt_eval_dur_ms, 2),
        "total_latency_ms": round(elapsed_sec * 1000.0, 2),
        "prompt_tokens": prompt_tokens,
        "eval_tokens": eval_tokens,
        "total_tokens": total_tokens,
        "tokens_per_second": round(tok_per_sec, 2),
        "vram_before_mb": vram_before["vram_used_mb"],
        "vram_after_mb": vram_after["vram_used_mb"],
        "vram_delta_mb": round(vram_after["vram_used_mb"] - vram_before["vram_used_mb"], 1),
        "resident_models_before": resident_before,
        "resident_models_after": resident_after,
        "response_preview": data.get("response", "")[:100].strip(),
    }


async def run_lifecycle_benchmark(keep_alive_setting: str = MODEL_KEEP_ALIVE) -> Dict[str, Any]:
    """Run the complete 10-step lifecycle benchmark suite."""
    print("=" * 75)
    print(f"STARTING LIFECYCLE BENCHMARK (keep_alive={keep_alive_setting})")
    print("=" * 75)

    results: Dict[str, Any] = {}

    # ──────────────────────────────────────────────────────────────────
    # Step 1: Force clean state -> Measure Cold T1
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 1] Measuring Cold Tier 1 (DeepSeek-R1 8B)...")
    unload_all_models()
    t1_cold = await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    results["1_t1_cold"] = t1_cold
    print(f"   State: {t1_cold['state']} | Total: {t1_cold['total_latency_ms']}ms | Load: {t1_cold['load_duration_ms']}ms | TTFT: {t1_cold['ttft_ms']}ms | VRAM: {t1_cold['vram_after_mb']}MB")

    # ──────────────────────────────────────────────────────────────────
    # Step 2: Measure Warm T1 (consecutive same model)
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 2] Measuring Warm Tier 1 (DeepSeek-R1 8B)...")
    t1_warm = await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    results["2_t1_warm"] = t1_warm
    print(f"   State: {t1_warm['state']} | Total: {t1_warm['total_latency_ms']}ms | Load: {t1_warm['load_duration_ms']}ms | TTFT: {t1_warm['ttft_ms']}ms | VRAM: {t1_warm['vram_after_mb']}MB")

    # ──────────────────────────────────────────────────────────────────
    # Step 3: Force clean state -> Measure Cold T2
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 3] Measuring Cold Tier 2 (Qwen3 8B)...")
    unload_all_models()
    t2_cold = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    results["3_t2_cold"] = t2_cold
    print(f"   State: {t2_cold['state']} | Total: {t2_cold['total_latency_ms']}ms | Load: {t2_cold['load_duration_ms']}ms | TTFT: {t2_cold['ttft_ms']}ms | VRAM: {t2_cold['vram_after_mb']}MB")

    # ──────────────────────────────────────────────────────────────────
    # Step 4: Measure Warm T2 (consecutive same model)
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 4] Measuring Warm Tier 2 (Qwen3 8B)...")
    t2_warm = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    results["4_t2_warm"] = t2_warm
    print(f"   State: {t2_warm['state']} | Total: {t2_warm['total_latency_ms']}ms | Load: {t2_warm['load_duration_ms']}ms | TTFT: {t2_warm['ttft_ms']}ms | VRAM: {t2_warm['vram_after_mb']}MB")

    # ──────────────────────────────────────────────────────────────────
    # Step 5 & 6: Switching T1 -> T2 and T2 -> T1
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 5] Switch T1 -> T2 (Load T1 then call T2)...")
    unload_all_models()
    await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    t1_to_t2 = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    results["5_switch_t1_to_t2"] = t1_to_t2
    print(f"   State: {t1_to_t2['state']} | Total: {t1_to_t2['total_latency_ms']}ms | Load: {t1_to_t2['load_duration_ms']}ms | VRAM: {t1_to_t2['vram_after_mb']}MB | Active models: {t1_to_t2['resident_models_after']}")

    print("\n[Step 6] Switch T2 -> T1 (Call T1 immediately after T2)...")
    t2_to_t1 = await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    results["6_switch_t2_to_t1"] = t2_to_t1
    print(f"   State: {t2_to_t1['state']} | Total: {t2_to_t1['total_latency_ms']}ms | Load: {t2_to_t1['load_duration_ms']}ms | VRAM: {t2_to_t1['vram_after_mb']}MB | Active models: {t2_to_t1['resident_models_after']}")

    # ──────────────────────────────────────────────────────────────────
    # Step 7: Repeated T1 (T1 -> T1 -> T1)
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 7] Repeated T1 Requests (T1 x 3)...")
    t1_rep1 = await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    t1_rep2 = await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    results["7_t1_rep1"] = t1_rep1
    results["7_t1_rep2"] = t1_rep2
    print(f"   Rep 1: Load={t1_rep1['load_duration_ms']}ms | Total={t1_rep1['total_latency_ms']}ms | VRAM={t1_rep1['vram_after_mb']}MB")
    print(f"   Rep 2: Load={t1_rep2['load_duration_ms']}ms | Total={t1_rep2['total_latency_ms']}ms | VRAM={t1_rep2['vram_after_mb']}MB")

    # ──────────────────────────────────────────────────────────────────
    # Step 8: Repeated T2 (T2 -> T2 -> T2)
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 8] Repeated T2 Requests (T2 x 3)...")
    t2_rep1 = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    t2_rep2 = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    t2_rep3 = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    results["8_t2_rep1"] = t2_rep1
    results["8_t2_rep2"] = t2_rep2
    results["8_t2_rep3"] = t2_rep3
    print(f"   Rep 1: Load={t2_rep1['load_duration_ms']}ms | Total={t2_rep1['total_latency_ms']}ms")
    print(f"   Rep 2: Load={t2_rep2['load_duration_ms']}ms | Total={t2_rep2['total_latency_ms']}ms")
    print(f"   Rep 3: Load={t2_rep3['load_duration_ms']}ms | Total={t2_rep3['total_latency_ms']}ms")

    # ──────────────────────────────────────────────────────────────────
    # Step 9: Alternating Stress Cycle (T1 -> T2 -> T1 -> T2)
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 9] Alternating Council Cycle (T1 -> T2 -> T1 -> T2)...")
    alt_t1_1 = await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    alt_t2_1 = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    alt_t1_2 = await run_single_inference(TIER1_MODEL, keep_alive=keep_alive_setting)
    alt_t2_2 = await run_single_inference(TIER2_MODEL, keep_alive=keep_alive_setting)
    results["9_alt_t1_1"] = alt_t1_1
    results["9_alt_t2_1"] = alt_t2_1
    results["9_alt_t1_2"] = alt_t1_2
    results["9_alt_t2_2"] = alt_t2_2
    print(f"   Cycle 1 T1: Load={alt_t1_1['load_duration_ms']}ms | Total={alt_t1_1['total_latency_ms']}ms | VRAM={alt_t1_1['vram_after_mb']}MB")
    print(f"   Cycle 1 T2: Load={alt_t2_1['load_duration_ms']}ms | Total={alt_t2_1['total_latency_ms']}ms | VRAM={alt_t2_1['vram_after_mb']}MB")
    print(f"   Cycle 2 T1: Load={alt_t1_2['load_duration_ms']}ms | Total={alt_t1_2['total_latency_ms']}ms | VRAM={alt_t1_2['vram_after_mb']}MB")
    print(f"   Cycle 2 T2: Load={alt_t2_2['load_duration_ms']}ms | Total={alt_t2_2['total_latency_ms']}ms | VRAM={alt_t2_2['vram_after_mb']}MB")

    # ──────────────────────────────────────────────────────────────────
    # Step 10: Coexistence Assessment
    # ──────────────────────────────────────────────────────────────────
    print("\n[Step 10] Checking Final Resident Models in VRAM...")
    resident_final = get_resident_models()
    gpu_final = get_gpu_vram()
    results["10_resident_final"] = resident_final
    results["10_gpu_final"] = gpu_final
    print(f"   Final Resident Count: {len(resident_final)}")
    for m in resident_final:
        print(f"     - {m.get('name')}: size_vram={m.get('size_vram', 0)/(1024*1024):.1f}MB, expires_at={m.get('expires_at')}")
    print(f"   Final GPU VRAM Used: {gpu_final['vram_used_mb']}MB / {gpu_final['vram_total_mb']}MB")

    # Save to json file
    out_dir = Path("performance")
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_tag = str(keep_alive_setting).replace(":", "_")
    out_file = out_dir / f"model_lifecycle_results_{clean_tag}.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[+] Saved detailed lifecycle results to {out_file}")

    return results


if __name__ == "__main__":
    asyncio.run(run_lifecycle_benchmark())
