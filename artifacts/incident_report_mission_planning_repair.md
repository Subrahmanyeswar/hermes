# Incident Report: HERMES Mission Planning, Runtime Persistence, and Audit Port Collision

**Incident Date:** 2026-10-18  
**Resolution Date:** 2026-10-19  
**Release:** HERMES v1.0.0-rc1  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Runtime:** Python 3.12.0 (`venv\Scripts\python.exe`)  
**Scope:** Reliability, Core Runtime State, Network Recovery, Application Preflight, Audit Tooling, Live GUI Acceptance, Regression Reconciliation

---

## 1. Executive Summary

During mission execution in a test workspace (`C:\Users\SUBBU\Downloads\test 1`), mission `m_a8442b65` appeared stuck in `RUNNING` in the GUI with 0 steps and 0 checks, and the backend subsequently appeared offline. When running `scripts/audit_stage6_real_execution.py`, an `OSError: [WinError 10048]` (address in use) occurred and crashed the audit.

A forensic investigation traced this failure to five interdependent software bugs across `StateReducer`, `AgentLoop`, `NetworkRecoveryCoordinator`, and `audit_stage6_real_execution.py`. All five bugs were resolved, verified with 14 incident recovery tests (including seven deterministic safety invariant tests B.1–B.7), validated across the full 23-module regression suite under strict warning escalation flags (229/229 tests passed), and verified via a live browser acceptance test driving headless Chrome over CDP against a live FastAPI app on an isolated audit server.

---

## 2. Forensic Root-Cause Analysis

### Bug 1: StateReducer Run Identity Omission on Attempt Increment (`core/runtime_state/reducer.py`)
- **Symptom:** Mission `m_a8442b65` was recorded in the database with status `RUNNING` at sequence cursor 4484, despite event sequence 4524 (`MISSION_FAILED`) having been successfully published to the event journal.
- **Root Cause:** In `StateReducer.reduce()`, lines 99–113:
  ```python
  if (
      event.run_id
      and state.mission.run_id
      and event.run_id != state.mission.run_id
      and (event.attempt_number or 0) <= (state.mission.attempt_number or 1)
  ):
      return state  # Stale run event
  
  if event.run_id and not state.mission.run_id:
      state.mission.run_id = event.run_id
  if event.attempt_number and event.attempt_number > state.mission.attempt_number:
      state.mission.attempt_number = event.attempt_number
  ```
  When continuation attempt 2 was emitted by `MISSION_RESUMED` (`run_id: run_2_5d20ec26`, `attempt_number: 2`), `state.mission.attempt_number` was incremented to 2, but `state.mission.run_id` was left unchanged (`run_1_4c3a7fc2`) because `state.mission.run_id` was already populated.
  Consequently, on the very next attempt-2 event (sequence 4485), `event.run_id != state.mission.run_id` evaluated to True (`run_2` != `run_1`), and `event.attempt_number <= state.mission.attempt_number` evaluated to True (`2 <= 2`). `StateReducer` dropped all subsequent attempt-2 events (including `MISSION_FAILED`) as stale.
- **Resolution:** Updated `StateReducer.reduce()` so that whenever `event.attempt_number > state.mission.attempt_number`, both `state.mission.attempt_number` and `state.mission.run_id` are synchronized. In addition, `MISSION_RESUMED` explicitly updates `run_id`, `attempt_number`, `waiting_reason`, and `current_action`.

### Bug 2: Missing Positional Argument in DB Mission Save (`core/agent_loop/loop.py`)
- **Symptom:** When model generation timed out and AgentLoop transitioned to `WAITING_FOR_NETWORK` (Condition D) or `WAITING_FOR_PROVIDER` (Condition C), the mission state in the SQLite database was not updated to `WAITING`.
- **Root Cause:** `SQLiteDatabase.save_mission()` requires `workspace_path: str` as its second positional argument:
  `save_mission(self, mission_id: str, workspace_path: str, status: str, ...)`
  In `core/agent_loop/loop.py` lines 584 and 614, `db.save_mission` was invoked without `workspace_path`. This raised a `TypeError`, which was caught and swallowed by an exception handler, leaving the mission record in an unpersisted or stale state.
- **Resolution:** Updated both call sites to provide `workspace_path=ws_path`, along with `run_id=self._run_id` and `attempt_number=self._attempt_number`.

### Bug 3: Circuit State Desynchronization (`core/adaptive_routing.py` & `core/network/coordinator.py`)
- **Symptom:** Immediately upon auto-resuming from `WAITING_FOR_PROVIDER`, attempt 2 failed 5 consecutive times in less than 1 second, with the log reporting: `[ADAPTIVE ROUTING] T1 circuit is OPEN_CIRCUIT. Zero-wait failover to T2`.
- **Root Cause:** Although `NetworkRecoveryCoordinator` detected provider recovery and emitted `NETWORK_RESTORED`, the circuit breaker state within `AdaptiveRouter` (`providers[1].state`) remained `OPEN_CIRCUIT`. Resumed execution bypassed Tier 1 completely and directly attempted Tier 2, exhausting the failure budget immediately.
- **Resolution:** Added `notify_provider_recovered(tier=1)` to `AdaptiveRouter` and ensured `NetworkRecoveryCoordinator.notify_provider_recovered()` synchronizes the circuit breaker when genuine provider recovery occurs, while ensuring generic internet restoration alone does NOT prematurely close the provider circuit.

### Bug 4: Missing Application Preflight in Empty Workspaces (`core/agent_loop/loop.py`)
- **Symptom:** Workspace `test 1` contained 0 application files, but the prompt asked to: *"Add a GET /health endpoint to the existing application that returns status: ok. Do not change existing routes."* HERMES proceeded to plan against an empty directory.
- **Root Cause:** `AgentLoop` lacked a preflight check to verify that a target application exists before decomposing and attempting to modify it.
- **Resolution:** Added workspace preflight detection in `AgentLoop.run()`. If the prompt explicitly specifies modifying an existing application/codebase and the workspace has 0 application files, HERMES reports an informative `MISSION_FAILED` preflight error (`failure_code: EMPTY_WORKSPACE_EXISTING_APPLICATION`) instead of stalling or hallucinating. Also added `MissionStatus.FAILED` to legal transitions from `MissionStatus.CREATED`.

### Bug 5: Audit Runner Port Collision and Fragility (`scripts/audit_stage6_real_execution.py`)
- **Symptom:** The Stage 6 audit runner bound to hardcoded port 8765. If a HERMES GUI backend was already running on 8765, uvicorn failed with `[WinError 10048]`. The audit runner continued blindly, polled health against the existing server, attached CDP to the wrong server, and crashed in `finally` when awaiting the failed server task.
- **Root Cause:** Hardcoded port 8765 without port-availability checks, no check on `server_task.done()`, and unhandled exception re-raise in `finally`.
- **Resolution:** Added `is_port_available()` and `find_free_port()`, supported dynamic port allocation, added a check on `server_task.done()` during the readiness loop, verified the `workspace_root` returned by `/api/health`, made the `finally` block resilient to server exceptions, and isolated the Project Hub registry using a temporary registry file.

---

## 3. Comprehensive Verification Evidence

### A. Full 23-Module Regression Suite Execution & Reconciliation

#### 1. Test Count Reconciliation: Baseline (186) -> Intermediate (204) -> Final (229)

- **Prior 186-Test Baseline:** Recorded in `artifacts/phase11/alignment_verifier_results.md` (2026-10-14). Consisted of 19 modules totaling 186 tests:
  - Phase 1–8 suites: 93 tests
  - Phase 9 suite (`test_phase9_cache_safety` [4], `test_phase9_checkpoint_adversarial` [2], `test_phase9_path_containment` [5], `test_phase9_persistence_batch_failure` [3]): 14 tests
  - Phase 10 suite (`test_phase10_crash_and_lifecycle_races` [8], `test_phase10_filesystem_and_journal_truth` [8], `test_phase10_network_and_provider_faults` [7]): 23 tests
  - Phase 11 suite (`test_phase11_contracts` [9], `test_phase11_alignment_verifier` [27]): 36 tests
  - Stage 2 & 9 suites (`test_stage2_server_and_event_stream` [12], `test_stage9_workspace_hub` [8]): 20 tests
  - Total: 93 + 14 + 23 + 36 + 20 = **186 tests**.

- **Intermediate 204-Test Suite (Incident Triage Run):**
  When triaging the incident, four Phase 9 / Stage 9 modules were temporarily omitted:
  - `test_phase9_checkpoint_adversarial.py` (2 tests)
  - `test_phase9_path_containment.py` (5 tests)
  - `test_phase9_persistence_batch_failure.py` (3 tests)
  - `test_stage9_workspace_hub.py` (8 tests)
  - Subtotal omitted: 2 + 5 + 3 + 8 = **18 tests** (186 - 18 = 168 tests retained).
  In their place, four other existing/incident modules were executed:
  - `test_runtime_state.py` (13 tests)
  - `test_stage6_real_execution.py` (5 tests)
  - `test_stage7_reliability_and_recovery.py` (11 tests)
  - Initial `test_incident_planning_and_lifecycle_recovery.py` (7 tests)
  - Subtotal added: 13 + 5 + 11 + 7 = **36 tests**.
  - Total: 168 + 36 = **204 tests**.

- **Final 229-Test Suite (Full Reconciled Regression):**
  Re-integrating the 4 omitted modules (18 tests) and expanding `test_incident_planning_and_lifecycle_recovery.py` from 7 to 14 tests (+7 safety invariants B.1–B.7):
  - Prior intermediate: 204 tests
  - Re-added omitted modules: +18 tests
  - Incident suite expansion (B.1–B.7): +7 tests
  - Total: 204 + 18 + 7 = **229 tests**.

*Note on the "233" hypothesis:* The hypothesis of 233 tests assumed `test_phase9_checkpoint_adversarial.py` had 5 tests (it has 2, delta -3) and `test_stage9_workspace_hub.py` had 9 tests (it has 8, delta -1, because Scenarios D and E are tested together in `test_scenario_d_and_e_task_workspace_binding_and_switching`). 233 - 3 - 1 = **229**. No tests were deleted, skipped, or lost.

#### 2. Per-Module Breakdown (23 Modules, 229 Tests)

| # | Module Name | Collected Tests | Status |
|:---:|:---|:---:|:---:|
| 1 | `tests/test_phase1_mission_lifecycle.py` | 7 | ✅ PASS |
| 2 | `tests/test_phase2_complete.py` | 10 | ✅ PASS |
| 3 | `tests/test_phase3_complete.py` | 12 | ✅ PASS |
| 4 | `tests/test_phase4_stop_control.py` | 8 | ✅ PASS |
| 5 | `tests/test_phase5_resume_control.py` | 10 | ✅ PASS |
| 6 | `tests/test_phase6_transport_hardening.py` | 16 | ✅ PASS |
| 7 | `tests/test_phase7_network_recovery.py` | 15 | ✅ PASS |
| 8 | `tests/test_phase8_gui_integration.py` | 15 | ✅ PASS |
| 9 | `tests/test_phase9_cache_safety.py` | 4 | ✅ PASS |
| 10 | `tests/test_phase9_checkpoint_adversarial.py` | 2 | ✅ PASS |
| 11 | `tests/test_phase9_path_containment.py` | 5 | ✅ PASS |
| 12 | `tests/test_phase9_persistence_batch_failure.py` | 3 | ✅ PASS |
| 13 | `tests/test_stage9_workspace_hub.py` | 8 | ✅ PASS |
| 14 | `tests/test_phase10_crash_and_lifecycle_races.py` | 8 | ✅ PASS |
| 15 | `tests/test_phase10_filesystem_and_journal_truth.py` | 8 | ✅ PASS |
| 16 | `tests/test_phase10_network_and_provider_faults.py` | 7 | ✅ PASS |
| 17 | `tests/test_phase11_contracts.py` | 9 | ✅ PASS |
| 18 | `tests/test_phase11_alignment_verifier.py` | 27 | ✅ PASS |
| 19 | `tests/test_incident_planning_and_lifecycle_recovery.py` | 14 | ✅ PASS |
| 20 | `tests/test_runtime_state.py` | 13 | ✅ PASS |
| 21 | `tests/test_stage2_server_and_event_stream.py` | 12 | ✅ PASS |
| 22 | `tests/test_stage6_real_execution.py` | 5 | ✅ PASS |
| 23 | `tests/test_stage7_reliability_and_recovery.py` | 11 | ✅ PASS |
| **TOTAL** | **23 Modules** | **229** | **✅ 100% PASS** |

#### 3. Execution Command and Output (Strict Warning Mode)

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
  -W error::pytest.PytestReturnNotNoneWarning -W error::SyntaxWarning -v
```

**Terminal Summary:**
```text
======================= 229 passed in 109.70s (0:01:49) =======================
```
- **Exit code:** 0
- **Warnings triggered:** 0
- **Skipped:** 0
- **Failures:** 0

---

### B. Exact Recovery Safety Invariants (B.1 – B.7)
Implemented and verified in `tests/test_incident_planning_and_lifecycle_recovery.py`:
1. **B.1: Internet restoration does not reset Tier 1 circuit without provider-specific recovery** (`test_b1_internet_restoration_does_not_reset_t1_circuit` - PASSED).
2. **B.2: Genuine Tier 1 recovery resets circuit before continuation** (`test_b2_genuine_t1_recovery_resets_circuit_before_continuation` - PASSED).
3. **B.3: Mission cannot immediately exhaust retry budget against unavailable fallback provider without truthful waiting/recovery handling** (`test_b3_fallback_provider_unavailability_enters_waiting_without_budget_exhaustion` - PASSED).
4. **B.4: Existing-app modification request in an empty workspace produces an informative blocker** (`test_b4_existing_app_modification_empty_workspace_produces_informative_blocker` - PASSED).
5. **B.5: New-app creation request in an empty workspace is not rejected by preflight** (`test_b5_new_app_creation_empty_workspace_not_rejected_by_preflight` - PASSED).
6. **B.6: Stale events from earlier attempt cannot overwrite current attempt's outcome or terminal state** (`test_b6_stale_events_earlier_attempt_cannot_overwrite_current_outcome_or_terminal` - PASSED).
7. **B.7: Recovery retains immutable workspace binding and preserves unresolved filesystem uncertainty** (`test_b7_recovery_retains_immutable_workspace_binding_and_preserves_uncertainty` - PASSED).

---

### C. Live GUI Acceptance Test (FastAPI /health Addition)
Executed `scripts/audit_gui_live_health_addition.py`:
- **Workspace:** `C:\Users\SUBBU\Downloads\hermes\.temp_gui_health_ws`
- **Application:** Real FastAPI application (`main.py` with `/users`, `test_main.py` with unit tests).
- **Prompt:** *"Add a GET /health endpoint to the existing application that returns status: ok. Do not change existing routes."*
- **Server:** Isolated FastAPI server running on dynamically allocated port 8768 (ownership verified).
- **Browser:** Headless Chrome running with CDP on port 9230.
- **Direct HTTP Verification:**
  - `GET /users` returned status `200` with expected payload `{"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}`.
  - `GET /health` returned status `200` with expected payload `{"status": "ok"}`.
- **Pytest Exit Code:** `0` (2/2 tests passed in 0.49s).
- **GUI Views Audited and Captured:**
  - `05_live_gui_planning_and_progress.png`: Planning, step progress, and active execution cards.
  - `06_live_gui_changes_tab.png`: Modified `main.py` and `test_main.py` diff cards showing endpoint addition.
  - `07_live_gui_checks_tab.png`: Passing acceptance check cards with pytest execution output.
  - `08_live_gui_outcome_tab.png`: Terminal COMPLETED banner with execution summary.
- **Tripartite Agreement Verified:**
  - API snapshot (`/api/missions/m_live_gui_health_add`): `status="COMPLETED"`, `is_terminal=true`.
  - Persisted SQLite state (`hermes_runtime.db`): `status="COMPLETED"`.
  - Frontend GUI: `COMPLETED` overview and successful check verification.
- **Evidence JSON:** Exported to `artifacts/stage6/live_gui_evidence.json` with overall verdict `PASS`.

---

## 4. Modified Files Inventory

| File | Nature of Change |
|:---|:---|
| `core/runtime_state/reducer.py` | Synchronized `state.mission.run_id` when `attempt_number` increases; enriched `MISSION_RESUMED`. |
| `core/runtime_state/models.py` | Added `MissionStatus.FAILED` to allowed transitions from `MissionStatus.CREATED`. |
| `core/agent_loop/loop.py` | Added `workspace_path` to Condition C/D `db.save_mission()` calls; added empty workspace preflight. |
| `core/adaptive_routing.py` | Added `notify_provider_recovered(tier=1)` to restore `HEALTHY` state and reset circuit breaker. |
| `core/network/coordinator.py` | Guarded `create_task()` calls against missing event loops; synchronized provider recovery. |
| `core/server/security.py` | Supported loopback host headers on dynamic audit ports while strictly blocking external domains. |
| `scripts/audit_stage6_real_execution.py` | Dynamic port allocation, strict-mode checking, fail-fast startup verification, and resilient cleanup. |
| `scripts/audit_gui_live_health_addition.py` | Standalone end-to-end audit proving live GUI display of results and tripartite agreement. |
| `tests/test_stage7_reliability_and_recovery.py` | Isolated test database and generated unique mission IDs to eliminate test pollution. |
| `tests/test_incident_planning_and_lifecycle_recovery.py` | Comprehensive regression suite covering all 5 failure modes and invariants B.1–B.7. |
