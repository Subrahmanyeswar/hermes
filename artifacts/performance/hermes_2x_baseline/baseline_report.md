# HERMES 2.x — Development Baseline & RC3 Freezing Report

**Document ID:** `HERMES-2X-BASELINE-REPORT`  
**Date:** 2026-09-25  
**Reference Tag:** `v1.0.0-rc3`  
**Reference Commit:** `da30412b41d73343e63dc149f52833c61bb19990`  
**Development Branch:** `hermes-2.x`  
**Baseline Status:** `FROZEN_BASELINE_ESTABLISHED`  
**Test Suite Status:** `BASELINE_HAS_FAILURES` (1,116 Passed / 28 Failed)

---

## 1. Executive Summary & Freezing Declaration

This report establishes the empirical, reproducible development baseline for **HERMES 2.x** and formally freezes **`v1.0.0-rc3`** as the immutable reference point.

Under Prompt 2 mandate:
1. Reference release tag `v1.0.0-rc3` (`da30412b41d73343e63dc149f52833c61bb19990`) is locked and immutable.
2. A clean development branch `hermes-2.x` has been branched directly from commit `da30412`.
3. All empirical measurements (hardware, process memory, test suite pass/failure counts, model stack configuration, and behavioral bugs) reflect the ground truth of the system without speculative or optimistic numbers.
4. Forensic findings from the Prompt 1 investigation (Expense Tracker stall) have been reproduced and catalogued as verified baseline defects.
5. Zero code modifications, zero architectural rewrites, and zero performance optimizations were performed in this prompt.

---

## 2. Git Reference & Branch Verification

| Field | Value | Verification Status |
| :--- | :--- | :--- |
| **Reference Tag** | `v1.0.0-rc3` | VERIFIED |
| **Reference Commit** | `da30412b41d73343e63dc149f52833c61bb19990` | VERIFIED |
| **Commit Subject** | `feat: release v1.0.0-rc3` | VERIFIED |
| **Development Branch** | `hermes-2.x` | VERIFIED |
| **Merge Base** | `da30412b41d73343e63dc149f52833c61bb19990` | VERIFIED (`git merge-base hermes-2.x v1.0.0-rc3^{commit}`) |
| **Tree Cleanliness** | Maintained pre-existing user files (`MEMORY.md`, `HEREMES (things to do later).txt`) | PRESERVED |

---

## 3. Hardware & Runtime Environment Fingerprint

All measurements in this section were physically executed and verified on the local host machine.

| Parameter | Specification | Measurement Type |
| :--- | :--- | :--- |
| **Operating System** | Windows 11 Home / Pro (Build 10.0.26200, AMD64) | MEASURED |
| **Python Runtime** | Python 3.10.0 (64-bit, CPython) | MEASURED |
| **CPU Architecture** | 12th Gen Intel(R) Core(TM) i5-12450HX (8 Cores, 12 Logical Processors) | MEASURED |
| **Physical Memory (RAM)**| 15.71 GB Total (16,870,281,216 bytes), ~3.31 GB Free at test execution | MEASURED |
| **Discrete GPU** | NVIDIA GeForce RTX 3050 6GB Laptop GPU (PCI: 01:00.0) | MEASURED |
| **GPU Driver / CUDA** | Driver 591.44 / CUDA 13.1 | MEASURED |
| **VRAM Capacity** | 6,144 MB Total (4,229 MB allocated/in-use, 1,774 MB free at idle baseline) | MEASURED |
| **Process Startup RSS** | 16.81 MB (clean Hermes module startup) | MEASURED |
| **Host Storage (C:)** | 478.3 GB Used / 31.4 GB Available | MEASURED |

---

## 4. Model Hierarchy & Configuration Baseline

The model routing architecture in the RC3 baseline is structured across three tiers, reading from `config/model_config.py` and environment overrides:

| Tier | Model Name | Provider | Endpoint | Keep-Alive | Latency Budget |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1 (Fast)** | `z-ai/glm-5.3-flash` | NVIDIA NIM (`nvidia_nim`) | `https://integrate.api.nvidia.com/v1` | 300s | 300s |
| **Tier 2 (Heavy)** | `gpt-oss:120b-cloud` | Ollama Cloud (`ollama`) | `http://localhost:11434` | 60s | 360s |
| **Tier 3 (Fallback)**| `nemotron-3-ultra:cloud`| Ollama Cloud (`ollama`) | `http://localhost:11434` | 300s | 360s |

- **Streaming:** Enabled (`True`)
- **Global Timeout (`MODEL_TIMEOUT_SECONDS`):** 360 seconds
- **Default Keep-Alive (`MODEL_KEEP_ALIVE`):** 300 seconds

---

## 5. Canonical Test Suite Execution & Analysis

The full regression test suite was executed from the repository root via `pytest -v` (`PYTHONPATH=.`).

### Summary Metrics
- **Total Tests Collected:** 1,144
- **Passed:** 1,116 (97.55%)
- **Failed:** 28 (2.45%)
- **Skipped:** 0
- **Warnings:** 119
- **Execution Time:** 2,331.33 seconds (38 minutes 51 seconds)
- **Status Classification:** `BASELINE_HAS_FAILURES`

### Categorization of the 28 Test Failures

The 28 test failures are not random; they group deterministically into six distinct root cause categories:

#### 1. Windows Shell Incompatibility (1 failure)
- `tests/test_audit_trail.py::test_S05_count_files`
- *Root Cause:* Test executes Unix shell pipeline `ls -1 | wc -l` using `subprocess.check_output(..., shell=True)`. On Windows, `wc` is not an internal or external command, throwing an unhandled `CalledProcessError`.

#### 2. Windows Path Normalization (1 failure)
- `tests/test_memory_system.py::test_M01_save_memory_fact`
- *Root Cause:* Assertion compares `fact.source_path` directly to `'data/memory'`. On Windows, `os.path` operations normalize path separators to backslashes (`C:\Users\SUBBU\Downloads\hermes\data\memory`), failing the equality assertion.

#### 3. Model Hierarchy Test Assertion Drift (8 failures)
- `tests/test_gate_15_4.py::test_tier1_fast_model`
- `tests/test_gate_15_4.py::test_tier2_heavy_model`
- `tests/test_gate_23.py::test_model_selection_hierarchy`
- `tests/test_gate_23.py::test_tier2_model_configured`
- `tests/test_gate_23.py::test_tier1_keep_alive_is_zero`
- `tests/test_gate_23.py::test_vram_fit_under_12gb`
- `tests/test_model_config.py::test_model_selection_hierarchy`
- `tests/test_model_config.py::test_tier2_model_configured`
- *Root Cause:* These tests were authored when the stack used local models (`deepseek-r1:8b`, `qwen2.5-coder:7b`) with `keep_alive=0`. When the production configuration was migrated to cloud/NIM endpoints (`z-ai/glm-5.3-flash`, `gpt-oss:120b-cloud`), test assertions in `tests/test_gate_15_4.py`, `tests/test_gate_23.py`, and `tests/test_model_config.py` were not updated.

#### 4. Latency Budget & Timeout Assertion Drift (8 failures)
- `tests/test_decision_engine.py::test_F01_tier_assignment_latency` (marginal 0.000100s microsecond timer boundary jitter)
- `tests/test_gate_23.py::test_active_model_latency_budget` (asserts <= 120s, configured 300s)
- `tests/test_gate_23.py::test_tier2_latency_budget` (asserts <= 240s, configured 360s)
- `tests/test_gate_23.py::test_stream_chunk_timeout` (asserts <= 120s, configured 360s)
- `tests/test_gate_23.py::test_retry_backoff_schedule`
- `tests/test_model_config.py::test_active_model_latency_budget` (asserts <= 120s, configured 300s)
- `tests/test_model_config.py::test_tier2_latency_budget` (asserts <= 240s, configured 360s)
- `tests/test_model_config.py::test_tier1_keep_alive_is_zero` (asserts == 0, configured 300)
- *Root Cause:* Gate 23 tests enforce tight local inference SLAs (120s/240s) rather than cloud NIM / Ollama remote SLAs (300s/360s).

#### 5. Config Parameter Mismatches (3 failures)
- `tests/test_model_config.py::test_vram_fit_under_12gb`
- `tests/test_model_config.py::test_stream_chunk_timeout`
- `tests/test_model_config.py::test_retry_backoff_schedule`
- *Root Cause:* Asserts parameter values matching obsolete local model specifications.

#### 6. Orchestrator Mock Method Signature Drift (5 failures)
- `tests/integration/test_pipeline_e2e.py::test_v4_pipeline_full_e2e`
- `tests/test_v4_integration.py::test_v4_orchestrator_initialization`
- `tests/test_v4_integration.py::test_v4_stage_transitions`
- `tests/test_v4_integration.py::test_v4_quality_gate_flow`
- `tests/test_v4_integration.py::test_v4_error_recovery`
- *Root Cause:* These integration tests invoke `mock_run()` with keyword argument `mission_id`, but the mocked function signature in the test harness does not accept `mission_id`, raising `TypeError: mock_run() got an unexpected keyword argument 'mission_id'`.

#### 7. Meta-Verification Suite Failures (2 failures)
- `tests/test_submission_ready.py::test_package_integrity`
- `tests/test_submission_ready.py::test_gate_verification_suite`
- *Root Cause:* `test_submission_ready.py` runs a sub-process executing the gate tests above. Because Gate 15-4 and Gate 23 fail, this aggregator test fails downstream.

---

## 6. Deterministic Behavioral Reproductions

Three empirical issues identified during Prompt 1 forensic analysis were subjected to isolated reproduction scripts in the baseline:

### 1. QualityVerifier Keyword Truncation Defect (`agents/quality_verifier.py`)
- **Bug Mechanism:** In `QualityVerifier.verify()`, required keywords extracted from task descriptions are filtered by:
  ```python
  keywords = [kw.lower() for kw in task_description.split() if len(kw) > 4]
  ```
- **Reproduction:** For the task `"Card components implemented"`, the word `"Card"` (length 4) is dropped. As a result, the keyword filter produces `['components', 'implemented']`.
- **Consequence:** The verifier failed to detect `<article class="card card-balance">` and `.card` styles in the generated CSS/HTML, producing a persistent false-negative evaluation of `NEEDS_IMPROVEMENT`.
- **Status:** **VERIFIED & REPRODUCED** (Reproduced via `scratch/reproduce_quality_verifier.py`).

### 2. TUI Background Consumer UnboundLocalError (`ui/app.py`)
- **Bug Mechanism:** `from pathlib import Path` was only imported conditionally or locally in an earlier block in `ui/app.py`. When a `structured_feedback` event is received before that block runs, line 165 references `Path` directly:
  ```python
  feedback_file = Path(event.data.get("feedback_path", ""))
  ```
- **Reproduction:** Feeding a synthetic `structured_feedback` event into `_consume_mission_events` immediately triggers `UnboundLocalError: local variable 'Path' referenced before assignment`.
- **Consequence:** The background thread consuming events crashes silently. No further UI events are processed, freezing the visual interface at the current task (e.g. `[1/7]`), while the orchestrator continues in the background.
- **Status:** **VERIFIED & REPRODUCED** (Reproduced via `scratch/reproduce_tui_crash.py`).

### 3. Tool Identity Stripping in UI Progress Updates (`ui/app.py`)
- **Bug Mechanism:** In `ui/app.py:_consume_mission_events`, handling for `pipeline_stage` calls:
  ```python
  self.chat.update_progress(f"Stage: {event.stage_name}")
  ```
  It does not forward `event.tool_name` or `event.data.get("tool_name")` to the widget.
- **Consequence:** The TUI status bar displays `Tool: None` or defaults to `unknown_tool` during active tool invocations (`write_files_batch`, `read_file`).
- **Status:** **VERIFIED & REPRODUCED**.

---

## 7. Known Architectural Gaps Recorded in Baseline

1. **Dual Event Bus Implementations:**
   - `core/event_bus.py` implements a pub/sub `HermesEvent` system.
   - `core/mission_runner.py` implements a separate `_event_queue` (`MissionEvent`).
   - The Textual UI subscribes only to `mission_runner._event_queue`, leaving internal bus events unseen by the TUI.
2. **Workspace Directory Normalization:**
   - Workspace tools allow tools to write both at the workspace root (`new2/index.html`) and inside subdirectories (`new2/generated_projects/expense-tracker/index.html`), creating path divergence during iterative evaluation loops.
3. **Remote Cloud SSE Reliability:**
   - Heavy repeated generation loops through `nvidia_nim` / `z-ai/glm-5.3-flash` occasionally experience server-side SSE connection resets or 300s timeouts, requiring client-side reconnect handling.

---

## 8. Summary of Baseline Rules for HERMES 2.x

1. **Tag v1.0.0-rc3 is Immutable:** No tags or release commits will be force-pushed or altered.
2. **Branch hermes-2.x is the Active Development Line:** All forward development, defect resolution, and architectural improvements will branch from or land in `hermes-2.x`.
3. **No Unmeasured Claims:** All future PRs and commits must classify measurements strictly as `MEASURED`, `DERIVED`, `UNAVAILABLE`, or `NOT APPLICABLE`.
4. **Targeted Defect Resolution:** Subsequent prompts will address the catalogued defects (TUI consumer crash, QualityVerifier length drop, Windows path/shell portability, and test assertion synchronization) in dedicated, verifiable steps.
