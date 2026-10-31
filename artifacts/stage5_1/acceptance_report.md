# HERMES Stage 5.1 — Windows Process Safety and Launcher Failure-Path Verification Acceptance Report

**Date**: 2026-10-11  
**Runtime**: Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Repository**: `C:\Users\SUBBU\Downloads\hermes`  
**Status**: **ACCEPTED & VERIFIED (PASS)**

---

## 1. Executive Summary

Stage 5.1 verified the actual Windows process lifecycle, port conflict handling, startup timeouts, child process containment, and process identity cross-verification for the HERMES launcher harness. 

Every target requirement across Sections A through E and real browser smoke scenarios was tested and verified against real OS processes and a live Headless Chrome browser over the Chrome DevTools Protocol (CDP).

---

## 2. Verification Results by Section

### A. Port Conflict Protection & Foreign Process Safety
- **Dynamic Port Conflict**: Ran a controlled, unrelated HTTP/TCP process listening on a dynamic port (`127.0.0.1:<free_port>`). Verified that `launcher.launch_server(port=port)` detected the port as occupied by an unverified process, returned failure exit code `1`, and strictly refused to terminate or interfere with the unrelated process.
- **Default Port Safety (8765)**: Verified identical non-interference behavior on the default port. When an unrelated third-party process occupies `8765`, HERMES returns code `1` and leaves the foreign process completely untouched.
- **Zero False-Positive Health**: Verified that foreign HTTP endpoints on target ports do not trick `/api/health` verification into reporting a healthy HERMES instance.

### B. Startup Timeout & Early Failure Handling
- **Startup Timeout Enforcement**: Tested unresponsive server startup simulation. Verified that `launcher.wait_for_health` strictly times out at the configured deadline (tested with 1.0s timeout), terminates the failed child process, cleans up the PID file, and returns failure code `1`.
- **Early Process Crash Detection**: Tested immediate crash detection when the subprocess exits before listening. The launcher detects the premature return code immediately, logs the exit code, and avoids hanging until timeout.
- **Log Credential Redaction**: Verified that launcher diagnostic logging automatically redacts API keys, credentials, and tokens matching patterns such as `nvapi-*`, `AIza*`, and `sk-*`.

### C. PID-File Integrity & Process Identity Verification
- **Stale PID Cleanup**: Tested launcher behavior when an orphaned or stale `hermes_gui_server.pid` points to a non-existent PID. The launcher detects that the port is free and the process is dead, safely cleans up the stale PID file, and proceeds without error.
- **Foreign PID File Immunity**: Tested safety when a foreign PID file points to an unrelated active process (e.g. system or test process). Verified that `launcher.stop_server()` inspects the process command-line (`launcher.is_hermes_process`), detects that it is NOT a HERMES server (`uvicorn` / `main.py serve`), and strictly refuses to terminate it.

### D. Repeat Launch & Stop Safety
- **Healthy Server Reuse**: Verified that repeated invocations of `launch_server()` or `python main.py gui` against an already healthy instance return exit code `0` immediately without spawning a duplicate process.
- **Idempotent Stop**: Calling `stop_server()` when no server is running returns `True` cleanly without raising exceptions or logging false errors.
- **Clean Verified Stop**: `stop_server()` terminates only verified HERMES child processes and immediately unlinks the PID file.

### E. Health & Browser Integration
- Browser opening is strictly gated on a verified HTTP 200 response from `/api/health`.

---

## 3. Real Browser Smoke Acceptance Audit (`scripts/audit_stage5_1_smoke.py`)

Conducted automated browser verification using Headless Google Chrome (`1440x900`) interacting over Chrome DevTools Protocol (CDP):

| Scenario | Description | Result | Evidence Artifact |
|---|---|---|---|
| **Scenario 1** | Normal launch and connection via loopback; Orchid Lilac (`#DEBAD6`) / Forest Green (`#005437`) design tokens, TopBar `127.0.0.1:8765` indicator, and workspace display | **PASS** | `01_normal_launch_and_connection.png` |
| **Scenario 2** | Browser refresh with live page; verified constant backend process count (no duplicate spawned processes) | **PASS** | `02_browser_refresh_no_duplicates.png` |
| **Scenario 3** | Server process terminated while browser open; verified client polling detects failure and displays offline state warning banner (`Local HERMES backend offline at http://127.0.0.1:8765`) | **PASS** | `03_backend_offline_state.png` |
| **Scenario 4** | Server restarted; verified client polling automatically reconnects to `127.0.0.1:8765` and clears offline warning banner | **PASS** | `04_reconnected_after_restart.png` |

All screenshots and JSON evidence recorded in [`artifacts/stage5_1/`](file:///C:/Users/SUBBU/Downloads/hermes/artifacts/stage5_1/).

---

## 4. Test Suite & Build Verification

- **Automated Regression Suites**: 51/51 tests passing in 7.81s:
  - `tests/test_runtime_reliability_gate.py`: 6 passed
  - `tests/test_stage2_server_and_event_stream.py`: 12 passed
  - `tests/test_stage3_gui_prototype_acceptance.py`: 5 passed
  - `tests/test_stage4_review_and_diff_acceptance.py`: 6 passed
  - `tests/test_stage4_1_audit_acceptance.py`: 6 passed
  - `tests/test_stage5_launch_lifecycle.py`: 7 passed
  - `tests/test_stage5_1_process_safety.py`: 9 passed
- **Frontend Production Build**: `npm run build` in `gui/` completed with 0 errors (`196.59 kB JS`, `1.16 kB CSS`).
- **Workspace Invariants**:
  - Model stack preserved: T1: NVIDIA NIM `z-ai/glm-5.3-flash`, T2: Ollama Cloud `gpt-oss:120b-cloud`, T3: Ollama Cloud `nemotron-3-ultra:cloud`.
  - Campus Lab Manager untouched.
  - Zero git reset, clean, or commit operations performed.
