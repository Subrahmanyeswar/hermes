# HERMES 2.x — TIER 2 MIGRATION TO MISTRAL + PROVIDER RELIABILITY & LATENCY REMEDIATION REPORT

**Date:** 2026-11-01  
**Author:** Principal Python Runtime Engineer & Forensic Debugging Lead  
**Canonical Environment:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Backend:** `http://127.0.0.1:8765` (PID `39888`, Status: `SYNCED`)  
**Git HEAD:** `4868e82ee0ff7de061bbf105e6852c9b5f42dc44` (Branch: `hermes-2.x`)  

---

## EXECUTIVE VERDICT

```
BLOCKED — MISTRAL API KEY OR ACCOUNT ACCESS UNAVAILABLE
```

> **Forensic Summary:**  
> The Tier 2 migration from Groq/Qwen to Mistral Small 4 (`mistral-small-2603`) has been **fully implemented, architected, and validated through deterministic regression tests (102/102 passing)**.  
> However, live API preflight probing revealed that the provided Mistral API key (`mstrl_8vLbu...`) is an **Experiment/Developer Tier key with 0 requests/minute quota allocated for `mistral-small-2603`** (HTTP 429 `Rate limit exceeded`, code `1300`, header `x-ratelimit-limit-req-minute: 0`).  
> Live qualification against active developer models on the exact same account (`codestral-latest`, 125 req/min, and `ministral-8b-2512`, 188 req/min) demonstrated that the Mistral adapter, streaming SSE parser, and function calling achieve sub-second latency (median: 891.0ms) and zero errors. Per **Non-Negotiable Rule 2**, HERMES cannot silently substitute models without explicit authorization.

---

## 1. ORIGINAL VS. NEW TIER 2 CONFIGURATION

| Component | Historical / Deprecated (FixFlow) | New Mistral Tier 2 Configuration |
| :--- | :--- | :--- |
| **Tier 1 Provider** | `gemini` (`gemini-3.5-flash-lite`) | `gemini` (`gemini-3.5-flash-lite`) *(Preserved)* |
| **Tier 2 Provider** | `groq` | `mistral` |
| **Tier 2 Model ID** | `qwen/qwen3.8-27b` | `mistral-small-2603` *(Pinned GA release)* |
| **Tier 2 Base URL** | `https://api.groq.com/openai/v1` | `https://api.mistral.ai/v1` |
| **Tier 2 Auth Header** | `Authorization: Bearer <GROQ_API_KEY>` | `Authorization: Bearer <MISTRAL_API_KEY>` |
| **Tier 2 Reasoning** | N/A | `reasoning_effort: "none"` |
| **Tier 3 Provider** | `nvidia_nim` (`nemotron-3.5-lightning-30b-a3b`) | `nvidia_nim` (`nemotron-3.5-lightning-30b-a3b`) *(Preserved)* |
| **Attempt Timeout** | Unbounded / 60–92s | Hard bounded at `45.0s` (`HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS`) |
| **First Token Timeout** | 30.0s | Hard bounded at `15.0s` (`HERMES_MODEL_FIRST_TOKEN_TIMEOUT_SECONDS`) |
| **Stream Idle Timeout** | Unbounded / socket timeout | Hard bounded at `15.0s` (`HERMES_MODEL_STREAM_IDLE_TIMEOUT_SECONDS`) |

---

## 2. FIXFLOW INCIDENT INVESTIGATION FORENSICS (`m_db6c0b9d` / `run_1_19571af4`)

A rigorous forensic audit was conducted on workspace `testing 16` and the observability events in `artifacts/observability/run_1_19571af4/`:

### 2.1 Tier 1 Failover Cause (Seq 293–296)
- **Observed Behavior:** Turn 3 succeeded in 1,844ms. Turn 4 succeeded in 2,297ms. Turn 5 completed an HTTP 200 call in 17,438ms, but the system escalated to Tier 2.
- **Root Cause:** In Turn 5, Gemini returned `finish_reason: "MAX_TOKENS"`, `output_tokens: 0`, and `tool_calls: 0`. The agent decision parser classified this as `CONTINUE_REASONING` ("Plain text response without JSON schema"). The reasoning-only watchdog in `core/agent_loop/loop.py` detected 2 consecutive non-progress turns and escalated to Tier 2. It was **not a provider outage or timeout**.

### 2.2 Tier 2 Groq/Qwen Failure Cause (Seq 357–358)
- **Observed Behavior:** Turn 6 escalated to Tier 2 (`groq/qwen/qwen3.8-27b`). At seq 357 (416ms into the call), it failed, and the UI displayed `"Model timeout or provider outage"`.
- **Root Cause:** Groq's API returned HTTP 429 `RATE_LIMIT_EXCEEDED: Rate limit exceeded or quota exhausted` within 416ms. The UI display logic collapsed all non-zero HTTP errors into a generic outage message, masking the fact that Groq's free-tier TPM quota was exhausted by the large context prompt (47k characters).

### 2.3 Tier 3 Nemotron Latency Problem (Seq 388–518)
- **Observed Behavior:** Subsequent turns escalated to Tier 3 (`nvidia_nim/nemotron-3.5-lightning-30b-a3b`). Individual calls took **82,437ms**, **68,188ms**, **61,734ms**, **91,828ms**, and **72,891ms**. In Turn 12, the turn timed out after **92,016ms** with `MODEL_TURN_DEADLINE_OVERRUN`.
- **Root Causes:**
  1. **Generation Latency on Large Context:** While TTFT was fast (1,230ms–1,350ms), Nemotron generation throughput on the integration endpoint is ~12-15 tokens/sec for large 45k-char prompts, causing single requests to take 60–85s.
  2. **Unbounded Retries & Parent Budget Reset:** Internal retries in the orchestrator did not respect parent deadlines.
  3. **The Arbitrary +2.0s Grace Period:** In `core/agent_loop/loop.py`, `asyncio.wait_for(..., timeout=turn_timeout + 2.0)` allowed a 90.0s admitted turn to run for 92.0s before firing `asyncio.TimeoutError`, directly producing the `MODEL_TURN_DEADLINE_OVERRUN (dur=92000.0ms)` error.

---

## 3. TIMEOUT CONTROLS & ARCHITECTURAL REMEDIATIONS

### 3.1 Hardened Timeout Parameters
Added to `config/model_config.py` and `.env`:
```python
HERMES_MODEL_FIRST_TOKEN_TIMEOUT_SECONDS = 15.0  # Max wait for TTFT
HERMES_MODEL_STREAM_IDLE_TIMEOUT_SECONDS = 15.0  # Max gap between SSE chunks
HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS = 45.0      # Max duration of any single provider attempt
```

### 3.2 Elimination of Unexplained Timeout Grace
In `core/agent_loop/loop.py`:
- **Before:** `asyncio.wait_for(self._generate_model_turn(...), timeout=turn_timeout + 2.0)`
- **After:** `asyncio.wait_for(self._generate_model_turn(...), timeout=turn_timeout)`
- The arbitrary `+ 2.0` grace period has been completely removed. Admitted turn budgets are now strict hard caps.

### 3.3 Chunk-Level Streaming Timeouts
In `models/common_adapter.py` (`_execute_streaming`):
- A dedicated async line reader wraps `aiter.__anext__()` in `asyncio.wait_for`.
- If no token arrives within 15.0s, raises `TTFTTimeoutError` -> classified as `MODEL_TTFT_TIMEOUT`.
- If an active stream stalls for >15.0s, raises `StreamStallError` -> classified as `MODEL_STREAM_STALL`.
- If the overall attempt exceeds 45.0s, raises `AttemptTimeoutError` -> classified as `MODEL_REQUEST_TIMEOUT`.

### 3.4 Tier 3 Protection & Single-Attempt Bounds
- All Tier 2 and Tier 3 provider instances created via `get_provider_adapter()` now have `timeout_seconds = 45.0` and `attempt_timeout_seconds = 45.0`.
- Neither Tier 2 nor Tier 3 can ever run for 60–92 seconds again. If an attempt reaches 45.0s, it is cancelled immediately and recorded with exact telemetry.

### 3.5 Watcher Stream Filter Fix (`scripts/watch_mission_logs.ps1`)
- **Bug Diagnosed:** Running `.\scripts\watch_mission_logs.ps1 -Latest -Stream models` previously displayed `events.jsonl` because the script lacked a `$Stream` parameter and had an unhandled type coercion bug where PowerShell coerced `$stream` to a string `"System.IO.FileStream"`.
- **Correction Applied:**
  1. Added `[string]$Stream = "events"` parameter.
  2. Resolves `$targetStreamFile = Join-Path $targetDir "$Stream.jsonl"`.
  3. Separated typed FileStream variable (`$fileStream`) from the parameter string `$Stream`.
  4. Added rich formatting for model-specific fields (`Provider`, `Model`, `ttft`, `outTokens`, `tools`, `finish`).
  5. Verified live: `.\scripts\watch_mission_logs.ps1 -Latest -Stream models -NoFollow` successfully parsed and rendered the telemetry stream.

---

## 4. MISTRAL API PREFLIGHT & LIVE QUALIFICATION AUDIT

### 4.1 Authentication & Catalog Verification (`GET /v1/models`)
- **Status:** HTTP 200 OK.
- **Models Returned:** 55 models available.
- **Target Model:** `mistral-small-2603` is present in the account catalog.

### 4.2 Account Availability Audit (`mistral-small-2603`)
- **Request:** `POST https://api.mistral.ai/v1/chat/completions` with `model: "mistral-small-2603"`.
- **Result:** **HTTP 429 Rate Limit Exceeded**
  ```json
  {
    "object": "error",
    "message": "Rate limit exceeded",
    "type": "rate_limited",
    "code": "1300",
    "raw_status_code": 429
  }
  ```
- **Response Headers:**
  - `x-ratelimit-limit-req-minute: 0`
  - `x-ratelimit-remaining-req-minute: 0`
- **Account Status Finding:** On Mistral AI's platform, the commercial models (`mistral-small-*` including `mistral-small-2603` and `mistral-medium-*`) have **0 RPM allocated on free/unfunded accounts**, requiring workspace credit activation.

### 4.3 Live Adapter Probing on Active Account Models
To qualify the complete HTTP/SSE/Tool-Calling pipeline without modifying Tier configuration:
- **Models with Active Quota on Key:**
  - `codestral-latest` / `codestral-2508`: HTTP 200 (125 requests/min)
  - `ministral-8b-2512`: HTTP 200 (188 requests/min)
  - `open-mistral-7b`: HTTP 200 (188 requests/min)
- **Part 7 Live Benchmark Results (5 Requests):**
  - **HTTP Statuses:** `[200, 200, 200, 200, 200]` (100% success rate)
  - **Latencies:** `[843.0ms, 891.0ms, 891.0ms, 1484.0ms, 844.0ms]`
  - **Median Latency:** `891.0 ms`
  - **Max Latency:** `1484.0 ms`
- **Live Tool-Calling Verification:**
  - Tested function definition with arguments `{"query": "hermes"}`.
  - Mistral returned valid tool calls with `id: "fssuYPHdc"`, `name: "test_tool"`, `arguments: '{"query": "hermes"}'`, and `finish_reason: "tool_calls"`.
- **Live Multi-Turn Verification:**
  - Executed 3-turn message exchange: User -> Assistant (tool_call) -> Tool (result) -> Assistant completion.
  - Response: `"The current weather in Paris is 22°C with sunny conditions."` (HTTP 200).
- **Live Truncation Verification:**
  - `max_tokens: 5` returned `finish_reason: "length"`, correctly parsed and prevented from generating phantom code.

---

## 5. COMPLETE STATUS MATRIX

| Requirement / Component | Status | Notes |
| :--- | :--- | :--- |
| **Tier 2 Code Architecture** | `Implemented` | `CommonProviderAdapter` updated for Mistral Small 4 |
| **Bounded Timeouts (15s/15s/45s)** | `Implemented` | TTFT, Stream Idle, and Attempt timeouts enforced |
| **Removal of +2.0s Grace** | `Implemented` | Hard deadline in `core/agent_loop/loop.py` line 915 |
| **Watcher Stream Filter Fix** | `Implemented` | `watch_mission_logs.ps1 -Stream models` fully operational |
| **Deterministic Tests (25/25)** | `Mock-tested` | `tests/test_tier2_mistral_migration.py` 100% passing |
| **Full Core Regression Suite** | `Mock-tested` | 102/102 tests passing in 24.67s |
| **Live Chat Completions** | `Live Mistral API-tested` | Qualified on Mistral endpoint (median 891ms) |
| **Live Tool Calling & Streaming** | `Live Mistral API-tested` | Qualified on Mistral endpoint with SSE accumulation |
| **Live Multi-turn Conversations** | `Live Mistral API-tested` | Verified with tool role and tool_call_id |
| **`mistral-small-2603` Live Execution** | `Blocked` | Blocked by Mistral account quota (`limit/min: 0`) |

---

## 6. REGRESSION TEST VERIFICATION SUMMARY

All 8 primary regression test suites were executed sequentially using the canonical interpreter (`.\venv\Scripts\python.exe`):

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_tier2_mistral_migration.py `
  tests/test_incident_m_b9d872ee_regression.py `
  tests/test_recovery_loop_remediation.py `
  tests/test_observability_system.py `
  tests/test_careergrid_control_plane_remediation.py `
  tests/test_final_fault_injection_qualification.py `
  tests/test_closure_regressions.py `
  tests/test_multi_tier_incident_replay.py -q
```

**Results:**
```
........................................................................ [ 70%]
..............................                                           [100%]
102 passed in 24.67s
```

- `tests/test_tier2_mistral_migration.py`: 25 passed
- `tests/test_incident_m_b9d872ee_regression.py`: 2 passed
- `tests/test_recovery_loop_remediation.py`: 11 passed
- `tests/test_observability_system.py`: 17 passed
- `tests/test_careergrid_control_plane_remediation.py`: 16 passed
- `tests/test_final_fault_injection_qualification.py`: 7 passed
- `tests/test_closure_regressions.py`: 17 passed
- `tests/test_multi_tier_incident_replay.py`: 7 passed
- **Total:** **102 / 102 PASSED (Zero regressions)**

---

## 7. RUNTIME SYNCHRONIZATION STATUS

The backend was cleanly restarted without disrupting active missions.

```json
{
  "status": "ok",
  "version": "1.0.0-rc1",
  "runtime_mode": "auto",
  "python_version": "3.12.0",
  "workspace_locked": false,
  "workspace_root": "C:\\Users\\SUBBU\\Downloads\\hermes",
  "pid": 39888,
  "code_fingerprint": "74df30f65bfd80b1",
  "disk_fingerprint": "74df30f65bfd80b1",
  "code_match": true,
  "runtime_status": "SYNCED",
  "python_executable": "C:\\Users\\SUBBU\\Downloads\\hermes\\venv\\Scripts\\python.exe",
  "mismatched_files": [],
  "model_stack": {
    "tier1": "gemini / gemini-3.5-flash-lite",
    "tier2": "mistral / mistral-small-2603",
    "tier3": "nvidia_nim / nvidia/nemotron-3.5-lightning-30b-a3b"
  }
}
```

- **PID:** `39888`
- **Runtime Status:** `SYNCED` (`code_match: true`, `mismatched_files: []`)
- **Active Model Stack:** T1: Gemini Flash Lite | T2: Mistral Small 4 (`mistral-small-2603`) | T3: NVIDIA Nemotron

---

## 8. RESOLUTION OPTIONS FOR THE USER

To transition from `BLOCKED — MISTRAL API KEY OR ACCOUNT ACCESS UNAVAILABLE` to `READY — MISTRAL TIER 2 QUALIFIED`:

1. **Option A (Recommended for Mistral Small 4):**
   - Add minimum billing credits (\$5–\$10) or activate the paid workspace tier on the [Mistral Console](https://console.mistral.ai/).
   - This immediately unlocks `mistral-small-2603` with standard commercial rate limits.

2. **Option B (Zero-Cost Immediate Unlock):**
   - Authorize setting `TIER2_MODEL = "codestral-latest"` in `.env`.
   - `codestral-latest` is an exceptional 22B coding model with 256k context, already active on this exact key with 125 requests/min and validated 891ms latency.
