"""
Phase 3 Inference Runtime Benchmark Driver.
Executes standardized benchmark suite across Ollama and direct llama-cpp CUDA,
capturing full metrics, context scaling, and sustained stress analysis.
"""
import os
import sys
import json
import time
from pathlib import Path
from typing import List, Dict, Any

from benchmarks.inference_runtime_benchmark.system_info import get_system_snapshot
from benchmarks.inference_runtime_benchmark.metrics import NormalizedInferenceResult
from benchmarks.inference_runtime_benchmark.ollama_runner import OllamaBenchmarkRunner
from benchmarks.inference_runtime_benchmark.llama_cpp_runner import LlamaCppBenchmarkRunner

WORKSPACE = Path(__file__).resolve().parent.parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase3"
PROMPTS_FILE = WORKSPACE / "benchmarks" / "inference_prompts.json"

def run_ollama_benchmark(model: str = "deepseek-r1:8b", repetitions: int = 5) -> List[Dict[str, Any]]:
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        suite = json.load(f)["prompts"]

    runner = OllamaBenchmarkRunner()
    results = []

    print(f"\n============================================================")
    print(f" STARTING OLLAMA BENCHMARK: {model} ({repetitions} reps per prompt)")
    print(f"============================================================")

    # Cold run on Prompt A
    print(f"[Ollama] Running COLD start on PROMPT_A...")
    cold_res = runner.run_inference(model, suite[0], repetition=0, cold=True)
    results.append(cold_res.to_dict())
    print(f"  -> Cold Load: {cold_res.load_ms:.1f}ms | TTFT: {cold_res.ttft_ms:.1f}ms | Gen: {cold_res.tokens_per_second:.2f} tok/s | Total: {cold_res.total_latency_ms:.1f}ms")

    # Warm repetitions across all prompts
    for prompt_item in suite:
        pid = prompt_item["id"]
        print(f"\n[Ollama] Testing {pid} ({prompt_item['type']})...")
        for rep in range(1, repetitions + 1):
            res = runner.run_inference(model, prompt_item, repetition=rep, cold=False)
            results.append(res.to_dict())
            print(f"  Rep {rep}/{repetitions} | Load: {res.load_ms:.1f}ms | TTFT: {res.ttft_ms:.1f}ms | Gen: {res.tokens_per_second:.2f} tok/s ({res.generation_tokens} tok in {res.generation_ms:.1f}ms) | Total: {res.total_latency_ms:.1f}ms")

    return results

def run_llama_cpp_benchmark(repetitions: int = 5) -> List[Dict[str, Any]]:
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        suite = json.load(f)["prompts"]

    # Initialize runner
    runner = LlamaCppBenchmarkRunner()
    results = []

    print(f"\n============================================================")
    print(f" STARTING LLAMA-CPP CUDA BENCHMARK (Direct GGUF, {repetitions} reps)")
    print(f"============================================================")

    # Cold run on Prompt A
    print(f"[llama-cpp CUDA] Running COLD engine load on PROMPT_A...")
    cold_res = runner.run_inference(suite[0], repetition=0, cold=True)
    results.append(cold_res.to_dict())
    print(f"  -> Cold Init: {cold_res.load_ms:.1f}ms | TTFT: {cold_res.ttft_ms:.1f}ms | Gen: {cold_res.tokens_per_second:.2f} tok/s | Total: {cold_res.total_latency_ms:.1f}ms")

    # Warm repetitions
    for prompt_item in suite:
        pid = prompt_item["id"]
        print(f"\n[llama-cpp CUDA] Testing {pid} ({prompt_item['type']})...")
        for rep in range(1, repetitions + 1):
            res = runner.run_inference(prompt_item, repetition=rep, cold=False)
            results.append(res.to_dict())
            print(f"  Rep {rep}/{repetitions} | Load: {res.load_ms:.1f}ms | TTFT: {res.ttft_ms:.1f}ms | Gen: {res.tokens_per_second:.2f} tok/s ({res.generation_tokens} tok in {res.generation_ms:.1f}ms) | Total: {res.total_latency_ms:.1f}ms")

    runner.unload_engine()
    return results

def run_context_scaling_benchmark(model: str = "deepseek-r1:8b") -> List[Dict[str, Any]]:
    runner = OllamaBenchmarkRunner()
    context_lengths = [100, 500, 1000, 2000, 4000]
    results = []

    print(f"\n============================================================")
    print(f" STARTING CONTEXT SCALING BENCHMARK: {model}")
    print(f"============================================================")

    base_context = "HERMES is an autonomous agent architecture with hierarchical reasoning. " * 300

    for ctx_target in context_lengths:
        char_count = ctx_target * 4
        test_prompt = f"Summarize the following architecture notes in 2 sentences:\n{base_context[:char_count]}"
        prompt_item = {
            "id": f"CTX_{ctx_target}",
            "prompt": test_prompt,
            "system": "You are a precise technical summarizer.",
            "max_tokens": 100
        }
        res = runner.run_inference(model, prompt_item, repetition=1, cold=False, num_ctx=max(4096, ctx_target + 500))
        results.append({
            "target_prompt_tokens": ctx_target,
            "actual_prompt_tokens": res.prompt_tokens,
            "prompt_eval_ms": res.prompt_eval_ms,
            "prompt_eval_tok_per_sec": res.prompt_eval_tokens_per_sec,
            "ttft_ms": res.ttft_ms,
            "generation_tok_per_sec": res.tokens_per_second,
            "total_ms": res.total_latency_ms
        })
        print(f"  Ctx Target: {ctx_target:4d} | Actual P-Tokens: {res.prompt_tokens:4d} | Eval Time: {res.prompt_eval_ms:7.1f}ms | Prompt Tok/s: {res.prompt_eval_tokens_per_sec:6.1f} | TTFT: {res.ttft_ms:7.1f}ms")

    return results

def run_sustained_stress_test(model: str = "deepseek-r1:8b", iterations: int = 15) -> List[Dict[str, Any]]:
    runner = OllamaBenchmarkRunner()
    prompt_item = {
        "id": "SUSTAINED_STRESS",
        "prompt": "Write a Python script that calculates prime numbers using the Sieve of Eratosthenes up to 1,000,000 and includes performance benchmarks with timeit.",
        "system": "You are a Python performance expert.",
        "max_tokens": 300
    }
    results = []
    print(f"\n============================================================")
    print(f" STARTING SUSTAINED STRESS BENCHMARK: {model} ({iterations} iterations)")
    print(f"============================================================")

    for i in range(1, iterations + 1):
        res = runner.run_inference(model, prompt_item, repetition=i, cold=False)
        results.append({
            "iteration": i,
            "tok_per_sec": res.tokens_per_second,
            "gen_ms": res.generation_ms,
            "vram_after_mb": res.vram_after_mb,
            "total_ms": res.total_latency_ms
        })
        print(f"  Iter {i:02d}/{iterations:02d} | Gen Speed: {res.tokens_per_second:5.2f} tok/s | Gen Time: {res.generation_ms:7.1f}ms | VRAM: {res.vram_after_mb:.1f} MB")

    return results

def main():
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. System Info Snapshot
    print("Capturing system hardware and software snapshot...")
    sys_snap = get_system_snapshot()
    (PERF_DIR / "system_info.json").write_text(json.dumps(sys_snap, indent=2), encoding="utf-8")
    print(f"[OK] Saved {PERF_DIR / 'system_info.json'}")

    # 2. Ollama T1 Benchmark (DeepSeek-R1 8B)
    t1_results = run_ollama_benchmark(model="deepseek-r1:8b", repetitions=5)
    (PERF_DIR / "ollama_t1_results.json").write_text(json.dumps(t1_results, indent=2), encoding="utf-8")
    print(f"[OK] Saved {PERF_DIR / 'ollama_t1_results.json'}")

    # 3. Direct llama-cpp CUDA T1 Benchmark
    try:
        lcp_results = run_llama_cpp_benchmark(repetitions=5)
        (PERF_DIR / "llama_cpp_t1_results.json").write_text(json.dumps(lcp_results, indent=2), encoding="utf-8")
        print(f"[OK] Saved {PERF_DIR / 'llama_cpp_t1_results.json'}")
    except Exception as e:
        print(f"[WARNING] llama-cpp benchmark encountered error: {e}")

    # 4. Context Scaling Test
    ctx_results = run_context_scaling_benchmark(model="deepseek-r1:8b")
    (PERF_DIR / "context_scaling_results.json").write_text(json.dumps(ctx_results, indent=2), encoding="utf-8")
    print(f"[OK] Saved {PERF_DIR / 'context_scaling_results.json'}")

    # 5. Sustained Stress Test
    stress_results = run_sustained_stress_test(model="deepseek-r1:8b", iterations=15)
    (PERF_DIR / "sustained_stress_results.json").write_text(json.dumps(stress_results, indent=2), encoding="utf-8")
    print(f"[OK] Saved {PERF_DIR / 'sustained_stress_results.json'}")

    # 6. Ollama T2 Benchmark (Qwen3 8B)
    t2_results = run_ollama_benchmark(model="qwen3:8b", repetitions=3)
    (PERF_DIR / "ollama_t2_results.json").write_text(json.dumps(t2_results, indent=2), encoding="utf-8")
    print(f"[OK] Saved {PERF_DIR / 'ollama_t2_results.json'}")

    print("\n============================================================")
    print(" ALL BENCHMARK RUNS COMPLETED SUCCESSFULLY.")
    print("============================================================")

if __name__ == "__main__":
    main()
