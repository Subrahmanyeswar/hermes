# HERMES RELIABILITY REPAIR REPORT: STALE RUNNING MISSION LIFECYCLE RECONCILIATION

**Date:** 2026-10-19  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Mandatory Python Interpreter:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Status:** **Fully Diagnosed, Repaired, and Reconciled (241/241 Tests Passing)**

---

## 1. Incident Overview & Root Cause Diagnosis

### The Observed Symptom
In a live session with mission `m_a8442b65` (workspace: `C:\Users\SUBBU\Downloads\test 1`):
- GUI displayed `Status: RUNNING`, `WAITING (WORKING)`, and `wait_reason: WORKING`.
- Clicking "Pause Mission" threw `HTTP 409 Conflict: Mission 'm_a8442b65' is not actively executing (status: RUNNING).`
- Clicking "Stop Mission" failed to transition or clear the stale state.
- No buttons enabled the user to recover or terminate the mission.

### Root Cause Analysis (Code Inspection)
1. **Divergence Between In-Memory State and SQLite Database:**
   When a mission process crashed, was interrupted, or terminated without an active task registered in `adapter._active_tasks` or `adapter._mission_controls`, SQLite retained `status: RUNNING` and `wait_reason: WORKING`.
2. **Defective Stop Control (`RuntimeAdapter.stop_mission`):**
   `stop_mission` only checked `self._active_tasks.get(mission_id)`. If there was no active in-flight worker, `task.cancel()` was skipped, and the method did not transition or persist `CANCELLED` status for missions recorded as `RUNNING` in SQLite.
3. **Uninformative and Rigid Pause Endpoint (`/api/missions/{mission_id}/pause`):**
   When `control` was absent in memory, the pause endpoint rejected the request with HTTP 409 without reconciling the database record, leaving the GUI locked in an unrecoverable state.
4. **Snapshot Desynchronization (`GET /api/missions/{mission_id}`):**
   The snapshot endpoint read `state.mission.status` from `StateStore`, but stale database records or terminal transitions did not forcefully clear `wait_reason: "WORKING"`, allowing `WORKING` to persist in the UI snapshot even for non-working states.
5. **UI Control Blindspot in Composer (`Composer.tsx`):**
   The action controls only rendered Resume/Stop if `isPaused`. When a mission was in waiting/recovery without being explicitly paused, the controls did not render the Resume or Stop buttons.

---

## 2. Architectural Corrections Implemented

### A. Authoritative Stop for Active and Stale Missions (`core/server/runtime_adapter.py`)
- In `stop_mission()`:
  - If an active background task exists (`task and not task.done()`): cancels the task, marks `control.mark_terminal()`, and publishes `MISSION_CANCELLED` to ensure memory state reflects cancellation immediately.
  - If no active task is running (stale execution): checks the SQLite database record and StateStore.
  - If already terminal (`COMPLETED`, `FAILED`, `CANCELLED`, `ABORTED`), returns `False` (idempotent, safe repetition).
  - If non-terminal, emits `MISSION_CANCELLED` via `event_bus.publish_durable()`, marks `control.mark_terminal()`, and synchronously saves `status="CANCELLED"`, `wait_reason="NONE"`, `execution_active=False`, `recovery_required=False` to both `missions` and `snapshots` tables.

### B. Truthful Pause Reconciliation (`core/server/app.py`)
- In `POST /api/missions/{mission_id}/pause`:
  - When `control` is absent and `m_row.get("status") == "RUNNING"`, automatically reconciles the stale record in SQLite to `status="WAITING"`, `wait_reason="WAITING_FOR_RECOVERY"`, `recovery_required=True`, and emits `MISSION_WAITING`.
  - Returns an informative HTTP 409 detail:
    `"Mission '{mission_id}' is not actively executing. Reconciled status to WAITING (WAITING_FOR_RECOVERY). Use Resume to recover or Stop to cancel."`

### C. Snapshot Truthfulness & Terminal Sanitization (`core/server/app.py`)
- In `GET /api/missions/{mission_id}`:
  - When `is_term` is True, forcefully clears `is_paused = False`, `pause_pending = False`, `wait_reason = None`, and `recovery_required = False`.
  - Reconciles status with `m_row` when the database has transitioned to `WAITING` or `CANCELLED`, ensuring the UI snapshot is strictly truthful.

### D. GUI Control Accessibility (`gui/src/components/Composer.tsx`)
- Updated the action controls condition from `isPaused` to:
  `{isPaused || (waitReason && !isRunning) ? (`
  Ensures missions in `WAITING (WAITING_FOR_RECOVERY)` or other non-running waiting states clearly display the Resume and Stop action buttons.

---

## 3. Dedicated Verification Suite (`tests/test_stale_running_control_reconciliation.py`)

12 deterministic test cases covering all lifecycle scenarios:
1. `test_case_1_active_running_mission_stop_cancels_and_persists`: Active running mission Stop requests immediately cancel worker and persist `CANCELLED`.
2. `test_case_2_stale_running_mission_stop_transitions_to_cancelled`: Stale RUNNING mission Stop request without active worker transitions to `CANCELLED` in SQLite (`missions` and `snapshots`) and StateStore.
3. `test_case_3_stop_during_waiting_recovery_state`: Stop during waiting/recovery state safely cancels mission.
4. `test_case_4_active_mission_pause_observes_protocol`: Active mission Pause request observes pause protocol.
5. `test_case_5_stale_running_pause_reconciles_to_waiting`: Stale RUNNING mission Pause request without live worker reconciles to `WAITING` (`WAITING_FOR_RECOVERY`), returns informative blocker, and persists truthful state.
6. `test_case_6_repeated_stop_requests_idempotency`: Repeated Stop requests are idempotent and preserve terminal state without corruption.
7. `test_case_7_stop_race_cannot_resurrect_running`: Concurrent Stop and late worker event: terminal `CANCELLED` cannot be resurrected to `RUNNING`.
8. `test_case_8_stale_worker_cannot_overwrite_newer_attempt`: Stale worker event from earlier attempt cannot overwrite newer attempt.
9. `test_case_9_persistence_failure_reporting`: Disk persistence failure during Stop logs warning and does not corrupt in-memory cancellation.
10. `test_case_10_resume_of_terminal_mission_legal_transition`: Resume of stopped/terminal mission follows legal transitions and rejects completed missions.
11. `test_case_11_workspace_binding_and_write_ahead_integrity`: Workspace binding and write-ahead integrity are preserved during stop and pause.
12. `test_case_12_api_endpoint_boundaries`: API endpoint verification across TestClient boundaries for both active and stale states.

---

## 4. Full Regression Execution & Verification

### Command Executed:
```powershell
C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe -m pytest `
  tests/test_phase1_mission_lifecycle.py tests/test_phase2_complete.py tests/test_phase3_complete.py `
  tests/test_phase4_stop_control.py tests/test_phase5_resume_control.py tests/test_phase6_transport_hardening.py `
  tests/test_phase7_network_recovery.py tests/test_phase8_gui_integration.py tests/test_phase9_cache_safety.py `
  tests/test_phase9_checkpoint_adversarial.py tests/test_phase9_path_containment.py `
  tests/test_phase9_persistence_batch_failure.py tests/test_stage9_workspace_hub.py `
  tests/test_phase10_crash_and_lifecycle_races.py tests/test_phase10_filesystem_and_journal_truth.py `
  tests/test_phase10_network_and_provider_faults.py tests/test_phase11_contracts.py `
  tests/test_phase11_alignment_verifier.py tests/test_incident_planning_and_lifecycle_recovery.py `
  tests/test_runtime_state.py tests/test_stage2_server_and_event_stream.py `
  tests/test_stage6_real_execution.py tests/test_stage7_reliability_and_recovery.py `
  tests/test_stale_running_control_reconciliation.py `
  -W error::pytest.PytestReturnNotNoneWarning -W error::SyntaxWarning
```

### Full Suite Results:
- **Total Modules:** 24
- **Total Tests Collected:** 241 (229 baseline + 12 new)
- **Passed:** 241
- **Failed:** 0
- **Skipped:** 0
- **Warnings Triggered:** 0
- **Duration:** 28.19 seconds
- **Exit Code:** 0
