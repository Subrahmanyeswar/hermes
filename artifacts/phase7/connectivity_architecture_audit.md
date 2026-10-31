# HERMES Phase 7 — Connectivity Architecture Audit
**Internet-Loss Detection, Durable Waiting & Automatic Recovery**

- **Target Release:** HERMES v1.0.0-rc1
- **Repository Root:** `C:\Users\SUBBU\Downloads\hermes`
- **Canonical Python:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)
- **Audit Date:** October 13, 2026
- **Architecture Status:** **APPROVED & QUALIFIED**

---

## 1. Executive Overview

HERMES Phase 7 establishes deterministic, survivable network fault tolerance across transient Internet dropouts, upstream model provider outages, backend process restarts, and browser SSE disconnections.

Previously, network transport or provider outages would either fail missions permanently or loop repeatedly, exhausting retries or leaving inconsistent intermediate state. In Phase 7, HERMES distinguishes four discrete connectivity failure conditions, enters truthful, durable waiting states (`MissionStatus.WAITING`), preserves settled execution boundaries, and automatically recovers eligible missions upon connectivity restoration with zero token waste and zero duplicate side effects.

---

## 2. Taxonomy of Four Failure Conditions

HERMES strictly differentiates four failure scenarios through `classify_error_condition()` in `core/network/connectivity.py`:

| Condition | Failure Type | Root Cause & Detection | Authoritative Action |
|---|---|---|---|
| **Condition A** | Browser Disconnect | Browser tab closed, client SSE stream disconnected, frontend refreshed. Backend remains alive and online. | **Mission continues unabated** in background; events journaled to SQLite; GUI catches up on reconnect via `/events` replay. |
| **Condition B** | Backend Restart / Crash | Backend process crashes or restarts during mid-execution; lock heartbeat expires. | Startup recovery marks inactive missions with `recovery_required=True`; `NetworkRecoveryCoordinator` discovers and cold-resumes. |
| **Condition C** | Provider Outage | General Internet is reachable (`ConnectivityMonitor` succeeds), but specific model provider returns 5xx, 429, or cloud timeout. | Transition to `WAITING` with `WaitReason.WAITING_FOR_PROVIDER`; execution paused; circuit breaker guards provider; auto-resumed when provider recovers. |
| **Condition D** | Internet Loss | Neutral public endpoints (`1.1.1.1`, `8.8.8.8`, `icanhazip.com`) unreachable; DNS/socket failures across all probes. | Transition to `WAITING` with `WaitReason.WAITING_FOR_NETWORK`; execution paused without burning provider tokens; auto-resumed upon WAN recovery. |

---

## 3. Shared Connectivity Monitor Architecture

The `ConnectivityMonitor` (`core/network/connectivity.py`) provides centralized WAN health probing:

1. **Neutral Probe Endpoints**:
   - Primary: `https://1.1.1.1/cdn-cgi/trace` (Cloudflare)
   - Secondary: `https://dns.google/resolve?name=example.com` (Google Public DNS)
   - Fallback: `https://icanhazip.com`
   - *Zero LLM Token Usage*: Probing strictly employs lightweight HTTP `HEAD`/`GET` requests against public CDNs with a 2.5-second timeout, consuming 0 billable provider tokens.
2. **Hysteresis & Flapping Suppression**:
   - Consecutive failures threshold: `failure_threshold = 2` (default) before transitioning from `ONLINE` to `OFFLINE`.
   - Consecutive successes threshold: `recovery_threshold = 2` (default) before declaring WAN restoration.
   - Debounce window: Prevents rapid re-triggering during network instability.
3. **Event Notification**:
   - Emits asynchronous callbacks to registered listeners (e.g., `NetworkRecoveryCoordinator`).
   - Clean shutdown during FastAPI server lifespan (`aclose()` / `stop()`).

---

## 4. Truthful Durable Waiting States

When Condition C or Condition D occurs:
1. **Authoritative Status**:
   - Status transitions to `MissionStatus.WAITING`.
   - `WaitReason` is set to `WAITING_FOR_NETWORK` (Condition D) or `WAITING_FOR_PROVIDER` (Condition C).
   - `execution_active = 0` and `recovery_required = 1` recorded durably in SQLite `missions` table.
   - Emits canonical `MISSION_WAITING` event with error metadata.
2. **Boundary Preservation**:
   - Active task remains unsettled; completed earlier tasks remain settled and immutable.
   - Checkpoint state reflects last settled execution boundary.
   - Tool write-ahead journal (`tool_operations`) prevents phantom side effects.
3. **Execution Teardown**:
   - Agent loop exits cleanly without raising uncaught exceptions.
   - Background task completes; control context terminates cleanly without marking mission terminal.

---

## 5. Automatic Recovery Coordinator Architecture

The `NetworkRecoveryCoordinator` (`core/network/coordinator.py`) orchestrates automated recovery:

1. **Recovery Trigger**:
   - Automatically invoked when `ConnectivityMonitor` detects network restoration, or manually via `POST /api/network/recover`.
2. **Eligibility & Fencing**:
   - **Eligible**: Missions with `status == "WAITING"` and `recovery_required == 1`.
   - **Ineligible Fencing**:
     - Completed missions (`status == "COMPLETED"`).
     - User-cancelled missions (`cancelled_by_user == True`).
     - Permanent provider errors (`AUTHENTICATION_FAILURE`, `AUTHORIZATION_RESTRICTION`, `BILLING_FAILURE`).
     - Corrupted checkpoint manifests or missing state blobs (transitions to `FAILED`).
     - Missing or inaccessible original workspace folders (transitions to `FAILED`).
3. **Continuation Run Identity**:
   - New run identity allocated: `run_{attempt_number}_{uuid}`.
   - Original workspace bound and verified.
   - Resumes deterministically from first unfinished task using `RecoveryEngine`.
4. **Anti-Flapping & Concurrency Control**:
   - In-memory `_recovering_missions` set deduplicates concurrent recovery triggers.
   - Debounce delay prevents duplicate resumes during recovery cascades.

---

## 6. Frontend & API Integration

1. **REST Endpoints**:
   - `GET /api/network/status`: Returns current WAN connectivity status, latency, and waiting mission counts.
   - `POST /api/network/recover`: Triggers immediate recovery sweep across all eligible waiting missions.
2. **GUI Experience**:
   - Dedicated `WAITING` status badge in TopBar with amber visual warning.
   - SSE listener triggers live updates on `MISSION_WAITING`, `NETWORK_RESTORED`, and `MISSION_RESUMED` events.
   - Clean frontend build verified (`npm --prefix gui run build`).
