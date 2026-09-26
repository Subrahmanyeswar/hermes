# CONTEXT MANAGEMENT & LONG-HORIZON CONTINUITY

**Branch:** `hermes-2.x`  
**Milestone:** Prompt 7 — Context Engine 2.x  

---

## 1. Context Lifecycle Pipeline

Every turn in HERMES follows this strict context pipeline:

```
Collect Candidates
       │
       ▼
Check Freshness (Disk & FileIdentityCache)
       │
       ▼
Score Relevance (Deterministic Priority Tiers)
       │
       ▼
Budget Evaluation (Headroom & Usable Capacity)
       │
       ▼
Graduated Pressure Relief (if utilization > 60%)
 ├── Level 1: Trim inline tool results
 ├── Level 2: Microcompact duplicate observations
 └── Level 3: Full compaction with structured summary
       │
       ▼
Validate ContextPack (Contradiction & Secret Gates)
       │
       ▼
Partition Cache Segments (STABLE_PREFIX vs DYNAMIC)
       │
       ▼
Serialize to Model Messages
       │
       ▼
T1 Model Turn
```

---

## 2. Invariants & Negative Guarantees

The Context Engine enforces non-negotiable architectural boundaries:

1. **State Store Immunity:** Compaction is a context projection operation. It **never mutates** `StateStore` truth.
2. **Mandatory State Protection:** User goals, active blockers, security rules, and verified evidence cannot be pruned by relevance ranking.
3. **No Shadow Filesystem:** The engine never caches stale repository snapshots; disk truth always takes precedence.
4. **Secret Redaction Before Persistence:** Any oversized output persisted to `artifacts/context/tool-results/` is sanitized using regex secret detection before writing to disk.
5. **Prompt Injection Containment:** External files and tool outputs are labeled and fenced strictly as `<file_data>` and `<observation_data>`, preventing adversarial text from elevating to `<system>` instructions.
6. **No Infinite Compaction Loops:** Compaction is bounded; if summarization fails, a safe deterministic fallback summary is produced immediately.

---

## 3. Benchmarks & Performance Profile

Profiled on Windows under realistic 100-turn workload:

| Operation | Description | p50 Latency | p95 Latency |
| :--- | :--- | :--- | :--- |
| **`build_context`** | Freshness check + Relevance + Budget + Pack | **0.08 ms** | **0.31 ms** |
| **`relevance.score_all`** | Deterministic keyword + priority scoring | **0.10 ms** | **0.17 ms** |
| **`budgeter.budget`** | Partitioned headroom allocation | **0.02 ms** | **0.04 ms** |
| **`ext_store.put`** | Large artifact file write + SHA-256 (20KB) | **4.19 ms** | **6.31 ms** |
| **`clear_result`** | In-memory pointer swap & clearing | **0.00 ms** | **0.00 ms** |
| **`microcompact`** | Duplicate collapse & log trimming | **0.00 ms** | **0.00 ms** |
| **`full_compact`** | Level 3 structured summary assembly | **0.02 ms** | **0.05 ms** |

---

## 4. 100-Turn Long-Horizon Stability Verification

In automated tests simulating 100 continuous turns of edits, bash executions, and searches (`test_100_turn_synthetic_mission_long_horizon_stability`):
- **Peak Context:** Remained strictly bounded within the configured usable budget.
- **Mean Context:** Kept at **< 70%** of usable capacity.
- **Zero Memory Leaks:** Bulky outputs were externalized and cleared.
- **Goal Retention:** User intent and system directives remained fully intact at turn 100.
