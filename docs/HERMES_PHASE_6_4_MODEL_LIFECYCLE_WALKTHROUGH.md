# HERMES Phase 6.4 — Model Switching & Foreground Residency Walkthrough
===========================================================================

**Project:** HERMES vNext  
**Phase:** Phase 6.4 — Model Switching & Foreground Model Residency Optimization  
**Date:** September 1, 2026  
**Status:** COMPLETED & VERIFIED (125/125 Tests Passing)  

---

## 1. Executive Summary

Phase 6.4 conducted a comprehensive empirical audit of GPU memory residency, cold vs. warm load latencies, and model switching behavior on the target **NVIDIA GeForce RTX 3050 Laptop GPU (6 GB VRAM)**.

### Key Empirical Findings:
1. **Single-Model VRAM Dominance:** Both `deepseek-r1:8b` and `qwen3:8b` require **5,495 MB (91.5%)** of the available 6,144 MB VRAM.
2. **Dual Residency Infeasible:** Simultaneously keeping both 8B models in VRAM requires **10.7 GB**, which physically exceeds the 6.0 GB hardware ceiling. Ollama strictly enforces single-model eviction.
3. **Switch Cost:** Switching between models incurs an **~8.6-second reload latency**. In contrast, warm model reuse takes only **~150–190 ms (5.1x faster)**.
4. **Residency Strategy Selected:** **Foreground T1 Affinity with Intelligent Single-Model Residency & Background Memory Priority Locking**.

---

## 2. Model Residency Architecture

```
                               HERMES REQUEST
                                     │
                                     ▼
                      ModelResidencyManager.acquire()
                                     │
                  Is Requested Model Already Resident?
                                /                                       YES          NO
                              │             │
                        [Zero Delay]   [Acquire Lock]
                       (150ms warm)         │
                                     Is Foreground Active?
                                          /                                               YES        NO (Background Memory)
                                        │          │
                                 [Evict & Load]   [Yield / Wait for Idle]
                                  (keep_alive)          │
                                        │          [Process Background]
                                        ▼               ▼
                                    EXECUTED         RELEASED
```

---

## 3. Decision Matrix

| Strategy | Feasibility on 6GB | Switch Cost | VRAM Safety | Stability | Selected? | Rationale |
|---|---|---|---|---|---|---|
| **Strategy A: Foreground T1 Affinity** | **YES (5.5 GB)** | **0s (Warm)** / **8.6s (Switch)** | **100% Safe** | **HIGH** | **SELECTED** | Keeps T1 warm across turns; T2 loaded only on demand |
| **Strategy B: Permanent T2 Residency** | YES (5.5 GB) | 8.6s on every T1 turn | 100% Safe | LOW | REJECTED | Forces T1 (primary reasoning model) to reload constantly |
| **Strategy D: Dual Coexistence** | **NO (Needs 11GB)**| N/A | **CRITICAL OOM** | CRITICAL | **REJECTED** | Impossible on 6GB VRAM; triggers severe memory thrashing |

---

## 4. Test Verification Suite

All 125 core unit and integration tests passed:
- `tests/test_model_residency.py`:
  1. `test_first_model_acquire_and_release` — PASSED
  2. `test_warm_model_reuse_zero_switches` — PASSED
  3. `test_model_switch_tracking` — PASSED
  4. `test_foreground_priority_guard` — PASSED
  5. `test_concurrent_acquisition_lock` — PASSED
  6. `test_feature_flag_rollback` — PASSED
- Full core regression suite: **125 passed / 0 failed in 5.92s**

---

## 5. Files Changed

1. **`core/model_residency_manager.py`** `[NEW]` — Centralized `ModelResidencyManager`, state machine, lock/deduplication, and foreground priority guard.
2. **`config/model_config.py`** `[MODIFIED]` — Added `OPTIMIZED_MODEL_RESIDENCY_ENABLED`, `T1_KEEP_ALIVE = "300s"`, `T2_KEEP_ALIVE = "60s"`.
3. **`models/ollama_client.py`** `[MODIFIED]` — Integrated with `ModelResidencyManager` to coordinate acquisitions and releases.
4. **`memory/extractor.py`** `[MODIFIED]` — Configured background memory extraction with `is_foreground=False` to prevent model thrashing.
5. **`tests/test_model_residency.py`** `[NEW]` — Comprehensive unit and integration test suite.
6. **`benchmarks/phase6_4_model_lifecycle_benchmark.py`** `[NEW]` — Lifecycle and mission benchmark harness.
7. **`docs/HERMES_PHASE_6_4_BENCHMARK.md`** `[NEW]` — Benchmark report.
8. **`docs/HERMES_PHASE_6_4_MODEL_LIFECYCLE_WALKTHROUGH.md`** `[NEW]` — Walkthrough report.
