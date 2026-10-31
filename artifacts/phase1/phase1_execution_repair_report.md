# HERMES Phase 1: Critical Execution Repair, Greenfield Build Support, and Truthful Failure Handling

**Author:** Principal Runtime Engineer & Software Reliability Architect  
**Date:** 2026-10-21  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Interpreter:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Branch:** `hermes-2.x`  
**Status:** Verification Passed (100% Acceptance & Regression Suite Clean)

---

## 1. Executive Summary

Phase 1 focused on resolving critical execution defects identified in the Phase 0 forensic baseline audit:
1. **Greenfield Task False-Positive Preflight Rejection:** Prompts requesting new applications (such as the LabFlow reference prompt) that contained conditional negative safety instructions (e.g., *"If any existing files are present, do not overwrite them"*) were erroneously triggering `EMPTY_WORKSPACE_EXISTING_APPLICATION` and failing preflight in empty workspaces. Furthermore, the initialization of `.artifacts/missions/...` by `MissionPlanningService` was inadvertently recognized as application files due to a missing hidden directory filter.
2. **File Tool Atomicity & Resiliency:** Hardened `tools/file_tools.py` (`WriteFileTool` and `ReadFileTool`) by introducing Pydantic model coercion for dictionary inputs, atomic staging writes with Windows file-lock retry, and directory auto-creation.
3. **Truthful Outage Handling (Condition C & D):** Prevented `AgentLoop` from exhausting its 5-turn consecutive failure budget when encountering external network or provider outages. Instead, the loop now truthfully enters `WAITING` (`WAITING_FOR_PROVIDER` or `WAITING_FOR_NETWORK`) with full durable recovery state preserved.
4. **Activity Stream Synchronization:** Repaired the event-history clearing race in `gui/src/App.tsx`. Snapshots arriving from polling or event notifications no longer wipe the accumulated event history for `ActivityPanel`. Events are now deduplicated in a bounded ring buffer (1000 events max).
5. **Runtime Identity Verification:** Added code fingerprinting (`SHA-256` of core runtime files), process ID attribution, and server startup timestamp verification to `/api/health` and `core/server/launcher.py` to prevent undetected server-code mismatch.

---

## 2. Forensic Investigation & Implementation Details

### 2.1 Greenfield vs. Modification Preflight Logic (`core/agent_loop/loop.py`)
- **Root Cause 1 (Regex False-Positive):** The previous classification regex was matching the substring `"existing"` inside negative safety instructions such as `"if any existing files are present, do not overwrite"`.
- **Root Cause 2 (Metadata File Match):** `MissionPlanningService` initialized before preflight, writing `progress.json` into `.artifacts/missions/<mission_id>/`. Because `.artifacts` was not in `_WS_IGNORE_PATTERNS`, `p.name` (`progress.json`) was treated as an existing application file.
- **Fix:**
  - Added `_should_require_existing_application(prompt: str)` which strips conditional clauses matching `\bif\s+(?:any\s+)?existing\b.*?\b(?:do\s+not|report|preserve|skip|wait|halt)\b` and negative instructions matching `\bdo\s+not\s+(?:overwrite|modify|delete|change)\s+existing\b`.
  - Added strict modifier pattern checks (`add ... to existing`, `modify existing`, etc.) while checking for `\bfrom\s+scratch\b`.
  - Hardened workspace file scanning to ignore all relative path components starting with `.` (e.g. `.artifacts`, `.hermes`, `.git`, `.venv`) and known metadata roots.
  - Ensured that on preflight rejection, `AgentLoop.run()` emits `EventType.MISSION_FAILED`, saves the mission to the database as `FAILED` with code `EMPTY_WORKSPACE_EXISTING_APPLICATION`, and returns an authoritative `AgentLoopResult` (avoiding bare `None` returns).

### 2.2 File Tool Execution & Atomicity (`tools/file_tools.py`)
- **Pydantic Dictionary Coercion:** When action execution injects execution metadata (such as `_operation_id` or `_workspace`), `WriteFileTool.execute` and `ReadFileTool.execute` (both sync and async) now gracefully instantiate `self.Input(**inp)` if given a raw dictionary.
- **Atomic File Writing:** Non-append writes in `WriteFileTool` now stage content to a temporary sibling file (`.<filename>.tmp_<uuid>`) and use atomic `os.replace` with a 5-attempt retry loop for Windows file-locking tolerances. Parent directories are created with `mkdir(parents=True, exist_ok=True)`.

### 2.3 Truthful Outage Handling & Bounded Failure Progression (`core/agent_loop/loop.py`)
- When model invocation fails in `AgentLoop.run()`, the error is passed to `classify_error_condition(t1_exc, is_internet_online=is_online)`.
- If classified as `CONDITION_C` (fallback provider outage), the loop emits `EventType.MISSION_WAITING`, persists the mission with `status="WAITING"` and `wait_reason="WAITING_FOR_PROVIDER"`, marks the control context as waiting, and exits the loop without burning consecutive failure turns.
- If classified as `CONDITION_D` (network offline), it records `wait_reason="WAITING_FOR_NETWORK"`.
- In `core/server/runtime_adapter.py`, background execution finalization now reconciles any mission whose background worker finished while still in `RUNNING` or `CREATED` to `FAILED`, preventing zombie running missions in SQLite.

### 2.4 Event History Synchronization (`gui/src/App.tsx`)
- In `gui/src/sync.ts`, `processIncomingSnapshot` filters unapplied events whose `sequence <= snapshot.last_sequence`.
- In `gui/src/App.tsx`, `streamEvents` (used by `<ActivityPanel events={streamEvents} />`) was previously being overwritten with `res.nextState.events`. When a snapshot arrived, all events up to `last_sequence` were pruned, causing the next event to overwrite `streamEvents` with a 1-element array.
- In `gui/src/App.tsx`, `setStreamEvents` was refactored to accumulate, deduplicate, and bound events (up to 1000 items) independently of the snapshot buffer. Snapshots update the state/tasks/metrics while preserving the complete event activity history.

### 2.5 Runtime Identity & Code Fingerprinting (`core/server/app.py` & `core/server/launcher.py`)
- Added `_APP_STARTUP_TIME = time.time()` and `_SERVER_CODE_FINGERPRINT = _compute_code_fingerprint()`.
- Updated `/api/health` to expose `startup_time`, `pid`, `code_fingerprint`, and `code_match`.
- Updated `core/server/launcher.py` with `compute_local_code_fingerprint()` so that health checks verify if the server listening on the port matches the code on disk.

---

## 3. Test & Verification Results

| Suite / Test File | Tests Run | Result | Key Invariants Verified |
| :--- | :---: | :---: | :--- |
| `tests/test_incident_planning_and_lifecycle_recovery.py` | 14 | **PASSED** (14/14) | Preflight greenfield/existing discrimination, Condition C/D outage handling, circuit recovery, multi-attempt run identity. |
| `tests/test_phase1_mission_lifecycle.py` | 7 | **PASSED** (7/7) | Concurrent run control isolation, legal transition graph, terminal immutability, immutable workspace binding. |
| `tests/test_forensic_regressions.py` | 15 | **PASSED** (15/15) | Tool name preservation, workspace prefix containment, repair budget enforcement, canonical launcher parity. |
| `tests/test_phase2_core_runtime_repair.py` | 20 | **PASSED** (20/20) | Read-before-edit, identical write unchanged, duplicate root prevention, topological planning dependencies. |
| `tests/test_stage2_server_and_event_stream.py` | 12 | **PASSED** (12/12) | `/api/health`, workspace listing, snapshot retrieval, SSE ordering, security origin validation, path traversal rejection. |
| `tests/test_stage3_gui_prototype_acceptance.py` | 5 | **PASSED** (5/5) | Static SPA serving, reference failure truth, genuine success verification evidence, stop action cancellation. |
| `tests/test_write_files_batch.py` | 16 | **PASSED** (16/16) | Single/multi file batch writes, parent dir creation, rollback on commit failure, traversal rejection. |
| `tests/test_phase3_file_safety.py` | 9 | **PASSED** (9/9) | Containment rejections, stale file protection, atomic write, newline preservation. |
| `tests/test_final_execution_consistency.py` | 43 | **PASSED** (43/43) | Milestone bounding, markdown stripping, idempotent writes, read loop protection, artifact manifest. |
| `tests/test_agent_loop.py` | 11 | **PASSED** (11/11) | Multi-turn tool execution, model failure resilience, stall detection, cancellation, path discipline. |
| `node gui/test_snapshot_race.mjs` | 5 scenarios | **PASSED** (5/5) | Delayed snapshot rejection against live event, attempt number rejection, duplicate deduplication, buffer reconciliation. |
| Frontend compilation (`npm run build`) | 1602 modules | **PASSED** (0 errors) | TypeScript type checking and Vite production bundling succeeded cleanly in 2.36s. |

**Total Python Tests Verified:** 152 passed, 0 failed.

---

## 4. Acceptance Criteria Verification Matrix

- [x] **Greenfield Execution:** Greenfield prompt (LabFlow) passes preflight without false-positive `EMPTY_WORKSPACE_EXISTING_APPLICATION`.
- [x] **Existing Codebase Protection:** Prompts explicitly requesting modification to an existing application fail preflight immediately when the workspace contains 0 application files.
- [x] **File Writing Truthfulness:** File writes are atomic, handle dictionaries and Pydantic inputs cleanly, and reject path traversal outside workspace boundaries.
- [x] **Truthful Failure & WAITING State:** Provider/network outages cleanly transition the mission to `WAITING` instead of burning turn budgets into consecutive failures.
- [x] **Event History Preserved:** ActivityPanel event log is retained across snapshot polls and SSE updates.
- [x] **Runtime Identity:** Server reports PID, startup timestamp, and SHA-256 code fingerprint on `/api/health`.
- [x] **Zero Unapproved Dependencies:** Python 3.12 virtual environment preserved without package additions or modifications.
