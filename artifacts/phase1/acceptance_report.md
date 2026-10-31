# HERMES — Phase 1: Canonical Mission Lifecycle and Run Control Acceptance Report

**Date:** 2026-10-12  
**Branch:** `hermes-2.x`  
**Interpreter:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Status:** COMPLETE & PASSING  

---

## 1. Executive Summary

Phase 1 establishes the canonical mission lifecycle and isolated run-control foundation for HERMES v1.0.0-rc1. All objectives have been implemented and verified with zero regression to existing systems:
1. **Authoritative Mission State Machine:** Formally defined `LEGAL_MISSION_TRANSITIONS` and `is_legal_mission_transition` across all 10 canonical statuses (`CREATED`, `PLANNING`, `RUNNING`, `WAITING`, `PAUSED`, `COMPLETING`, `COMPLETED`, `FAILED`, `CANCELLED`, `ABORTED`).
2. **Terminal-State Immutability:** Formally guarded terminal states (`COMPLETED`, `FAILED`, `CANCELLED`, `ABORTED`) against resurrection or regression by late model turns, tool completions, or cancellations.
3. **Stable Identity and Monotonic Attempts:** Propagated stable `mission_id`, unique per-run `run_id`, and monotonic `attempt_number` through `MissionState`, `HermesEvent`, `StateReducer`, `Mission`, `AgentLoop`, `MissionSnapshot`, and GUI TypeScript models.
4. **Isolated Execution Controls:** Eliminated shared mutable abort events on cached `ApplicationRuntime` by implementing `MissionControlContext` and per-run scoped `AgentLoop` instantiation in `RuntimeAdapter`.
5. **Precise Control Semantics:** Formally defined and tested semantics for **Stop**, **Pause**, **Cancel**, and **Resume**. Durable checkpoint recovery is explicitly deferred to Phase 2/3 without false claims of cold persistence.
6. **Zero Breaking Changes:** Maintained 100% backward compatibility with Project Hub, workspace locking, SSE event streaming, process safety, and the frontend GUI (`npm run build` passes).

---

## 2. Transition Matrix Summary

| State | Allowed Next States | Strictly Forbidden Next States | Is Terminal |
|---|---|---|:---:|
| `CREATED` | `PLANNING`, `RUNNING`, `CANCELLED`, `ABORTED` | `WAITING`, `PAUSED`, `COMPLETING`, `COMPLETED`, `FAILED` | No |
| `PLANNING` | `RUNNING`, `WAITING`, `PAUSED`, `FAILED`, `CANCELLED`, `ABORTED` | `CREATED`, `COMPLETING`, `COMPLETED` | No |
| `RUNNING` | `WAITING`, `PAUSED`, `COMPLETING`, `COMPLETED`, `FAILED`, `CANCELLED`, `ABORTED` | `CREATED`, `PLANNING` | No |
| `WAITING` | `RUNNING`, `PAUSED`, `COMPLETING`, `FAILED`, `CANCELLED`, `ABORTED` | `CREATED`, `PLANNING`, `COMPLETED` | No |
| `PAUSED` | `RUNNING`, `CANCELLED`, `ABORTED` | `CREATED`, `PLANNING`, `WAITING`, `COMPLETING`, `COMPLETED`, `FAILED` | No |
| `COMPLETING` | `COMPLETED`, `FAILED`, `CANCELLED`, `ABORTED` | `CREATED`, `PLANNING`, `RUNNING`, `WAITING`, `PAUSED` | No |
| `COMPLETED` | *None* | All states | **Yes** |
| `FAILED` | *None* | All states | **Yes** |
| `CANCELLED` | *None* | All states | **Yes** |
| `ABORTED` | *None* | All states | **Yes** |

---

## 3. Implementation Details & Architecture Rectification

### 3.1. Elimination of Cross-Mission Abort Contamination
- **Prior Defect:** In `core/server/runtime_adapter.py`, `rt = await self.get_or_create_runtime(workspace_root)` cached runtimes per workspace root. Calling `start_mission` directly set `rt.cancellation.global_abort_event = abort_evt` and `rt.agent_loop.abort_event = abort_evt`. This caused any subsequent mission in the same workspace to overwrite the abort event of running missions, allowing stop signals to cross-contaminate.
- **Rectification:** Introduced `MissionControlContext` in `core/runtime_state/models.py`. In `RuntimeAdapter`, each mission run receives an isolated `MissionControlContext` containing its own `abort_event` and `pause_event`. Furthermore, an isolated `AgentLoop` is instantiated for each mission run, ensuring full lifecycle isolation.

### 3.2. Pure State Reduction and Identity Validation
- `core/runtime_state/reducer.py` now enforces:
  - Dropping cross-mission events (`event.mission_id != state.mission.mission_id`).
  - Dropping stale run events (`event.run_id != state.mission.run_id`).
  - Strict validation of `is_legal_mission_transition(state.mission.status, target_status)`. Invalid transitions are recorded in `state.metadata["last_invalid_transition"]` without modifying state.
  - Rejection of out-of-order sequence regressing state (`event.sequence <= state.last_event_sequence`).

### 3.3. Identity Model Propagation
- `core/runtime_state/models.py`: Added `run_id` and `attempt_number` to `MissionState`, `HermesRuntimeState.create_empty()`, and defined `MissionControlContext`.
- `core/runtime_state/events.py`: Added `run_id` and `attempt_number` to `HermesEvent`.
- `core/mission_planner.py`: Added `run_id`, `attempt_number`, and `abort_event` to `Mission`.
- `core/agent_loop/loop.py`: Propagated `run_id` and `attempt_number` across all agent turn events, and added `pause_event` awareness.
- `core/server/models.py` & `core/server/app.py`: Added `run_id` and `attempt_number` to `MissionSnapshot` with defensive coercion.
- `gui/src/types.ts`: Added `run_id` and `attempt_number` to `MissionSnapshot` and `HermesEvent`.

---

## 4. Test Verification Evidence

### 4.1. Acceptance Suite (`tests/test_phase1_mission_lifecycle.py`)
- **Scenario A:** Complete Legal Transition Graph Coverage — **PASSED**
- **Scenario B:** Comprehensive Illegal Transition Rejection — **PASSED**
- **Scenario C:** Terminal-State Immutability — **PASSED**
- **Scenario D:** Mission Identity Stability & Monotonic Attempts — **PASSED**
- **Scenario E:** Concurrent Run-Control Isolation — **PASSED**
- **Scenario F:** Workspace Binding & Snapshot Consistency — **PASSED**
- **Scenario G:** Safe Run-Control Operations (Stop, Pause, Cancel, Resume) — **PASSED**

### 4.2. Full Regression Suite (60/60 PASSED)
Executed command:
```powershell
& "C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe" -m pytest `
  tests/test_phase1_mission_lifecycle.py `
  tests/test_runtime_state.py `
  tests/test_stage9_workspace_hub.py `
  tests/test_stage2_server_and_event_stream.py `
  tests/test_tool_workspace_enforcement.py `
  tests/test_persistence_database.py `
  tests/test_stage5_1_process_safety.py -v
```
**Result:** **60 passed in 13.50s**. Zero failures.

### 4.3. Production GUI Build
Executed command:
```powershell
npm --prefix gui run build
```
**Result:** Built cleanly in 1.92s with zero TypeScript compiler or Vite errors.

---

## 5. Artifact Directory Inventory

The following evidence files are published in `artifacts/phase1/`:
- `artifacts/phase1/acceptance_report.md`: Complete Phase 1 acceptance documentation.
- `artifacts/phase1/mission_transition_matrix.json`: Machine-readable specification of legal and illegal transitions.
- `artifacts/phase1/mission_identity_evidence.json`: Identity structure and propagation contracts across backend and frontend.
- `artifacts/phase1/run_control_isolation.json`: Run control isolation architecture and lifecycle operational contracts.

---

## 6. Phase Continuity & Non-Destructive Invariant Compliance
- **Zero Destructive Git Commands:** No commits, resets, cleanups, or checkouts were performed.
- **Model Stack Preservation:** Locked models (NVIDIA NIM `z-ai/glm-5.3-flash`, Ollama `gpt-oss:120b-cloud`, Ollama `nemotron-3-ultra:cloud`) remained completely untouched; zero external API requests were triggered during test runs.
- **Boundary Preservation:** Campus Lab Manager and unrelated directories were untouched.
- **Phase 2 Hand-off:** The lifecycle and execution-control contract is now established. Durable checkpoints and cold recovery are cleanly unblocked for Phase 2.
