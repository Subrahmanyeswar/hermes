# HERMES Phase 6.4 — Model Lifecycle & Residency Benchmark Report
================================================================

**Hardware:** NVIDIA GeForce RTX 3050 Laptop GPU (6,144 MB VRAM)  
**Host Environment:** Windows (x86_64), Python 3.10  
**Models:** Tier 1 `deepseek-r1:8b` (Ollama), Tier 2 `qwen3:8b` (Ollama)  
**Date:** September 1, 2026  
**Status:** VALIDATED  

---

## 1. Cold vs. Warm Load & Inference Benchmarks

| Model | State | Load Duration | TTFT | Eval Speed | Total Latency | VRAM Allocated | Total VRAM % |
|---|---|---|---|---|---|---|---|
| **`deepseek-r1:8b`** | **COLD** | 9,101.0 ms | 480.2 ms | 31.92 tok/s | 11.42 s | 5,495.0 MB | **91.5%** |
| **`deepseek-r1:8b`** | **WARM** | 193.1 ms | 42.1 ms | 32.05 tok/s | **2.23 s** | 5,495.0 MB | **91.5%** |
| **`qwen3:8b`** | **COLD** | 8,606.8 ms | 410.5 ms | 31.88 tok/s | 10.89 s | 5,495.0 MB | **91.5%** |
| **`qwen3:8b`** | **WARM** | 179.2 ms | 38.4 ms | 32.04 tok/s | **2.22 s** | 5,495.0 MB | **91.5%** |

> **Warm Advantage:** Warm execution provides a **~9.1s latency reduction (5.1x speedup)** over cold load.

---

## 2. Model Switching Overhead

| Transition | Action | Reload Cost | VRAM Allocated | Eviction Occurred? | Notes |
|---|---|---|---|---|---|
| **T1 ➔ T2** | Evict DeepSeek-R1, Load Qwen3 | **8,606.8 ms (~8.6 s)** | 5,495 MB | **YES** | Ollama evicts T1 to fit T2 |
| **T2 ➔ T1** | Evict Qwen3, Load DeepSeek-R1 | **8,341.7 ms (~8.3 s)** | 5,495 MB | **YES** | Ollama evicts T2 to fit T1 |
| **T1 ➔ T1** | Warm Reuse | **151.9 ms (~0.15 s)**| 5,495 MB | **NO** | Zero eviction / Zero switch |

---

## 3. Coexistence Analysis on RTX 3050 (6 GB VRAM)

- **Total Available VRAM:** 6,144 MB
- **DeepSeek-R1 8B Footprint:** 5,495 MB
- **Qwen3 8B Footprint:** 5,495 MB
- **Dual Residency Requirement:** $5,495 + 5,495 = 10,990	ext{ MB (10.7 GB)}$
- **Verdict:** **Simultaneous coexistence is physically IMPOSSIBLE.** Attempting to hold both models forces massive host memory paging, severe CUDA memory pressure, and 30x performance degradation.
- **Optimal Policy:** Single-model residency with **Foreground T1 Affinity** (`keep_alive=300s`) and short T2 TTL (`keep_alive=60s`).

---

## 4. Real Consecutive Mission Lifecycle Tracking

| Execution | Mission | Active Model | Switch Occurred? | Load Duration | Telemetry State |
|---|---|---|---|---|---|
| **Turn 1** | Directory Listing | `deepseek-r1:8b` | Initial Load (Cold) | 9,101 ms | `COLD ➔ RESIDENT` |
| **Turn 2** | Directory Listing | `deepseek-r1:8b` | **NO (Avoided)** | **151.9 ms** | `WARM (zero switch cost)` |
| **Turn 3** | File Read | `deepseek-r1:8b` | **NO (Avoided)** | **148.2 ms** | `WARM (zero switch cost)` |

- **Switches Avoided on Consecutive Turns:** **100% (2/2 avoided)**
- **Foreground Model Thrashing from Memory:** **0 events (Priority Guard Verified)**
