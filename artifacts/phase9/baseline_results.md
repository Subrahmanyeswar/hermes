# HERMES Phase 9 — Performance Baseline Measurement Results

**Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 9 — Measure and Optimize Speed  
**Platform:** Windows 11 / AMD64  
**Python Runtime:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Harness:** `benchmarks/benchmark_phase9_baseline.py`  
**Execution Timestamp:** 2026-10-13T15:37:31Z  
**Status:** Canonical Baseline Established  

---

## 1. Summary of Baseline Metrics

The following metrics represent the authoritative, pre-optimization baseline measured under canonical environment conditions.

### 1.1 Event Bus & Dispatch Latency
| Metric | Value | Target Criteria | Status |
| :--- | :--- | :--- | :--- |
| **Single Publish Latency (P50)** | **0.0079 ms** | < 0.05 ms | PASS |
| **Single Publish Latency (P95)** | **0.0138 ms** | < 0.10 ms | PASS |
| **Single Publish Average** | **0.0107 ms** | < 0.10 ms | PASS |
| **Burst Throughput (5,000 events)** | **77,479 events/sec** | > 10,000 events/sec | PASS |
| **Burst Total Duration (5,000 events)** | **64.53 ms** | < 250 ms | PASS |
| **Replay 500 Events from Journal** | **215.20 ms** | Bottleneck Target | High Disk Contention |

*Analysis:* While in-memory publish is sub-millisecond, un-batched SQLite journal flushing creates significant lock contention during concurrent replay queries.

---

### 1.2 Snapshot Assembly & Checks Extraction Latency
| Metric | P50 (ms) | P95 (ms) | Mean (ms) | Scaling Observation |
| :--- | :--- | :--- | :--- | :--- |
| **Snapshot Assembly (10 events)** | **0.194 ms** | **0.315 ms** | **0.210 ms** | Fast baseline |
| **Snapshot Assembly (100 events)** | **0.271 ms** | **0.512 ms** | **0.315 ms** | +39.7% growth vs 10 events |
| **Snapshot Assembly (500 events)** | **0.535 ms** | **0.729 ms** | **0.561 ms** | +175.8% growth vs 10 events |

*Analysis:* Latency increases linearly with event scale due to full event-array scanning, synchronous filesystem checks (`Path.exists()`), and full re-extraction of verification checks on every snapshot poll.

---

### 1.3 Workspace Indexing & Checkpoint Snapshotting Latency
| Metric | Duration (ms) | Files / Operations | Analysis |
| :--- | :--- | :--- | :--- |
| **Cold Workspace Index** | **112.05 ms** | 50 files indexed | Initial AST + symbol scan |
| **Warm Workspace Refresh** | **23.65 ms** | 0 files changed | Incremental mtime check |
| **Cold Checkpoint Snapshot** | **192.59 ms** | 50 files streamed to CAS | Full file hashing & blob write |
| **Warm Checkpoint Snapshot (0 changes)** | **23.73 ms** | 50 files (unmodified) | Re-reads & re-hashes all 50 files |
| **Single File Modified Checkpoint** | **29.98 ms** | 1 modified, 49 unchanged | Re-hashes all unchanged files |

*Analysis:* In `WorkspaceSnapshotter`, untouched files are unconditionally re-read from disk and re-hashed with SHA-256 despite being identical to `prior_manifest`.

---

### 1.4 Persistence Layer (SQLite Database Operations)
| Operation | P50 Latency (ms) | Mean Latency (ms) | Sample Size |
| :--- | :--- | :--- | :--- |
| **Mission Record Creation** | **0.026 ms** | **0.033 ms** | 50 iterations |
| **Single Event Journal Append** | **0.085 ms** | **0.100 ms** | 100 iterations |
| **Runtime Snapshot Save** | **0.055 ms** | **0.068 ms** | 20 iterations |
| **Runtime Snapshot Read** | **0.031 ms** | **0.036 ms** | 50 iterations |

*Analysis:* Individual SQLite operations are sub-millisecond, but lack of batching in the persistence worker queue amplifies I/O under sustained event bursts.

---

### 1.5 Mission Control & Lifecycle Latency
| Control Action | P50 Latency (ms) | Mean Latency (ms) | Notes |
| :--- | :--- | :--- | :--- |
| **Pause Request Dispatch** | **0.0182 ms** | **0.0206 ms** | In-flight pause flag signal |
| **Stop Request Dispatch** | **0.0006 ms** | **0.0009 ms** | Abort event set |

*Analysis:* Mission lifecycle signaling is fast and non-blocking in memory.

---

## 2. Baseline Conclusions
The baseline benchmarks establish that the core in-memory runtime is fast. The primary latency bottlenecks stem from:
1. **Redundant file reading and SHA-256 rehashing** on warm checkpoints in `WorkspaceSnapshotter`.
2. **Synchronous filesystem existence checks and full linear event scanning** on every GUI snapshot poll in `core/server/app.py`.
3. **Un-batched SQLite journal writes** in `EventBus._persistence_worker_loop`.

These targets form the basis of the Phase 9 Optimization Plan.
