# Z.ai Rate-Limit & Concurrency Optimization Report

**Date:** 2026-10-30  
**Environment:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Backend:** `http://127.0.0.1:8765`  
**Target Provider:** Z.ai / BigModel (`glm-4.7-flash` via `https://api.z.ai/api/paas/v4`)  
**Workspace:** `C:\Users\SUBBU\Downloads\testing`  

---

## 1. Executive Summary

An investigation was conducted to determine why Z.ai (`glm-4.7-flash`) passed direct diagnostics but triggered HTTP 429 (`RATE_LIMIT_EXCEEDED`) during mission execution. 

### Key Findings
1. **Concurrency Ceiling of 1:** The Z.ai account operates under free-tier limits where concurrent requests are strictly capped at **1 active in-flight request**. If a second request arrives while the first is generating, Z.ai rejects immediately with HTTP 429 (`code: 1302: "Rate limit reached for requests"`).
2. **Transient Cluster Overload:** Under cluster load, Z.ai returns HTTP 429 (`code: 1305: "The service may be temporarily overloaded, please try again later"`).
3. **No Upstream Retry Headers:** Raw HTTP inspection confirmed Z.ai returns **no `Retry-After` header** or `x-ratelimit-*` headers on 429 responses.
4. **Adapter Gap:** The adapter previously had no semaphore protection for Z.ai and immediately failed on attempt 1 without backing off, guaranteeing instant failover to NVIDIA even on sub-second concurrency collisions.
5. **Probe Interference:** Background reachability checks competed with in-flight turn generation.

### Implemented Solutions
- Enforced a strict provider-level `asyncio.Semaphore(1)` for Z.ai in `models/common_adapter.py`.
- Implemented bounded backoff with max 2 retries (attempt intervals: 2.0s, 4.0s) for recoverable 429 / 1305 responses.
- Protected background probes and diagnostics: if `_semaphore.locked()`, background health checks do not burn the single concurrency slot.
- Cleaned up lingering stale backend processes.

### Validation Results
1. **Isolated Live Generation:** Succeeded with HTTP 200 (52.31s latency, content generated).
2. **Isolated Tool Call:** Succeeded with HTTP 200 (24.77s latency, native `fs_write` tool call produced).
3. **Live End-to-End Mission (`m_a81c3909`):** **Completed in 36.17 seconds using purely Tier 1 Z.ai (`glm-4.7-flash`)** without falling back to NVIDIA NIM. Deliverable `zai_success.txt` verified on disk with exact content `ZAI_VERIFIED_2026`.
4. **Regression Tests:** All 14 tests in `tests/test_simple_mission_completion.py` passed in 1.75s; all 24 tests in `tests/test_three_tier_providers.py` passed.

---

## 2. Forensic Investigation of the 7 Inquiries

| Inquiry | Finding | Evidence / Details |
|:---|:---|:---|
| **1. Z.ai RPM and concurrency limits** | Strict concurrency = 1 | Querying `GET /models` confirmed `glm-4.7-flash` is the only active free tier model; all other models (`glm-4.7`, `glm-5.3-flash`) returned code `1113` (insufficient balance). Rapid consecutive requests returned code `1302` ("Rate limit reached for requests"). |
| **2. Background health probes competing** | Yes, previously | Probing while a turn was executing caused immediate code `1302` collision. Fixed by semaphore check in `is_available` and `run_diagnostics`. |
| **3. Multiple concurrent AgentLoop requests** | Prevented by Semaphore | Z.ai adapter now enforces `asyncio.Semaphore(1)`. Multiple requests serialize gracefully. |
| **4. Lingering backend processes** | Multiple processes detected | Identified and terminated stale PID 19004 and legacy scripts. Started single canonical instance (`PID 1132`) under virtual environment. |
| **5. Connection pooling & semaphores** | Added provider-specific semaphore | Added `self._semaphore = asyncio.Semaphore(1)` for Z.ai in `CommonProviderAdapter`. |
| **6. `Retry-After` header presence** | Not present | Inspected raw headers: `{date, content-type, transfer-encoding, connection, set-cookie, ga-traceid, x-log-id, strict-transport-security}`. No `Retry-After` provided. |
| **7. Fast retries or duplicate requests** | Adapter had 0 retries | Previously aborted immediately on turn 1 429. Added bounded backoff (2.0s, 4.0s, capped at max 2 retries). |

---

## 3. Verification Evidence

### Test 1: Isolated Live Text Generation
- **Provider:** `zai`
- **Model:** `glm-4.7-flash`
- **HTTP Status:** `200 OK`
- **Latency:** 52.31s
- **Output:** `"Hello, how are you?"`
- **Reasoning Tokens:** 835 characters

### Test 2: Isolated Live Filesystem Tool Call
- **Provider:** `zai`
- **Model:** `glm-4.7-flash`
- **HTTP Status:** `200 OK`
- **Latency:** 24.77s
- **Tool Output:**
  ```json
  [
    {
      "function": {
        "name": "fs_write",
        "arguments": "{\"path\":\"zai_test.txt\",\"content\":\"HERMES_ZAI_OK\"}"
      },
      "id": "call_-7120806359427181122",
      "type": "function"
    }
  ]
  ```

### Test 3: Live End-to-End Mission (`m_a81c3909`)
- **Mission ID:** `m_a81c3909`
- **Prompt:** `"Create a file named zai_success.txt containing exactly ZAI_VERIFIED_2026. Verify the file exists on disk and finish."`
- **Workspace:** `C:\Users\SUBBU\Downloads\testing`
- **Final Status:** **COMPLETED**
- **Total Wall Time:** **36.17 seconds**
- **Turns Executed:** 1
- **Provider Used:** **`zai` (Tier 1)**
- **Model Used:** **`glm-4.7-flash`**
- **Failovers to NVIDIA:** **0 (Zero failovers — Z.ai completed the entire mission directly)**
- **Deliverable Verified on Disk:** `C:\Users\SUBBU\Downloads\testing\zai_success.txt` containing `ZAI_VERIFIED_2026`.

```
[1793383099.301] TIER_SELECTED: {'tier': 1, 'model': 'glm-4.7-flash', 'provider': 'zai'}
[1793383099.301] MODEL_REQUESTED: {'model': 'glm-4.7-flash', 'provider': 'zai'}
[1793383134.497] MODEL_COMPLETED: {'model': 'glm-4.7-flash', 'tier': 1, 'latency': 35.188s}
[1793383134.651] MISSION_COMPLETED: {'reason': 'Profile A passed: Verified 1 file(s) on disk with valid content.'}
```

---

## 4. Operational Architecture & Fallback Invariants

1. **Z.ai as Primary:** Tier 1 Z.ai (`glm-4.7-flash`) is now operational for direct autonomous coding missions.
2. **NVIDIA NIM as Resilient Shield:** If Z.ai's public free cluster experiences persistent quota exhaustion or sustained multi-attempt overload, HERMES automatically fails over to Tier 2 NVIDIA NIM (`nvidia/nemotron-3.5-lightning-30b-a3b`) in milliseconds.
3. **No Infinite Retries:** Backoff is strictly bounded to 2 retries (max ~6s wait) before escalating to Tier 2.
