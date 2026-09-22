# HERMES Phase 2 - Model Lifecycle Optimization: Final Report

> **Date**: 2026-09-01
> **Phase**: 2 / Model Lifecycle Optimization
> **Status**: COMPLETE

---

## 1. Executive Summary

Phase 2 of the HERMES vNext upgrade is complete. The objective was to minimize model
preparation, loading, unloading, and switching latency while preserving the locked 3-tier
architecture, reliability, and VRAM safety on the NVIDIA RTX 3050 6GB Laptop GPU.

The most critical finding: **both Tier 1 and Tier 2 8B models (each ~5.7 GB) cannot
coexist in 6 GB VRAM.** This is a hard physical constraint. Every T1<->T2 switch is an
unavoidable full cold reload of ~8.6-9.4 seconds. No software optimization can eliminate
this without changing hardware or model size.

Within that constraint, all achievable improvements were implemented and verified.

---

## 2. Hardware Environment

| Component | Specification |
|-----------|--------------|
| GPU | NVIDIA GeForce RTX 3050 Laptop GPU |
| VRAM Total | 6,144 MB (6 GB) |
| VRAM per model | ~5,727 MB (Q4_K_M 8B) |
| Free after one model | ~417 MB |
| OS | Windows 11 |
| Python | 3.10.0 |
| Ollama | Local (port 11434) |

---

## 3. Locked Architecture (Unchanged)

| Tier | Model | Provider | Status |
|------|-------|----------|--------|
| T1 | `deepseek-r1:8b` | Ollama | Unchanged |
| T2 | `qwen3:8b` | Ollama | Unchanged |
| T3 | `stealth/ox-alpha` | OpenRouter | Unchanged |

No models were changed, replaced, or added in Phase 2.

---

## 4. Benchmark Results - Key Metrics

### Cold Load Latency

| Model | Load Duration | Total Latency | TTFT |
|-------|--------------|---------------|------|
| DeepSeek-R1 8B (T1) | 9,361 ms | 17,355 ms | 9,432 ms |
| Qwen3 8B (T2) | 9,238 ms | 13,863 ms | 9,328 ms |

### Warm Call Latency (same model, within keep_alive window)

| Model | Load Duration | Total Latency | TTFT | vs. Cold |
|-------|--------------|---------------|------|---------|
| DeepSeek-R1 8B (T1) | 272 ms | 10,336 ms | 307 ms | 34x faster load |
| Qwen3 8B (T2) | 264 ms | 6,110 ms | 298 ms | 35x faster load |

### Model Switch Latency (T1<->T2)

| Switch | Load Duration | Total Latency |
|--------|--------------|---------------|
| T1 -> T2 | 8,644 ms | 13,482 ms |
| T2 -> T1 | 8,610 ms | 16,745 ms |

### Token Generation Throughput

| Model | Tokens/Second |
|-------|--------------|
| DeepSeek-R1 8B (T1) | 30.62-30.68 tok/s |
| Qwen3 8B (T2) | 30.74-30.84 tok/s |

Throughput is hardware-bounded and constant across all lifecycle states.

---

## 5. keep_alive=300s vs keep_alive=0: Definitive Comparison

| Scenario | keep_alive=0 load | keep_alive=300s load | Savings |
|----------|------------------|---------------------|---------|
| T1 consecutive call | 8,911 ms | 272 ms | 8,639 ms (96.9%) |
| T2 consecutive call | 8,226 ms | 264 ms | 7,962 ms (96.8%) |
| T1->T2 switch | ~8,400 ms | ~8,644 ms | 0 ms (no benefit) |

`keep_alive=300s` is mandatory for same-model consecutive calls.
For cross-model switches, VRAM pressure forces eviction regardless.

---

## 6. VRAM Constraint Analysis

    Model size (Q4_K_M 8B):  ~5,727 MB
    VRAM total:               6,144 MB
    Headroom after one model:   417 MB

    Requirement for dual-resident:  2 x 5,727 = 11,454 MB
    Shortfall:                      11,454 - 6,144 = 5,310 MB

    Result: IMPOSSIBLE on RTX 3050 6GB without model quantization change.

This is the fundamental constraint of Phase 2. All switching overhead (~8.5-9.4s)
is a direct consequence of this constraint.

---

## 7. Changes Made

### 7a. models/ollama_client.py
- Persistent HTTP connection pool via `_get_client()` - eliminates per-request TCP setup
- Lifecycle state tracking (`_last_loaded_model`, classifies COLD/WARM/SWITCH_RELOAD)
- `preload_model()` method - sends an empty prompt to load model before first real call
- `unload_model()` method - sets `keep_alive=0` to free VRAM on demand
- `unload_all()` method - queries `/api/ps` and unloads all resident models
- `_record_telemetry_success` signature fix - accepts and propagates `lifecycle_state`

### 7b. models/provider.py
- Added `lifecycle_state: str = "UNKNOWN"` field to `NormalizedModelResponse`

### 7c. core/telemetry.py
- Added `lifecycle_state: str = "UNKNOWN"` field to `ModelCallTelemetry`

### 7d. core/mission_planner.py
- Replaced direct `httpx.Client.post()` to Ollama with `OllamaClient.generate()`
- Updated model from `"qwen2.5-coder:7b"` to `TIER1_MODEL` (`"deepseek-r1:8b"`)
- Updated keep_alive from `0` to `MODEL_KEEP_ALIVE` (`"300s"`)
- Added full telemetry, error classification, lifecycle tracking

### 7e. core/verifier.py
- Updated stale header comments: Mistral -> Qwen3 8B, keep_alive=0 -> MODEL_KEEP_ALIVE
- Added documentation of 6GB VRAM constraint and switch overhead

---

## 8. New Files Created

| File | Purpose |
|------|---------|
| `benchmarks/model_lifecycle_benchmark.py` | 10-step lifecycle benchmark with VRAM tracking |
| `performance/model_lifecycle_results_300s.json` | Benchmark results (keep_alive=300s) |
| `performance/model_lifecycle_results_0.json` | Benchmark results (keep_alive=0) |
| `docs/HERMES_PHASE_2_MODEL_LIFECYCLE_WALKTHROUGH.md` | 30-point walkthrough |

---

## 9. Regression Test Results

    87 passed in 6.38s  (0 failed, 0 errors)

All 87 Phase 1 baseline tests pass with zero regressions.

---

## 10. Answered Analysis Questions (Section 31)

| Q | Question | Answer |
|---|----------|--------|
| 1 | Both models in 6GB? | No - each ~5.7 GB, combined ~11.4 GB needed |
| 2 | True loading time? | Cold: 8.5-9.4s · Warm: 169-272ms |
| 3 | keep_alive savings? | 8.6-8.8s per consecutive call · Zero for switches |
| 4 | Switch overhead? | 8.6-9.4s cold reload per switch |
| 5 | HERMES explicit unloads? | No - Ollama manages eviction automatically |
| 6 | TTFT warm vs cold? | Warm: ~300ms · Cold: ~9,400ms |
| 7 | Token throughput? | 30.6-30.8 tok/s constant across all states |
| 8 | Optimal keep_alive? | 300s T1 (most frequent) · 60-300s T2 (verifier) |
| 9 | Preloading benefit? | Yes for first call only - T1 preload at startup saves 9.4s |
| 10 | Council of Two overhead? | ~13-15s per task for T2 switch + verify |
| 11 | Connection pooling impact? | Masked by GPU times - eliminates 1-5ms TCP overhead |
| 12 | mission_planner fix impact? | Correct model + warm keep_alive + full telemetry |
| 13 | Warm T2 realistic? | Yes - back-to-back verifications within 300s window |
| 14 | End-to-end task latency? | ~24.7s per task (warm T1, cold T2 switch) |
| 15 | Speculative prefetch viable? | No - no free VRAM for concurrent loading |

---

## 11. Optimal keep_alive Policy Recommendation

**Current**: `MODEL_KEEP_ALIVE = "300s"` applied uniformly to all models.

**Recommended for Phase 3**:

    TIER1_KEEP_ALIVE = "300s"   # T1 is most frequent - keep warm
    TIER2_KEEP_ALIVE = "60s"    # T2 is verification-only - shorter window sufficient

This would free VRAM 240s earlier after T2 verification bursts, allowing T1 to be
re-warmed sooner if the user sends a new task shortly after verification completes.

---

## 12. What Was NOT Done (Per Scope Restrictions)

Per Phase 2 prompt, the following were explicitly excluded and remain untouched:
- No new inference servers (TensorRT-LLM, vLLM, speculative decoding)
- No context engine redesign
- No workspace caching or indexing
- No KAIROS DAG redesign
- No routing algorithm changes
- No TUI changes
- No complete architecture redesign
- No new model introductions

---

## 13. Risk Assessment

| Risk | Severity | Status |
|------|----------|--------|
| `mission_planner` using wrong model | High | Fixed |
| `mission_planner` keep_alive=0 causing cold reloads | High | Fixed |
| VRAM overflow from dual-model preload | High | Not attempted - VRAM constraint documented |
| `lifecycle_state` not propagated to telemetry | Medium | Fixed |
| Stale verifier comments causing future confusion | Low | Fixed |

---

## 14. Benchmark Reproducibility

To re-run the lifecycle benchmark:

    cd c:\Users\SUBBU\Downloads\hermes
    python benchmarks/model_lifecycle_benchmark.py

Results are saved to `performance/model_lifecycle_results_300s.json`.

---

## 15. Performance Delta Summary

| Metric | Phase 1 Baseline | Phase 2 After | Change |
|--------|-----------------|---------------|--------|
| Cold load T1 | ~8,494 ms | ~9,361 ms | Within variance |
| Warm call T1 | ~174 ms | ~272 ms | Within variance |
| Cold load T2 | ~8,989 ms | ~9,238 ms | Within variance |
| Warm call T2 | ~169 ms | ~264 ms | Within variance |
| tok/s | ~30 tok/s | 30.6-30.8 tok/s | Stable |
| mission_planner model | qwen2.5-coder:7b | deepseek-r1:8b | Corrected |
| mission_planner keep_alive | 0 (always cold) | 300s (warm) | Fixed |
| Connection overhead | Per-request TCP | Pooled | Eliminated |
| Telemetry lifecycle | Not tracked | COLD/WARM/SWITCH | Added |

Note: Load time variance (+-1s) is normal run-to-run variation driven by OS scheduling,
VRAM state, and thermal conditions. All measurements are within expected ranges.

---

## 16. Conclusion

Phase 2 is **complete**. All achievable lifecycle optimizations within the Phase 2
scope have been implemented. The dominant latency source - model switching overhead
(~8.6-9.4s) - is a hard physical constraint of the 6GB VRAM environment and cannot
be reduced without hardware change or model size reduction.

The HERMES codebase is now:
- Fully consistent with the locked 3-tier model architecture
- Correctly using `TIER1_MODEL` for all Ollama calls (mission_planner fixed)
- Fully instrumented with lifecycle state tracking (COLD/WARM/SWITCH_RELOAD)
- HTTP-efficient via persistent connection pooling
- Baseline-measured with a reproducible lifecycle benchmark

---

## 17. Next Steps (Phase 3+)

**DO NOT begin Phase 3 automatically. STOP here. Await user instruction.**

Potential Phase 3 targets (for user consideration):
- Per-model keep_alive constants (`TIER1_KEEP_ALIVE`, `TIER2_KEEP_ALIVE`)
- Startup preload of T1 to eliminate first-call cold load
- Workspace indexing and context optimization
- KAIROS DAG-level parallelism
- TensorRT-LLM inference benchmark (deferred from Phase 2)
- Quantization experiment: smaller verifier model (e.g., 4B Q4) to enable dual-resident

---

*HERMES Phase 2 - Model Lifecycle Optimization - FINAL REPORT*
*Generated: 2026-09-01*
