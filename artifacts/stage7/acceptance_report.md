# HERMES — Stage 7: Sustained Mission Reliability, Model Fallback, and Recovery Acceptance Report

**Date**: October 11, 2026  
**Repository**: `C:\Users\SUBBU\Downloads\hermes`  
**Canonical Python Interpreter**: `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`  
**Model Stack (Preserved & Locked)**:  
- **T1**: NVIDIA NIM — `z-ai/glm-5.3-flash`  
- **T2**: Ollama Cloud — `gpt-oss:120b-cloud`  
- **T3**: Ollama Cloud — `nemotron-3-ultra`  

---

## 1. Executive Summary & Exit Gate Classification

### Overall Gate Verdict: **PASS**

Stage 7 evaluated the HERMES autonomous runtime under repeated, multi-step software-engineering tasks, controlled fault injection, model fallback conditions, user cancellation, and connection interruption.

All required scenarios (A through G) were audited and verified. The cumulative acceptance test suite (covering Stages 0 through 7) executed **75 tests with 0 failures** under the canonical Python interpreter, and the graphical interface production build succeeded with 0 TypeScript or bundling errors.

### Scenario-by-Scenario Classification

| Scenario | Focus | Execution Type | Status | Summary |
| :--- | :--- | :--- | :---: | :--- |
| **Scenario A** | Repeated Equivalent Tasks | Live Browser & NIM Model | **PASS** | 10 live missions executed across isolated workspaces (Creation: 2/3 passed, 1 incomplete within 40s; Modification: 2/3 passed, 1 failed; Read-Only: 3/3 passed; Multi-Step: 1/1 passed). Observed success rate: 80% (8/10). All failures were accurately identified and never misreported as success. |
| **Scenario B** | Bounded Retries & Loop Prevention | Deterministic Fault Injection | **PASS** | Max turns (`max_turns=3`), consecutive failures (`max_consecutive_failures=3`), and wall time limits enforced. Stall detector flags duplicate action loops. Repeated completion claims on failed checks are strictly rejected by `GoalCompleteGuard`. |
| **Scenario C** | Model & Provider Fallback | Controlled Fault Injection | **PASS** | `NvidiaTimeoutError` / `NvidiaConnectionError` triggers automated failover to Tier 2 (`gpt-oss:120b-cloud`) and Tier 3 (`nemotron-3-ultra`). Adaptive circuit breaker trips into `OPEN_CIRCUIT` after 2 consecutive timeouts for zero-wait routing. Exhaustion terminates cleanly without false success. |
| **Scenario D** | Multi-Step Task Integrity | Live Browser & NIM Model + Test | **PASS** | Live 4-step mission (`calc.py` inspection, implementation, test writing, verification) completed and verified via pytest. Deliberate failing prerequisite blocks dependent completion from claiming success. |
| **Scenario E** | Cancellation During Active Work | Live Browser & CDP | **PASS** | User clicking Stop button in GUI halts running task, invalidates pending approvals in `ApprovalStore`, and locks status to `CANCELLED` (never `COMPLETED`). Late events cannot resurrect terminal state. |
| **Scenario F** | Interruption & Recovery | Live Browser & API Test | **PASS** | Navigating away and reconnecting via Chrome CDP preserves full UI state. SSE stream reconnection with `Last-Event-ID` / cursor replays monotonic events without event loss or drift. In-memory restart behavior documented. |
| **Scenario G** | Security & Artifact Integrity | Deterministic Verification | **PASS** | Workspace boundary escapes (`../escape_jail.py`) blocked with `WorkspaceBoundaryError`. Terminal missions cannot reuse stale approval requests. 100% SHA-256 manifest match on read-only tasks. |

---

## 2. Repeated Live Tasks (Scenario A Execution Matrix)

All repeated missions were executed in separate isolated workspaces (`data/ws_stage7_*`) using the live T1 model (`z-ai/glm-5.3-flash`):

| Category | Run ID | Mission ID | Terminal Status | Verification Command | Exit Code | SHA-256 Integrity | Verdict |
| :--- | :---: | :--- | :---: | :--- | :---: | :---: | :---: |
| **Creation** | 1 | `m_fd2b4b4a` | `RUNNING` | `python.exe -c "import math_lib; assert math_lib.add(2, 3) == 5"` | 0 | File written | **FAIL** (Incomplete at 40s timeout) |
| **Creation** | 2 | `m_6e9d0797` | `COMPLETED` | `python.exe -c "import math_lib; assert math_lib.add(2, 3) == 5"` | 0 | Non-empty (+12/-0) | **PASS** |
| **Creation** | 3 | `m_9c631fb2` | `COMPLETED` | `python.exe -c "import math_lib; assert math_lib.add(2, 3) == 5"` | 0 | Non-empty (+6/-0) | **PASS** |
| **Modification** | 1 | `m_1071d3bd` | `COMPLETED` | `python.exe -c "import greeter; assert greeter.greet('Hermes') == 'Hello, Hermes!'"` | 0 | Modified (+1/-1) | **PASS** |
| **Modification** | 2 | `m_e1d771e5` | `COMPLETED` | `python.exe -c "import greeter; assert greeter.greet('Hermes') == 'Hello, Hermes!'"` | 0 | Modified (+1/-1) | **PASS** |
| **Modification** | 3 | `m_c0432dd2` | `FAILED` | `python.exe -c "import greeter; assert greeter.greet('Hermes') == 'Hello, Hermes!'"` | 1 | Unchanged (+0/-0) | **PASS (Accurate Failure)** |
| **Read-Only** | 1 | `m_9b438364` | `COMPLETED` | SHA-256 Manifest Comparison | 0 | 100% Identical | **PASS** (Reported Heading & Desc) |
| **Read-Only** | 2 | `m_f197e64e` | `COMPLETED` | SHA-256 Manifest Comparison | 0 | 100% Identical | **PASS** (Reported Heading & Desc) |
| **Read-Only** | 3 | `m_b7cf5cbf` | `COMPLETED` | SHA-256 Manifest Comparison | 0 | 100% Identical | **PASS** (Reported Heading & Desc) |
| **Multi-Step** | 1 | `m_a0d8d360` | `COMPLETED` | `python.exe -m pytest test_calc.py -q` | 0 | Modified & Created (+5/-1) | **PASS** |
| **Cancellation** | 1 | `m_f0f6c2d2` | `CANCELLED` | Stop requested via UI Button | 0 | Halted immediately | **PASS** |

**Observed Reliability Rate**:  
- Creation: 2/3 (66.7%)  
- Modification: 2/3 (66.7%)  
- Read-Only: 3/3 (100.0%)  
- Multi-Step: 1/1 (100.0%)  
- Overall Successful: 8/10 completed; 100% truthful status representation (zero false successes).

---

## 3. Bounded Retries & Fault Injection (Scenarios B, C, D, E, F, G)

Implemented and verified in [`tests/test_stage7_reliability_and_recovery.py`](file:///C:/Users/SUBBU/Downloads/hermes/tests/test_stage7_reliability_and_recovery.py):

```
platform win32 -- Python 3.12.0, pytest-9.1.1 -- C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe
collected 11 items

tests/test_stage7_reliability_and_recovery.py::test_scenario_b_turn_budget_enforcement PASSED [  9%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_b_consecutive_failure_budget_exhaustion PASSED [ 18%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_b_failed_check_cannot_be_overridden_by_repeated_claim PASSED [ 27%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_c_provider_timeout_failover_to_tier2 PASSED [ 36%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_c_all_tiers_exhausted_raises_cleanly PASSED [ 45%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_c_circuit_breaker_trips_on_consecutive_timeouts PASSED [ 54%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_d_failing_prerequisite_blocks_dependent_completion PASSED [ 63%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_e_cancellation_sets_cancelled_and_invalidates_approvals PASSED [ 72%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_f_sse_reconnection_preserves_event_order_and_cursor PASSED [ 81%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_g_path_boundary_traversal_blocked_under_failure PASSED [ 90%]
tests/test_stage7_reliability_and_recovery.py::test_scenario_g_terminal_mission_cannot_reuse_stale_approvals PASSED [100%]

============================= 11 passed in 3.71s ==============================
```

---

## 4. Cumulative Regression Suite (All Stages Combined)

Executed all eleven acceptance test suites in a single combined pytest run:
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
  -q
```

**Output**:
```
75 passed in 13.28s (Exit Code: 0)
```

**Frontend Production Build**:
```powershell
npm run build # in gui/ -> tsc && vite build -> Exit Code 0 in 1.96s
```

---

## 5. Artifact Manifest

All audit artifacts and evidence records have been captured and saved under [`artifacts/stage7/`](file:///C:/Users/SUBBU/Downloads/hermes/artifacts/stage7/):
- [`mission_matrix.json`](file:///C:/Users/SUBBU/Downloads/hermes/artifacts/stage7/mission_matrix.json): Complete records of the 11 live missions, SHA-256 manifests, diff counts, verification outputs, and verdicts.
- [`retry_and_fallback_evidence.json`](file:///C:/Users/SUBBU/Downloads/hermes/artifacts/stage7/retry_and_fallback_evidence.json): Configured budgets, model tier definitions, and fault-injection results.
- [`recovery_evidence.json`](file:///C:/Users/SUBBU/Downloads/hermes/artifacts/stage7/recovery_evidence.json): Reconnection verification, cancellation locks, boundary protection, and restart semantics.
- `01_browser_creation_outcome.png`: Creation mission outcome screen.
- `02_browser_multistep_outcome.png`: Multi-step mission outcome screen.
- `03_browser_multistep_changes.png`: Multi-step diff review tab.
- `04_browser_cancellation_outcome.png`: Cancelled mission UI state.
- `05_browser_reconnected.png`: Post-interruption reconnected browser view.

---

## 6. Environment & Model Stack Preservation

- **Repository Integrity**: All pre-existing user modifications and untracked files were strictly preserved. No destructive Git commands were run.
- **Model Stack Lock**: Preserved unchanged (T1: NVIDIA NIM `z-ai/glm-5.3-flash`, T2: Ollama Cloud `gpt-oss:120b-cloud`, T3: Ollama Cloud `nemotron-3-ultra`).
- **External Projects**: Campus Lab Manager was untouched.
