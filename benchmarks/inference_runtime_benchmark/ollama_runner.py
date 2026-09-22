"""
Phase 3 Ollama Inference Benchmark Runner.
Executes normalized prompt suite against the Ollama HTTP API with full hardware tracking.
"""
import time
import httpx
import psutil
from typing import Dict, Any, List
from benchmarks.inference_runtime_benchmark.metrics import NormalizedInferenceResult
from benchmarks.inference_runtime_benchmark.system_info import get_gpu_info

class OllamaBenchmarkRunner:
    def __init__(self, base_url: str = "http://localhost:11434", timeout_sec: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_sec))

    def unload_model(self, model: str) -> bool:
        try:
            resp = self.client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "keep_alive": 0, "prompt": "", "stream": False},
                timeout=httpx.Timeout(15.0)
            )
            return resp.status_code == 200
        except Exception:
            return False

    def preload_model(self, model: str, keep_alive: str = "300s") -> bool:
        try:
            resp = self.client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "keep_alive": keep_alive, "prompt": "", "stream": False},
                timeout=httpx.Timeout(self.timeout_sec)
            )
            return resp.status_code == 200
        except Exception:
            return False

    def run_inference(
        self,
        model: str,
        prompt_item: Dict[str, Any],
        repetition: int,
        cold: bool = False,
        keep_alive: str = "300s",
        num_ctx: int = 4096,
        temperature: float = 0.0,
    ) -> NormalizedInferenceResult:
        prompt_id = prompt_item.get("id", "UNKNOWN")
        prompt_text = prompt_item.get("prompt", "")
        system_text = prompt_item.get("system", "")
        max_tokens = prompt_item.get("max_tokens", 512)

        if cold:
            self.unload_model(model)
            time.sleep(1.0)

        gpu_before = get_gpu_info()
        vram_before = gpu_before.get("vram_used_mb", 0.0)

        body = {
            "model": model,
            "prompt": prompt_text,
            "system": system_text,
            "keep_alive": keep_alive,
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": 1.0,
                "top_k": 0,
            }
        }

        url = f"{self.base_url}/api/generate"
        cpu_start = psutil.cpu_percent(interval=None)
        start_perf = time.perf_counter()

        error_list = []
        data = {}
        success = True

        try:
            resp = self.client.post(url, json=body)
            elapsed_sec = time.perf_counter() - start_perf
            if resp.status_code == 200:
                data = resp.json()
            else:
                success = False
                error_list.append(f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            elapsed_sec = time.perf_counter() - start_perf
            success = False
            error_list.append(str(e))

        cpu_end = psutil.cpu_percent(interval=None)
        gpu_after = get_gpu_info()
        vram_after = gpu_after.get("vram_used_mb", 0.0)

        load_dur_ms = (data.get("load_duration", 0) or 0) / 1_000_000.0
        prompt_eval_dur_ms = (data.get("prompt_eval_duration", 0) or 0) / 1_000_000.0
        eval_dur_ms = (data.get("eval_duration", 0) or 0) / 1_000_000.0
        prompt_tokens = data.get("prompt_eval_count", 0) or 0
        eval_tokens = data.get("eval_count", 0) or 0
        total_tokens = prompt_tokens + eval_tokens

        tok_per_sec = 0.0
        if eval_dur_ms > 0:
            tok_per_sec = eval_tokens / (eval_dur_ms / 1000.0)

        prompt_eval_tok_per_sec = 0.0
        if prompt_eval_dur_ms > 0:
            prompt_eval_tok_per_sec = prompt_tokens / (prompt_eval_dur_ms / 1000.0)

        ttft_ms = load_dur_ms + prompt_eval_dur_ms

        return NormalizedInferenceResult(
            runtime="ollama",
            model=model,
            quantization="Q4_K_M",
            prompt_id=prompt_id,
            repetition=repetition,
            cold=cold,
            load_ms=round(load_dur_ms, 2),
            ttft_ms=round(ttft_ms, 2),
            prompt_eval_ms=round(prompt_eval_dur_ms, 2),
            generation_ms=round(eval_dur_ms, 2),
            total_latency_ms=round(elapsed_sec * 1000.0, 2),
            prompt_tokens=prompt_tokens,
            generation_tokens=eval_tokens,
            total_tokens=total_tokens,
            tokens_per_second=round(tok_per_sec, 2),
            prompt_eval_tokens_per_sec=round(prompt_eval_tok_per_sec, 2),
            vram_before_mb=vram_before,
            vram_peak_mb=max(vram_before, vram_after),
            vram_after_mb=vram_after,
            gpu_util_percent=gpu_after.get("gpu_util_percent", 0.0) if "gpu_util_percent" in gpu_after else 0.0,
            cpu_util_percent=round((cpu_start + cpu_end) / 2.0, 1),
            context_length=num_ctx,
            batch_size=1,
            concurrency=1,
            temperature=temperature,
            max_tokens=max_tokens,
            generated_text=data.get("response", ""),
            errors=error_list,
            success=success
        )
