# HERMES Phase 10 — Canonical Baseline & Component Inventory

**Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 10 — Fault-Injection and End-to-End Release Gate  
**Platform:** Windows 11 / AMD64  
**Python Runtime:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Date:** 2026-10-13  

---

## 1. Verified Architecture & Component Inventory

| Component / Subsystem | Primary Source Files | Key Interfaces & Responsibilities |
| :--- | :--- | :--- |
| **Runtime State & Reducer** | `core/runtime_state/models.py`<br>`core/runtime_state/reducer.py` | Authoritative mission state, immutable mission-to-workspace binding, attempt numbers, run IDs, task states, watermark tracking, monotonic sequence validation. |
| **Durable Persistence** | `core/persistence/database.py`<br>`core/persistence/blobs.py` | SQLite ACID transactions, `append_mission_events_batch()`, CAS content-addressed blob store with SHA-256 integrity, single-stat CAS deduplication. |
| **Event Bus & Journaling** | `core/event_bus.py` | In-memory sequence counter, pub/sub failure isolation, daemon persistence worker with atomic micro-batching (up to 100 items), retry fallback with exponential backoff, flush on `all_tasks_done`. |
| **Checkpoints & Snapshotting** | `core/checkpoints/file_snapshot.py` | `WorkspaceSnapshotter`, full CAS content SHA-256 verification via `blob_store.put_file`, post-hash `stat_after` concurrency check, component-aware `Path.resolve().is_relative_to()` path containment, directory junction/symlink pruning. |
| **Server & HTTP/SSE API** | `core/server/app.py`<br>`core/server/runtime_adapter.py`<br>`core/server/checks_service.py` | FastAPI application, localhost security middleware, authoritative snapshot retrieval, SSE stream delivery, watermark memoization with multi-attribute cache key, Project Hub endpoints. |
| **Network Recovery & Connectivity** | `core/network/connectivity.py`<br>`core/network/coordinator.py` | Background Internet connectivity monitor with hysteresis, provider outage classification, waiting state transitions, auto-recovery coordinator, flapping and duplication prevention. |
| **Model Transport & Circuit Breaker** | `core/transport/client_manager.py`<br>`models/nvidia_client.py`<br>`models/ollama_client.py` | Shared HTTP client reuse, timeout classification, secret redaction, streaming chunk parsing, circuit breaker pattern, explicit fallback across model tiers. |
| **Frontend GUI & Project Hub** | `gui/src/`<br>`gui/test_snapshot_race.mjs` | React/TypeScript GUI, Vite production bundle, client-side state machine with delayed snapshot rejection, stale event filtering, duplicate deduplication. |

---

## 2. Immutable Three-Tier Model Stack

The established production configuration remains strictly preserved:
1. **Tier 1 (Primary Fast-Path):**
   - Provider: **NVIDIA NIM**
   - Model: `z-ai/glm-5.3-flash`
   - Endpoint: `https://integrate.api.nvidia.com/v1`
   - Authentication: `NVIDIA_API_KEY`
2. **Tier 2 (Secondary Fallback):**
   - Provider: **Ollama Cloud**
   - Model: `gpt-oss:120b-cloud`
   - Daemon: `http://127.0.0.1:11434`
3. **Tier 3 (Tertiary Escalation):**
   - Provider: **Ollama Cloud**
   - Model: `nemotron-3-ultra:cloud`
   - Daemon: `http://127.0.0.1:11434`

---

## 3. Canonical Test Suite Discovery & Inventory

A total of **127 automated tests** across 14 modules are collected and verified:

### 3.1 Core Regression Modules (113 Tests)
1. `tests/test_phase1_mission_lifecycle.py` — **7 tests**
2. `tests/test_phase2_complete.py` — **10 tests**
3. `tests/test_phase3_complete.py` — **12 tests**
4. `tests/test_phase4_stop_control.py` — **8 tests**
5. `tests/test_phase5_resume_control.py` — **10 tests**
6. `tests/test_phase6_transport_hardening.py` — **16 tests**
7. `tests/test_phase7_network_recovery.py` — **15 tests**
8. `tests/test_phase8_gui_integration.py` — **15 tests**
9. `tests/test_stage2_server_and_event_stream.py` — **12 tests**
10. `tests/test_stage9_workspace_hub.py` — **8 tests**

### 3.2 Phase 9 Safety & Audit Modules (14 Tests)
11. `tests/test_phase9_checkpoint_adversarial.py` — **2 tests** (Same-size restored-timestamp content detection, concurrency re-stat)
12. `tests/test_phase9_path_containment.py` — **5 tests** (Prefix attack rejection, nested path validation, symlink rejection, junction pruning, canonical edge cases)
13. `tests/test_phase9_persistence_batch_failure.py` — **3 tests** (Monotonic ordering, transient retry fallback, shutdown draining)
14. `tests/test_phase9_cache_safety.py` — **4 tests** (Task status change invalidation, mission completion invalidation, memory bounds, negative cache bypass)

---

## 4. Browser Testing Infrastructure

- **Browser Executable:** Google Chrome detected at `C:\Program Files\Google\Chrome\Application\chrome.exe`.
- **Protocol:** Chrome DevTools Protocol (CDP) over WebSockets.
- **Client Libraries:** `httpx` 0.28.1 and `websockets` 12.0 installed in the canonical virtual environment.
- **Client Synchronization Test:** `node gui/test_snapshot_race.mjs` (5/5 scenarios).
- **GUI Production Build:** `npm --prefix gui run build` (tsc + vite, 1,602 modules).
