# HERMES 2.x — Headless Parity Specification

## 1. Principle of Surface Equivalence

HERMES 2.x enforces strict architectural parity across all presentation surfaces:
```text
                          HERMES RUNTIME
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
    TUI 2.x                HEADLESS CLI            REPLAY ENGINE
(Rich Rendering)         (Text / JSON / NDJSON)    (Pure Event Audit)
```

No core capability, state mutation, or security evaluation is exclusive to the TUI. Headless mode executes the exact same underlying `AgentLoop`, `StateStore`, `SecurityService`, and `SessionManager` as the interactive interface.

---

## 2. CLI Invocation Patterns

The CLI entrypoint is `main.py`, providing subcommands for automated pipelines, CI/CD, scripts, and administrative queries:

### Headless Mission Run
```bash
# Direct prompt execution
python main.py run "Refactor database models to async" --format text

# Piped prompt execution via stdin
cat prompt.txt | python main.py run - --format json

# Machine-readable streaming events (NDJSON)
python main.py run "Run test suite and fix failing tests" --format stream-json
```

### Administrative & Diagnostics Subcommands
```bash
python main.py doctor [--probe]     # Bounded system, network, and environment checks
python main.py status               # Authoritative runtime and mission state
python main.py diff                 # Uncommitted workspace file changes
python main.py cost                 # Truthful token accounting across model tiers
python main.py tasks                # Active task DAG and background jobs queue
```

---

## 3. Presentation Sinks

Headless output is managed by pluggable sinks in `core/sinks.py`:

1. **`TextSink`** (Default):
   - Human-readable plain text output.
   - Real-time milestone notifications (turn start, tool execution, security events).
   - Formatted summary box upon completion with status, duration, and exit code.

2. **`JsonSink`**:
   - Single structured JSON document emitted upon execution completion.
   - Contains mission metadata, session ID, task array, checkpoint IDs, and total cost metrics.
   - Ideal for CI/CD pipeline automation and wrapper scripts.

3. **`StreamJsonSink`**:
   - Line-delimited JSON (NDJSON) streaming events.
   - Emits an event object for every `HermesEvent` in real time.
   - Terminates with an event object of type `"completed"`.

4. **`NullSink`**:
   - Discards all presentation rendering while preserving state persistence.
   - Used for zero-overhead background soak and benchmark testing.

---

## 4. Standard Exit Codes

All headless CLI commands adhere to deterministic POSIX exit codes:

| Exit Code | Meaning | Condition |
|---|---|---|
| `0` | **Success** | Mission completed successfully; all goals and acceptance checks passed. |
| `1` | **Execution Failure** | Mission aborted due to tool failure, test failure, or unrecoverable error. |
| `2` | **Usage / Argument Error**| Invalid syntax, unknown command, or missing required CLI options. |
| `3` | **Security Denial** | Operation blocked by security policy, or failed closed on human approval requirement (`ASK`). |
| `5` | **Cancelled** | Execution cancelled via SIGINT (Ctrl+C) or external abort signal. |
