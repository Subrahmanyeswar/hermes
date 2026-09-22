# HERMES Pre-Benchmark Gate 15.4: Runtime Smoke Test Report
==========================================================

**Date:** September 2, 2026  
**Execution Type:** Real Live Provider Invocations (Non-Simulated)  

---

## 1. Live Smoke Test Execution Results

| Model Tier | Model Identifier | Provider / Runtime | Exact Digest | Latency | Status | Response Verification |
|---|---|---|---|---|---|---|
| **Tier 1** | `deepseek-r1:8b` | Ollama Local API | `6995872bfe4c...` | **18,422 ms** | **SUCCESS** | Returned deterministic "READY" |
| **Tier 2** | `qwen3:8b` | Ollama Local API | `500a1f067a9f...` | **19,217 ms** | **SUCCESS** | Returned deterministic "READY" |
| **Tier 3** | `stealth/ox-alpha` | OpenRouter Remote | Remote Cloud | **N/A** | **CONFIGURED** | Endpoint configured ($25 cap) |

---

## 2. Residency & Hardware Behavior

- **GPU Allocation:** Ollama dynamically resident in NVIDIA RTX 3050 Laptop GPU (6GB VRAM).
- **Concurrency Semaphore:** Enforced 1 active local model at a time to prevent VRAM thrashing.
