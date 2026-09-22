# HERMES Intelligent Model Routing Architecture
================================================

**Module:** `core.intelligent_router`  
**Date:** September 1, 2026  
**Status:** PRODUCTION READY  

---

## 1. Multi-Tier Escalation Model

| Tier | Model | Role | Invocation Policy |
|---|---|---|---|
| **Tier 1** | `deepseek-r1:8b` (Local Ollama) | Primary Reasoning & Implementation | Primary default for all non-simple tasks |
| **Tier 2** | `qwen3:8b` (Local Ollama) | Conditional Independent Verifier | Invoked **only** when confidence < 0.70, risk >= 0.60, or verification is inconclusive |
| **Tier 3** | `stealth/ox-alpha` (Cloud OpenRouter) | Final Disagreement Arbitrator | Invoked **only** on unresolved T1/T2 disagreement under the $25 lifetime cap |

---

## 2. Multi-Signal Decision Matrix

1. **Hard Fail-Safe:** `risk_score >= 0.90` or destructive commands ➔ `FAIL_SAFE` (Explicit user confirmation).
2. **Read-Only Pass-Through:** Read-only tools (`read_file`, `list_directory`, `grep_search`) ➔ `ACCEPT_T1` in 0.002ms.
3. **High Confidence + Verified:** `confidence >= 0.70`, `risk < 0.60`, `verification == PASSED` ➔ `ACCEPT_T1` (Bypasses T2 & T3).
4. **Low Confidence / Elevated Risk:** `confidence < 0.70` or `risk >= 0.60` ➔ `ESCALATE_T2`.
5. **Agreement Resolution:** `t2_agree == True` and `0 critical issues` ➔ `ACCEPT_T2` (No T3).
6. **Disagreement Arbitration:** `t2_agree == False` or critical issues ➔ `ESCALATE_T3`.
