# HERMES KAIROS DAG Execution Architecture
===========================================

**Module:** `core.kairos_dag`  
**Date:** September 1, 2026  
**Status:** PRODUCTION READY  

---

## 1. Core Data Structures & State Machine

### `TaskState`
- `BLOCKED`: Unresolved upstream dependencies.
- `READY`: All prerequisites completed; eligible for scheduling.
- `RUNNING`: Actively executing in a worker task.
- `RETRYING`: Transient error; requeued for retry.
- `FAILED`: Unrecoverable error; blocks dependent tasks.
- `COMPLETED`: Execution and verification passed.
- `CANCELLED`: Aborted by user or cascading cancellation.

### `DependencyGraph`
- Direct topological representation of tasks and dependencies.
- DFS-based cycle detection preventing deadlocks.
- Event-driven topological unblocking: when a task completes, downstream dependents are unblocked immediately.

---

## 2. Hardware-Aware Concurrency Engine

- **GPU Model Serialization:** Enforces `asyncio.Semaphore(1)` around Tier 1 and Tier 2 local model generation, preventing VRAM thrashing and OOM on NVIDIA RTX 3050 6GB.
- **Filesystem Write Set Conflict Locks:** Fine-grained per-file locks prevent concurrent race conditions on shared files.
- **Bounded Concurrency:** Configurable `KAIROS_MAX_CONCURRENCY` (default: 4) for parallel I/O, tests, and non-conflicting tasks.
