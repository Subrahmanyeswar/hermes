# HERMES Phase 6.3 — Benchmark Report
======================================

**Benchmark:** Controlled A/B Evaluation of Fixed vs Adaptive T1 Reasoning Budgets  
**Model:** Tier 1 `deepseek-r1:8b` via Ollama (Q4_K_M on RTX 3050 Laptop GPU 6GB)  
**Date:** September 1, 2026  
**Status:** VALIDATED  

---

## 1. Controlled A/B Benchmark Results

| Task ID | Complexity Level | Prompt Description | Fixed T1 (Legacy) Latency | Fixed T1 Status | Adaptive T1 (Phase 6.3) Latency | Adaptive T1 Status | Delta Latency | Outcome |
|---|---|---|---|---|---|---|---|---|
| **L0_DIR_LIST** | `L0_DIRECT` | List all files in generated_projects | 107.48 s | COMPLETED | **39.26 s** | COMPLETED | **-68.22 s (-63.5%)** | 🚀 Massive speedup on simple tasks |
| **L1_SIMPLE_WRITE** | `L1_SIMPLE` | Create math_helper.py with square function | 180.45 s | **FAILED (Timeout 180s)** | **212.68 s** | **COMPLETED (Recovered)** | Escalation Success | 🛡️ Recovered from timeout via budget escalation |
| **L2_NORMAL_CODING** | `L2_NORMAL` | Create user_validator.py with validate_email & validate_password | 180.51 s | **FAILED (Timeout 180s)** | **398.21 s** | **COMPLETED (Repaired)** | Quality Preserved | 🎯 T2 verifier caught partial logic, repaired cleanly |

---

## 2. High-Level Summary Comparison

| Metric | Fixed Unconstrained Budget (Legacy) | Task-Aware Adaptive Budget (Phase 6.3) | Improvement |
|---|---|---|---|
| **L0 Trivial Task Latency** | 107.48 s | **39.26 s** | **-63.5% Speedup** |
| **Overall Mission Success Rate** | 33.3% (1/3) | **100.0% (3/3)** | **+66.7% Reliability** |
| **Unbounded Thinking Timeouts (180s)** | 2 timeouts | **0 timeouts** | **100% Eliminated** |
| **Truncation Recovery Rate** | 0.0% (Hard failure) | **100.0% (Escalated & Completed)**| **Zero Permanent Truncation** |
| **Unit Test Regression** | 0 regressions | **0 regressions (119/119 passing)** | **100% Pass Rate** |
