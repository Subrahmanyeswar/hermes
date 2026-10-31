# HERMES Phase 9 — Performance Baseline & Bottleneck Audit

**Target Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 9 — Measure and Optimize Speed  
**Platform:** Windows 11 / AMD64  
**Python Runtime:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Timestamp:** 2026-10-13T15:37:31Z  
**Verification Status:** Audit & Baseline Captured  

---

## 1. Executive Summary

A comprehensive performance profiling audit of HERMES v1.0.0-rc1 was executed to measure latency, throughput, disk I/O, event propagation, and state snapshot assembly under realistic agent workloads.

The system was benchmarked using the reproducible harness `benchmarks/benchmark_phase9_baseline.py` across five primary runtime subsystems:
1. **Unified Event Bus & Journal Ingestion** (`core/event_bus.py`, `core/persistence/database.py`)
2. **Authoritative Snapshot Assembly & Verification Checks Extraction** (`core/server/app.py`, `core/server/checks_service.py`)
3. **Workspace Indexing, Boundary Validation & File Snapshotting** (`core/workspace.py`, `core/checkpoints/file_snapshot.py`)
4. **Persistence Layer & SQLite Storage** (`core/persistence/database.py`)
5. **Mission Control & Lifecycle Cancellation Latency** (`core/server/runtime_adapter.py`)

The measurements revealed four clear, quantifiable bottlenecks where safe speed optimizations can yield major performance improvements without compromising data durability, boundary validation, or crash recovery guarantees.

---

## 2. Subsystem Architectural Analysis & Profiling

### Subsystem 1: Event Bus & Journal Persistence Worker (`core/event_bus.py`)
- **Observed Behavior:**
  - Event dispatch in memory is fast: `single_publish_p50` is **0.0079 ms** with burst throughput of **77,479 events/sec**.
  - However, SQLite replay of older events (`replay_500_events_ms`) was measured at **215.20 ms**.
- **Root Cause Analysis:**
  - `EventBus._persistence_worker_loop` processes items from `_persist_queue` in strict 1-by-1 increments.
  - Each item executes `target_db.append_mission_event(event)`, which initiates a discrete SQLite `BEGIN IMMEDIATE TRANSACTION ... COMMIT` cycle.
  - Under event bursts (e.g., streaming chunks, progress ticks, tool outputs), this results in thousands of synchronous disk fsyncs, creating heavy lock contention on `hermes_state.db` and blocking concurrent replay queries.
- **Identified Optimization:**
  - Introduce transaction micro-batching in `_persistence_worker_loop`: drain all queued events (up to a bounded batch size, e.g., 100 items) and commit them in a single SQLite transaction using `append_mission_events_batch`.
  - Maintain an in-memory sequence index in `EventBus` to eliminate unnecessary database fallbacks when queries fall within buffered memory.

### Subsystem 2: Checkpoint File Snapshotting (`core/checkpoints/file_snapshot.py`)
- **Observed Behavior:**
  - Cold checkpoint snapshot on 50 files: **192.59 ms**.
  - Warm checkpoint snapshot with zero file changes: **23.73 ms**.
  - Incremental snapshot with 1 modified file: **29.98 ms**.
- **Root Cause Analysis:**
  - In `WorkspaceSnapshotter.create_snapshot()`, even when a `prior_manifest` is provided, the snapshotter unconditionally executes `self.blob_store.put_file(full_path)` for *every single file*.
  - `put_file()` reads the entire file content from disk in 64KB chunks and computes a full SHA-256 hash.
  - For unmodified files where `mtime_ns` and `size_bytes` exactly match `prior_manifest.files[rel_path]`, the content has not changed and the blob already exists in CAS storage. Re-reading and re-hashing all untouched workspace files on every turn boundary introduces severe disk thrashing.
- **Identified Optimization:**
  - Implement fast-path stat validation: if `prior_manifest` has the file entry with identical `mtime_ns` and `size_bytes`, reuse `prior_snap.blob_id` and mark as `FileChangeType.TRACKED` without re-reading the file from disk.
  - Compute new SHA-256 and store CAS blob *only* when `mtime_ns` or `size_bytes` differs, or when the file is newly added.

### Subsystem 3: Snapshot Assembly & Checks Synthesis (`core/server/app.py`, `core/server/checks_service.py`)
- **Observed Behavior:**
  - 10-event snapshot assembly: **0.194 ms**.
  - 100-event snapshot assembly: **0.271 ms**.
  - 500-event snapshot assembly: **0.535 ms**.
- **Root Cause Analysis:**
  - The endpoint `GET /api/missions/{mission_id}` is polled continuously by the React GUI (at 500ms intervals).
  - On every poll, `get_mission_snapshot()`:
    1. Fetches *all* historical events from sequence 0 via `eff_adapter.get_events_since(mission_id, 0)`.
    2. Performs synchronous filesystem check: `Path(raw_ws).exists()`.
    3. Executes linear scans and reverse scans over all events to find output strings, modified files, and verified task evidence.
    4. Calls `extract_mission_checks()`, which re-parses every single event from the beginning of the mission.
  - As missions accumulate hundreds of events, this repeated work creates linear scaling overhead on every HTTP polling tick.
- **Identified Optimization:**
  - Cache the validated workspace existence check for locked workspaces (avoid synchronous `Path.exists()` syscalls on every 500ms poll).
  - Fast-path final output lookup using reverse iterator short-circuiting.
  - Cache extracted checks keyed by `(mission_id, state.last_event_sequence)`: when no new events have occurred, return the precomputed `MissionChecksResponse` immediately without rescanning historical events.

### Subsystem 4: Workspace Indexing & Incremental Scanning (`core/workspace.py`)
- **Observed Behavior:**
  - Cold workspace index (50 files): **112.05 ms**.
  - Warm workspace refresh: **23.65 ms**.
- **Root Cause Analysis:**
  - In `WorkspaceManager.refresh_index()`, when `WORKSPACE_INTELLIGENCE_ENABLED` is False or during fallback, it calls `_build_index()`, performing a full tree walk.
  - When `WORKSPACE_INTELLIGENCE_ENABLED` is True, it queries SQLite for every file row.
- **Identified Optimization:**
  - Ensure lightweight in-memory mtime/size caching so that unmodified directory hierarchies skip redundant stat operations during `refresh_index()`.

---

## 3. Invariant Safety Evaluation

Before implementing optimizations, all candidate changes were evaluated against the system's hard safety contracts:

| Optimization Target | Potential Risk | Safety Invariant Preserved | Verification Protocol |
| :--- | :--- | :--- | :--- |
| **WorkspaceSnapshotter mtime Cache** | Missed file modification if mtime unchanged | Preserves nanosecond `mtime_ns` check + exact size check. Manifest hash generation formula remains identical. | Checkpoint integrity tests & discrepancy detection. |
| **Persistence Batching** | Out-of-order writes or lost events | Sequence numbers are allocated monotonically before queuing. Single transaction preserves all ACID properties and atomicity. | Full Phase 2 & Phase 8 replay regression suite. |
| **Snapshot Checks Caching** | Stale check status displayed in UI | Cache invalidated whenever `state.last_event_sequence` increments or mission state changes. | Snapshot synchronization tests & race condition script. |
| **Workspace Path Exists Cache** | Unnoticed deleted workspace | Workspace root is validated on mission startup, resume preview, and lock operations. Cache TTL bounded. | Boundary escape tests & 403 enforcement tests. |

---

## 4. Next Steps
1. Record official baseline results in `artifacts/phase9/baseline_results.md`.
2. Produce formal `artifacts/phase9/optimization_plan.md`.
3. Apply targeted optimizations in `core/checkpoints/file_snapshot.py`, `core/persistence/database.py`, `core/event_bus.py`, and `core/server/app.py`.
4. Re-benchmark using `benchmarks/benchmark_phase9_baseline.py` and document improvements in `artifacts/phase9/optimization_results.md`.
5. Run complete 10-module regression suite and GUI production build.
