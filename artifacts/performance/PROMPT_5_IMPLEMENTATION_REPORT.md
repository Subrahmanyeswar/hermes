# HERMES Performance Optimization Program — Prompt 5 of 8
# Parser Hardening + Structured Output + Safe <=3-File Batch Generation (`write_files_batch`)
# Implementation, Empirical Verification, and Final Closure Report

**Status:** PASS_AND_LOCKED  
**Date:** 2026-09-17  
**Runtime:** HERMES v4.0 Local-First Autonomous SWE Engine  
**Hardware Profile:** Local Workstation (NVIDIA GeForce RTX 3050 Laptop GPU, 6GB VRAM, 16GB System RAM)  
**Primary Models:** `deepseek-r1:8b` (Tier 1 Code Generation), `qwen3:8b` (Tier 2 Verification)  

---

## 1. Executive Summary

Prompt 5 addresses the primary multi-file execution bottleneck identified during Prompt 4 profiling: **repetitive multi-turn tool round-trips for small multi-file software engineering tasks**. While Prompt 4 reduced input context overhead by 28.86% via prefix caching and selective tool schemas, generation remained the dominant runtime component because small multi-file projects (such as `index.html`, `styles.css`, and `app.js`) previously required 3 separate model turns, 3 prompt serialization cycles, and 3 sequential tool dispatches.

Prompt 5 resolves this multi-turn overhead through two complementary pillars:
1. **Parser & Structured Output Robustness:** Native structured output forwarding via Ollama JSON schema constraints, coupled with deterministic `ResponseParser` hardening (strict unknown-tool rejection, string-literal-aware depth tracking, and JSON-in-content injection defense).
2. **Safe Batch File Execution:** Introducing `write_files_batch` bounded strictly to $\le 3$ files with pre-mutation security validation, transactional staging, backup restoration on detected commit failure, unconditional cleanup, and strict benchmark-mode isolation.

---

### Dual Performance Summary: Observed Workload vs. Controlled Matched-Content

To ensure research-grade scientific integrity, HERMES explicitly distinguishes **observed model-generation performance on an end-to-end task** from **controlled file-write path performance under identical file contents**. Neither result is substituted for the other.

```
====================================================================================================
ORIGINAL OBSERVED RUN (EduPath Mini 3-File Web Project)
====================================================================================================
Model Turns:               3 turns -> 1 turn (-66.7%, -2 turns)
Tool Dispatches:           3 dispatches -> 1 dispatch (-66.7%, -2 dispatches)
Elapsed Wall Latency:      61.684 s -> 24.133 s (-60.88%, 2.56x lower elapsed time)
Input Tokens:              750 tokens -> 376 tokens (-49.87%, -374 tokens)
Output Tokens:             1,875 tokens -> 724 tokens (-61.39%, -1,151 tokens)
Interpretation Scope:      Observed end-to-end task execution. Generated artifact contents and lengths
                           differed between sequential and batch runs; hence the 2.56x elapsed time
                           reduction reflects combined benefits of eliminated turn handshakes,
                           prompt re-evaluation savings, and concise consolidated batch generation.
====================================================================================================
CONTROLLED MATCHED-CONTENT RUN (Deterministic Fixtures: index.html, styles.css, app.js)
====================================================================================================
Artifact Hashes:           100% EXACT MATCH across all 3 files (SHA256 verified)
Tool Dispatches:           3 dispatches -> 1 dispatch (-66.7%, -2 dispatches)
Write-Path Median Latency: 37.719 ms -> 21.362 ms (-43.37%, -16.357 ms)
Write-Path Min Latency:    36.319 ms -> 18.195 ms (-49.90%)
Write-Path Max Latency:    42.668 ms -> 28.470 ms (-33.28%)
Repetitions:               3 independent runs per configuration
Interpretation Scope:      Pure write-path execution under 100% identical file contents. Demonstrates
                           that write_files_batch reliably reduces top-level tool dispatches by 66.7%
                           and reduces write-path staging and commit overhead by 43.37%.
====================================================================================================
```

---

## 2. Architecture & Design Implementation

Prompt 5 integrates robust parsing and safe batch execution into the HERMES local runtime architecture:

```
                    PROMPT 5 ARCHITECTURE
                               │
                ┌──────────────┴──────────────┐
                │                             │
         PARSER ROBUSTNESS             BATCH EXECUTION
                │                             │
      Structured Output               <=3 Files Hard Limit
      Schema Validation               Pre-mutation Security Check
      Deterministic Fallback          Staged File Writes
      Unknown-Tool Rejection          Backup on Overwrite
      JSON-in-Content Defense         Rollback on Commit Failure
                │                     Unconditional Temp Cleanup
                └──────────────┬──────────────┘
                               │
                               ▼
                     VERIFIED REPO FILES
```

### 2.1 Native Structured Output Forwarding (`models/ollama_client.py`)
- Added optional `format: Optional[Union[str, dict]] = None` parameter to `OllamaClient.generate()`.
- Forwards `format="json"` or structured JSON schemas directly into Ollama's HTTP body options, enabling constrained grammar decoding when supported by the underlying engine.

### 2.2 Response Parser Hardening (`core/response_parser.py`)
Prior to Prompt 5, `ResponseParser` accepted any JSON dictionary containing a `"tool"` key, allowing hallucinated tools (e.g., `teleport_to_mars`) to pass as `ParseSuccess` and fail only downstream.
- **Unknown Tool Rejection:** `_validate_and_build()` validates tool names against `_get_known_tools()`. Unknown tool hallucinations are strictly rejected and diagnosed with `unknown_tool_rejected:<tool>`.
- **String-Literal-Aware Depth Tracking:** `_try_extract_json_object()` tracks string literal boundaries (`in_string` and escape sequence handling). Curly braces `{` and `}` inside JavaScript code or JSON data strings no longer prematurely truncate JSON extraction.
- **JSON-in-Content Injection Defense:** Code content containing simulated tool keys (such as `{"tool": "delete_file"}`) is safely handled as raw string content without triggering nested parser hijacking.
- **Demo Placeholder Rejection:** Rejects mock string content (e.g., `"full content here"`, `"the code string"`) across both `write_file` and `write_files_batch`.
- **Batch Schema Verification:** Validates batch invariants ($1 \le \text{files} \le 3$, non-empty paths, string contents, and unique normalized paths).

### 2.3 Safe Batch File Tool (`tools/file_tools.py`)
Implemented `WriteFilesBatchTool` registered as `write_files_batch`:
- **Hard Upper Bound:** Strict invariant: $1 \le \text{len}(files) \le 3$. Payloads with 0 files or $\ge 4$ files are immediately rejected. Tasks with 4+ files fall back to the sequential path.
- **Payload Limit:** Maximum total batch payload is bounded at 1,000,000 bytes (1 MB).
- **Security Boundary Enforcement:** Every path in the batch is pre-validated against `workspace_manager.validate_path()`. Any path traversal (`../`) or null-byte injection immediately fails with exit code 126 before any disk write.
- **Duplicate Normalized Path Detection:** Rejects batches targeting the same file via multiple paths (e.g., `app.py` and `./app.py`).
- **Transactional Staging & Rollback Semantics:**
  1. *Staging:* Files are written to a temporary staging directory (`hermes_batch_staging_<hex>`).
  2. *Backup:* If target files already exist on disk, copies are backed up to a temporary backup directory (`hermes_batch_backup_<hex>`).
  3. *Commit:* Staged files are moved/written to their destination paths.
  4. *Rollback:* If any failure occurs during commit, backed-up files are restored, newly created files are deleted, and no corrupted state remains.
  5. *Cleanup:* All temporary staging and backup directories are cleaned up unconditionally in a `finally:` block.
  6. *Index Refresh:* Automatically calls `workspace_manager.refresh_index()` upon success or rollback.

### 2.4 Adaptive Selective Tool Exposure (`tools/registry.py`)
- **Benchmark Isolation Guarantee:** In benchmark mode (`execution_mode == "benchmark"`), `selective_tool_schema_for_prompt()` unconditionally returns the canonical 20 tools. `write_files_batch` is strictly excluded from benchmark schemas.
- **Production Routing:** In production mode, `write_files_batch` is exposed in prompt schemas *only* when `allow_batch_tools=True` on eligible 2–3 file tasks. Single-file tasks and 4+ file tasks expose only `write_file`.

### 2.5 Validation & Progressive Verification Integration (`core/tool_validator.py`, `core/verification_gate.py`)
- **`ToolValidator`:** Implemented parameter normalization for `files` list items (resolving aliases like `target_file` -> `path`, `CodeContent` -> `content`) and added batch path traversal and duplicate checks in `validate_security()`.
- **`VerificationGate`:** Classified `write_files_batch` as `ToolRiskCategory.LOW_RISK_WRITE`. Implemented Level 0 deterministic file existence checks and Level 1 structural Python AST and JSON syntax validation across all files in the batch.

---

## 3. Empirical Results & Comparative Analysis

### 3.1 Original Observed EduPath Mini Run (Historical Workload Evidence)

The end-to-end A/B evaluation was conducted on the canonical **EduPath Mini** 3-file web project (`index.html`, `styles.css`, `app.js`) under warm model conditions (`deepseek-r1:8b`), `think=False`, and `temperature=0.1`.

| Metric | Sequential `write_file` (3 Turns) | Safe Batch `write_files_batch` (1 Turn) | Delta / Change | Evidence Classification |
| :--- | :--- | :--- | :--- | :--- |
| **Model Turns** | 3 turns | 1 turn | **-66.7% (-2 turns)** | `[MEASURED]` |
| **Tool Dispatches** | 3 dispatches | 1 dispatch | **-66.7% (-2 dispatches)** | `[MEASURED]` |
| **Total Wall Clock Latency** | 61.684 s | 24.133 s | **-60.88% (-37.551 s)** | `[MEASURED]` |
| **Speedup Ratio** | 1.00x | **2.56x** | **2.56x lower elapsed time** | `[DERIVED]` |
| **Input Tokens (Prompt Eval)** | 750 tokens | 376 tokens | **-49.87% (-374 tokens)** | `[MEASURED]` |
| **Output Tokens (Generation)** | 1,875 tokens | 724 tokens | **-61.39% (-1,151 tokens)** | `[MEASURED]` |
| **Total Tokens Processed** | 2,625 tokens | 1,100 tokens | **-58.10% (-1,525 tokens)** | `[MEASURED]` |
| **Tool Execution Latency** | 74.38 ms (sum of 3) | 60.85 ms (batch commit) | **-18.19% (-13.53 ms)** | `[MEASURED]` |
| **Response Parsing Latency** | 0.90 ms (sum of 3) | 0.12 ms | **-86.67% (-0.78 ms)** | `[MEASURED]` |
| **All Target Files Created** | Yes (3/3) | Yes (3/3) | **100% parity** | `[MEASURED]` |

#### Causal Breakdown of Observed EduPath Mini Run:
- **Sequential Run:** Generated 2,228 bytes for `index.html` (Turn 1: 23.66s), 1,633 bytes for `styles.css` (Turn 2: 24.65s), and 1,305 bytes for `app.js` (Turn 3: 13.30s). Total generation was 1,875 tokens across 3 separate LLM invocations.
- **Batch Run:** Generated 650 bytes for `index.html`, 412 bytes for `styles.css`, and 1,159 bytes for `app.js` in a single unified generation of 724 tokens (Turn 1: 24.07s).
- **Attribution Note:** The 2.56x elapsed time reduction and 61.39% output token reduction reflect both the architectural benefits of collapsing 3 turns into 1 turn and differences in generated file verbosity.

---

### 3.2 Controlled Matched-Content A/B Experiment

To isolate the pure write-path execution efficiency from generative variability, an identical-content experiment was executed using fixed deterministic fixtures for `index.html`, `styles.css`, and `app.js` across 3 independent repetitions (`artifacts/performance/prompt5/matched_batch_ab_results.json`).

#### Cryptographic Hash Parity (100% Identical Final Artifacts):
- `index.html`: `ae1bf4a2e1d27cce9f89d9f3b7781f5e09622489c604e5105a2af8186e860f92` (**MATCH**)
- `styles.css`: `c9496d3fbdea9e4813bb3b5485b2a2d4df0f02c99601310a31dede3cb904ce35` (**MATCH**)
- `app.js`: `b84853580650f0a2cbbe78dd698d7ff1246807fcf525a654528007a930d6b0e3` (**MATCH**)

#### Controlled Latency & Dispatch Results:

| Metric | Sequential `write_file` (3 Dispatches) | Batch `write_files_batch` (1 Dispatch) | Delta | Delta (%) |
| :--- | :--- | :--- | :--- | :--- |
| **Top-Level Tool Dispatches** | 3 dispatches | 1 dispatch | **-2 dispatches** | **-66.7%** |
| **Min Total Write Latency** | 36.319 ms | 18.195 ms | -18.124 ms | -49.90% |
| **Median Total Write Latency** | **37.719 ms** | **21.362 ms** | **-16.357 ms** | **-43.37%** |
| **Max Total Write Latency** | 42.668 ms | 28.470 ms | -14.198 ms | -33.28% |
| **Median Tool Execution Only** | 37.079 ms | 21.362 ms | -15.717 ms | -42.39% |
| **Verification Gate Latency** | 0.640 ms (3x L0/L1) | 0.215 ms (1x Batch L0/L1) | -0.425 ms | -66.41% |

#### Controlled Experiment Conclusion:
Under 100% matched artifact contents, `write_files_batch` reduces top-level tool dispatches by 66.7% (3 to 1) and reduces write-path staging, verification, and commit latency by 43.37% (37.72 ms to 21.36 ms).

---

### 3.3 Structured Output vs. Free-Form Parser Empirical Evaluation

A dedicated head-to-head empirical evaluation (`artifacts/performance/prompt5/structured_output_ab_results.json`) was conducted across 8 representative tool-calling scenarios:
1. Standard single-file write (`write_file`)
2. Safe batch write (`write_files_batch` with 3 files)
3. Malformed JSON response (unclosed quotes, syntax errors)
4. Unknown tool hallucination (`teleport_to_mars`)
5. JSON-like file content simulating a tool payload (content-as-data)
6. Complex JavaScript code with deeply nested curly braces
7. Multiline code content with indented blocks
8. Escaped characters (quotes, backslashes, tabs)

#### Summary Results:

| Path | Correct Extraction / Safe Rejection | Fallback Triggered | Avg Latency | Security & Containment |
| :--- | :--- | :--- | :--- | :--- |
| **Hardened Free-Form Parser** | **8 / 8 (100%)** | 0 / 8 | 0.218 ms | 100% Contained |
| **Structured Output Path** | **8 / 8 (100%)** | 2 / 8 (safe delegation) | 0.090 ms | 100% Contained |

#### Findings on Structured Output:
- **Primary Benefit is Determinism, Not Speed:** Both paths operate under 0.5 ms per call. The true advantage of structured output is enforcing strict grammar boundaries at model decode time, preventing conversational chatter, preamble text, or markdown fencing malformations from corrupting the tool call.
- **Safe Fallback Delegation:** When structured decoding encounters malformed syntax or unknown tools (Cases 3 & 4), it safely falls back to `ResponseParser` diagnostics without infinite loops or unauthorized execution.
- **Content-as-Data Preservation:** Both paths correctly treated JSON content inside files as pure payload data without nested parser hijacking.

---

### 3.4 Batch Transaction & Rollback Semantics

To ensure precise technical accuracy, the filesystem guarantee of `write_files_batch` is defined as:
> **"Prevalidated multi-file staging with rollback on detected commit failure."**  
> *The implementation validates all parameters and paths before disk mutation, stages writes in a temporary directory, backs up existing target files when necessary, attempts commit, restores original files upon any detected failure, and unconditionally cleans up all temporary staging directories.*

An empirical validation suite of 10 failure and edge-case scenarios (`artifacts/performance/prompt5/batch_atomicity_results.json`) was executed:

| Scenario | Tested Condition | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- |
| **1. Valid 1-File Batch** | Single file write | File committed cleanly | 1 file on disk, 0 temp leaks | **PASS** |
| **2. Valid 2-File Batch** | Two files write | Both committed cleanly | 2 files on disk, 0 temp leaks | **PASS** |
| **3. Valid 3-File Batch** | Three files write | All 3 committed cleanly | 3 files on disk, 0 temp leaks | **PASS** |
| **4. Duplicate Path** | `./dup.txt` and `dup.txt` | Pre-mutation rejection | Zero bytes written, 0 temp leaks | **PASS** |
| **5. Path Traversal** | `../../escape.txt` | Pre-mutation rejection | Exit code 126, 0 disk mutation | **PASS** |
| **6. New File Commit Failure** | Disk failure on 2nd file | Roll back 1st file | 1st file removed, 0 residue | **PASS** |
| **7. Existing File Restoration** | Overwrite existing + failure | Restore original backup | Original content 100% restored | **PASS** |
| **8. Temp Directory Cleanup** | Directory audit after run | Zero orphaned folders | 0 temp directories leaked | **PASS** |
| **9. 4+ Files Upper Bound** | Batch with 4 files | Schema/Pydantic rejection | Pre-execution validation error | **PASS** |
| **10. 0 Files Lower Bound** | Batch with 0 files | Schema/Pydantic rejection | Pre-execution validation error | **PASS** |

All 10/10 scenarios passed with zero filesystem leaks.

---

## 4. Claim Reconciliation & Final Claim Audit

In accordance with HERMES research integrity standards, every performance claim has been audited against direct empirical evidence:

| Original Phrasing / Claim Area | Audited Status | Scoped Technical Claim | Supporting Evidence |
| :--- | :--- | :--- | :--- |
| **"2.56x speedup"** | Clarified / Scoped | 2.56x lower elapsed time was observed on the specific EduPath Mini run (61.68s -> 24.13s), where artifact contents differed. Pure write-path latency reduction under matched contents is measured at 43.37%. | Section 3.1 & 3.2; `batch_generation_results.json` & `matched_batch_ab_results.json` |
| **"61.39% output token reduction"** | Clarified / Scoped | Scoped as an observed outcome of the EduPath Mini run, driven jointly by consolidated JSON schema wrapping and differing file content lengths. It is not claimed as an invariant batch-only property. | Section 3.1; `batch_generation_results.json` |
| **"Guaranteed atomic rollback"** | Reworded | Downgraded to "prevalidated multi-file staging with rollback on detected commit failure". Universal OS-level atomic filesystem guarantees are not claimed. | Section 3.4; `batch_atomicity_results.json` |
| **"100% faster / eliminates all waste"** | Eliminated | Replaced with exact measured metrics: -66.7% turns (3 -> 1), -66.7% tool dispatches (3 -> 1), and -43.37% write-path latency. | Section 1 & 3.2 |
| **"Zero correctness risk"** | Qualified | Replaced with evidence-based statements: 228/228 unit tests passing, 47/47 Prompt 5 tests passing, zero security regressions detected across 10 staging scenarios. | Section 5; pytest execution records |

---

## 5. Verification Suites & Cryptographic Integrity

### 5.1 Test Execution Matrix

| Test Suite | Command | Tests | Passed | Duration | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Parser Hardening Suite** | `pytest tests/test_prompt5_parser_hardening.py` | 21 | 21 | 0.34s | **PASS** |
| **Write Files Batch Tool Suite** | `pytest tests/test_write_files_batch.py` | 16 | 16 | 0.64s | **PASS** |
| **Batch Routing & Gate Suite** | `pytest tests/test_prompt5_batch_routing.py` | 10 | 10 | 0.35s | **PASS** |
| **Total Prompt 5 Test Suite** | *Combined Prompt 5 test execution* | **47** | **47** | **0.79s** | **PASS** |
| **Prompt 4 Context Suite** | `pytest tests/test_prompt4_context_optimization.py` | 9 | 9 | 0.26s | **PASS** |
| **Prompt 3 Isolation Suite** | `pytest tests/test_prompt3_benchmark_isolation.py` | 7 | 7 | 2.28s | **PASS** |
| **Dataset Integrity Suite** | `pytest tests/test_benchmark_dataset_integrity.py` | 6 | 6 | 0.08s | **PASS** |
| **Canonical Offline Unit Suite** | `pytest tests/test_part7_... tests/test_cost_accounting.py` | **228** | **228** | **14.31s** | **PASS** |

### 5.2 Frozen Benchmark Cryptographic Invariants
Verified with `python scripts/verify_benchmark_hashes.py`:
- `artifacts/final_benchmark_dataset.json`: `f3475b6415364ccea70f4710bfe2137fe84d91cce5d1db822e8d156716cf4d72` (**EXACT MATCH**)
- `artifacts/final_benchmark_success_contract.json`: `4cf78a7dce0cfedfeb81e5e6929241fb7fd69d5eba0ba2b91888f6744834fff3` (**EXACT MATCH**)
- `artifacts/FINAL_BENCHMARK_EXECUTION_PROTOCOL.md`: `8740e0a6face5b1b4ce1b23839a97605cffb63045e289bda7b297fb83d8bfe15` (**EXACT MATCH**)

---

## 6. Artifact Directory Manifest

All Prompt 5 artifacts are persisted and verified:
1. `artifacts/performance/prompt5/parser_baseline.json`: Baseline parser evaluations.
2. `artifacts/performance/prompt5/parser_hardening_results.json`: Post-hardening validation results.
3. `artifacts/performance/prompt5/batch_generation_results.json`: Historical EduPath Mini observed run telemetry.
4. `artifacts/performance/prompt5/matched_batch_ab_results.json`: 3-repetition matched-content controlled experiment with SHA256 parity.
5. `artifacts/performance/prompt5/structured_output_ab_results.json`: Dedicated 8-case structured output vs free-form evaluation.
6. `artifacts/performance/prompt5/batch_atomicity_results.json`: 10-scenario staging, rollback, restoration, and cleanup empirical record.
7. `artifacts/performance/prompt5/write_files_batch_results.json`: Tool specification and security verification audit.
8. `artifacts/performance/prompt5/prompt5_state.json`: Component-level state file.
9. `artifacts/performance/PROMPT_5_STATE.json`: Root performance program state file.
10. `artifacts/performance/PROMPT_5_IMPLEMENTATION_REPORT.md`: This comprehensive closure report.

---

## 7. Conclusion & Final Closure Gate

All empirical, architectural, security, and documentation requirements for Prompt 5 are satisfied:
- Parser hardened against unknown tools and JSON-in-content injection.
- Structured output evaluated with verified safe fallback.
- `write_files_batch` strictly bounded to $\le 3$ files with prevalidated staging and rollback on detected failure.
- Both observed workload (2.56x lower elapsed time) and matched-content write-path (-43.37% latency, -66.7% dispatches) documented and cleanly attributed.
- 100% benchmark isolation and canonical test integrity maintained.

**Final Verdict:** **PROMPT_5 = PASS_AND_LOCKED**
