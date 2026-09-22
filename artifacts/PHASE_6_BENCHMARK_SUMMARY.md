# HERMES — PHASE 6 FINAL BENCHMARK SUMMARY REPORT
**Run ID**: `final_benchmark_20260905_140302`  
**Execution Window**: `2026-09-05 08:33:02 UTC` $\rightarrow$ `2026-09-05 16:05:45 UTC`  
**Commit**: `be1a563bd73830efa0dff2400788ffe89d2ebc96`  
**Benchmark Valid**: `True`  

---

## 1. Top-Level Execution Metrics
- **Total Evaluated Tasks**: **80**
- **Objective Completed (PASS)**: **1 / 80** (1.25%)
- **Objective Failed (FAIL)**: **79 / 80** (98.75%)
- **First-Attempt Success**: **1 / 80** (1.25%)
- **Repair Required**: **0**
- **Repair Successes**: **0**
- **False Completions**: **0 / 80** (0.0% — Eliminated by Objective Evaluator)

---

## 2. Model & Routing Distribution
- **Tier 1 (DeepSeek-R1 8B) Invocations**: 198
- **Tier 2 (Qwen3 8B) Invocations**: 40
- **Tier 3 (Cloud / OpenRouter) Requests**: 0
- **Tier 3 Cost Total**: $0.0000
- **Tokens Processed**: 594,059 (Input: 261,892, Output: 332,167)

---

## 3. End-to-End Latency Distribution
- **Mean Latency**: `337.8488s`
- **P50 (Median)**: `211.8828s`
- **P75**: `309.7876s`
- **P90**: `372.3838s`
- **P95**: `397.3817s`
- **P99**: `2176.5844s`

---

## 4. Hardware & Thermal Invariants
- **Peak VRAM Allocated**: `5600.0 MB` (Headroom on 6,144 MB GPU)
- **Peak GPU Temperature**: `89 °C`
- **Mean CPU Load**: `55.8%`
- **Mean GPU Utilization**: `93.2%`
