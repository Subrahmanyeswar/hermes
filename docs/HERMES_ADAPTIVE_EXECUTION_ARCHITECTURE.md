# HERMES Adaptive Execution Architecture
=========================================

**Module:** `core.adaptive_execution`  
**Date:** September 1, 2026  
**Status:** PRODUCTION READY  

---

## 1. Execution Modes

| Mode | Target Scope | LLM Calls | Planning Overhead | Verification Engine |
|---|---|---|---|---|
| **`SIMPLE`** | Deterministic filesystem & info (`mkdir`, `read`, `list`, `stat`) | **0 LLM Calls** | None (0ms) | Deterministic postcondition check |
| **`STANDARD`**| Localized coding, bug fixes, single-file edits, unit tests | **1 T1 Call** | ContextPack (Phase 8) | Progressive Verification Gate (Phase 6.2) |
| **`COMPLEX`** | Multi-file architecture, migrations, full-stack systems | **T1 + T2 + T3** | Full KAIROS DAG Plan | Full multi-tier verifier + repair loops |

---

## 2. Multi-Signal Request Classification

`TaskComplexityClassifier` operates deterministically in **<0.1 ms**:
1. **Complex Keyword Scanning:** Detects architectural scope (`refactor entire`, `complete system`, `migrate`, `frontend and backend`).
2. **Simple Regex Pattern Matching:** Maps natural commands (`create folder X`, `read file Y`, `show project structure`) to deterministic tool executions.
3. **Safe Default:** Ambiguous or non-deterministic code queries default to `STANDARD`.

---

## 3. Runtime Escalation & Hysteresis

`EscalationManager` tracks runtime conditions:
- `SIMPLE ➔ STANDARD`: Triggered on direct tool execution failure or unexpected syntax error.
- `STANDARD ➔ COMPLEX`: Triggered when discovered dependencies exceed 3 files or multi-step verification fails.
- **Hysteresis Invariant:** Active missions never downgrade to preserve correctness and safety.
