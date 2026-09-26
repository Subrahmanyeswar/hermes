# HERMES 2.x — Agent Loop Architectural Specification

**Status:** Authoritative Runtime Contract  
**Version:** HERMES 2.x (`Prompt 4`)  
**Anchor Baseline:** `3ce8f81`  
**State Architecture Baseline:** `712a84b` (`Prompt 3`)  
**Reference Tag:** `v1.0.0-rc3` (`da30412b...`)  

---

## 1. Executive Mission & Core Invariant

Prompt 4 executes the fundamental runtime-control-flow transformation of HERMES 2.x. It replaces the rigid, stage-controlled 12-stage pipeline with a **model-driven continuous agent execution loop** (`AgentLoop`).

### The Central Control-Flow Principle
```
MODEL CHOOSES
HARNESS ALLOWS
ENVIRONMENT OBSERVES
EVIDENCE DECIDES
STATE SURVIVES
UI OBSERVES
```

Under this architecture:
1. **Model Chooses:** T1 is the primary reasoning and decision engine. It proposes what to read, what to search, what to edit, what tests to run, whether to ask the user, whether verification is needed, and whether the task appears complete.
2. **Harness Allows:** The HERMES harness remains strictly authoritative over security, permissions, workspace boundaries, tool availability, execution limits, cancellation, and terminal state transitions.
3. **Environment Observes:** Tools and system interactions produce structured ground-truth observations (`Observation`), not conversational claims.
4. **Evidence Decides:** Completion is governed by physical file artifacts, syntax validation, tests, and verifier contracts—never by model assertion or confidence.
5. **State Survives:** Execution state is maintained in the authoritative `StateStore` via pure reduction of canonical `EventBus` events. UI crashes or subscriber exceptions cannot terminate execution or corrupt state.
6. **UI Observes:** The TUI, telemetry, and external adapters are read-only observers projecting state via pure ViewModels.

---

## 2. Architecture & Migration Diagram

### Previous Architecture (Rigid Stage Pipeline)
```
      USER
        │
        ▼
     PLANNER
        │
     TASK 1
        │
     STAGE 1 (Sanitise) ──► STAGE 2 (Plan) ──► STAGE 3 (Memory)
        │
     STAGE 4 (T1 Call) ──► STAGE 5 (Validation) ──► STAGE 6 (Tool Exec)
        │
     STAGE 7 (T2 Verify) ──► STAGE 8 (Router) ──► STAGE 9 (T3 Arbitrate)
        │
     STAGE 10 (Memory) ──► STAGE 11 (Queue) ──► STAGE 12 (Response)
        │
     TASK 2 (Repeat same sequence regardless of need)
```

### New HERMES 2.x Architecture (Model-Driven Agent Loop)
```
                             USER
                               │
                               ▼
                         MISSION INTAKE
                               │
                               ▼
                      AUTHORITATIVE STATE ◄──────────────────────┐
                               │                                 │
                               ▼                                 │
                        CONTEXT ENGINE                           │
                               │                                 │
                               ▼                                 │
                         ┌─────────────┐                         │
                         │  AGENT LOOP │                         │
                         └──────┬──────┘                         │
                                │                                │
                                ▼                                │
                               T1                                │
                                │                                │
                   ┌────────────┼─────────────┐                  │
                   │            │             │                  │
                   ▼            ▼             ▼                  │
                 TOOL        ASK USER      DELEGATE*             │
                   │            │             │                  │
                   ▼            ▼             ▼                  │
                HARNESS     PERMISSION      POLICY               │
                 POLICY        GATE                               │
                   │            │             │                  │
                   └────────────┼─────────────┘                  │
                                ▼                                │
                           OBSERVATION                           │
                                │                                │
                                ▼                                │
                            EVENT BUS                            │
                                │                                │
                                ▼                                │
                          STATE REDUCER                          │
                                │                                │
                                └────────────────────────────────┘
                                │
                                ▼ (Candidate / Verification)
                            EVIDENCE
                                │
                      ┌─────────┴─────────┐
                      ▼                   ▼
                DETERMINISTIC           T2
                   CHECKS                │
                                        ▼
                                       T3
                               (only when needed)
                                        │
                                        ▼
                                      JUDGE
                                        │
                         ┌──────────────┴──────────────┐
                         ▼                             ▼
                      ACCEPT                         REPAIR
                         │                             │
                         ▼                             ▼
                      COMPLETE                 REPAIR OBSERVATION
                                                       │
                                                       └─────────► Next T1 Turn
```

---

## 3. Legacy Stage Classification & New Lifecycle Dimensions

The old 12-stage pipeline is not deleted; it has been converted from **"mandatory execution sequence"** into **"telemetry and lifecycle dimensions describing what happened"**:

| Legacy Stage | Name | New Role / Classification | Dimension |
|---|---|---|---|
| **Stage 1** | Input Sanitisation | HARNESS SERVICE | `INTAKE` |
| **Stage 2** | Task Planning | INITIAL HINTS / OBJECTIVE INTERPRETATION | `INTAKE` / `CONTEXT` |
| **Stage 3** | Skill + Memory Injection | HARNESS SERVICE / GROUNDING | `CONTEXT` |
| **Stage 4** | Tier 1 Generation | CORE AGENT ACTION | `AGENT` |
| **Stage 5** | Tool Validation & Security | HARNESS SERVICE / AUTHORIZATION | `ACTION` |
| **Stage 6** | Tool Execution | HARNESS SERVICE / ENVIRONMENT RUNTIME | `ACTION` |
| **Stage 7** | Tier 2 Verification | ADAPTIVE VERIFICATION SERVICE | `VERIFY` |
| **Stage 8** | Disagreement Routing | HARNESS SERVICE / ARBITRATION | `JUDGE` |
| **Stage 9** | Tier 3 Arbitration | ESCALATION SERVICE | `JUDGE` |
| **Stage 10** | Memory Extraction | DECOUPLED BACKGROUND SERVICE | `MEMORY` |
| **Stage 11** | Task Queue Update | STATE REDUCTION / OBSERVABILITY | `CONTEXT` |
| **Stage 12** | Response Construction | OBSERVABILITY / COMPLETION CONTRACT | `COMPLETE` |

### The 10 New Lifecycle Dimensions
Runtime activity flows fluidly between these dimensions:
1. `INTAKE`: Mission initialization, goal interpretation, constraint extraction.
2. `CONTEXT`: Dynamic assembly of workspace skeleton, goal criteria, error hints, and recent observations.
3. `AGENT`: Model decision turn (T1 native tool calls, reasoning, proposals).
4. `ACTION`: Harness policy evaluation (boundary, permissions, schema) and physical tool execution.
5. `OBSERVE`: Capture of exit codes, stdout/stderr, filesystem deltas, and user responses into ground truth.
6. `VERIFY`: Deterministic syntax checks, test execution, and targeted verification.
7. `JUDGE`: Multi-tier arbitration (T2/T3) invoked adaptively based on risk and evidence.
8. `REPAIR`: Agentic repair cycles triggered by verification feedback.
9. `MEMORY`: Asynchronous trajectory facts extraction without blocking the foreground loop.
10. `COMPLETE`: Authoritative completion validation and terminal status declaration.

---

## 4. Component Contracts

### A. Semantic Decision Model (`core/agent_loop/decisions.py`)
Classifies model output into one of 8 canonical decision types:
- `ACT`: Proposes execution of a registered tool with parameters.
- `ASK_USER`: Pauses the loop in `WAITING_FOR_USER` to solicit clarification.
- `VERIFY`: Requests explicit structural or semantic verification.
- `DELEGATE`: Requests subagent delegation (contract boundary).
- `COMPLETE`: Proposes mission completion candidate.
- `CONTINUE_REASONING`: Emits thought or conversational text and continues.
- `ABORT`: Halts execution.
- `INVALID`: Model emitted unparseable or malformed content.

### B. Action Envelope & Harness Policy (`core/agent_loop/actions.py`)
Model proposes actions via `ActionEnvelope`:
```
ActionEnvelope: action_id, mission_id, task_id, turn_id, tool_name, arguments, status
```
Passes through `HarnessPolicy`:
1. Tool registry existence check (`get_tool(name)`).
2. Permission gate check (`PermissionGate(mode).check(tool_class)`).
3. Workspace boundary and path-traversal check (`..` and external roots blocked).
4. Schema validation and alias normalization (`tool_validator`).
Only after passing all gates is `tool_instance.execute()` invoked.

### C. Observation Model (`core/agent_loop/observations.py`)
Every executed action produces a structured `Observation`:
```
Observation: observation_id, mission_id, turn_id, action_id, source_type, source_id,
             success, summary, content, exit_code, evidence_ids, error_message
```
Observations are formatted and grounded into subsequent model turns. Giant command outputs are bounded and summarized to protect the model's context budget.

### D. Two-Layer Completion Contract (`core/agent_loop/completion.py`)
1. **Layer 1: Model Completion Candidate.** The model asserts that it has finished.
2. **Layer 2: Harness & Evidence Verification.**
   - Physical artifact verification: if the request implied building or creating code, real non-empty files must exist in the workspace root.
   - Deterministic syntax checks: Python AST parse (`ast.parse`) and JSON syntax validation for all written files.
   - Quality verification: `QualityVerifier` inspects project completeness and acceptance criteria.
   - If checks pass: mission enters `COMPLETED`.
   - If checks fail: mission enters `REPAIRING`, emits `AGENT_REPAIR_REQUESTED`, and the next turn receives a detailed repair observation.

### E. Safety Budgets & Stall Detection (`core/agent_loop/loop.py`)
The loop enforces:
- `max_turns` (default 40-50).
- `max_wall_time_seconds` (default 600s).
- `max_consecutive_failures` (default 5).
- `stall_window_size` (default 4): detects repeated identical tool calls with identical parameters and injects corrective guidance without crashing.

---

## 5. Execution Modes: Agentic vs. Strict

HERMES 2.x supports two distinct execution modes:
- **`AGENTIC MODE` (default for interactive missions):** Continuous model-driven execution via `AgentLoop`. T1 dynamically determines every inspection, modification, test, and repair step.
- **`STRICT MISSION MODE` (benchmarks, regression tests, high assurance):** Deterministic task-by-task execution via `MissionRunner`.

Both modes share the same `StateStore`, `EventBus`, tool registry, security gates, verification engines, and telemetry.

---

## 6. Implementation Status & Next Milestones

- **Implemented in Prompt 4:**
  - `core/agent_loop/types.py` (models, enums, envelopes)
  - `core/agent_loop/decisions.py` (`DecisionInterpreter`)
  - `core/agent_loop/observations.py` (`ObservationBuilder`)
  - `core/agent_loop/actions.py` (`HarnessPolicy`, `ActionExecutor`)
  - `core/agent_loop/completion.py` (`CompletionPolicy`)
  - `core/agent_loop/loop.py` (`AgentLoop`)
  - `core/agent_loop/__init__.py` (package exports)
  - Canonical event additions (`AGENT_*`, `ACTION_*`) in `core/runtime_state/events.py` and `reducer.py`
  - Integration bridges in `kairos/mission_driver.py` and `core/mission_runner.py`
  - Telemetry support in `core/telemetry.py`
- **Deferred to Later Prompts:**
  - Prompt 5: Standardized Tool Platform (`read_file`, `edit_file`, `write_file`, `bash_exec`, `grep_search`, `glob_find`) and progressive tool discovery.
  - Prompt 7: Context Engineering & LLMLingua-style dynamic context compaction.
  - Prompt 9: Dynamic Goal & Todo tracking.
  - Prompt 10: Multi-agent delegation architecture.
  - Prompt 12: Network failure auto-reconnection and provider recovery.
  - Prompt 13: Hardened Prompt Injection boundaries & Recursive Security Classifier.
