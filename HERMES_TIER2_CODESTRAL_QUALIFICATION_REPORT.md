# HERMES 2.x — TIER 2 MISTRAL `codestral-latest` QUALIFICATION & VERIFICATION REPORT

**Incident / Context:** Decision B Execution — Tier 2 Migration to Mistral  
**Active Model Stack:**
- **Tier 1:** `gemini / gemini-3.5-flash-lite` (Primary)
- **Tier 2:** `mistral / codestral-latest` (Qualified Fast Coding & Recovery Tier)
- **Tier 3:** `nvidia_nim / nvidia/nemotron-3.5-lightning-30b-a3b` (Escalation / Reasoning Tier)
**Canonical Python Interpreter:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Backend Status:** `http://127.0.0.1:8765/api/health` → `status: "ok"`, `runtime_status: "SYNCED"`, `code_match: true`  

---

## 1. Executive Summary & Verdict

Following approval of **Decision B**, HERMES Tier 2 has been configured to use Mistral's qualified coding model `codestral-latest`. 

All qualification gates have been executed:
1. **Model Stack Verification:** Tier 1 and Tier 3 remain untouched. Tier 2 connects directly to `https://api.mistral.ai/v1` with native function calling and SSE streaming.
2. **Deterministic Regression Suites:** **97/97 tests passed** across all 8 test suites in 34.67 seconds.
3. **Live Model Qualification Suite (`test_tier2_codestral_real_qualification.py`):** **5/5 live tests passed** covering connectivity, clean JavaScript generation, multi-turn native tool calls (`fs.write`, `fs.read`), syntax error recovery, and forensic telemetry logging.
4. **End-to-End Mission Verification:** Controlled mission `m_7f08fbe6` executed through the live backend API, generating a full 4-file counter application in **11.5 seconds** with **100% valid JavaScript syntax** and clean acceptance gate passage.
5. **Observability & Log Streaming:** Verified `.\scripts\watch_mission_logs.ps1` with stream filtering (`-Stream events`, `-Stream models`, `-NoFollow`).

**Verdict: READY — TIER 2 `codestral-latest` FULLY QUALIFIED AND OPERATIONAL.**

---

## 2. Configuration Details & Diff

### Exact Model ID
- **Current Active Model:** `codestral-latest`
- **Intended Target Model (Documented):** `mistral-small-2603` (to be restored when credits are provisioned)
- **API Base URL:** `https://api.mistral.ai/v1`

### Configuration Diff

#### A. `.env`
```diff
-TIER2_PROVIDER=groq
-TIER2_MODEL=qwen/qwen3.8-27b
-TIER2_BASE_URL=https://api.groq.com/openai/v1
+TIER2_PROVIDER=mistral
+TIER2_MODEL=codestral-latest
+TIER2_BASE_URL=https://api.mistral.ai/v1
+MISTRAL_API_KEY=mstrl_***
```

#### B. `config/model_config.py`
```diff
-TIER2_PROVIDER = os.getenv("TIER2_PROVIDER", "groq")
-TIER2_MODEL = os.getenv("TIER2_MODEL", "qwen/qwen3.8-27b")
-TIER2_BASE_URL = os.getenv("TIER2_BASE_URL", "https://api.groq.com/openai/v1")
+TIER2_PROVIDER = os.getenv("TIER2_PROVIDER", "mistral")
+TIER2_MODEL = os.getenv("TIER2_MODEL", "codestral-latest")  # Target: mistral-small-2603
+TIER2_BASE_URL = os.getenv("TIER2_BASE_URL", "https://api.mistral.ai/v1")
+MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
```

#### C. `models/common_adapter.py`
1. **Loop-Aware Client & Semaphore:** Prevents `RuntimeError: Event loop is closed` across async tasks.
2. **Mistral Adapter Dispatch:** Sets `codestral-latest` as the default Mistral model while preserving `mistral-small-2603` support.
3. **Gated `reasoning_effort`:** Ensures `reasoning_effort` parameter is only sent to reasoning models (`small` / `2603`), avoiding HTTP 400 rejections on coding models.
4. **Diagnostic Ping:** Uses `"Respond with only the word PONG."` with `max_tokens=32` to guarantee clean `finish_reason: "stop"` and accurate latency tracking.

---

## 3. Performance & Latency Comparison

| Metric | Legacy Groq/Qwen / Stalled Runs | Mistral `codestral-latest` (Tier 2) | Status |
| :--- | :--- | :--- | :--- |
| **Ping Latency** | 2,500ms – 8,000ms | **610ms – 860ms** | 🚀 **~5x faster** |
| **Native Tool Call Latency** | 3,200ms – 12,000ms | **766ms – 812ms** | 🚀 **~6x faster** |
| **Syntax Repair Turnaround** | Stalled / 149s timeout | **889ms** | 🚀 **Instant repair** |
| **Code Generation Latency** | 15s – 45s | **1,063ms** | 🚀 **Sub-second** |
| **TTFT (Time to First Token)** | 2.5s – 15s | **< 600ms** | 🚀 **Immediate streaming** |
| **HTTP Errors** | Rate limit / stall | **0 errors (125 req/min quota)** | ✅ **Clean** |

---

## 4. Test & Verification Results

### A. Full Test Suite (97/97 Passed in 34.67s)
```
tests\test_tier2_mistral_migration.py .........................          [ 25%] (25/25 passed)
tests\test_tier2_codestral_real_qualification.py .....                   [ 30%] (5/5 passed)
tests\test_careergrid_control_plane_remediation.py ................      [ 47%] (16/16 passed)
tests\test_final_fault_injection_qualification.py .......                [ 54%] (7/7 passed)
tests\test_observability_system.py .............                         [ 68%] (13/13 passed)
tests\test_recovery_loop_remediation.py ..............                   [ 82%] (14/14 passed)
tests\test_incident_m_b9d872ee_regression.py ...                         [ 85%] (3/3 passed)
tests\test_simple_mission_completion.py ..............                   [100%] (14/14 passed)
============================= 97 passed in 34.67s =============================
```

### B. Live Qualification Highlights (`test_tier2_codestral_real_qualification.py`)
1. **Health Check:** Diagnostic ping returned `healthy=True`, `status="HEALTHY"`, `tool_call_supported=True`, `latency=860ms`.
2. **JavaScript Generation:** Generated full EventEmitter class with zero syntax defects (`validate_javascript_content` passed).
3. **Multi-Turn Tool Calling:** Issued `fs_write` for `greeting.txt`, followed immediately by `fs_read` after observation delivery, parsing outputs flawlessly.
4. **Failure Recovery & Syntax Repair:** Corrected broken JavaScript with unclosed function braces on the first turn; validator confirmed `is_valid: True`.
5. **Observability Telemetry:** Telemetry logged directly into `models.jsonl` with correct tier, model, duration, and token usage.

### C. Live Mission Qualification (`m_7f08fbe6`)
- **Workspace:** `C:\Users\SUBBU\Downloads\temp_codestral_qual`
- **Total Duration:** 11.5 seconds (20:16:05 to 20:16:17)
- **Files Created:**
  - `package.json` (213 bytes)
  - `index.html` (614 bytes)
  - `style.css` (1,686 bytes)
  - `app.js` (576 bytes)
- **Syntax Validation:** `Syntax valid: True, error: None, line: None`
- **Result:** `MISSION_COMPLETED` with all acceptance checks passed.

---

## 5. Answers to User Questions

### When should you run `.\scripts\watch_mission_logs.ps1 -Latest`?
You can run it in **two modes**:
1. **Live While Mission is Running (Recommended):**
   ```powershell
   .\scripts\watch_mission_logs.ps1 -Latest
   ```
   Run this in a separate PowerShell terminal right after starting a task in the UI. It will follow the log in real-time like `tail -f`, displaying model turns, tool executions, and tier escalations as they happen.
2. **Immediately After a Mission Completes or Fails (Post-Mortem):**
   ```powershell
   # Inspect the entire event timeline without blocking
   .\scripts\watch_mission_logs.ps1 -Latest -NoFollow

   # Inspect model call timings, latencies, and token counts
   .\scripts\watch_mission_logs.ps1 -Latest -Stream models -NoFollow

   # Inspect any errors or exceptions that occurred
   .\scripts\watch_mission_logs.ps1 -Latest -Stream errors -NoFollow
   ```

### Where are all the mission logs stored?
Every mission run automatically creates a persistent, isolated forensic folder at:
```
C:\Users\SUBBU\Downloads\hermes\artifacts\observability\<run_id>\
```
Inside each folder you will find:
- `events.jsonl`: Complete chronological event journal.
- `models.jsonl`: Model calls with tier, model name, prompt tokens, completion tokens, latency, and TTFT.
- `tools.jsonl`: Tool calls, arguments, exit codes, and execution durations.
- `errors.jsonl`: Any warnings, errors, or syntax issues encountered.
- `runtime.jsonl`: Host health snapshots, memory, and sync status.
- `mission_summary.md`: Auto-generated markdown report summarizing the run.

---

## 6. Reversible Rollback Instructions

To restore `mistral-small-2603` once credits are added to the Mistral account:

1. Update `.env`:
   ```bash
   TIER2_MODEL=mistral-small-2603
   ```
2. Update `config/model_config.py`:
   ```python
   TIER2_MODEL = os.getenv("TIER2_MODEL", "mistral-small-2603")
   ```
3. Restart the backend:
   ```powershell
   # Kill running backend on port 8765
   Stop-Process -Id (Get-NetTCPConnection -LocalPort 8765).OwningProcess -Force
   # Start backend
   .\venv\Scripts\python.exe -m uvicorn core.server.app:app --host 127.0.0.1 --port 8765 --log-level info
   ```
4. Verify synchronization:
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8765/api/health
   # Verify: "runtime_status": "SYNCED", "tier2": "mistral / mistral-small-2603"
   ```
