# HERMES 2.x — Authoritative Runtime State Architecture Specification

**Status:** Authoritative Runtime Contract  
**Version:** HERMES 2.x (`Prompt 3`)  
**Anchor Commit:** `3ce8f81`  
**Reference Tag:** `v1.0.0-rc3`  

---

## 1. Core Architectural Invariant

The fundamental principle governing the HERMES 2.x runtime is:

```
MODEL / RUNTIME
     │
     ▼
   EVENT
     │
     ▼
 EVENT BUS
     │
     ▼
STATE REDUCER
     │
     ▼
 STATE STORE
     │
  ┌──┴────────┬──────────┐
  ▼           ▼          ▼
TELEMETRY  VIEW MODEL  LOGGING
              │
              ▼
             TUI
```

**The Canonical Axiom:**
> **Execution produces events.**  
> **Events produce state.**  
> **State is authoritative.**  
> **Everything else observes state.**

The UI, telemetry, logging, and external adapters are **projections** of the authoritative runtime state. Under no circumstances may backend execution directly mutate UI widgets, and under no circumstances does the UI own mission or task state.

---

## 2. The Five HERMES 2.x Architectural Principles

1. **Principle 1 — Model Chooses What to Do:**  
   The LLM proposes tools, plans, code modifications, and repairs. The model does *not* directly mutate UI state or declare mission completion.
2. **Principle 2 — Harness Decides What is Allowed:**  
   The harness enforces workspace boundaries, security gates, permissions, timeouts, and lifecycle transitions.
3. **Principle 3 — Evidence Decides Whether Something Actually Worked:**  
   Completion is governed by physical tool results, test outputs, exit codes, and deterministic/semantic verifications—never by model assertions or conversational claims.
4. **Principle 4 — State Survives Failures:**  
   A TUI crash, formatting error, or unhandled UI coroutine exception does *not* terminate mission execution or erase runtime state. Disconnections produce explicit `DISCONNECTED` / `RECONNECTING` states.
5. **Principle 5 — UI Observes State; UI Never Owns Execution:**  
   The TUI can accept user input, request cancellations, and display progress, but runtime state exists independently and can be resynchronized via snapshots.

---

## 3. Canonical Runtime State Tree

The authoritative root state is defined in [`core/runtime_state/models.py`](file:///c:/Users/SUBBU/Downloads/hermes/core/runtime_state/models.py) as `HermesRuntimeState`:

```
HermesRuntimeState
    ├── mission: MissionState
    │   ├── mission_id, request_id, session_id
    │   ├── status: CREATED | PLANNING | RUNNING | WAITING | PAUSED | COMPLETING | COMPLETED | FAILED | CANCELLED | ABORTED
    │   └── prompt, start_time, end_time, workspace_root
    ├── goal: GoalState
    │   ├── goal_id, description, acceptance_criteria
    │   └── progress (0.0 - 1.0), status, achieved_objectives
    ├── progress: ProgressState
    │   ├── completed_tasks, total_tasks, overall_fraction
    │   ├── active_task_id, current_stage, current_action
    │   └── waiting_reason: NONE | WORKING | WAITING_FOR_MODEL | WAITING_FOR_TOOL | WAITING_FOR_VERIFICATION | WAITING_FOR_PERMISSION | WAITING_FOR_NETWORK | WAITING_FOR_USER | REPAIRING | COMPLETED | FAILED | CANCELLED
    ├── current_task: Optional[TaskState]
    ├── tasks: Dict[str, TaskState]
    │   ├── task_id, title, status, order_index, dependencies
    │   └── started_at, completed_at, attempts, iteration
    ├── tool_execution: ToolExecutionState
    │   ├── active_tool_call_id, tool_name, status, exit_code, success, duration
    │   └── recent_tools (bounded history)
    ├── model_execution: ModelExecutionState
    │   ├── active_request_id, tier, provider, model
    │   └── status, started_at, first_token_at, duration, tokens
    ├── verification: VerificationState
    │   ├── verification_id, status, method, verdict, confidence, issues
    ├── network: NetworkState
    │   ├── connectivity: CONNECTED | DISCONNECTED | RECONNECTING | DEGRADED | FAILED
    │   └── endpoint, latency_ms, reconnecting, retry_count
    ├── permission: PermissionState
    │   ├── permission_request_id, action, risk, status, decision
    ├── session: SessionState
    ├── evidence: Dict[str, EvidenceState]
    ├── checkpoint: CheckpointState
    ├── state_version: int (monotonically increasing)
    └── last_event_sequence: int
```

---

## 4. Canonical Event Model & Taxonomy

The canonical event envelope is defined in [`core/runtime_state/events.py`](file:///c:/Users/SUBBU/Downloads/hermes/core/runtime_state/events.py) as `HermesEvent`:

- **Identity & Traceability:** Every event carries `event_id`, `event_type`, `timestamp`, `sequence`, `source`, `mission_id`, and optional causal links: `session_id`, `task_id`, `request_id`, `turn_id`, `tool_call_id`, `verification_id`, `checkpoint_id`.
- **Security & Redaction:** Event instantiation automatically scrubs API keys (e.g. `sk-...`, `ghp_...`), passwords, bearer tokens, and internal chain-of-thought blocks (`<think>...</think>`).
- **Comprehensive Taxonomy:** Covering mission, goal, task, model, tool, verification, repair, network, permission, session, evidence, checkpoint, and system observability lifecycles.

---

## 5. EventBus & StateStore Invariants

Implemented in [`core/event_bus.py`](file:///c:/Users/SUBBU/Downloads/hermes/core/event_bus.py) and [`core/runtime_state/store.py`](file:///c:/Users/SUBBU/Downloads/hermes/core/runtime_state/store.py):

1. **Monotonic Sequence Ordering:** Every published event is assigned a strictly increasing integer sequence number.
2. **Deduplication:** Events with identical `event_id` are processed exactly once. Re-publishing duplicate events is an idempotent no-op.
3. **Subscriber Failure Isolation:** An unhandled exception in any subscriber (such as a TUI rendering crash or logging failure) is isolated and logged. It *never* terminates the event bus, interrupts state reduction, or stops backend execution.
4. **Deterministic Reduction:** `StateReducer.reduce(state, event)` is pure and side-effect free. Given identical starting state and event sequence, it produces identical final state.
5. **Terminal State Protection:** Once a mission or task transitions to a terminal state (`COMPLETED`, `FAILED`, `CANCELLED`, `ABORTED`), late out-of-order events cannot resurrect or regress it back to `RUNNING`.
6. **Snapshot Immutability:** `store.get_snapshot()` returns an isolated deep copy. Callers cannot corrupt live authoritative state by modifying their snapshot copy.

---

## 6. View Model Projection & Renderer Safety

Implemented in [`core/runtime_state/selectors.py`](file:///c:/Users/SUBBU/Downloads/hermes/core/runtime_state/selectors.py):

- **Zero Side-Effects:** Selectors format, select, and normalize data without performing network calls, file system I/O, or state mutations.
- **Partial-State Safety:** `ViewModelBuilder` handles unpopulated or partial values safely before data reaches the renderer:
  - `verification.confidence = None` $\rightarrow$ `"Pending"` (prevents format string exceptions).
  - `tool_execution.tool_name = None` $\rightarrow$ `"Unknown tool"` (never renders raw `"None"`).
  - `exit_code = None` $\rightarrow$ `"-"`.
- **Authoritative "Why Waiting?":** Progress displays derive directly from `ProgressState.waiting_reason` and active component states, providing unambiguous feedback (e.g. `"Reconnecting to provider endpoint (attempt 2)..."` rather than generic `"Evaluating..."`).

---

## 7. Migration & Compatibility Bridges

To preserve existing functionality and tests:
- **`ExecutionStateStore` Compatibility:** `StateStore` implements all properties and methods of the legacy `ExecutionStateStore` (`status`, `tasks`, `progress`, `current_model`, `current_tool`, `recent_events`, etc.).
- **MissionRunner Bridge:** `MissionRunner._emit()` publishes canonical `HermesEvent` objects to `event_bus` while continuing to service the internal queue.
- **TUI Consumer Hardening:** In `ui/app.py`, local variable shadowing of `Path` was eliminated, and the event consumption loop isolates per-event handler errors to prevent thread termination.

---

## 8. Current Limitations & Non-Goals (Prompt 3 Scope)

The following capabilities are deliberately **not** implemented in Prompt 3 and are scheduled for subsequent prompts:
- Autonomous Continuous Agent Loop (Prompt 4)
- Context Compaction & Token Windows (Future Prompts)
- Subagent Collaboration Swarms (Future Prompts)
- Git Worktrees & Workspace Checkpoint Engine (Prompt 14)
- Full TUI 2.0 Canvas Redesign (Prompt 15)
- Automated Provider Reconnect Engine (Prompt 12)
- Dynamic Tool Discovery & Indexing (Prompt 10)
- QualityVerifier short keyword truncation fix (Prompt 5)

---

## 9. Prompt 11 Subsystems — Evidence, Verification, Repair & Escalation

HERMES 2.x Prompt 11 extends the Authoritative Runtime State with:
1. **Durable Evidence (`EvidenceRecord`, `EvidenceState`):** Append-only factual environment observations, cryptographic digests, freshness tracking (`FRESH`, `STALE`, `INVALIDATED`), and trust class ordering.
2. **Deterministic Verification (`VerificationResult`, `VerificationVerdict`):** AST parsing, filesystem assertions, JSON schema checks, and test runner outputs evaluated against durable evidence bundles.
3. **T1 Self-Repair (`RepairState`, `RepairBudget`, `RepairFingerprint`):** Bounded repair attempts (max 2-3 per check), cryptographic stall detection on identical failures, and structured guidance injection.
4. **Selective Escalation (`EscalationState`, `T2CriticResult`, `T3JudgeResult`):** Multi-tier evaluation with low-risk bypass for routine actions, T2 skeptical review for high-risk modifications, and T3 arbitration strictly bound by the Constitutional Fact Invariant.

