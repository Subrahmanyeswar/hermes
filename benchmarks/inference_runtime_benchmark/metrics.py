"""
Normalized result schema and metrics models for Phase 3 inference benchmarking.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import json

@dataclass
class NormalizedInferenceResult:
    runtime: str                           # 'ollama' | 'llama_cpp_cuda' | 'tensorrt_llm'
    model: str                             # 'deepseek-r1:8b' | 'qwen3:8b'
    quantization: str                      # 'Q4_K_M'
    prompt_id: str                         # 'PROMPT_A', 'PROMPT_B', etc.
    repetition: int                        # 1..N
    cold: bool                             # True for first cold run, False for warm
    
    # Latency & Duration Metrics (milliseconds)
    load_ms: float = 0.0                   # Model/engine load time
    ttft_ms: float = 0.0                   # Time to first token (load + prompt eval)
    prompt_eval_ms: float = 0.0            # Prompt processing duration
    generation_ms: float = 0.0             # Output token generation duration
    total_latency_ms: float = 0.0          # End-to-end request duration
    
    # Token Counts & Throughput
    prompt_tokens: int = 0
    generation_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0         # Generation throughput (gen_tokens / gen_sec)
    prompt_eval_tokens_per_sec: float = 0.0 # Prompt processing throughput
    
    # Hardware Utilization & Memory
    vram_before_mb: float = 0.0
    vram_peak_mb: float = 0.0
    vram_after_mb: float = 0.0
    gpu_util_percent: float = 0.0
    cpu_util_percent: float = 0.0
    
    # Execution Metadata
    context_length: int = 4096
    batch_size: int = 1
    concurrency: int = 1
    temperature: float = 0.0
    max_tokens: int = 512
    generated_text: str = ""
    errors: List[str] = field(default_factory=list)
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
