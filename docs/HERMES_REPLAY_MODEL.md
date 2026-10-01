# HERMES 2.x — Replay Model & Audit Engine

## 1. Replay is NOT Execution

The fundamental law of the HERMES Replay Engine (`core/replay/engine.py`) is:

> **Replay is pure state reconstruction from event history. It MUST NEVER perform live actions.**

When replaying a previous session or trace file:
- **0 Model Calls**: The LLM is never invoked.
- **0 Tool Executions**: Tools are never invoked.
- **0 Shell Commands**: Host processes are never launched.
- **0 Network Requests**: No sockets or HTTP connections are opened.
- **0 Filesystem Mutations**: Workspace files are never modified.
- **0 Database Writes**: No journal or task database writes occur.

---

## 2. Deterministic State Reconstruction

Replay works by feeding historical `HermesEvent` records sequentially into the pure `StateReducer`:
```text
Event 1 (MISSION_CREATED) ──> StateReducer ──> State_v1
Event 2 (TASK_CREATED)    ──> StateReducer ──> State_v2
Event 3 (TASK_COMPLETED)  ──> StateReducer ──> State_v3
...
Event N (MISSION_COMPLETED)──> StateReducer ──> State_vFinal
```

Because `StateReducer.reduce(state, event)` is a pure mathematical transition function with zero side effects:
- Replaying the identical event journal always produces the identical final state.
- Measured throughput exceeds **2,000,000 events/second** on standard hardware.

---

## 3. Supported Input Formats

The Replay Engine supports two input sources:
1. **Persistent Session Journals**:
   Replayed directly from SQLite journal storage by session ID:
   ```bash
   python main.py replay sess_9f3b20a1 --format text
   ```
2. **Exported Trace Files**:
   Replayed from JSON array or JSONL files:
   ```bash
   # Replay JSON trace file with NDJSON streaming output
   python main.py replay path/to/trace.json --format stream-json

   # Replay JSONL trace file with structured JSON summary
   python main.py replay path/to/trace.jsonl --format json
   ```

---

## 4. Replay Presentation Sinks

Replay events can be piped into any presentation sink (`TextSink`, `JsonSink`, `StreamJsonSink`, or TUI ViewModels). This allows developers to:
- Inspect past agent reasoning steps and decisions in the terminal.
- Re-run visual projections in the TUI without spending tokens or touching the workspace.
- Export telemetry and audit evidence for compliance and evaluation harnesses.
