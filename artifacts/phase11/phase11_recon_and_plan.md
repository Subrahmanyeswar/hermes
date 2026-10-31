# HERMES Phase 11 — Fault Injection, Chaos Testing, Recovery Integrity & Release Qualification
## Reconnaissance & Execution Plan

**Author:** HERMES Lead Systems Architect & Verification Agent  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Branch:** `hermes-2.x`  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (3.12.0)  
**Date:** 2026-10-22  

---

### 1. Executive Summary & Verification Context

Phase 11 qualifies HERMES 2.x for release under adversarial real-world conditions, including network cuts, unexpected process crashes, abrupt cancellations during active I/O, concurrent mission contention, workspace drift outside the control plane, and tool infrastructure exceptions.

All verification adheres strictly to the non-negotiable safety rules:
- **Canonical Python Virtual Environment:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0). Zero modifications to installed packages; zero venv rebuilds.
- **Model Stack Preservation:** Tier 1 NIM `z-ai/glm-5.3-flash`, Tier 2 `gpt-oss:120b-cloud`, Tier 3 `nemotron-3-ultra:cloud` preserved without tampering.
- **Skill Integrity Locks:** All 24 production skills byte-verified against locked SHA-256 fingerprints.
- **Phase 10 Integrity:** All Phase 10 optimization components preserved byte-for-byte.
- **Workspace Isolation:** All test files, simulated state databases, and crash targets reside exclusively within isolated pytest `tmp_path` allocations; the repository root is never used as a disposable workspace.

---

### 2. Architecture & Invariant Mapping

#### Scenario 1: Network Loss and Resumption
- **Subsystems:** `core.network.connectivity.ConnectivityMonitor`, `core.network.coordinator.NetworkRecoveryCoordinator`, `core.runtime_state.models.MissionStatus`.
- **Fault Injected:** Drop simulated connectivity during active mission execution.
- **Guaranteed Behavior:** The mission transitions safely to `WAITING` with reason `WAITING_FOR_NETWORK`. No false completion or unhandled crash is emitted. When network connectivity restores, the coordinator safely resumes execution or marks the mission ready without duplicate task re-execution.

#### Scenario 2: Process Crash, Cold Restart & WAL Integrity
- **Subsystems:** `core.persistence.database.SQLiteDatabase`, `core.persistence.recovery.RecoveryEngine`, `core.runtime_state.models.HermesRuntimeState`.
- **Fault Injected:** Simulate abrupt worker crash with uncheckpointed in-memory state; cold restart against on-disk SQLite WAL database.
- **Guaranteed Behavior:**
  1. SQLite `PRAGMA integrity_check` returns `ok`.
  2. WAL recovery settles uncommitted transactions without corruption.
  3. `RecoveryEngine.determine_first_unfinished_task` inspects verified tasks and identifies the next pending task without re-executing already verified and completed tasks.

#### Scenario 3: Stop / Cancellation During Active File Write
- **Subsystems:** `tools.file_tools.WriteFileTool`, `core.cancellation_controller.CancellationController`, `core.event_bus.event_bus`.
- **Fault Injected:** Trigger cancellation or stop signal while a file write operation is in-flight.
- **Guaranteed Behavior:**
  1. Atomic write staging via temporary files (`.tmp_*`) ensures the target file is either untouched or completely written, never left half-written or corrupt.
  2. Temporary staging files are cleaned up upon abort.
  3. Mission state updates truthfully to `CANCELLED` and no subsequent writes occur.

#### Scenario 4: Five Concurrent Mission Requests (Single-Active-Mission Policy)
- **Subsystems:** `core.server.runtime_adapter.RuntimeAdapter`, `core.server.app`, `core.persistence.locks.SessionLock`.
- **Fault Injected:** 5 concurrent mission launch requests executed against the runtime controller.
- **Guaranteed Behavior:**
  1. Exactly 1 mission acquires execution ownership and transitions to `RUNNING`.
  2. The remaining 4 concurrent requests are cleanly rejected with `RuntimeError` / HTTP 409 Conflict under the single-active-mission policy.
  3. No race condition allows concurrent dual active writers to corrupt workspace state or sessions.

#### Scenario 5: Workspace Drift (Modifications Outside HERMES)
- **Subsystems:** `core.persistence.recovery.RecoveryEngine`, `core.workspace_cache.WorkspaceManifestCache`.
- **Fault Injected:** Modify file content, delete a committed file, and introduce unexpected files externally while HERMES is halted.
- **Guaranteed Behavior:**
  1. `RecoveryEngine.reconcile_disk_with_ledger` immediately flags `USER_MODIFIED` for modified files.
  2. Deleted committed files are flagged as `FILE_MISSING` and block unsafe resumption.
  3. `WorkspaceManifestCache.scan_workspace(force=True)` refreshes in-memory structures to reflect physical reality rather than trusting stale cache.

#### Scenario 6: Tool Infrastructure Exception (Unhandled Failure)
- **Subsystems:** `core.bounded_executor.BoundedExecutor`, `core.error_handler.ErrorHandler`.
- **Fault Injected:** A tool or task raises an unhandled infrastructure exception (e.g. `NameError` or `ImportError`).
- **Guaranteed Behavior:**
  1. `BoundedExecutor` captures the exception into a structured `TaskExecutionRecord` with `success=False`.
  2. The exception is preserved in telemetry/records.
  3. The task is never marked as `COMPLETED`, preventing false completion.

#### Cross-Cutting Invariants
1. **Stale Event Replay Rejection:** `EventBus` and `StateReducer` drop stale event sequences (`sequence <= last_event_sequence`) and seen event IDs.
2. **Stop/Resume Race:** Concurrent stop and resume signals prioritize cancellation or reject illegal transitions.
3. **Mission Resurrection Prevention:** Terminal statuses (`COMPLETED`, `FAILED`, `CANCELLED`, `ABORTED`) cannot transition back to `RUNNING`.
4. **Files Written != Application Complete:** Verification gates must pass before mission completion; mere presence of files does not trigger completion.

---

### 3. Test Suite Implementation Plan

We will create a comprehensive, deterministic, zero-external-dependency test suite in:
`tests/test_phase11_fault_injection.py`

Test Cases:
- `test_scenario1_network_loss_and_clean_resumption`
- `test_scenario2_process_crash_cold_restart_wal_recovery`
- `test_scenario3_stop_during_active_file_write_atomic_cleanup`
- `test_scenario4_concurrent_mission_requests_single_active_policy`
- `test_scenario5_workspace_drift_detection_and_blocking`
- `test_scenario6_tool_infrastructure_exception_visibility`
- `test_invariant_stale_event_replay_rejection`
- `test_invariant_mission_resurrection_prevention`
- `test_invariant_files_written_does_not_equal_completion`
- `test_invariant_sqlite_integrity_check_under_heavy_churn`

---

### 4. Verification & Release Qualification Pipeline

1. **Phase 11 Suite Run:** `pytest tests/test_phase11_fault_injection.py -v`
2. **Full Regression Validation:**
   - Phase 10: `tests/test_performance_optimization.py`
   - Phase 9: `tests/test_phase9_*.py`
   - Phase 8: `tests/test_phase8_*.py`
   - Phase 7: `tests/test_phase7_*.py`
   - Phase 6: `tests/test_phase6_skill_registry_routing.py`
   - Phase 5: `tests/test_phase5_*.py`
   - Full Pytest Regression Suite: `pytest -q`
3. **Frontend Production Build:** `cd gui && npm run build`
4. **Cryptographic Fingerprint Auditing:** Compute SHA-256 digests of all 24 skills and critical modules.
5. **Closure Deliverables:** Output `phase11_test_results.md`, `phase11_fault_injection_report.md`, `phase11_final_closure_evidence.json`, and `phase11_final_closure_report.md`.
