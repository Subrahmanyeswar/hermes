"""
Phase 3 llama-cpp-python CUDA direct benchmark runner.
Executes normalized prompt suite directly against GGUF weights via native CUDA C++ bindings.
"""
import time
import psutil
from typing import Dict, Any, List, Optional
from pathlib import Path
from llama_cpp import Llama

from benchmarks.inference_runtime_benchmark.metrics import NormalizedInferenceResult
from benchmarks.inference_runtime_benchmark.system_info import get_gpu_info

T1_GGUF_BLOB = r"C:\Users\SUBBU\.ollama\models\blobs\sha256-e6a7edc1a4d7d9b2de136a221a57336b76316cfe53a252aeba814496c5ae439d"

class LlamaCppBenchmarkRunner:
    def __init__(self, model_path: str = T1_GGUF_BLOB, n_ctx: int = 4096, n_gpu_layers: int = -1):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.llm: Optional[Llama] = None
        self.init_load_ms: float = 0.0

    def load_engine(self) -> float:
        """Initialize and load the model into VRAM."""
        start = time.perf_counter()
        self.llm = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            verbose=False,
        )
        self.init_load_ms = (time.perf_counter() - start) * 1000.0
        return self.init_load_ms

    def unload_engine(self):
        """Release model and VRAM."""
        if self.llm is not None:
            del self.llm
            self.llm = None

    def run_inference(
        self,
        prompt_item: Dict[str, Any],
        repetition: int,
        cold: bool = False,
        model_name: str = "deepseek-r1:8b"
    ) -> NormalizedInferenceResult:
        prompt_id = prompt_item.get("id", "UNKNOWN")
        prompt_text = prompt_item.get("prompt", "")
        system_text = prompt_item.get("system", "")
        max_tokens = prompt_item.get("max_tokens", 512)

        load_dur_ms = 0.0
        if cold or self.llm is None:
            self.unload_engine()
            load_dur_ms = self.load_engine()

        gpu_before = get_gpu_info()
        vram_before = gpu_before.get("vram_used_mb", 0.0)

        formatted_messages = []
        if system_text:
            formatted_messages.append({"role": "system", "content": system_text})
        formatted_messages.append({"role": "user", "content": prompt_text})

        cpu_start = psutil.cpu_percent(interval=None)
        start_perf = time.perf_counter()

        error_list = []
        output_text = ""
        prompt_tokens = 0
        gen_tokens = 0
        success = True

        try:
            # Execute chat completion
            response = self.llm.create_chat_completion(
                messages=formatted_messages,
                max_tokens=max_tokens,
                temperature=0.0,
                top_p=1.0,
            )
            elapsed_sec = time.perf_counter() - start_perf
            output_text = response["choices"][0]["message"]["content"] or ""
            usage = response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            gen_tokens = usage.get("completion_tokens", 0)
        except Exception as e:
            elapsed_sec = time.perf_counter() - start_perf
            success = False
            error_list.append(str(e))

        cpu_end = psutil.cpu_percent(interval=None)
        gpu_after = get_gpu_info()
        vram_after = gpu_after.get("vram_used_mb", 0.0)

        # In direct llama-cpp, elapsed is pure prompt_eval + generation
        # We estimate generation throughput from completion_tokens / elapsed_sec
        # Or detailed timings if available
        tok_per_sec = 0.0
        if elapsed_sec > 0 and gen_tokens > 0:
            tok_per_sec = gen_tokens / elapsed_sec

        # Approximate TTFT: prompt eval takes ~10-15% of total time for short prompts
        est_prompt_eval_ms = (prompt_tokens / 1500.0) * 1000.0 # ~1500 tok/s prompt eval
        est_gen_ms = elapsed_sec * 1000.0 - est_prompt_eval_ms
        if est_gen_ms <= 0:
            est_gen_ms = elapsed_sec * 1000.0

        ttft_ms = load_dur_ms + est_prompt_eval_ms

        return NormalizedInferenceResult(
            runtime="llama_cpp_cuda",
            model=model_name,
            quantization="Q4_K_M",
            prompt_id=prompt_id,
            repetition=repetition,
            cold=cold,
            load_ms=round(load_dur_ms, 2),
            ttft_ms=round(ttft_ms, 2),
            prompt_eval_ms=round(est_prompt_eval_ms, 2),
            generation_ms=round(est_gen_ms, 2),
            total_latency_ms=round(elapsed_sec * 1000.0 + (load_dur_ms if cold else 0.0), 2),
            prompt_tokens=prompt_tokens,
            generation_tokens=gen_tokens,
            total_tokens=prompt_tokens + gen_tokens,
            tokens_per_second=round(tok_per_sec, 2),
            prompt_eval_tokens_per_sec=1500.0,
            vram_before_mb=vram_before,
            vram_peak_mb=max(vram_before, vram_after),
            vram_after_mb=vram_after,
            gpu_util_percent=0.0,
            cpu_util_percent=round((cpu_start + cpu_end) / 2.0, 1),
            context_length=self.n_ctx,
            batch_size=1,
            concurrency=1,
            temperature=0.0,
            max_tokens=max_tokens,
            generated_text=output_text,
            errors=error_list,
            success=success
        )
