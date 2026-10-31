# HERMES Phase 9 — List of Changed Files

**Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 9 — Performance Baseline, Profiling & Safe Speed Optimization  
**Platform:** Windows 11 / AMD64  
**Date:** 2026-10-13  

---

## 1. Runtime Core Files Modified & Hardened

### 1. `core/checkpoints/file_snapshot.py`
- **Component:** `WorkspaceSnapshotter`
- **Security & Path-Containment Hardening:**
  - Enforced component-aware canonical path containment via `Path.resolve().is_relative_to(self.workspace_root)`.
  - Replaced vulnerable raw `startswith()` string check, eliminating sibling directory prefix bypass (`hermes-evil`).
  - Added Windows directory junction (`is_junction()`) and directory symlink (`is_symlink()`) pruning in `os.walk(followlinks=False)` to prevent traversal into external reparse targets.
  - Preserved CAS content verification via `blob_store.put_file(full_path)` and concurrency detection via `stat_after`.

### 2. `core/persistence/blobs.py`
- **Component:** `BlobStore.put`
- **Performance Tuning:**
  - Replaced redundant `dest_path.exists()` followed by `dest_path.stat()` with a single `try: dest_path.stat() ... except FileNotFoundError`, halving disk stat syscalls on CAS deduplication hits.

### 3. `core/persistence/database.py`
- **Component:** `SQLiteDatabase`
- **Changes & Hardening (Audit C):**
  - Implemented `append_mission_events_batch(self, events: List[Any], session_id: Optional[str] = None) -> int`.
  - Sorts events strictly by monotonic `sequence` prior to batch execution.
  - Executes batch insertion inside a single atomic transaction, updating `missions.last_event_sequence` per mission in one atomic operation.

### 4. `core/event_bus.py`
- **Component:** `EventBus`
- **Changes & Hardening (Audit C):**
  - Upgraded queue consumer loop to drain micro-batches of up to 100 queued events at once.
  - Dispatches grouped events via `append_mission_events_batch()`, drastically cutting down SQLite transaction lock overhead.
  - Wrapped batch dispatch in `try ... finally` to guarantee `task_done()` is always invoked.
  - Added transient batch error fallback: on transaction error, safely falls back to individual retries with exponential backoff before recording in `_persistence_failures`.
  - Fixed `EventBus.flush()` to synchronously wait until `_persist_queue.unfinished_tasks == 0` via `all_tasks_done` condition variable.

### 5. `core/server/checks_service.py`
- **Component:** `extract_mission_checks`
- **Changes & Hardening (Audit D):**
  - Added `_compute_checks_cache_key()` incorporating event sequence, event count, state last sequence, mission status, task status, verification IDs, verification evidence, completion reasons, and failure reasons.
  - Cache invalidates immediately when mission transitions or task status/evidence changes even without new events.
  - Bounded memory footprint with automatic eviction when cache entries exceed 200 items.

### 6. `core/server/app.py`
- **Component:** `get_mission_snapshot`
- **Changes & Hardening (Audit D):**
  - Canonicalized workspace path via `Path(raw_ws).resolve()` before cache key lookup.
  - Added negative cache bypass: non-existent directories are never cached, ensuring directory recreation is detected immediately.
  - Added bounded memory management for `_WS_EXIST_CACHE` (capped at 100 entries).

---

## 2. Benchmark Harness Files

### 1. `benchmarks/benchmark_phase9_baseline.py`
- Comprehensive self-contained benchmark suite measuring event bus dispatch, burst throughput, snapshot assembly at 10/100/500 events, workspace indexing, warm/cold checkpointing, SQLite operations, and control dispatch latency.

---

## 3. Dedicated Audit Test Suites Created

### 1. `tests/test_phase9_path_containment.py` (5 Tests)
- `test_sibling_directory_prefix_attack`: Validates rejection of `hermes-evil/malicious.py`.
- `test_legitimate_nested_paths`: Validates acceptance of legitimate nested workspace files.
- `test_symlink_escape`: Validates rejection of file symlink pointing outside workspace.
- `test_windows_junction_escape`: Validates pruning and rejection of Windows directory junctions targeting external directories.
- `test_path_canonicalization_edge_cases`: Validates mixed case, parent traversal `..`, relative paths, and fail-closed handling.

### 2. `tests/test_phase9_checkpoint_adversarial.py` (2 Tests)
- `test_adversarial_same_size_content_with_restored_mtime`: Proves same-size restored-mtime modified files are accurately detected as modified.
- `test_concurrent_modification_during_snapshot_recovery`: Proves files modified concurrently during snapshotting are re-evaluated safely.

### 3. `tests/test_phase9_persistence_batch_failure.py` (3 Tests)
- `test_mixed_mission_batch_monotonic_ordering`: Proves mixed-mission event batches maintain strict monotonic sequence order and per-mission watermarks.
- `test_batch_failure_fallback_to_individual_retries`: Proves batch failures gracefully fall back to individual retries without event loss.
- `test_shutdown_drains_queued_events`: Proves shutdown flushes all pending journal writes before thread exit.

### 4. `tests/test_phase9_cache_safety.py` (4 Tests)
- `test_checks_cache_invalidates_on_task_status_change`: Proves cache invalidates when task state changes without events.
- `test_checks_cache_invalidates_on_mission_completion`: Proves cache invalidates on mission terminal status changes.
- `test_checks_cache_bounded_memory`: Proves cache size is bounded against memory leaks.
- `test_workspace_negative_cache_bypass`: Proves workspace recreation is seen immediately without negative cache stale hits.

---

## 4. Artifact Files Maintained in `artifacts/phase9/`

- `artifacts/phase9/performance_audit.md`: Bottleneck profiling and architectural analysis.
- `artifacts/phase9/baseline_results.md`: Authoritative pre-optimization baseline metrics.
- `artifacts/phase9/baseline_metrics.json`: Machine-readable baseline data.
- `artifacts/phase9/optimization_plan.md`: Targeted optimization strategy and safety invariants.
- `artifacts/phase9/optimization_results.md`: Before vs. After comparison and percentage improvements.
- `artifacts/phase9/optimized_metrics.json`: Machine-readable post-optimization data.
- `artifacts/phase9/final_metrics.json`: Authoritative post-tuning benchmark metrics.
- `artifacts/phase9/final_audit_results.md`: Path containment security audit and throughput reconciliation.
- `artifacts/phase9/safety_regression_results.md`: Complete regression suite and race test logs.
- `artifacts/phase9/changed_files.md`: Inventory of modified code and test files.
- `artifacts/phase9/acceptance_report.md`: Formal Phase 9 sign-off and verification report.
