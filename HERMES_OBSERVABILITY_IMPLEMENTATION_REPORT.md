# HERMES 2.x — FORENSIC OBSERVABILITY & LIVE TELEMETRY IMPLEMENTATION REPORT

**Author:** Principal Python Runtime Engineer, AI Agent Observability Architect & Distributed Tracing Specialist  
**Harness:** HERMES 2.x Autonomous Application Development Platform  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Backend:** `http://127.0.0.1:8765` (PID 24332, Status: `SYNCED`)  
**Date:** November 1, 2026  

---

## 1. Executive Summary

This engineering implementation establishes a unified, multi-stream forensic telemetry and live terminal logging architecture for HERMES 2.x. Previously, mission failures involving long model-thinking intervals, provider timeouts, tier cycling, and tool errors were difficult to diagnose from the web UI alone. 

With this implementation, **every mission operation is visible, measurable, traceable, and persistently recorded across 8 specialized JSON Lines streams**, and an accompanying PowerShell live watcher streams color-coded telemetry to the console in real time.

All 59 regression and observability tests pass deterministically (Exit Code: 0). The `STALE RUNTIME` root cause has been diagnosed, repaired, and the backend server is verified `SYNCED` with matching loaded and disk fingerprints (`883974ebbcaea768`).

---

## 2. Stale Runtime Root Cause & Resolution

### 2.1 The Problem
In recent test runs (e.g. mission `m_1a2c5767`), the web UI displayed a persistent `STALE RUNTIME` badge.

### 2.2 Root Cause Analysis
1. **Process Desynchronization**: The backend server process (`PID 32404`) was booted at `12:39:22 IST`. When Python booted `core/server/app.py`, `_SERVER_CODE_FINGERPRINT` was calculated in memory as `"038876991c3c435d"`.
2. **Subsequent Code Modifications**: Between 13:00 and 13:10 IST, runtime remediation edits were applied to `core/agent_loop/loop.py`, `core/adaptive_routing.py`, etc.
3. **Mismatched Detection**: When `/api/health` was polled dynamically, it re-evaluated `_compute_code_fingerprint()`, which hashes `app.py`, `runtime_adapter.py`, and `loop.py`. Because `loop.py` on disk had changed, `disk_fingerprint` was `"1b79abf79bb46abb"`. Because `"038876991c3c435d" != "1b79abf79bb46abb"`, `code_match` became `False`, triggering `"runtime_status": "STALE_RUNTIME"`.
4. **Scope Deficiency**: The original fingerprint function only checked 3 files (`app.py`, `runtime_adapter.py`, `loop.py`), ignoring `adaptive_routing.py`, `common_adapter.py`, `core_tools.py`, etc., and gave no explanation of *which* files differed.

### 2.3 Remediation Implemented
1. **Expanded Monitored Manifest (`_CRITICAL_RUNTIME_FILES`)**:
   Expanded to all core runtime modules (`app.py`, `runtime_adapter.py`, `loop.py`, `types.py`, `decisions.py`, `recovery_policy.py`, `adaptive_routing.py`, `structured_observation.py`, `common_adapter.py`, `core_tools.py`).
2. **Granular Diff Detection (`_get_code_mismatches()`)**:
   The backend stores individual module SHA-256 hashes at boot time and now explicitly reports the list of mismatched files in `HealthResponse.mismatched_files`.
3. **Controlled Restart**:
   The stale process was terminated, port 8765 was verified clear, and the server was restarted using canonical Python 3.12.0. The new server process (PID 24332) reports:
   - `runtime_status`: `SYNCED`
   - `code_match`: `true`
   - `code_fingerprint`: `883974ebbcaea768`
   - `disk_fingerprint`: `883974ebbcaea768`
   - `mismatched_files`: `[]`

---

## 3. Files Created & Modified

### Created Files
| Path | Purpose |
| :--- | :--- |
| `core/observability/__init__.py` | Observability package exports and public APIs |
| `core/observability/schemas.py` | Canonical dataclasses, correlation context, and failure taxonomy |
| `core/observability/spans.py` | High-resolution monotonic timing spans and thinking interval classification |
| `core/observability/logger.py` | `MissionTelemetryLogger`: Multi-stream JSONL writer with auto-redaction and large payload offloading |
| `core/observability/bus_subscriber.py` | `ObservabilityBusSubscriber`: Connects EventBus to run telemetry loggers |
| `scripts/watch_mission_logs.ps1` | Live colorized PowerShell terminal log viewer |
| `tests/test_observability_system.py` | 13 deterministic tests (Tests A–M) covering all observability mechanisms |
| `scratch/run_telemetry_smoke_mission.py` | Controlled telemetry smoke test harness |
| `HERMES_LIVE_LOGGING_QUICKSTART.md` | Operator quickstart manual |
| `HERMES_OBSERVABILITY_IMPLEMENTATION_REPORT.md` | This formal implementation report |

### Modified Files
| Path | Changes Applied |
| :--- | :--- |
| `core/server/models.py` | Added `disk_fingerprint` and `mismatched_files` to `HealthResponse` |
| `core/server/app.py` | Multi-module fingerprint hashing, mismatch detection, `GET /api/telemetry/live`, `GET /api/telemetry/{run_id}/summary` |
| `core/runtime_state/events.py` | Added distributed tracing fields (`trace_id`, `span_id`, `parent_span_id`) to `HermesEvent` |
| `core/agent_loop/loop.py` | Wired `MissionTelemetryLogger`, model timing breakdown, tool call recording, file ops, deadline admission events, and markdown summary |

---

## 4. Structured Multi-Stream Log Schema

All logs are written to run-specific isolated directories:
`C:\Users\SUBBU\Downloads\hermes\artifacts\observability\<run_id>\`

### Log Stream Matrix
1. **`events.jsonl`**: The authoritative chronological stream of all events emitted during the run, linked by monotonic sequence and correlation IDs.
2. **`models.jsonl`**: Every model request and response. Includes provider name, tier, model ID, requested/effective max tokens, temperature, streaming status, TTFT, token counts, and sanitized payloads.
3. **`tools.jsonl`**: Every tool execution. Captures tool name, input arguments, start/end timestamps, duration, exit code, full stdout, full stderr, and target file.
4. **`recovery.jsonl`**: Recovery transitions, failure fingerprints, visited tiers, circuit-breaker states, and in-tier repair directives.
5. **`files.jsonl`**: File write and edit operations with relative path, operation type, size before/after, SHA-256 before/after, and model provenance.
6. **`validation.jsonl`**: Syntax checks (`node -c`, `node --check`, AST), HTML structure validation, CSS checks, browser checks, and console/network errors.
7. **`runtime.jsonl`**: Backend process health, PID, Python executable, loaded and disk source fingerprints, and deadline admission decisions.
8. **`errors.jsonl`**: All warnings, errors, and unhandled exceptions with full Python stack traces and sanitized error messages.
9. **`mission_summary.md`**: Human-readable markdown forensic summary generated upon run completion.

### Canonical Event JSON Schema
```json
{
  "timestamp_utc": "2026-11-01T09:16:19.503812+00:00",
  "timestamp_local": "2026-11-01T14:46:19.503812+05:30",
  "monotonic_ns": 1187328619000000,
  "run_id": "run_smoke_1793524603",
  "mission_id": "m_telemetry_smoke_01",
  "turn": 1,
  "event_seq": 14,
  "trace_id": "tr_9b83a1f8021c",
  "span_id": "sp_4a1b82d3",
  "parent_span_id": null,
  "component": "model_provider",
  "event_type": "MODEL_REQUEST_COMPLETED",
  "severity": "INFO",
  "tier": 1,
  "provider": "gemini",
  "model": "gemini-3.5-flash-lite",
  "duration_ms": 31.0,
  "status": "SUCCESS",
  "message": "Tier 1 [gemini/gemini-3.5-flash-lite] SUCCESS in 31.0ms",
  "payload": {
    "timings": {
      "phases": {
        "queue_wait_ms": 20.0,
        "time_to_first_token_ms": 320.0,
        "streaming_generation_ms": 510.0,
        "total_duration_ms": 850.0
      },
      "anomaly": null
    }
  }
}
```

---

## 5. Thinking Interval Attribution & Anomaly Classification

To eliminate unexplained "Thinking..." stalls, all model operations are deconstructed into measurable constituent phases:
- **`queue_wait_ms`**: Time spent waiting on semaphore or concurrency throttles.
- **`time_to_first_token_ms` (TTFT)**: Latency until the first byte/token chunk arrives from the provider endpoint.
- **`streaming_generation_ms`**: Time spent streaming tokens.
- **`response_parsing_ms`**: Time spent parsing JSON tool calls or structured outputs.
- **`local_or_network_overhead_ms`**: Residual latency.

### Anomaly Flagging
- **`MODEL_TTFT_LATENCY_EXCESSIVE`**: Triggered when TTFT $> 30\text{s}$.
- **`MODEL_TOTAL_LATENCY_EXCESSIVE`**: Triggered when total call duration $> 60\text{s}$.
- **`LOCAL_PROCESSING_OVERHEAD_HIGH`**: Triggered when unaccounted local latency $> 5\text{s}$.

---

## 6. Live Terminal Watcher (`watch_mission_logs.ps1`)

The live watcher runs in PowerShell and tails `events.jsonl` using a non-locking `FileStream`:
```powershell
.\scripts\watch_mission_logs.ps1 -Latest
```
### Live Sample Output
```text
================================================================================
 HERMES 2.x FORENSIC TELEMETRY STREAM :: run_smoke_1793524603
 Log directory: C:\Users\SUBBU\Downloads\hermes\artifacts\observability\run_smoke_1793524603
 Events stream: C:\Users\SUBBU\Downloads\hermes\artifacts\observability\run_smoke_1793524603\events.jsonl
================================================================================
TIMESTAMP      SEV      EVENT_TYPE                 DETAILS
--------------------------------------------------------------------------------
[14:46:45.154] INFO    RUNTIME_SNAPSHOT           Runtime state: SYNCED (PID 7496)
[14:46:45.227] INFO    GOAL_CREATED               GOAL_CREATED
[14:46:45.239] INFO    MISSION_STARTED            MISSION_STARTED
[14:46:45.249] INFO    TASK_STARTED               TASK_STARTED
[14:46:45.250] INFO    AGENT_TURN_STARTED         AGENT_TURN_STARTED
[14:46:45.269] INFO    TIER_SELECTED              [Tier 1] TIER_SELECTED
[14:46:45.270] INFO    MODEL_REQUESTED            MODEL_REQUESTED
[14:46:45.271] INFO    MODEL_CALL_ADMISSION_ALLOWED Model call admission granted: 60.0s turn budget | Budget=298.7s
[14:46:45.293] INFO    MODEL_COMPLETED            [Tier 1] MODEL_COMPLETED (dur=30ms)
[14:46:45.294] INFO    MODEL_REQUEST_COMPLETED    [Tier 1] Tier 1 [gemini/gemini-3.5-flash-lite] SUCCESS in 31.0ms (dur=31.0ms)
[14:46:45.337] INFO    TOOL_COMPLETED             Tool fs.write succeeded (exit=0) in 0.0ms | exit=0
[14:46:45.338] INFO    FILE_WRITE_COMPLETED       File write: smoke.txt (67 bytes, changed=True)
[14:46:45.340] INFO    ACCEPTANCE_CHECK_PASSED    ACCEPTANCE_CHECK_PASSED
[14:46:45.484] INFO    MISSION_COMPLETED          MISSION_COMPLETED
```

---

## 7. Security & Credential Redaction Verification

All logged payloads pass through recursive redaction:
- API keys matching `sk-...`, `ghp_...`, Bearer tokens, cookies, authorization headers, and passwords are unconditionally replaced with `[REDACTED_SECRET]`.
- Verified deterministically in `test_k_sensitive_data_redaction`: zero raw secrets leaked into any generated log file.

---

## 8. Test Suite Verification & Exit Codes

### Pytest Execution Summary
All 6 test suites executed using canonical Python `3.12.0`:
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_incident_m_b9d872ee_regression.py tests/test_closure_regressions.py tests/test_multi_tier_incident_replay.py tests/test_loop_recovery_and_completion.py tests/test_recovery_loop_remediation.py tests/test_observability_system.py -v
```

```text
tests/test_incident_m_b9d872ee_regression.py     3 passed
tests/test_closure_regressions.py               18 passed
tests/test_multi_tier_incident_replay.py         6 passed
tests/test_loop_recovery_and_completion.py       5 passed
tests/test_recovery_loop_remediation.py         14 passed
tests/test_observability_system.py              13 passed
============================= 59 passed in 23.43s =============================
Exit Code: 0
```

---

## 9. Controlled Telemetry Smoke Test Record

- **Smoke Mission ID:** `m_telemetry_smoke_01`
- **Run ID:** `run_smoke_1793524603`
- **Workspace:** `C:\Users\SUBBU\Downloads\telemetry_smoke_ws`
- **Log Directory:** `C:\Users\SUBBU\Downloads\hermes\artifacts\observability\run_smoke_1793524603\`
- **Terminal Status:** `COMPLETED`
- **Files Verified:** All 8 stream files + `mission_summary.md` generated and formatted properly.

---

## 10. Final Gate Authorization Verdict

READY FOR NEXT APPLICATION BENCHMARK
