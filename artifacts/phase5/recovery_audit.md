# HERMES Phase 5 — Recovery Audit & Pre-Implementation Architecture Report

**Release Target:** HERMES v1.0.0-rc1  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Python Runtime:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Audit Date:** October 12, 2026  

---

## 1. Executive Summary

Phase 5 introduces safe, truthful resume from the first unfinished task. This audit evaluates the existing persistence, checkpointing, and execution state infrastructure delivered in Phases 1–4, establishing the concrete design for Phase 5 recovery and reconciliation.

---

## 2. Answers to Section 3 Architecture & Recovery Audit Questions

### 1. Where and how are checkpoints currently loaded and deserialized?
- **Loading & Deserialization:**
  - Checkpoints are saved in `core/persistence/database.py` in the `checkpoints` table with full manifest JSON in `manifest_json` and on the filesystem under `<base_dir>/checkpoints/<checkpoint_id>/manifest.json`.
  - State blobs are serialized and stored via `core/persistence/serializer.py` (`serialize_runtime_state` and `deserialize_runtime_state`).
  - `CheckpointEngine.get_checkpoint(checkpoint_id)` loads `CheckpointManifest.from_dict(...)` from SQLite or filesystem fallback.
  - Runtime snapshots are stored in the `snapshots` table in SQLite (`save_snapshot` / `get_snapshot`) and deserialized into `HermesRuntimeState`.

### 2. What integrity checks already exist, and what checks are missing?
- **Existing Checks:**
  - `CheckpointEngine.verify_checkpoint_integrity(checkpoint_id)` verifies that:
    1. Checkpoint record exists.
    2. Checkpoint `state_hash` blob exists in `BlobStore` and matches its SHA-256 hash.
    3. All files recorded in `checkpoint.workspace.files` exist in `BlobStore` and match their recorded `blob_id` SHA-256 hash.
- **Missing Checks:**
  - Manifest hash verification: recalculating `manifest_hash = sha256(canonical_json(manifest))` and verifying it matches `chk.manifest_hash`.
  - Schema version check: ensuring `chk.schema_version` is supported.
  - Workspace directory validation: ensuring the physical workspace directory still exists, is accessible, and matches `chk.workspace.root` or `saved_mission["workspace_path"]`.
  - Ledger-to-disk reconciliation: verifying whether files on disk match the expected post-condition of settled tool operations or have been tampered with/edited post-interruption.

### 3. How is the original workspace path preserved, validated, and protected against substitution?
- **Preservation:**
  - Preserved in `missions` table (`workspace_path`), in `snapshots` table (`workspace_path`), and in `checkpoints` table via `checkpoint.workspace.root`.
- **Validation:**
  - On mission startup, `validate_workspace_access` validates the path and prevents path traversal.
  - In Phase 5 resume: The original workspace path recorded in the mission row in SQLite must be authoritatively locked. If the user currently selected a different folder in Project Hub, the Resume action MUST bind to the original workspace path, or fail with a clear blocker error if that directory no longer exists or is inaccessible.
  - HERMES repository root protection: If the workspace path is `HERMES_ROOT`, resume must enforce confirmation or respect repository root safety rules.

### 4. What fields are recorded in tool intents and results, and how are files correlated?
- **Schema in `tool_operations` Table:**
  - `operation_id`, `mission_id`, `tool_name`, `status` (`INTENT_COMMITTED`, `EXECUTING`, `RESULT_COMMITTED`, `FAILED`, `CANCELLED`, `OUTCOME_UNKNOWN`).
  - `intent_seq`, `result_seq`, `task_id`, `turn_id`, `run_id`, `attempt_number`, `session_id`.
  - `target_path`, `workspace_root`, `arguments_summary`, `arguments_json`.
  - `prior_hash`, `post_hash`, `exit_code`, `output_summary`, `error_message`, `duration_seconds`, `side_effects_json`, `created_at`, `committed_at`.
- **File Correlation:**
  - File operations record `target_path` (relative or absolute), `prior_hash` (SHA-256 before write/edit), and `post_hash` (SHA-256 after write/edit).
  - This allows exact verification of disk state against ledger records.

### 5. How are incomplete, crashed, or ambiguous tool executions currently marked and detected?
- **Detection & Marking:**
  - In `RuntimeAdapter.restore_persisted_missions()`: on startup, tool operations with status `INTENT_COMMITTED` or `EXECUTING` are marked as `OUTCOME_UNKNOWN` (`error_message="INTERRUPTED_BY_RESTART..."`).
  - Operations that never reached `record_tool_result` remain `INTENT_COMMITTED` if process was terminated abruptly before `restore_persisted_missions` runs.
  - `OUTCOME_UNKNOWN` indicates uncertain outcome requiring disk-vs-ledger reconciliation before continuation.

### 6. How is task progress represented in the state store, mission planner, and database?
- **Representation:**
  - `HermesRuntimeState.tasks`: map of `task_id -> TaskState` with `status` (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `BLOCKED`, `CANCELLED`), `is_verified`, `verification_evidence`, `files_created`, `files_modified`.
  - `MissionPlanningService`: maintains `todos` (`TodoState`), `requirements` (`RequirementState`), `acceptance_ledger` (`AcceptanceLedger`).
  - `snapshots` table in SQLite serializes the full `HermesRuntimeState` including all tasks and requirements.

### 7. How are task dependencies and ordering defined and evaluated?
- **Definitions:**
  - In `MissionPlanningService`, requirements and tasks define `dependencies: List[str]`.
  - Tasks can only transition to execution when all dependent tasks are `COMPLETED` and verified.
  - In linear / plan order, tasks are indexed sequentially or topologically sorted.

### 8. What verification evidence is preserved, where is it stored, and how is it validated?
- **Storage:**
  - `verification_evidence` table in `SQLiteDatabase` records `evidence_id`, `mission_id`, `run_id`, `command`, `working_dir`, `interpreter`, `exit_code`, `duration_seconds`, `output_summary`, `status`, `rationale`, `created_at`.
  - `HermesRuntimeState.evidence` contains `EvidenceItem` records with hash, command, exit code, and timestamps.
- **Validation:**
  - If a task was marked completed and verified in run N, but files related to that task were modified post-interruption, the verification evidence is invalidated and the task must be re-verified or re-run.

### 9. How do mission and run identities change across lifecycle transitions and restarts?
- **Lifecycle Invariants:**
  - `mission_id` remains constant across the entire mission lifecycle (e.g., `m_12345678`).
  - Terminal runs are immutable: if run 1 (`run_1_abcd`) was cancelled or failed, it can NEVER transition back to `RUNNING`.
  - A continuation attempt creates a new run identity: `run_id = f"run_{next_attempt}_{uuid.hex[:8]}"`, `attempt_number = prev_attempt + 1`.
  - `attempt_number` increments monotonically.
  - `MISSION_CREATED` / `MISSION_RESUMED` events record the new run ID and attempt number while preserving historical terminal events.

### 10. How is terminal state currently protected against duplicate execution?
- **Enforcement:**
  - `MissionControlContext.mark_terminal()` marks the control context terminal.
  - `Mission.is_terminal` and `HermesRuntimeState.mission.is_terminal` reject non-terminal transitions.
  - `RuntimeAdapter._active_tasks` tracks running missions; if a mission is already running, duplicate resume requests are rejected with 409 Conflict.

### 11. What APIs currently exist for resume, and what is missing?
- **Existing:**
  - `RuntimeAdapter.validate_resume_eligibility()` and `RuntimeAdapter.resume_mission()` exist for unpausing an in-flight paused mission via `pause_event`.
  - No HTTP endpoint exists for `/api/missions/{mission_id}/resume`.
  - No cold-resume / post-interruption resume endpoint exists.
- **Missing:**
  - `POST /api/missions/{mission_id}/resume` endpoint.
  - `GET /api/missions/{mission_id}/resume-preview` endpoint (or pre-validation response).
  - Backend recovery coordinator (`RecoveryEngine` / `MissionRecoveryManager`) to coordinate checkpoint validation, disk reconciliation, and continuation task launch.

### 12. How does the frontend surface mission state, resume controls, and user feedback?
- **Current GUI State:**
  - `TopBar.tsx` displays project, backend status, and mission status.
  - `Composer.tsx` provides `Send` (when idle) and `Stop` (when running).
  - `RightPane.tsx` displays Outcome tab with hero status card, delivered response, failure traceback, copy workspace, and `Retry Task` (which simply resubmits the original prompt as a brand-new mission).
- **Missing GUI Controls:**
  - Dedicated `Resume Mission` action for stopped/cancelled/failed missions.
  - Presentation of reconciliation findings (e.g., "Resuming from Task 2 (Write Tests); Task 1 already completed").
  - Clear error blocking presentation if original workspace is missing or modified.

### 13. What failure modes could cause a resume attempt to corrupt the workspace or mission history?
- **Risk 1:** Replaying all past model completions or past tool operations against the workspace, clobbering existing files or duplicating side effects.
- **Risk 2:** Mutating the previous terminal `run_id` in SQLite, wiping out historical abort records.
- **Risk 3:** Resuming in a different workspace folder than where the mission started.
- **Risk 4:** Ignoring post-interruption file edits made by the user, overwriting manual edits without notice.
- **Risk 5:** Continuing from an `OUTCOME_UNKNOWN` tool operation where a partial write occurred.
- **Risk 6:** Marking tasks complete without verifying their preconditions and dependencies.

---

## 3. Implementation Plan for Phase 5

1. **Recovery and Reconciliation Module (`core/persistence/recovery.py`):**
   - Checkpoint integrity validation (manifest hash, blob existence, state hash).
   - Workspace directory validation (original path immutability, existence, accessibility, HERMES root protection).
   - Operation ledger disk reconciliation:
     - Check each recorded tool operation against disk.
     - Compare current disk hash against `post_hash` and `prior_hash`.
     - Detect `OUTCOME_UNKNOWN` or mismatched files.
   - Task selection:
     - Determine the earliest unfinished or unverified task whose dependencies are satisfied.
2. **Runtime Continuation Engine in `core/server/runtime_adapter.py`:**
   - Implement `resume_interrupted_mission(mission_id)`.
   - Prevent duplicate resumes (concurrency lock).
   - Allocate new run identity (`run_id`, `attempt_number = attempt_number + 1`).
   - Emit `MISSION_RESUMED` event.
   - Launch scoped `AgentLoop` initialized from recovered state.
3. **API Endpoints in `core/server/app.py`:**
   - `POST /api/missions/{mission_id}/resume`: validates and starts continuation run.
   - `GET /api/missions/{mission_id}/resume-preview`: inspects and returns reconciliation summary without side effects.
4. **GUI Integration:**
   - Add Resume button in `RightPane.tsx` and API methods in `gui/src/api.ts`.
5. **Phase 5 Acceptance Test Suite (`tests/test_phase5_resume_control.py`):**
   - Scenarios A through J covering all prompt requirements.
