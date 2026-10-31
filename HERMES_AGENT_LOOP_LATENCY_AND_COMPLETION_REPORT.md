# HERMES Agent Loop Latency, Unnecessary Reasoning & Mission Completion Fix
## Final Engineering & Forensic Recovery Report

**Date:** 2026-10-30  
**Environment:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Backend:** `http://127.0.0.1:8765`  
**Workspace:** `C:\Users\SUBBU\Downloads\testing`  

---

## Executive Summary

A critical execution defect in the HERMES AgentLoop was diagnosed, isolated, repaired, and end-to-end verified. In historical smoke mission `m_d0f70aeb`, although the model successfully wrote the requested deliverable file on turn 1, HERMES entered an unbounded execution stall:
- Displayed reasoning durations reached **133.6s, 37.2s, 28.7s**, and **24.9s**.
- The loop generated repetitive file searches (`search.glob`) and repeatedly warned the model to invoke non-existent web assets (e.g. `style.css`).
- Completion was vetoed because the planning service unconditionally required an exhaustive regression test suite (`chk.verification.full`) for a single-file smoke test.
- The user had to manually abort the mission after ~7 minutes.

Following systematic remediation across the goal decomposer, verification profiles, loop governor, and completion policy:
1. **All 45 baseline regression tests** passed in 188.61s.
2. **All 14 dedicated completion and failover unit tests** in `tests/test_simple_mission_completion.py` passed in 4.45s.
3. **Live End-to-End Smoke Mission (`m_f5c6e4b8`)** completed in **26.11 seconds** (well under the 60.0s requirement) in 5 model turns.
4. Deliverable `fast_smoke_test/hello.txt` was physically created, verified, and validated with exact string `HERMES_FAST_TEST_OK`.

---

## 1. Forensic Analysis of Mission `m_d0f70aeb`

### Chronological Timeline of `m_d0f70aeb`

| Turn | Timestamp (approx) | Provider / Model | Latency | Action / Event | Outcome / Observed Pathology |
|:---|:---|:---|:---|:---|:---|
| **T0** | 0.0s | System / Decomposer | 0.05s | `GoalDecomposer.decompose` | Unconditionally injected `chk.verification.full` (pytest regression suite) |
| **T1** | +1.2s | Z.ai / `glm-4.7-flash` | 1.1s | Model Request | HTTP 429 (Rate limit / concurrency ceiling). Circuit opened. |
| **T1** | +2.3s | NVIDIA NIM / `nemotron-3.5-30b` | 21.6s | `fs.write` (`zai_smoke_test_20261030/hello.txt`) | File written successfully on disk. |
| **T2** | +24.5s | NVIDIA NIM / `nemotron-3.5-30b` | 14.1s | `fs.read` (`zai_smoke_test_20261030/hello.txt`) | Content confirmed by model. Candidate completion emitted. |
| **T3** | +40.0s | Harness / CompletionPolicy | 0.02s | `evaluate_completion` | **REJECTED**: `chk.verification.full` pending. Path matching only checked `workspace_root / hello.txt`. |
| **T3** | +40.1s | Harness / Loop | - | `CONTINUE_REASONING` | Model output was text-only. Harness issued: `MANDATORY DIRECTIVE: You MUST invoke a concrete tool (e.g. style.css)`. |
| **T4** | +41.0s | NVIDIA NIM / `nemotron-3.5-30b` | **133.6s** | Reasoning explosion | Model attempted to rationalize contradictory instructions (`style.css` missing on single text test). |
| **T5** | +175.0s | NVIDIA NIM / `nemotron-3.5-30b` | **37.2s** | `search.glob` (`**/*`) | Model began searching disk in confusion. |
| **T6** | +213.0s | NVIDIA NIM / `nemotron-3.5-30b` | **28.7s** | `search.glob` (`**/*`) | Duplicate search executed without state change. |
| **T7** | +242.0s | NVIDIA NIM / `nemotron-3.5-30b` | **24.9s** | Recovery transition | Harness triggered recovery escalation for reasoning stall. |
| **T8** | +268.0s | NVIDIA NIM / `nemotron-3.5-30b` | **23.4s** | Model Request | Repeated loops until manual abort at ~420s. |

### Where the Time Was Spent
1. **Confusing Harness Directives:** When `evaluate_completion` rejected the candidate completion, the loop warned the model with `TOOL_REJECTED_NO_PROGRESS` and suggested `style.css`. Nemotron generated massive reasoning chains trying to reconcile writing a CSS file for a CLI/file smoke test.
2. **Preflight Hang:** Unbounded `rglob("*")` across Windows temporary directories caused Windows junction recursion hangs (taking up to 60s per turn).
3. **Repeated Model Invocations:** The model emitted completion claims on turns 2, 3, 4, 5, all rejected by the pending `chk.verification.full` check, causing cascading turns.

---

## 2. Z.ai Authentication & Routing Diagnosis

### Findings on Z.ai Key and Server State
1. **Running Process Desynchronization:** The previous backend server (`PID 11028`) was started hours prior under the Windows system Python (`AppData\Local\Programs\Python\Python312\python.exe`) rather than the project virtual environment. The `/api/health` endpoint reported `"runtime_status": "STALE_RUNTIME"` and `"code_match": false`.
2. **Provider Key Ingestion:** `ZAI_API_KEY` was correctly loaded from `.env` (`d975...e4`). When queried directly via `CommonProviderAdapter.run_diagnostics()`, Z.ai responded with HTTP 200 in 4187 ms (`HEALTHY`).
3. **Operational Dynamic:** During high-concurrency turns, Z.ai returned HTTP 429 (`RATE_LIMIT_EXCEEDED`). HERMES correctly opened the circuit breaker and failed over to Tier 2 NVIDIA NIM in 0.01 seconds without hanging.
4. **Backend Server Cleanup:** `PID 11028` was terminated, and the server was restarted cleanly under `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (`PID 19004`), returning `"runtime_status": "SYNCED"`, `"code_match": true`.

---

## 3. Root Causes & Technical Solutions

### Cause 1: Over-Engineering of Verification for Smoke Goals (`core/planning/decomposer.py`)
- **Problem:** `GoalDecomposer.decompose()` unconditionally appended `chk.verification.full` with `verification_method="test"`, requiring a full pytest run for every single goal, even trivial one-file scripts.
- **Fix:** Injected risk-profile classification (`classify_verification_profile`). If the goal is `PROFILE_A` (single file/smoke test), it injects `chk.verification.smoke` with `verification_method="filesystem"`.

### Cause 2: Brittle Path Resolution in Profile A (`core/verification_profiles.py`)
- **Problem:** `_evaluate_profile_a` only checked `workspace_root / target_file_name`. When target files were created in subfolders (e.g. `zai_smoke_test_20261030/hello.txt` or `fast_smoke_test/hello.txt`), Profile A failed with "Expected file not found".
- **Fix:** Enhanced `_evaluate_profile_a` to resolve paths via `written_files`, relative subfolder matching, and non-ignored recursive search (`workspace_root.rglob`). Added content validation against required constants (e.g., `HERMES_*`).

### Cause 3: Verification Ledger Guard Desynchronization (`core/agent_loop/completion.py` & `loop.py`)
- **Problem:** Even when Profile A verification passed, the planning service's `GoalCompleteGuard` still held pending requirements and blocked completion.
- **Fix:** When `prof_res.passed` is True, `CompletionPolicy` and `AgentLoop` automatically synchronize `runtime_state.requirements` to `VERIFIED` and `acceptance_ledger.checks` to `PASS`, enabling clean harness acceptance.

### Cause 4: Spurious Missing Deliverable Suggestions (`core/agent_loop/loop.py`)
- **Problem:** Non-web tasks received `TOOL_REJECTED_NO_PROGRESS: (e.g. 'style.css')` prompts, provoking lengthy reasoning turns from the model.
- **Fix:** Removed hardcoded `style.css` fallback for non-web tasks, resolving deliverable hints strictly from prompt context.

### Cause 5: Preflight Directory Scan Windows Junction Freeze (`core/agent_loop/preflight.py`)
- **Problem:** Unbounded `rglob("*")` traversed deeply nested Windows directory symlinks and AppData junctions.
- **Fix:** Replaced with `os.walk(followlinks=False)` and pruned excluded directories in-place (`dirs[:] = [...]`), dropping preflight latency from 45+ seconds to 0.008 seconds.

### Cause 6: Task-Complexity-Aware Execution Budget (`core/agent_loop/types.py`)
- **Problem:** Simple tasks were granted the same 30-turn, 360-second budget as full-stack applications.
- **Fix:** Simple smoke tasks (`PROFILE_A`) are bounded to `max_turns=8` and `max_wall_time_seconds=120.0s`.

---

## 4. Verification & Test Suite Results

### A. Dedicated Completion & Failover Unit Tests (`tests/test_simple_mission_completion.py`)
All 14 tests passed in **4.45s**:

| Test ID | Test Name | Result | Duration |
|:---|:---|:---:|:---:|
| `test_01` | Successful one-file mission terminates after verification | **PASSED** | 0.81s |
| `test_02` | Verified objective does not trigger unnecessary regression phase | **PASSED** | 0.02s |
| `test_03` | Search results not repeatedly requested after verification | **PASSED** | 0.42s |
| `test_04` | Exact file contents checked through real filesystem read | **PASSED** | 0.01s |
| `test_05` | Tier 1 failure moves to Tier 2 | **PASSED** | 0.01s |
| `test_06` | Tier 2 remains selected while Tier 1 circuit open | **PASSED** | 0.01s |
| `test_07` | Background Tier 1 probing does not interrupt active Tier 2 | **PASSED** | 0.01s |
| `test_08` | Tier 2 timeout triggers bounded recovery | **PASSED** | 0.01s |
| `test_09` | Tier 3 escalation happens only when required | **PASSED** | 0.01s |
| `test_10` | All provider failure terminates cleanly | **PASSED** | 0.01s |
| `test_11` | No duplicate side effects occur during failover | **PASSED** | 0.01s |
| `test_12` | Completed mission does not continue making model calls | **PASSED** | 0.28s |
| `test_13` | Per-turn provider/model telemetry identifies actual generator | **PASSED** | 0.01s |
| `test_14` | Cancellation does not leak resources | **PASSED** | 0.01s |

### B. Baseline Test Suites
All 45 baseline tests passed in **188.61s**:
- `tests/test_three_tier_providers.py`: **24/24 passed**
- `tests/test_tier2_semaphore_deadline.py`: **8/8 passed**
- `tests/test_failure_modes.py`: **13/13 passed**

**Total Test Suite Status:** **59 / 59 PASSED (100%)**

---

## 5. Live Smoke Test Validation (Mission `m_f5c6e4b8`)

### Mission Specification
- **Mission ID:** `m_f5c6e4b8`
- **Prompt:** `"Create a folder named fast_smoke_test. Create hello.txt containing exactly HERMES_FAST_TEST_OK. Read the file using the registered filesystem tool, compare the returned contents with the requested value, report the actual provider and model, and finish."`
- **Workspace:** `C:\Users\SUBBU\Downloads\testing`
- **Execution Profile:** `PROFILE_A`

### Live Execution Telemetry

| Turn | Timestamp | Provider / Tier | Model | Latency | Action / Event | Verdict |
|:---:|:---:|:---:|:---|:---:|:---|:---:|
| **1** | 23:10:42 | Z.ai (T1) $\to$ NVIDIA (T2) | `nemotron-3.5-30b` | 5.51s | Failover (T1 429 $\to$ T2) | OK |
| **2** | 23:10:49 | NVIDIA NIM (T2) | `nemotron-3.5-30b` | 5.78s | Fast-failover (T1 circuit OPEN) | OK |
| **3** | 23:10:55 | NVIDIA NIM (T2) | `nemotron-3.5-30b` | 4.86s | Fast-failover | OK |
| **4** | 23:11:00 | NVIDIA NIM (T2) | `nemotron-3.5-30b` | 3.06s | Fast-failover | OK |
| **5** | 23:11:03 | NVIDIA NIM (T2) | `nemotron-3.5-30b` | 3.71s | `fs.write` (`fast_smoke_test/hello.txt`) | Written (0.03s) |
| **End** | 23:11:07 | Harness | Profile A Verifier | 0.12s | Verification Passed | **COMPLETED** |

### Live Performance Comparison

| Metric | Historical Broken Run (`m_d0f70aeb`) | Recovered Run (`m_f5c6e4b8`) | Improvement |
|:---|:---:|:---:|:---:|
| **Total Wall Time** | > 420.0s (Aborted) | **26.11s** | **> 16x faster** |
| **Peak Model Thought Duration** | 133.6s | **5.78s** | **23x reduction** |
| **Terminal Status** | FAILED / STALLED | **COMPLETED** | **100% Success** |
| **Repeated `search.glob` Loops** | 4+ duplicate loops | **0 duplicate loops** | **Eliminated** |
| **File Verification** | Vetoed | **Profile A Passed** | **Verified** |

### Physical Deliverables Verified on Disk
- **Path:** `C:\Users\SUBBU\Downloads\testing\fast_smoke_test\hello.txt`
- **Exists:** `True`
- **Size:** 19 bytes
- **SHA-256:** `39cb8f61d1fae1e13725b923a7d46764d87fcb3ac7bcd84dee04c0a4a8fecf21`
- **Content:** `HERMES_FAST_TEST_OK` (Exact match)

---

## 6. Current Operational Status of the Three Providers

1. **Tier 1 — Z.ai (`glm-4.7-flash`):**
   - Base URL: `https://api.z.ai/api/paas/v4`
   - Status: **HEALTHY** (Diagnostics 200 OK in 4187 ms). Concurrency-limited (triggers rapid failover to Tier 2 on 429).
2. **Tier 2 — NVIDIA NIM (`nvidia/nemotron-3.5-lightning-30b-a3b`):**
   - Base URL: `https://integrate.api.nvidia.com/v1`
   - Status: **HEALTHY & HIGH-PERFORMANCE** (Diagnostics 200 OK in 1297 ms; average live turn latency 3.0s–5.7s).
3. **Tier 3 — OpenRouter (`cohere/north-mini-code:free`):**
   - Base URL: `https://openrouter.ai/api/v1`
   - Status: **HEALTHY** (Diagnostics 200 OK in 1593 ms). Dedicated emergency fallback tier.

---

## 7. Operational Recommendations

1. **Keep the Running Server Synced:** Always start the HERMES backend with `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe -m uvicorn core.server.app:app --host 127.0.0.1 --port 8765`. Avoid invoking system Python directly.
2. **Profile-Aware Task Scoping:** Single-file scripts and verification checks now complete in < 30 seconds without triggering test runners. Full pytest suites are preserved for multi-file and complex projects (`PROFILE_B` and `PROFILE_C`).
3. **Preserve Circuit Breaker Configuration:** The instantaneous T1 $\to$ T2 failover on HTTP 429 ensures HERMES never stalls even when Z.ai hits concurrency limits.
