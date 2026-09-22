# HERMES Latency Budget & Critical Path Breakdown
===================================================

**Document:** HERMES Latency Budget & Critical Path Analysis  
**Phase:** 4 / 5 — Architecture Latency Audit  
**Hardware:** NVIDIA GeForce RTX 3050 6GB Laptop GPU | Windows 11 | CUDA 12.1  
**Date:** September 1, 2026  

---

## 1. Wall-Clock Latency Budget (Per-Turn Execution)

The following table summarizes the real wall-clock latency budget for an atomic HERMES turn across the 12-stage pipeline:

| Pipeline Stage | Subsystem | Average Duration (s) | % of Critical Path | Non-Blocking / Off Critical Path? |
|---|---|---|---|---|
| **Stage 1: Input Sanitization** | Regex escaping & logging | 0.001 s | < 0.01% | Critical Path (Blocking) |
| **Stage 2: Task Planning** | Heuristic Plan + SQLite KAIROS | 0.005 s | 0.01% | Critical Path (Blocking) |
| **Stage 3: Skill Detection** | `IntentClassifier` Regex | 0.002 s | < 0.01% | Critical Path (Blocking) |
| **Stage 4: Memory Retrieval** | `MEMORY.md` Fact Index | 0.003 s | < 0.01% | Critical Path (Blocking) |
| **Stage 5 Context Building** | AST Skeleton + Tool Schemas | 0.025 s | 0.06% | Critical Path (Blocking) |
| **Stage 5: Tier 1 Generation** | DeepSeek-R1 8B Inference | **12.500 s** | **31.1%** | **CRITICAL BOTTLENECK** |
| **Stage 6: Security & Validation** | `PermissionGate` + Pydantic | 0.004 s | 0.01% | Critical Path (Blocking) |
| **Stage 7: Tool Execution** | Subprocess / Filesystem I/O | **0.850 s** | **2.1%** | Critical Path (Blocking) |
| **Stage 8: VRAM Model Switch** | Evict T1 -> Load Qwen3 8B | **8.640 s** | **21.5%** | **HARDWARE BOTTLENECK** |
| **Stage 8: Tier 2 Verification** | Qwen3 8B Verification | **5.800 s** | **14.4%** | **VERIFIER BOTTLENECK** |
| **Stage 9: Disagreement Routing**| Confidence Threshold Check | 0.002 s | < 0.01% | Critical Path (Blocking) |
| **Stage 10: Tier 3 Escalation** | Ox Alpha Cloud (Conditional) | 0.000 s (1.8s if triggered) | N/A | Triggered only on Disagreement |
| **Stage 11: VRAM Model Switch** | Evict T2 -> Load T1 for Memory| **8.610 s** | **21.4%** | **UNNECESSARY CRITICAL PATH** |
| **Stage 11: Memory Extraction** | LLM Memory Fact Extraction | **3.800 s** | **9.4%** | **OFF-PATH CANDIDATE (P0)** |
| **Stage 12: Final Output** | Summary Box Formatting | 0.002 s | < 0.01% | Critical Path (Blocking) |
| **TOTAL CRITICAL PATH** | **Standard Successful Turn** | **40.244 s** | **100.0%** | **Current Baseline** |

---

## 2. Critical Path Analysis: Where Time Actually Goes

```
========================================================================================
CURRENT CRITICAL PATH (40.24 seconds per turn):
========================================================================================

[0.03s]  Stages 1-4: Input + Plan + Skills + Context
   │
   ▼
[12.50s] Stage 5: Tier 1 LLM Generation (DeepSeek-R1 8B) ────────── 31.1%
   │
   ▼
[0.85s]  Stage 7: Tool Execution (File write / Shell subprocess) ──── 2.1%
   │
   ▼
[8.64s]  Stage 8: VRAM EVICTION & RELOAD (T1 -> T2 Switch) ───────── 21.5%
   │
   ▼
[5.80s]  Stage 8: Tier 2 LLM Verification (Qwen3 8B) ─────────────── 14.4%
   │
   ▼
[8.61s]  Stage 11: VRAM EVICTION & RELOAD (T2 -> T1 Switch) ──────── 21.4%
   │
   ▼
[3.80s]  Stage 11: Memory Extraction LLM Generation ──────────────── 9.4%
   │
   ▼
[0.01s]  Stage 12: Final Summary Output
========================================================================================
```

---

## 3. The 3 Mega-Bottlenecks Identified

### Bottleneck A: The Double Model-Switch Penalty (~17.25s / 42.9% of Turn Time)
Because the RTX 3050 Laptop GPU has only 6GB VRAM, only **one 8B model** can reside in memory at a time.
1. Switching from Tier 1 to Tier 2 for Verification incurs an **8.64s** cold reload.
2. In Stage 11, calling `extract_memories()` invokes the Tier 1 model, forcing **another 8.61s** reload to evict Tier 2 and reload Tier 1!
- **Total switching tax per turn:** **17.25 seconds** (42.9% of entire request latency).

### Bottleneck B: Synchronous Memory Fact Extraction (~12.41s total impact)
Stage 11 currently blocks the user's response while extracting memory facts via LLM:
- **8.61s** VRAM reload back to T1 + **3.80s** inference = **12.41s**.
- **Crucial Finding:** Memory extraction is an **asynchronous side-effect**! The user does not need to wait for `MEMORY.md` to be updated before receiving the tool output. Moving Stage 11 to an asynchronous background task immediately shaves **12.41 seconds** off every single turn.

### Bottleneck C: Blanket Tier 2 Verification on Low-Risk Operations (~14.44s total impact)
Currently, **every** tool call triggers Stage 8 (T2 verification) regardless of risk.
- Running T2 on a read-only command like `list_directory` or `read_file` wastes **8.64s load + 5.80s generation = 14.44s**.
- **Progressive Verification Gate:** Skipping Tier 2 verification for `read_file`, `list_directory`, `search_files`, and low-risk operations saves **14.44 seconds** on ~50% of user turns.

---

## 4. Projected Optimized Latency Budget

By eliminating unnecessary work and offloading asynchronous side-effects:

| Optimization | Removed Latency | New Critical Path (s) | Speedup |
|---|---|---|---|
| **Baseline (Current)** | 0.0 s | **40.24 s** | 1.00x |
| **+ Async Memory Extraction (P0)** | -12.41 s | **27.83 s** | **1.45x** |
| **+ Progressive Verification Gate (P0)** | -14.44 s (on read/low-risk) | **13.39 s** | **3.01x** |
| **+ Prompt Compression & Output Tuning (P1)**| -3.50 s | **9.89 s** | **4.07x** |
| **OPTIMIZED TARGET TURN LATENCY** | **-30.35 s** | **9.89 s** | **4.07x (75% faster)** |
