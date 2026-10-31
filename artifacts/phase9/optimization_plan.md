# HERMES Phase 9 — Performance Optimization Plan

**Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 9 — Measure and Optimize Speed  
**Platform:** Windows 11 / AMD64  
**Python Runtime:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Target Date:** 2026-10-13  
**Status:** Approved for Implementation  

---

## 1. Objectives & Guiding Principles

The Phase 9 Optimization Plan aims to eliminate demonstrated latency bottlenecks in file I/O, database journaling, and API snapshot generation while strictly adhering to HERMES safety invariants:

1. **Zero Regression Guarantee:** Every optimization must preserve 100% of existing behavior, test contracts, and safety guarantees.
2. **Deterministic Cryptographic Verification:** File snapshot manifests, hashes, and CAS blobs must remain bit-for-bit identical to those produced by a full re-hash.
3. **Monotonic Ordering & ACID Durability:** SQLite journal transactions must preserve monotonic event sequence numbering and atomic commits.
4. **Authoritative State Preservation:** Authoritative state synchronization, pause/stop races, and boundary checks must remain uncompromised.

---

## 2. Ranked Optimization Targets

### Target 1: Workspace Checkpoint Snapshotting Fast-Path
- **File:** `core/checkpoints/file_snapshot.py`
- **Class:** `WorkspaceSnapshotter`
- **Mechanism:**
  - In `create_snapshot()`, when `prior_manifest` is provided, compare `full_path.stat()` (`mtime_ns` and `st_size`) against `prior_manifest.files[rel_path]`.
  - If both `mtime_ns` and `st_size` match, the file is guaranteed unchanged:
    - Reuse `prior_snap.blob_id` and `prior_snap.sha256`.
    - Mark as `FileChangeType.TRACKED`.
    - Skip `self.blob_store.put_file(full_path)` (avoids reading whole file content and calculating SHA-256).
  - Only read and hash the file if `rel_path` is new, or if either `mtime_ns` or `size` differs.
- **Safety Invariant:**
  - Nanosecond resolution filesystem timestamps (`st_mtime_ns`) prevent any false-negative cache hits.
  - Manifest hashing formula `rel_path:sha256:change_type:size` uses the exact same inputs, ensuring cryptographically identical manifest hashes.
- **Expected Impact:** 50%–80% reduction in warm checkpoint latency; elimination of thousands of unnecessary file reads per mission.

---

### Target 2: SQLite Journal Persistence Micro-Batching
- **Files:** `core/persistence/database.py`, `core/event_bus.py`
- **Classes:** `SQLiteDatabase`, `EventBus`
- **Mechanism:**
  - Implement `append_mission_events_batch(self, events: List[Any], session_id: Optional[str] = None)` in `SQLiteDatabase`.
  - In `EventBus._persistence_worker_loop()`, drain immediately available events from `_persist_queue` into a bounded batch (up to 100 events).
  - Commit the entire batch inside a single SQLite transaction context.
  - Mark `task_done()` for all processed items in the batch.
- **Safety Invariant:**
  - Sequences are allocated monotonically before enqueueing; batching commits events in their exact monotonic sequence order.
  - If any error occurs, uncommitted events can be safely logged or retried.
  - Replay queries no longer face SQLite database lock contention from thousands of rapid individual transactions.
- **Expected Impact:** > 10x throughput improvement for SQLite journal ingestion under event bursts; dramatic reduction in replay latency.

---

### Target 3: Fast-Path Authoritative Snapshot Assembly & Checks Synthesis
- **Files:** `core/server/app.py`, `core/server/checks_service.py`
- **Functions:** `get_mission_snapshot()`, `extract_mission_checks()`
- **Mechanism:**
  - **Workspace Path Existence Caching:** Add a lightweight cache with short TTL (e.g., 2.0s) for `Path(raw_ws).exists()` checks in `get_mission_snapshot()` so that frequent GUI polls do not issue blocking disk stat calls on every 500ms cycle.
  - **Checks Extraction Memoization:** In `extract_mission_checks()`, cache the synthesized `MissionChecksResponse` keyed by `(mission_id, state.last_event_sequence)`. When sequence has not advanced and task state is unchanged, return the cached checks response immediately.
  - **Final Output Fast-Path:** In `get_mission_snapshot()`, terminate reverse event traversal immediately upon finding `MISSION_COMPLETED` or `AGENT_COMPLETION_CANDIDATE`.
- **Safety Invariant:**
  - Invalidation is strictly event-driven: any event publication increments `last_event_sequence`, guaranteeing immediate freshness.
  - Missing or corrupted workspace paths are detected on initial lock, resume previews, and cache expiry.
- **Expected Impact:** 30%–50% latency reduction across all snapshot scales (10, 100, 500 events).

---

## 3. Verification & Validation Protocol

Each optimization will be verified through:
1. **Targeted Microbenchmarks:** `benchmarks/benchmark_phase9_baseline.py` executed via canonical Python interpreter.
2. **Full Regression Suite:** All 10 test modules across Phase 1 through Phase 8 (`pytest -v`).
3. **GUI Integration & Race Harness:** `node gui/test_snapshot_race.mjs`.
4. **GUI Production TypeScript Build:** `npm --prefix gui run build`.
