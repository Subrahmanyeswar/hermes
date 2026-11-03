# HERMES 2.x — Forensic Audit: Duplicate Telemetry Event Investigation

**Investigation Target:** Redundant Event Serialization in Forensic Telemetry Logs  
**Primary Evidence Run:** `run_1_b0b6b6e7` (Mission `m_4a4c4035`, Workload F)  
**Investigation Mode:** Strict Read-Only Forensic Analysis  
**Repository Working Baseline:** Canonical Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes`)  
**Backend Status:** Active & Preserved (`PID 17992`, port 8765)  
**Authoritative Verdict:** **DUPLICATE EVENT EMISSION** (EventBus Listener Accumulation Leak)

---

## 1. Executive Summary & Root Cause Analysis

### 1.1 The Anomaly
In `artifacts/observability/run_1_b0b6b6e7/events.jsonl`, multiple telemetry events were observed to appear four consecutive times with distinct, incrementing sequence numbers (`event_seq`):
- **Turn 11 Rejection:** Sequences `958`, `959`, `960`, `961` all record the exact same action rejection (`act_rej_7c1128b2`, `fs.read`, `TOOL_REJECTED_NO_PROGRESS`).
- **Turn 12 Rejection:** Sequences `1000`, `1001`, `1002`, `1003` all record the exact same action rejection (`act_rej_4c33b737`, `fs.read`, `TOOL_REJECTED_NO_PROGRESS`).
- Model turn events (`MODEL_REQUESTED`, `MODEL_COMPLETED`, `TIER_SELECTED`) and tool events (`TOOL_STARTED`, `TOOL_COMPLETED`) likewise appear four times per single logical action.

### 1.2 Root Cause Identification
The root cause is an **EventBus subscriber listener leak / accumulation** across sequential missions running inside the long-lived backend process (`task-8401` / `uvicorn`).

#### The Exact Chain of Failure:
1. **Singleton Event Bus:**  
   The HTTP server creates a single, long-lived `EventBus` instance attached to `RuntimeAdapter` in `core/server/runtime_adapter.py`.
2. **Per-Mission AgentLoop Instantiation:**  
   Whenever a mission is started (`POST /api/missions`), `RuntimeAdapter._run_mission_background` instantiates a brand new, isolated `AgentLoop` instance (`core/server/runtime_adapter.py:410`).
3. **Unbounded Subscriber Attachment in `run()`:**  
   In `core/agent_loop/loop.py` (lines 441–445):
   ```python
   # Initialize Forensic Observability Telemetry
   from core.observability.logger import get_telemetry_logger
   from core.observability.bus_subscriber import ObservabilityBusSubscriber
   self.telemetry_logger = get_telemetry_logger(run_id=self._run_id, mission_id=self._mission_id)
   if not getattr(self, "_obs_subscriber", None):
       self._obs_subscriber = ObservabilityBusSubscriber(self.event_bus)
       self._obs_subscriber.attach()
   ```
   Because `self` is a newly created `AgentLoop` instance for that mission, `self._obs_subscriber` is always `None`.
4. **Permanent Registration on EventBus:**  
   `ObservabilityBusSubscriber.attach()` (`core/observability/bus_subscriber.py:27–31`) registers its `handle_event` callback onto the shared singleton `EventBus`:
   ```python
   def attach(self) -> None:
       if not self.is_attached:
           self.event_bus.subscribe(self.handle_event)
           self.is_attached = True
   ```
   `EventBus.subscribe()` (`core/event_bus.py:198`) appends `(self.handle_event, event_types)` to `self._subscribers`.
5. **Missing Cleanup / Detach:**  
   `ObservabilityBusSubscriber.detach()` exists, but **is never called anywhere in the codebase**. When `AgentLoop.run()` finishes, the `ObservabilityBusSubscriber` instance remains permanently subscribed in `self.event_bus._subscribers`.
6. **Cross-Run Dispatch Multiplexing:**  
   When an event is published for *any* subsequent mission, `ObservabilityBusSubscriber.handle_event` dynamically resolves the logger using `event.run_id`:
   ```python
   run_id = event.run_id
   telemetry = get_telemetry_logger(run_id=run_id, mission_id=event.mission_id)
   telemetry.log_event(...)
   ```
   Every accumulated subscriber instance processes the event and routes it to the *current active mission's* logger!

### 1.3 Mathematical Progression on Current Backend
Tracking every mission launched on the running server instance confirms a strict 1:1 correlation between mission execution order and event duplication count:

| Execution Order | Mission ID | Authoritative Run ID | Workload | EventBus Subscribers Active | Duplication Factor Observed |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **1st** | `m_8fecb1c9` | `run_1_2de3643a` | Workload B | **1** | **1x (Zero Duplication)** |
| **2nd** | `m_fe9d36d7` | `run_1_d246c09a` | Workload C | **2** | **2x Duplication** |
| **3rd** | `m_f88f7830` | `run_1_2035336b` | Workload D | **3** | **3x Duplication** |
| **4th** | `m_4a4c4035` | `run_1_b0b6b6e7` | Workload F | **4** | **4x Duplication** |

---

## 2. Event Publication Architecture & Sequence Diagram

The following sequence diagram traces the complete lifecycle of a single canonical action rejection from creation to physical JSONL log append:

```mermaid
sequenceDiagram
    autonumber
    participant Loop as AgentLoop (Turn 11)
    participant Bus as EventBus (Singleton)
    participant Sub1 as ObservabilityBusSubscriber (Workload B)
    participant Sub2 as ObservabilityBusSubscriber (Workload C)
    participant Sub3 as ObservabilityBusSubscriber (Workload D)
    participant Sub4 as ObservabilityBusSubscriber (Workload F)
    participant Logger as MissionTelemetryLogger (run_1_b0b6b6e7)
    participant Disk as events.jsonl

    Loop->>Loop: Detect read loop on index.html
    Loop->>Loop: Generate action_id = "act_rej_7c1128b2" (ONCE)
    Loop->>Bus: publish(EventType.ACTION_DENIED, action_id="act_rej_7c1128b2")
    
    Note over Bus: Bus has 4 registered subscribers in _subscribers
    
    Bus->>Sub1: handle_event(HermesEvent)
    Sub1->>Logger: log_event(event_type="ACTION_DENIED")
    Logger->>Logger: _event_seq incremented to 958
    Logger->>Disk: Append JSON line (seq=958, act_rej_7c1128b2)
    
    Bus->>Sub2: handle_event(HermesEvent)
    Sub2->>Logger: log_event(event_type="ACTION_DENIED")
    Logger->>Logger: _event_seq incremented to 959
    Logger->>Disk: Append JSON line (seq=959, act_rej_7c1128b2)
    
    Bus->>Sub3: handle_event(HermesEvent)
    Sub3->>Logger: log_event(event_type="ACTION_DENIED")
    Logger->>Logger: _event_seq incremented to 960
    Logger->>Disk: Append JSON line (seq=960, act_rej_7c1128b2)
    
    Bus->>Sub4: handle_event(HermesEvent)
    Sub4->>Logger: log_event(event_type="ACTION_DENIED")
    Logger->>Logger: _event_seq incremented to 961
    Logger->>Disk: Append JSON line (seq=961, act_rej_7c1128b2)
```

---

## 3. Evidence: Parallel Execution vs. Redundant Emission

Forensic evidence definitively proves that the quadruple records represent **redundant emissions of a single operation**, not four parallel operations:

1. **Deterministic Action ID Identity:**  
   `action_id = "act_rej_7c1128b2"` is generated using Python's `uuid.uuid4().hex[:8]` immediately prior to `self._publish_event()` (`core/agent_loop/loop.py:1579`). It is mathematically impossible for four independent operations to share this UUID.
2. **Filesystem Reality:**  
   In `temp_stress_workload_f`, files (`models.js`, `calculations.js`, `app.js`) were created once, have single inode records, and contain single copies of the code.
3. **Single Model Turn Invocations:**  
   While `MODEL_REQUESTED` and `MODEL_COMPLETED` were duplicated 4x (52 total lines for 13 turns) due to EventBus fan-out, the direct adapter event `MODEL_REQUEST_COMPLETED` (which does not pass through EventBus) was written **exactly 13 times** (once per turn).
4. **Sub-Millisecond Monotonic Timestamps:**  
   The timestamps for sequences 958, 959, 960, and 961 span a difference of less than 2.9 milliseconds (`21:03:36.909523` to `21:03:36.912460`), matching synchronous in-memory dispatch across four consecutive function calls in `EventBus.publish()`.

---

## 4. Impact on Telemetry Accuracy & Performance Metrics

| Metric / Stream | Affected? | Distortion Mechanism | Current Reality in `run_1_b0b6b6e7` |
| :--- | :---: | :--- | :--- |
| **Model Invocations in Summary** | **NO** | Counted via direct logger metric `self._stats['model_calls']`. | Correctly reported as **13**. |
| **Model Invocations via `models.jsonl`** | **YES** | `MODEL_REQUESTED` & `MODEL_COMPLETED` are published via EventBus. | 52 records instead of 13. |
| **Tool Operations in Summary** | **NO** | Counted via direct logger metric `self._stats['tool_calls']`. | Correctly reported as **11**. |
| **Tool Operations in `tools.jsonl`** | **YES** | `TOOL_STARTED` and `TOOL_COMPLETED` published via EventBus. | 44 `TOOL_STARTED` records instead of 11. |
| **Average Model Latency / TTFT** | **NO** | Computed from `MODEL_REQUEST_COMPLETED` payload timings. | Accurately recorded (Avg 3.00s, TTFT 6.19s). |
| **Total Event Count (`_stats['total_events']`)** | **YES** | Every call to `log_event()` increments `total_events`. | Inflated to **1,151** (true count $\approx 300$). |
| **Recorded Errors / `errors.jsonl`** | **YES** | `errors` stream receives duplicated events from all subscribers. | 12 error lines recorded instead of 3. |
| **Disk Storage / Log Size** | **YES** | Redundant JSON serialization increases disk footprint by $N\times$. | Log directory size is $\approx 4\times$ expected baseline. |

---

## 5. Comparison Across Specialized Stream Logs (`run_1_b0b6b6e7`)

A granular inspection of the eight stream files in `artifacts/observability/run_1_b0b6b6e7/` highlights which streams are affected by the EventBus fan-out:

```
Stream Log Comparison:
├── events.jsonl      [1,151 records] -> All EventBus events duplicated 4x.
├── models.jsonl      [277 records]   -> EventBus model events duplicated 4x; direct MODEL_REQUEST_COMPLETED 1x (13).
├── tools.jsonl       [99 records]    -> TOOL_STARTED 4x (44); TOOL_COMPLETED 4x from EventBus + 1x from direct logger (55).
├── errors.jsonl      [12 records]    -> Warning/Error events duplicated 4x (3 distinct warnings).
├── runtime.jsonl     [1 record]      -> Written once by logger initialization (NOT on EventBus).
├── recovery.jsonl    [0 records]     -> No recovery.jsonl direct writes triggered.
├── files.jsonl       [0 records]     -> Files tracked via tools stream.
└── validation.jsonl  [0 records]     -> Validation executed via node syntax gate.
```

---

## 6. Is a Code Change Necessary?

**YES.**

While mission execution logic, file generation, and high-level summary counters (`model_calls`, `tool_calls`) remain functionally accurate, leaving this uncorrected causes:
1. **Unbounded Memory & CPU Waste:** In a production server handling hundreds of missions, the number of EventBus subscribers will grow indefinitely ($N = 100 \implies 100\times$ event duplication), significantly slowing down event publishing and bloating log files to gigabytes.
2. **Log File Bloat:** JSONL logs become unnecessarily large and difficult to tail or inspect.
3. **Telemetry Inconsistency:** Event stream consumers and monitoring dashboards reading `events.jsonl` or `tools.jsonl` receive distorted event counts unless explicitly deduplicated by `event_id` or `action_id`.

---

## 7. Proposed Minimal Remediation (For Future Authorization)

The remediation is straightforward and requires zero architectural changes:

### Option 1: Attach `ObservabilityBusSubscriber` ONCE Globally (Architecturally Cleanest)
Because `ObservabilityBusSubscriber.handle_event(event)` already extracts `run_id` dynamically from each incoming event, there is no technical reason to create a subscriber inside `AgentLoop` per mission.
- **Location:** `core/server/runtime_adapter.py` inside `__init__()`.
- **Change:** Instantiate and attach a single `ObservabilityBusSubscriber(self.event_bus)` once at server startup.
- **Remove:** Remove subscriber instantiation from `core/agent_loop/loop.py:441–445`.

### Option 2: Guarantee Scoped Detach in `AgentLoop.run()` (Minimal Scoped Fix)
If the subscriber remains scoped to `AgentLoop`:
- **Location:** `core/agent_loop/loop.py` inside `run()`.
- **Change:** Wrap loop execution in a `try ... Finally:` block and invoke `self._obs_subscriber.detach()` in `finally:`.
- **Deduplication Safeguard:** In `ObservabilityBusSubscriber.handle_event()`, verify `if event.mission_id != self.mission_id: return` so old subscribers ignore other missions.

*(Note: Per constraints, no code changes have been implemented. This analysis is purely diagnostic.)*

---

## 8. Authoritative Verdict

```
════════════════════════════════════════════════════════════════════════════════
FINAL FORENSIC VERDICT: DUPLICATE EVENT EMISSION
════════════════════════════════════════════════════════════════════════════════
Root Cause:      EventBus subscriber listener accumulation across sequential
                 missions in the persistent backend process.
Trigger:         core/agent_loop/loop.py:444 attaches a new ObservabilityBusSubscriber
                 on every mission without ever calling detach().
Evidence:        Exact 1x, 2x, 3x, 4x progression across sequential missions B, C, D, F.
Action IDs:      Identical UUIDs (act_rej_7c1128b2) serialized with distinct sequence
                 numbers (958-961) in sub-millisecond dispatch order.
Underlying App:  Functionally intact; single execution per operation.
Remediation:     Required prior to high-volume autonomous runs, awaiting approval.
════════════════════════════════════════════════════════════════════════════════
```
