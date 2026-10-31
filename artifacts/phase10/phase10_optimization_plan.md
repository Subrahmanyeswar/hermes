# HERMES Phase 10 — Optimization Plan

**Phase:** 10  
**Title:** Performance Profiling, Incremental Workspace Auditing, Prompt-Prefix Optimization, Connection Reuse & Frontend Rendering Efficiency  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Git Branch:** `hermes-2.x`  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  

---

## 1. Architecture & Optimization Increments

In accordance with the Phase 10 directive:
**INSPECT → MEASURE BASELINE → IDENTIFY BOTTLENECK → MAKE ONE BOUNDED CHANGE → MEASURE AGAIN → RUN REGRESSIONS → VERIFY ACCEPTANCE → LOCK.**

We will execute 4 bounded optimization increments, followed by benchmark measurements and comprehensive regression testing.

### Increment A: Runtime Profiler (`core/profiler.py`)
- **Objective:** Provide a lightweight, zero-overhead span-based profiler for measuring async and sync execution stages without altering application semantics.
- **Invariants:**
  * Uses `time.perf_counter_ns()` for monotonic high-resolution timing.
  * Exception-safe: preserves and re-raises any exception while recording status in span.
  * Thread-safe and async-safe using thread-local / context-local storage.
  * Bounded in-memory telemetry buffer (e.g. max 1,000 spans) with explicit JSON export.
  * Never leaks sensitive data (prompts, API keys, credentials).
  * Per-span overhead target: < 0.01 ms (<10 µs).

### Increment B: Prompt Prefix Optimizer (`core/prompt_cache_optimizer.py`)
- **Objective:** Maximize provider-side KV cache reuse and ensure deterministic prompt prefix assembly.
- **Invariants:**
  * Normalizes and deterministically sorts tool schemas by canonical tool name.
  * Separates invariant static prefix (system role, static guidelines, canonical tool schemas) from dynamic task context (workspace state, memory, conversation turns).
  * Calculates stable SHA-256 prefix hash.
  * Prefix byte stability: 100% byte-for-byte identical across equivalent turns.
  * Does not alter instruction precedence or tool authorization.

### Increment C: Incremental Workspace Manifest Cache (`core/workspace_cache.py`)
- **Objective:** Accelerate repetitive workspace manifest, file metadata, and existence checks.
- **Invariants:**
  * Caches file metadata (path, size, mtime) and directory tree hierarchy in memory.
  * Fast manifest retrieval (< 1.0 ms vs 55-188 ms warm refresh).
  * Precise invalidation on file write, edit, create, delete, or rename. Invalidation cascades to parent directories.
  * Strict boundary safety: rejects relative traversals (`../../`) and sibling prefix bypasses via `WorkspaceBoundaryError`.
  * Preserves ignore policies (`.git`, `.hermes`, `.artifacts`, `node_modules`, `venv`, `__pycache__`).

### Increment D: Frontend Rendering & Event Synchronization (`gui/src/sync.ts` & `ActivityPanel.tsx`)
- **Objective:** Eliminate $O(N^2)$ cumulative event deduplication lag and prevent unbounded DOM growth in long missions.
- **Invariants:**
  * Introduce Set-based $O(1)$ lookup for seen event IDs and sequences in `gui/src/sync.ts`.
  * Bound visible in-memory event projection to 500 items in GUI while preserving all backend events.
  * Do not truncate or delete backend database records or state store history.
  * Retain Orchid Lilac / Forest Green palette and fixed non-interactive `AUTO` badge.
  * Run Vite production build (`npm run build`).

---

## 2. Test & Verification Plan

1. **Dedicated Test Suite (`tests/test_performance_optimization.py`):**
   - Profiler: duration recording, exception safety, async/sync spans, bounded buffer, overhead check.
   - Prompt Optimizer: deterministic tool sorting, prefix byte stability, schema invalidation.
   - Workspace Cache: initial scan, warm retrieval < 1ms, precise invalidation on write/delete, boundary containment.
   - HTTP Connection Reuse: verify `TransportClientManager` client reuse and lifecycle closing.
2. **Targeted Regressions:**
   - Phase 9 Reliability & Security suites (25 tests).
   - Phase 8 Architecture suites (20 tests).
   - Phase 7 Frontend & Design suites (23 tests).
   - Phase 6 Registry suites (26 tests).
   - Project Intelligence suite (20 tests).
   - Phase 5 Gate & Fencing suites (12 tests).
3. **Evidence Artifacts:**
   - `phase10_before_after_benchmarks.md`
   - `phase10_test_results.md`
   - `phase10_final_closure_evidence.json`
   - `phase10_final_closure_report.md`
