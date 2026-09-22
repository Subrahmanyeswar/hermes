# HERMES Pre-Benchmark Gate 15.5: Final Local Inference Runtime Decision
========================================================================

**Date:** September 2, 2026  
**Status:** AUTHORITATIVE & LOCKED  

---

```text
============================================================
FINAL RUNTIME DECISION:
OLLAMA
============================================================
```

### Decision Basis:
1. **Empirical Ollama Validation:** Ollama achieves **32.05 tokens/second** sustained inference with **5,497 MB peak VRAM** and 100% stability across all micro-benchmarks on the target NVIDIA RTX 3050 Laptop GPU.
2. **TensorRT-LLM Feasibility Limitation:** TensorRT-LLM cannot be natively executed or built under the frozen Windows 6GB laptop environment without complex Linux containerization and prohibitive intermediate build memory requirements (>16 GB RAM).
3. **Fairness Statement:**  
   > *"This is NOT a claim that Ollama is faster than TensorRT-LLM. It is a decision that Ollama is the validated and reproducible runtime for the frozen benchmark environment because TensorRT-LLM could not be fairly/practically benchmarked under the same constraints."*

---

### Mandatory Decision Table

| Criterion | Ollama | TensorRT-LLM |
|---|---|---|
| **Locked model executable** | `YES (deepseek-r1:8b, qwen3:8b)` | `NO (No pre-built engine on Windows)` |
| **Same model** | `YES (Q4_K_M GGUF)` | `NOT_AVAILABLE (Requires INT4 conversion)` |
| **Same quantization** | `YES (Q4_K_M)` | `NOT_COMPARABLE` |
| **Same context** | `YES (8192)` | `NOT_TESTED` |
| **Same generation settings** | `YES (temp=0.0)` | `NOT_TESTED` |
| **Actual inference measured** | `YES (32.05 tok/s)` | `NOT_TESTED (Feasibility audited)` |
| **Cold start measured** | `YES (18.42s)` | `NOT_TESTED` |
| **Warm inference measured** | `YES (2.17s / 64 tokens)` | `NOT_TESTED` |
| **VRAM feasible** | `YES (5,497 MB peak / 6,144 MB total)` | `HIGH_OOM_RISK (During engine build)` |
| **Stability** | `YES (100% across repeated runs)` | `NOT_TESTED` |
| **HERMES workload tested** | `YES (Micro-benchmarks & DAGs)` | `NOT_TESTED` |
| **Reproducibility** | `YES (Frozen digests in manifest)` | `NOT_REPRODUCIBLE (On target OS)` |
| **Operational complexity** | `LOW (Native background service)` | `HIGH (WSL2/Linux build pipeline required)` |

---

```text
============================================================
FINAL RUNTIME DECISION:
OLLAMA
============================================================
```
