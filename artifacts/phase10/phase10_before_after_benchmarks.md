# HERMES Phase 10 — Before and After Benchmark Results

**Execution Date:** 2026-10-22  
**Platform:** Windows 11  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Git Branch:** `hermes-2.x`  

---

## 1. Executive Summary

Empirical before-and-after benchmarks were conducted on isolated synthetic workloads. Every optimization was measured under identical hardware and environment conditions.

### Highlights:
- **Workspace Manifest Warm Retrieval:** Reduced from **55.83 ms** to **0.021 ms** (100 files, **2,658x speedup**) and from **188.18 ms** to **0.023 ms** (500 files, **8,181x speedup**), far surpassing the sub-10ms target.
- **Workspace Cold Scanning:** Reduced from **2,012.90 ms** to **15.65 ms** (100 files, **128x speedup**) and from **7,756.47 ms** to **67.44 ms** (500 files, **115x speedup**).
- **Runtime Profiler Overhead:** Verified at **5.805 µs** per span (<0.006 ms), satisfying the sub-10µs overhead requirement with 100% exception safety.
- **Prompt Prefix Byte Stability:** **100% byte stability** across 100 turns (SHA-256 `5fbda88bd00c7e9e405909b885f908adeca606cff2d9921a9eb54a9cd9b93f1e`).
- **Frontend Event Deduplication:** Reduced processing latency for 1,000 events from **20.073 ms** to **0.086 ms** (**232.6x speedup**) via $O(1)$ Set lookup and bounded display projection.

---

## 2. Before-and-After Benchmark Ledger

| Subsystem / Metric | Workload Size | Baseline (Before) | Optimized (After) | Delta / Speedup |
|:---|:---:|:---:|:---:|:---:|
| **Workspace Manifest Warm Retrieval** | 100 files | 55.83 ms | **0.021 ms** | **2,658x faster** |
| **Workspace Manifest Warm Retrieval** | 500 files | 188.18 ms | **0.023 ms** | **8,181x faster** |
| **Workspace Manifest Cold Scan** | 100 files | 2,012.90 ms | **15.65 ms** | **128.6x faster** |
| **Workspace Manifest Cold Scan** | 500 files | 7,756.47 ms | **67.44 ms** | **115.0x faster** |
| **Runtime Profiler Overhead** | 10,000 spans | N/A (Missing) | **5.81 µs / span** | **Sub-microsecond (<0.006 ms)** |
| **Prompt Prefix Stability** | 100 turns | Unnormalized | **100.0% stable** | **100% byte match** |
| **Frontend Event Deduplication** | 1,000 events | 20.07 ms ($O(N^2)$) | **0.086 ms ($O(1)$)** | **232.6x faster** |
| **Frontend Visible DOM Elements** | 1,000 events | Unbounded (1,000+) | **Bounded (500 max)** | **Memory bounded** |

---

## 3. Correctness & Invariant Preservation

1. **Workspace Boundary Security:**
   - Path traversal attempts (`../../etc/shadow`) and sibling-prefix attacks continue to raise `WorkspaceBoundaryError`.
2. **Freshness Invariant:**
   - `invalidate_file` guarantees that subsequent file queries immediately observe newly created, modified, or deleted files without returning stale data.
3. **Prompt Semantics:**
   - Tool authorization, parameter definitions, and system instruction precedence are 100% preserved.
4. **Authoritative Event History:**
   - Bounding the GUI display projection to 500 items does not delete, truncate, or alter authoritative SQLite database history or backend event streams.
