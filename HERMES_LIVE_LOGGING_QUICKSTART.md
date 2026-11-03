# HERMES 2.x — LIVE FORENSIC LOGGING QUICKSTART

This manual explains how to run and monitor HERMES missions with real-time terminal telemetry and examine specialized forensic logs.

---

## 1. Starting the Backend Server

Always start the backend using the canonical Python interpreter:

```powershell
cd C:\Users\SUBBU\Downloads\hermes
.\venv\Scripts\python.exe -m uvicorn core.server.app:app --host 127.0.0.1 --port 8765 --log-level info
```

### Verifying Synchronization
In another PowerShell terminal:
```powershell
.\venv\Scripts\python.exe -c "import urllib.request, json; print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8765/api/health').read()), indent=2))"
```
Ensure `"runtime_status": "SYNCED"` and `"code_match": true`.

---

## 2. Launching the Live Terminal Watcher

Open a dedicated PowerShell terminal and run:

```powershell
cd C:\Users\SUBBU\Downloads\hermes
.\scripts\watch_mission_logs.ps1 -Latest
```

### Watcher Options
- **Follow latest mission automatically:**
  ```powershell
  .\scripts\watch_mission_logs.ps1 -Latest
  ```
- **Follow a specific Mission ID:**
  ```powershell
  .\scripts\watch_mission_logs.ps1 -MissionId m_1a2c5767
  ```
- **Follow a specific Run ID:**
  ```powershell
  .\scripts\watch_mission_logs.ps1 -RunId run_smoke_1793524603
  ```
- **Print historical events without following:**
  ```powershell
  .\scripts\watch_mission_logs.ps1 -RunId run_smoke_1793524603 -NoFollow
  ```

---

## 3. Telemetry Log Storage & Directory Structure

Every mission run writes an isolated log directory under:
`C:\Users\SUBBU\Downloads\hermes\artifacts\observability\<run_id>\`

| File | What to Inspect |
| :--- | :--- |
| **`events.jsonl`** | Full chronological event stream with timestamps and monotonic sequencing. |
| **`models.jsonl`** | Model requests, latency breakdowns (TTFT, streaming, parse), token counts, and provider error bodies. |
| **`tools.jsonl`** | Every tool execution with arguments, duration, exit code, full stdout, and full stderr. |
| **`recovery.jsonl`** | Failure classifications, incident fingerprints, visited tiers, and circuit breaker transitions. |
| **`files.jsonl`** | File creation, edits, before/after SHA-256 digests, and size deltas. |
| **`validation.jsonl`** | Compiler checks (`node --check`, AST), HTML analysis, and browser evaluation. |
| **`runtime.jsonl`** | Backend health snapshots, loaded vs disk code fingerprints, and deadline admission decisions. |
| **`errors.jsonl`** | All warnings, provider failures, and unhandled exceptions with full Python stack traces. |
| **`mission_summary.md`** | Human-readable markdown summary produced upon mission termination. |

---

## 4. How to Diagnose Common Issues

### A. Diagnosing Long Thinking Stalls (e.g. 59s–71s)
Open `models.jsonl` or watch the live viewer:
- Check `phases.time_to_first_token_ms`: If $> 30\text{s}$, the provider was stalled on initial token delivery (`MODEL_TTFT_LATENCY_EXCESSIVE`).
- Check `phases.streaming_generation_ms`: If slow, network chunk delivery was congested.
- Check `phases.queue_wait_ms`: If high, local semaphore was congested.

### B. Diagnosing Provider Errors (HTTP 429, 500, 503)
Open `models.jsonl` and `errors.jsonl`:
- Inspect `payload.error_details`: Contains HTTP status code, sanitized provider response body, and `Retry-After` header.

### C. Diagnosing Compiler & Syntax Errors (e.g. `node -c app.js`)
Open `tools.jsonl` or `validation.jsonl`:
- Search for `node --check` or `node -c`.
- The full, unabridged `stderr` is stored in `payload.stderr_summary` (or linked in `tool_outputs/stderr_*.txt` for large outputs).

### D. Diagnosing Tier Escalation & Circuit Breakers
Open `recovery.jsonl`:
- Look for `TIER_TRANSITION_COMPLETED`.
- Shows `from_tier`, `to_tier`, `reason`, `circuit_state`, and `recovery_counters`.
- Explains why a tier was selected and whether Tier 1 rotation was authorized.

### E. Diagnosing Missing-Deliverable Stalls & No-Progress
Open `recovery.jsonl`:
- Search for `REASONING_STALL_EVALUATED`.
- Shows `consecutive_empty_turns`, `unmet_deliverables`, and mandatory corrective directives.

### F. Viewing the Final Forensic Summary
Open `mission_summary.md` in the run directory for a complete executive overview of mission duration, turns executed, final active tier, artifacts generated, and failure diagnostics.
