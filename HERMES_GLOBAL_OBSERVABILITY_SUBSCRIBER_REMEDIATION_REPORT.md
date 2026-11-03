# HERMES 2.x — MASTER OBSERVABILITY REMEDIATION REPORT
## Global Observability Subscriber Architecture & Telemetry Deduplication

- **Mission ID:** Remediation-GlobalObservabilitySubscriber-OptA
- **Date & Timestamp:** 2026-11-01T22:35:00+05:30
- **Author:** Principal Distributed Tracing Architect & AI Agent Observability Lead
- **Environment:** Windows 11 | Python 3.12.0 (Canonical Virtual Environment: `venv\Scripts\python.exe`)
- **Remediation Option:** Option A (Single Global EventBus Subscriber via RuntimeAdapter Lifecycle)
- **Authoritative Verdict:** **CLEAN PASS**

---

## 1. Executive Summary & Root Cause Analysis

### 1.1 The Forensic Problem
During the forensic audit of mission `run_1_b0b6b6e7`, four identical copies of every single telemetry event (`ACTION_DENIED`, `TOOL_STARTED`, `TOOL_COMPLETED`, `MODEL_REQUESTED`, `MODEL_COMPLETED`) were discovered appearing at identical timestamps with identical payloads and action IDs.

### 1.2 Root Cause
1. **Subscriber Accumulation on Singleton EventBus:**
   The `EventBus` in HERMES is instantiated once per backend lifecycle in `RuntimeAdapter`. However, in `AgentLoop.run()` (`core/agent_loop/loop.py`), an `ObservabilityBusSubscriber` was being created and attached to the shared `EventBus` on **every single mission execution**.
   Because `ObservabilityBusSubscriber` handlers were never detached upon mission completion, each mission run added another permanent subscriber callback to the list of `EventBus._subscribers`.
2. **Dynamic Routing Fanout:**
   In `ObservabilityBusSubscriber.handle_event()`, the subscriber dynamically resolved the active mission logger from the event's `run_id` (`get_telemetry_logger(run_id=event.run_id)`). When four missions had executed since the server started, four active subscriber instances were listening to the same shared `EventBus`. Every published event was received four times and passed to the active logger, resulting in $N \times$ duplicate writes in `events.jsonl` and `tools.jsonl`.
3. **Dual-Path Tool Completion Emission:**
   `EventType.TOOL_COMPLETED` was being emitted through the EventBus in `actions.py` while simultaneously being recorded via direct file logging in `AgentLoop.run()`. Without unified deduplication keys across both paths, completed tool records risked redundant entries.

---

## 2. Approved Remediation Architecture (Option A)

Under Option A, the lifecycle of the `ObservabilityBusSubscriber` was moved entirely to the `RuntimeAdapter` server lifecycle:
1. **Single Global Subscriber:** Exactly one `ObservabilityBusSubscriber` is attached to `RuntimeAdapter.event_bus` at server initialization.
2. **Per-Mission Removal:** Per-mission subscriber instantiation in `AgentLoop.run()` was completely removed.
3. **Lifecycle Idempotency:** `ObservabilityBusSubscriber.attach()` and `detach()` were made strictly idempotent with guard flags preventing multiple subscriptions.
4. **Reentrant Lock Safety:** Converted `_TELEMETRY_LOCK` in `logger.py` to `threading.RLock()` to prevent reentrant deadlocks when logger constructors register into active process state.
5. **Unified Tool Event Deduplication:** Enhanced `MissionTelemetryLogger` with multi-key tracking across `tool_call_id`, `action_id`, and `operation_id` to guarantee that `TOOL_STARTED` and `TOOL_COMPLETED` are serialized exactly once per physical tool call regardless of arrival order.

---

## 3. Exact Source Code Modifications

### 3.1 `core/observability/bus_subscriber.py`
- Added idempotency guards in `attach()` and `detach()`.
- Checked `event_bus._subscribers` directly to ensure duplicate handlers cannot be registered.
- Propagated `event.tool_call_id` into event payloads for end-to-end trace correlation.

```python
def attach(self) -> None:
    \"\"\"Attach subscriber to the event bus (strictly idempotent).\"\"\"
    with self._lock:
        if self._attached:
            return
        if hasattr(self.event_bus, "_subscribers"):
            existing = [
                h for h in self.event_bus._subscribers.get(None, [])
                if getattr(h, "__self__", None) is self or h == self.handle_event
            ]
            if existing:
                self._attached = True
                return
        self.event_bus.subscribe(self.handle_event)
        self._attached = True

def detach(self) -> None:
    \"\"\"Detach subscriber from the event bus safely.\"\"\"
    with self._lock:
        if not self._attached:
            return
        if hasattr(self.event_bus, "_subscribers") and None in self.event_bus._subscribers:
            self.event_bus._subscribers[None] = [
                h for h in self.event_bus._subscribers[None]
                if getattr(h, "__self__", None) is not self and h != self.handle_event
            ]
        self._attached = False
```

### 3.2 `core/server/runtime_adapter.py`
- Initialized one global `ObservabilityBusSubscriber` bound to `self.event_bus`.
- Added `detach_telemetry_subscriber()` for clean FastAPI teardown.

```python
self.telemetry_subscriber: Optional[Any] = None
self._init_telemetry_subscriber()

def _init_telemetry_subscriber(self) -> None:
    try:
        from core.observability.bus_subscriber import ObservabilityBusSubscriber
        self.telemetry_subscriber = ObservabilityBusSubscriber(self.event_bus)
        self.telemetry_subscriber.attach()
    except Exception as e:
        logger.warning(f"Failed to initialize global telemetry subscriber: {e}")

def detach_telemetry_subscriber(self) -> None:
    if self.telemetry_subscriber is not None:
        try:
            self.telemetry_subscriber.detach()
            self.telemetry_subscriber = None
        except Exception as e:
            logger.warning(f"Error detaching telemetry subscriber: {e}")
```

### 3.3 `core/server/app.py`
- Added graceful subscriber detachment to FastAPI `lifespan` handler on server shutdown.

```python
finally:
    if eff_adapter and hasattr(eff_adapter, "detach_telemetry_subscriber"):
        try:
            eff_adapter.detach_telemetry_subscriber()
        except Exception:
            pass
```

### 3.4 `core/agent_loop/loop.py`
- Removed per-mission subscriber attachment in `AgentLoop.run()`:
```python
# REMOVED:
# self._bus_subscriber = ObservabilityBusSubscriber(self.event_bus)
# self._bus_subscriber.attach()
```

### 3.5 `core/observability/logger.py`
- Replaced `threading.Lock()` with `threading.RLock()` to prevent reentrant deadlocks.
- Implemented multi-key deduplication tracking across `tool_call_id`, `action_id`, and `operation_id` for tool completion events.

---

## 4. Subscriber Count & Lifecycle Comparison

| Lifecycle Event | Pre-Remediation Subscriber Count | Remediated (Option A) Subscriber Count | Telemetry Event Duplication |
|---|---|---|---|
| Server Startup | 0 | **1** | N/A |
| Mission 1 Starts | 1 | **1** | 1x (Exact) |
| Mission 1 Completes | 1 (Lingering) | **1** | 1x (Exact) |
| Mission 2 Starts | 2 | **1** | 1x (Exact) |
| Mission 3 Starts | 3 | **1** | 1x (Exact) |
| Mission 4 Starts | 4 (Observed in `run_1_b0b6b6e7`) | **1** | 1x (Exact) |
| Server Shutdown | Leaked handlers | **0 (Clean Detach)** | Zero Stale Handlers |

---

## 5. Verification & Test Results

### 5.1 Targeted Remediation Test Suite (`tests/test_global_observability_subscriber_remediation.py`)
All 8 scenarios passed with 100% success rate:
- **Scenario A:** Exactly 1 record written per EventBus publication in `events.jsonl` -> **PASS**
- **Scenario B:** 4 sequential missions executed; subscriber count remains strictly 1 -> **PASS**
- **Scenario C:** Concurrent missions route events to independent run directories with zero cross-talk -> **PASS**
- **Scenario D:** Repeated `RuntimeAdapter` initialization is strictly idempotent -> **PASS**
- **Scenario E:** Subscriber shutdown and re-initialization leaves zero stale callbacks -> **PASS**
- **Scenario F:** Tool started and completed logged exactly once per logical operation -> **PASS**
- **Scenario G:** Event sequence numbers increment strictly monotonically (diff = 1) -> **PASS**
- **Scenario H:** Multi-tier recovery (Tier 1 -> Tier 2) mission logs each recovery transition 1x -> **PASS**

### 5.2 Unified Regression Suite
Executed against canonical Python 3.12.0 virtual environment (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`):
```text
tests\test_tier2_mistral_migration.py .........................          [ 19%]
tests\test_incident_m_b9d872ee_regression.py ...                         [ 21%]
tests\test_recovery_loop_remediation.py ..............                   [ 32%]
tests\test_observability_system.py .............                         [ 42%]
tests\test_careergrid_control_plane_remediation.py ................      [ 55%]
tests\test_final_fault_injection_qualification.py .......                [ 60%]
tests\test_closure_regressions.py ..................                     [ 74%]
tests\test_multi_tier_incident_replay.py ......                          [ 79%]
tests\test_tier2_codestral_real_qualification.py .....                   [ 82%]
tests\test_simple_mission_completion.py ..............                   [ 93%]
tests\test_global_observability_subscriber_remediation.py ........       [100%]

============================ 129 passed in 34.61s =============================
```

---

## 6. Live Mission Telemetry Qualification

A live mission (`m_49178fb9` / `run_1_52291bb0`) was executed against the running backend (PID 28856) to verify end-to-end deduplication in production conditions.

### 6.1 Server Runtime Health Check
- **Endpoint:** `GET http://127.0.0.1:8765/api/health`
- **Status:** `ok`
- **Runtime Status:** `SYNCED`
- **Code Match:** `true` (disk fingerprint matches running memory)
- **Model Stack:**
  - Tier 1: `gemini / gemini-3.5-flash-lite`
  - Tier 2: `mistral / codestral-latest`
  - Tier 3: `nvidia_nim / nvidia/nemotron-3.5-lightning-30b-a3b`

### 6.2 Telemetry Audit Results (`artifacts/observability/run_1_52291bb0`)
- **Total Events in `events.jsonl`:** 122
- **Event Sequence Monotonicity:** Strictly contiguous (Sequence 1 to 122, diff = 1 for all entries, 0 gaps, 0 duplicates).
- **Action Lifecycle Events:**
  - `ACTION_REQUESTED`: Exactly 1 per action.
  - `ACTION_ALLOWED`: Exactly 1 per action.
  - `TOOL_STARTED`: Exactly 1 per action.
  - `TOOL_COMPLETED`: Exactly 1 per action.
  - `OBSERVATION_CREATED`: Exactly 1 per action.
- **Tool Operation Breakdown (`tools.jsonl`):**
  - Total tool lines: 8
  - `TOOL_STARTED`: 4 (for 4 physical operations)
  - `TOOL_COMPLETED`: 4 (for 4 physical operations)
  - Multi-execution count: **1.0x (Zero duplicates)**
- **Model Telemetry (`models.jsonl`):**
  - `MODEL_REQUESTED` and `MODEL_COMPLETED` records match the physical API requests 1:1.

---

## 7. Rollback Instructions

If it is ever necessary to revert this remediation:
1. Revert `core/observability/bus_subscriber.py` to remove the idempotency check in `attach()`.
2. Revert `core/server/runtime_adapter.py` to remove `self._init_telemetry_subscriber()`.
3. Revert `core/server/app.py` to remove `detach_telemetry_subscriber()`.
4. Restore `self._bus_subscriber = ObservabilityBusSubscriber(self.event_bus)` in `core/agent_loop/loop.py`.
5. Revert `_TELEMETRY_LOCK` from `RLock` to `Lock` in `core/observability/logger.py`.

---

## 8. Authoritative Verdict

| Evaluation Dimension | Standard | Measured Result | Status |
|---|---|---|---|
| Subscriber Count per Bus | Exactly 1 | 1 | **PASSED** |
| EventBus Event Multiplication | 1x (No duplicates) | 1x across all events | **PASSED** |
| Sequence Monotonicity | Contiguous (diff = 1) | 1 to 122 (diff = 1) | **PASSED** |
| Tool Lifecycle Deduplication | 1 Start / 1 Complete | 4 Started / 4 Completed | **PASSED** |
| Full Regression Battery | 100% Pass | 129 / 129 Passed (34.61s) | **PASSED** |
| Live Backend Sync & Health | `SYNCED`, `code_match: true` | Verified on PID 28856 | **PASSED** |

**FINAL AUTHORITATIVE VERDICT: CLEAN PASS**
