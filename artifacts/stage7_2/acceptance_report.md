# HERMES — Stage 7.2: Concurrent Mission Isolation and Process Ownership Acceptance Report

## Executive Summary

Stage 7.2 evaluated the concurrent execution, process ownership, approval isolation, and terminal lifecycle guarantees of HERMES under simultaneous multi-mission conditions on Windows.

Prior stages implemented process cleanup and safety on single-mission lifetimes. Stage 7.2 identified and closed multi-mission cross-contamination gaps:
1. `tools/shell_tools.py` previously terminated all active subprocesses indiscriminately when any mission finished or stopped. Subprocess tracking has now been bound to specific missions via `CURRENT_MISSION_ID`, `PROCESS_MISSION_MAP`, and `terminate_active_subprocesses(mission_id=...)`, with full recursive process-tree termination on Windows via `psutil`.
2. `core/security/approvals.py` previously matched approval grants solely by tool name and fingerprint without scoping to `mission_id`. Approval grants are now bound to `mission_id`, preventing grants generated for Mission A from authorizing actions in Mission B.
3. `core/workspace.py` and `tools/file_tools.py` previously relied exclusively on a singleton `workspace_manager`. A task-local `CURRENT_WORKSPACE` context variable was introduced to allow concurrent missions to operate in isolated directories without filesystem collisions.

All 6 scenarios (A through F) were implemented and verified with deterministic tests in `tests/test_stage7_2_concurrent_isolation.py`. The complete cumulative regression suite of 85 tests across 13 test files passed cleanly (100%), and the frontend production build succeeded.

---

## Environment & Canonical Runtime

- **Repository**: `C:\Users\SUBBU\Downloads\hermes`
- **Canonical Python**: `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`
- **Model Stack Preservation**:
  - T1: NVIDIA NIM `z-ai/glm-5.3-flash` (unmodified)
  - T2: Ollama Cloud `gpt-oss:120b-cloud` (unmodified)
  - T3: Ollama Cloud `nemotron-3-ultra` (unmodified)
- **External Dependencies**: Campus Lab Manager and unrelated workspaces untouched.

---

## Scenario Verification Matrix

| Scenario | Description | Key Verification Checks | Status |
|---|---|---|---|
| **Scenario A** | Simultaneous Independent Missions | Concurrent execution in separate workspaces (`ws_a`, `ws_b`), independent outputs (`a_output.txt`, `b_output.txt`), zero cross-contamination, isolated SSE replay events. | **PASSED** |
| **Scenario B** | Cancel One Mission While Other Continues | Scoped cancellation terminates Mission A's subprocess; Mission B's subprocess remains alive and unmolested, and completes normally. | **PASSED** |
| **Scenario C** | One Mission Times Out While Another Completes | Mission A hits wall-time deadline and fails; pending approvals for Mission A are cancelled, while Mission B's pending approvals stay intact during active execution and B finishes successfully. | **PASSED** |
| **Scenario D** | Process-Tree Cleanup and Isolation | On Windows, recursive process termination terminates both parent and child processes of the target mission, while independent processes from other missions remain alive. | **PASSED** |
| **Scenario E** | Approvals and Event Isolation | Approval grants bound to `mission_id`. Grants for Mission A cannot match actions in Mission B. Invalidation of Mission A requests does not affect Mission B requests. | **PASSED** |
| **Scenario F** | Concurrent Deadline and Cancellation Races | Idempotent terminal transition; late failure events cannot resurrect a cancelled mission; duplicate cleanup calls are idempotent and safe. | **PASSED** |

---

## Full Regression Test Execution Summary

Command executed:
```powershell
C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe -m pytest `
  tests/test_runtime_reliability_gate.py `
  tests/test_stage2_server_and_event_stream.py `
  tests/test_stage3_gui_prototype_acceptance.py `
  tests/test_stage4_review_and_diff_acceptance.py `
  tests/test_stage4_1_audit_acceptance.py `
  tests/test_stage5_launch_lifecycle.py `
  tests/test_stage5_1_process_safety.py `
  tests/test_stage6_real_execution.py `
  tests/test_stage6_1_browser_correlation.py `
  tests/test_stage6_2_goal_fulfillment.py `
  tests/test_stage7_reliability_and_recovery.py `
  tests/test_stage7_1_stalled_finalization.py `
  tests/test_stage7_2_concurrent_isolation.py `
  -v
```

**Result**:
- **Exit Code**: `0`
- **Total Tests**: `85 passed in 25.97s`
- **Failures / Errors**: `0`

---

## Frontend Build Verification

Command executed:
```powershell
npm run build (in gui/)
```

**Result**:
- **Exit Code**: `0`
- **Output**:
  - `dist/index.html` (0.63 kB)
  - `dist/assets/index-Bljey2Z_.css` (1.16 kB)
  - `dist/assets/index-COWB10P5.js` (197.56 kB)
  - Built cleanly in 3.90s.
