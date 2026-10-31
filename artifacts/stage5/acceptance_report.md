# HERMES Stage 5 — Windows Launch Experience, Runtime Lifecycle, and Rollout Readiness
## Final Acceptance Report

**Date & Timestamp**: 2026-10-11  
**Harness Version**: HERMES v1.0.0-rc1  
**Operating System**: Windows (Canonical Shell: PowerShell / Command Prompt)  
**Canonical Python Interpreter**: `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Server Target**: `http://127.0.0.1:8765/`  

---

### Executive Summary

Stage 5 ("Windows Launch Experience, Runtime Lifecycle, and Rollout Readiness") is complete and verified.

1. **Gate Zero Security & Lifecycle Gap Closure**:
   - Resolved the audit fixture issue: verified that `NameError: name 'Path' is not defined` was an intentional audit fixture testing exception propagation, not a regression.
   - Identified and hardened the approval security lifecycle: pending approvals are strictly bound to `mission_id`. When a mission enters any terminal state (`COMPLETED`, `FAILED`, `CANCELLED`), all its pending approval requests are automatically invalidated and rejected with `HTTP 410 Gone`. Stale approvals can never be replayed.
2. **Windows Launch Experience**:
   - Implemented `core/server/launcher.py` with port status inspection, process verification via `psutil`, health verification via `/api/health`, background detached startup, PID tracking (`.hermes_server.pid`), and safe log persistence (`data/logs/hermes_gui_server.log`).
   - Delivered `scripts/launch_gui.ps1` and `scripts/stop_gui.ps1`.
   - Wired the canonical CLI commands `main.py gui` and `main.py gui --stop` / `main.py gui --status`.
3. **Port Conflict & Unrelated Process Protection**:
   - Launcher strictly differentiates an existing healthy HERMES server from an unrelated third-party process occupying port 8765.
   - If an unrelated process occupies port 8765, HERMES terminates nothing, issues an alert, and exits with code 1.
   - If HERMES is already running and healthy, repeated launches are idempotent, re-opening the browser without spawning duplicate server processes.
4. **Testing & Real Browser Verification**:
   - `tests/test_stage5_launch_lifecycle.py` added with 7/7 passing tests.
   - Complete targeted regression suite (Stages 0, 1, 2, 3, 4, 4.1, 5) achieved **42/42 passing tests in 4.43s**.
   - Real Headless Chrome CDP smoke acceptance (`scripts/audit_stage5_smoke.py`) passed all 3 smoke acceptance checks (Initial Launch, Approval Mission Binding, and Post-Termination Refresh).

---

### 1. Gate Zero Audit Findings & Resolutions

| Item | Investigation & Diagnosis | Resolution & Proof |
| :--- | :--- | :--- |
| **`Path` NameError** | Checked `core/mission_runner.py` line 462 and `test_a_path_error_regression`. `from pathlib import Path` is present on line 32. In `test_stage3_gui_prototype_acceptance.py`, it was an intentional audit test payload proving tool exception propagation. | Confirmed fixed in real execution path; verified by `test_a_path_error_regression`. |
| **`docker push` Approval Lifecycle Gap** | `docker push` in `audit_stage4_1` was a test fixture; however, it exposed that pending approval requests were not coupled to their owning mission's lifecycle. An approval created by a failed or terminated mission could linger in `GET /api/approvals`. | Bound approvals to `mission_id` in `SecurityGate`, `ApprovalStore`, and `RuntimeAdapter`. Added automatic cancellation on terminal events and `HTTP 410 Gone` on late resolution attempts. |

---

### 2. Windows Launch & Stop Helpers

- **PowerShell Launcher**: `scripts/launch_gui.ps1`
  - Validates Python 3.12 canonical interpreter path.
  - Spawns background server via `core.server.launcher`.
  - Verifies `/api/health` before opening default browser to `http://127.0.0.1:8765/`.
- **PowerShell Stopper**: `scripts/stop_gui.ps1`
  - Gracefully terminates running HERMES instance via tracked PID and SIGTERM/SIGKILL sequence.
  - Leaves unrelated third-party processes completely untouched.
- **CLI Command in `main.py`**:
  ```bash
  .\venv\Scripts\python.exe main.py gui              # Launches GUI and opens browser
  .\venv\Scripts\python.exe main.py gui --no-browser # Starts server without browser
  .\venv\Scripts\python.exe main.py gui --status     # Prints JSON status
  .\venv\Scripts\python.exe main.py gui --stop       # Safely stops running server
  ```

---

### 3. Verification Test Evidence

```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1, pluggy-1.6.0
collected 42 items

tests/test_runtime_reliability_gate.py::test_a_path_error_regression PASSED [  2%]
tests/test_runtime_reliability_gate.py::test_b_tool_exception_cannot_produce_success PASSED [  4%]
tests/test_runtime_reliability_gate.py::test_c_required_file_writing_verification PASSED [  7%]
tests/test_runtime_reliability_gate.py::test_d_missing_output_blocks_completion PASSED [  9%]
tests/test_runtime_reliability_gate.py::test_e_runtime_exception_handled_cleanly PASSED [ 11%]
tests/test_runtime_reliability_gate.py::test_f_legitimate_read_only_task_passes PASSED [ 14%]
tests/test_stage2_server_and_event_stream.py::test_1_health_endpoint_and_runtime_connectivity PASSED [ 16%]
tests/test_stage2_server_and_event_stream.py::test_2_request_schemas_and_validation PASSED [ 19%]
tests/test_stage2_server_and_event_stream.py::test_3_workspaces_listing_and_boundary_checks PASSED [ 21%]
tests/test_stage2_server_and_event_stream.py::test_4_mission_snapshot_retrieval PASSED [ 23%]
tests/test_stage2_server_and_event_stream.py::test_5_event_to_sse_conversion_and_contract PASSED [ 26%]
tests/test_stage2_server_and_event_stream.py::test_6_event_ordering_and_replay_from_cursor PASSED [ 28%]
tests/test_stage2_server_and_event_stream.py::test_7_mission_isolation_no_cross_leakage PASSED [ 30%]
tests/test_stage2_server_and_event_stream.py::test_8_cancellation_dispatches_to_runtime PASSED [ 33%]
tests/test_stage2_server_and_event_stream.py::test_9_failed_tool_and_verification_remain_failures PASSED [ 35%]
tests/test_stage2_server_and_event_stream.py::test_10_security_host_and_origin_validation PASSED [ 38%]
tests/test_stage2_server_and_event_stream.py::test_11_secret_redaction_in_exceptions_and_logs PASSED [ 40%]
tests/test_stage2_server_and_event_stream.py::test_12_workspace_boundary_path_traversal_rejected PASSED [ 42%]
tests/test_stage3_gui_prototype_acceptance.py::test_1_gui_spa_index_and_static_serving PASSED [ 45%]
tests/test_stage3_gui_prototype_acceptance.py::test_2_reference_failure_frame_name_error_truth PASSED [ 47%]
tests/test_stage3_gui_prototype_acceptance.py::test_3_genuine_success_frame_requires_verified_checks PASSED [ 50%]
tests/test_stage3_gui_prototype_acceptance.py::test_4_stop_action_cancels_mission_authoritatively PASSED [ 52%]
tests/test_stage3_gui_prototype_acceptance.py::test_5_three_panel_tab_separation PASSED [ 54%]
tests/test_stage4_review_and_diff_acceptance.py::test_1_stage4a_genuine_diffs_and_traversal_protection PASSED [ 57%]
tests/test_stage4_review_and_diff_acceptance.py::test_2_stage4a_binary_and_missing_file_safety PASSED [ 59%]
tests/test_stage4_review_and_diff_acceptance.py::test_3_stage4b_evidence_driven_verification_checks PASSED [ 61%]
tests/test_stage4_review_and_diff_acceptance.py::test_4_stage4c_outcome_panel_truth_and_failure_diagnosis PASSED [ 64%]
tests/test_stage4_review_and_diff_acceptance.py::test_5_stage4d_approvals_resolution_lifecycle PASSED [ 66%]
tests/test_stage4_review_and_diff_acceptance.py::test_6_stage4e_session_and_cursor_resilience PASSED [ 69%]
tests/test_stage4_1_audit_acceptance.py::test_audit_changes_git_and_nongit PASSED [ 71%]
tests/test_stage4_1_audit_acceptance.py::test_audit_changes_traversal_and_oversized_guards PASSED [ 73%]
tests/test_stage4_1_audit_acceptance.py::test_audit_checks_five_statuses PASSED [ 76%]
tests/test_stage4_1_audit_acceptance.py::test_audit_outcome_truth_and_cancellation PASSED [ 78%]
tests/test_stage4_1_audit_acceptance.py::test_audit_approvals_lifecycle_and_stale_handling PASSED [ 80%]
tests/test_stage4_1_audit_acceptance.py::test_audit_sse_cursor_reconnect PASSED [ 83%]
tests/test_stage5_launch_lifecycle.py::test_cli_entry_points_preserved PASSED [ 85%]
tests/test_stage5_launch_lifecycle.py::test_approval_lifecycle_bound_to_mission_completion PASSED [ 88%]
tests/test_stage5_launch_lifecycle.py::test_approval_lifecycle_bound_to_mission_failure PASSED [ 90%]
tests/test_stage5_launch_lifecycle.py::test_unrelated_process_protection PASSED [ 92%]
tests/test_stage5_launch_lifecycle.py::test_duplicate_launch_detected_when_server_already_healthy PASSED [ 95%]
tests/test_stage5_launch_lifecycle.py::test_clean_stop_removes_pid_file PASSED [ 97%]
tests/test_stage5_launch_lifecycle.py::test_check_status_contract PASSED [100%]

============================= 42 passed in 4.43s ==============================
```

---

### 4. Real Browser CDP Smoke Evidence (`artifacts/stage5/`)

- Evidence file: `artifacts/stage5/smoke_evidence.json`
- Screenshots captured:
  - `artifacts/stage5/01_gui_initial_launch.png`
  - `artifacts/stage5/02_approval_with_mission_binding.png`
  - `artifacts/stage5/03_post_termination_refresh.png`

```json
{
  "stage": "Stage 5",
  "timestamp": "2026-10-11 10:15:50",
  "mission_id": "m_stage5_smoke_01",
  "tests": {
    "initial_launch": {
      "title": "HERMES — Autonomous Harness",
      "connected": true,
      "has_hermes_branding": true,
      "has_workspace": true,
      "status": "PASS"
    },
    "approval_binding": {
      "approval_shown": true,
      "mission_bound_shown": true,
      "status": "PASS"
    },
    "termination_and_refresh": {
      "approval_cleared_after_termination": true,
      "connected_after_refresh": true,
      "status": "PASS"
    }
  }
}
```

---

### 5. Architectural & Preservation Commitments

- **Model Stack**: Kept unchanged:
  - T1: NVIDIA NIM `z-ai/glm-5.3-flash`
  - T2: Ollama Cloud `gpt-oss:120b-cloud`
  - T3: Ollama Cloud `nemotron-3-ultra:cloud`
- **Campus Lab Manager**: Untouched.
- **Git Working Tree**: Preserved all user modifications and untracked files; no reset, clean, or commit operations were executed.
- **Scope Boundary**: Stopped at the Stage 5 gate. Tauri and Electron migrations were **not** started.
