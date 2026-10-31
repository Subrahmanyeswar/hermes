# HERMES Phase 10 — Performance Baseline Report

**Execution Date:** 2026-10-22  
**Platform:** Windows 11  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Git Branch:** `hermes-2.x`  

---

## 1. Executive Summary

Prior to making any optimization changes, empirical measurements were captured on representative workloads using isolated synthetic temporary testbeds.

### Key Measured Bottlenecks:
1. **Workspace Manifest Scanning & Hashing Latency:**
   - On a 100-file project, initial cold indexing takes **2,012.90 ms** (~2.01s).
   - On a 500-file project, initial cold indexing takes **7,756.47 ms** (~7.76s).
   - Warm refresh (incremental scan through `workspace_indexer`) takes **55.83 ms** for 100 files and **188.18 ms** for 500 files.
   - For an agent executing repetitive file queries (`find_artifact`, `validate_path`, skeleton inspection), hitting the disk and database repeatedly imposes high latency. An in-memory, thread-safe, boundary-enforcing `WorkspaceCache` can provide sub-millisecond retrieval (<1ms) with immediate invalidation on mutations.
2. **Runtime Profiler Gap:**
   - HERMES lacks a centralized, low-overhead span-based profiler (`core/profiler.py`) that can measure async and sync stages with sub-microsecond overhead (<0.01ms) without modifying application exception behavior.
3. **Prompt Prefix Stability & Tool Schema Normalization:**
   - Prompt assembly is fast (~23.36 µs), but lacks a formal `PromptCacheOptimizer` ensuring deterministic sorting of tool schemas and canonical hash calculation to maximize potential LLM KV-cache reuse.
4. **Frontend Event Synchronization Overhead:**
   - In `gui/src/sync.ts`, event deduplication performs an $O(N)$ linear scan (`currentState.events.some(...)`) over an unbounded in-memory array. With 1,000+ events, this incurs $O(N^2)$ checks and unbounded DOM nodes in `ActivityPanel.tsx`.

---

## 2. Empirical Baseline Measurements

| Metric | Workload Size | Baseline Measurement | Unit |
|:---|:---:|:---:|:---:|
| `workspace_cold_lock_ms` | 100 files | **2012.90** | ms |
| `workspace_cold_lock_ms` | 500 files | **7756.47** | ms |
| `workspace_warm_refresh_ms` | 100 files | **55.83** | ms |
| `workspace_warm_refresh_ms` | 500 files | **188.18** | ms |
| `prompt_assembly_per_call` | 200 iterations | **23.36** | µs |
| `frontend_dedup_complexity` | N events | **$O(N)$ per event / $O(N^2)$ cumulative** | algorithmic |

---

## 3. Targeted Optimization Hypotheses & Acceptance Targets

1. **`core/profiler.py`:**
   - Implement low-overhead runtime profiler context manager.
   - Acceptance target: Per-span measurement overhead < 0.01 ms (<10 µs); 100% exception safety; thread/async safe.
2. **`core/workspace_cache.py`:**
   - Implement incremental, in-memory workspace cache with precise invalidation on write/edit/delete.
   - Acceptance target: Warm manifest query duration reduced from 55-188 ms to < 1.0 ms (>50x improvement) while maintaining 100% boundary safety and freshness.
3. **`core/prompt_cache_optimizer.py`:**
   - Implement deterministic tool schema sorting and static prefix byte verification.
   - Acceptance target: 100% byte stability across repeated identical queries; schema change correctly invalidates prefix hash.
4. **Frontend Rendering & Event Synchronization (`gui/src/sync.ts` & `ActivityPanel.tsx`):**
   - Replace $O(N)$ linear scan with Set-based $O(1)$ duplicate lookup.
   - Bound in-memory GUI event rendering window to 500 items while preserving all backend events.
   - Acceptance target: Event processing reduces from $O(N)$ to $O(1)$; frontend build succeeds cleanly.
