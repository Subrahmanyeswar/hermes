# HERMES 2.x — Command OS Architecture & Reference Specification

## 1. Overview & Architectural Philosophy

The HERMES Command OS represents the operator control plane of HERMES 2.x. It transforms commands from superficial terminal shell shortcuts into an authoritative, typed, observable, and isolated runtime system.

### Core Invariants:
1. **One Engine, Many Surfaces**: All interaction surfaces (Interactive TUI 2.x, Headless CLI, Scripting Pipes, and Historical Replay) share the identical canonical execution engine, security model, and persistence substrate.
2. **Deterministic Routing**: Every user input is categorized deterministically into one of four distinct prefix namespaces:
   - `/` — Command namespace: Pure queries, control operations, or state mutations.
   - `@` — Workspace Mention: Path containment verification, size-bounded preview, and data-quarantine context injection.
   - `!` — Shell Escape: Controlled host process execution through canonical Prompt 13 security gates.
   - Bare text — Autonomous Agent Prompt: Delegated to the canonical `AgentLoop`.
3. **Zero Inference Invariant for Pure Queries**: Pure query commands (`/status`, `/context`, `/cost`, `/doctor`, `/diff`, `/tasks`, `/help`) NEVER call an LLM under any circumstance.
4. **Observable Lifecycle**: Every command emits structured, monotonic events (`COMMAND_RECEIVED`, `COMMAND_COMPLETED`, `COMMAND_DENIED`, `COMMAND_FAILED`) to the `EventBus`.

---

## 2. Input Parsing Specification

Inputs are parsed by `core/commands/parser.py` (`UnifiedInputParser`).

| Input Pattern | Class | Description |
|---|---|---|
| `//text` | `NormalPromptInput` | Escaped `/` treated as literal text `/text`. |
| `@@text` | `NormalPromptInput` | Escaped `@` treated as literal text `@text`. |
| `!!text` | `NormalPromptInput` | Escaped `!` treated as literal text `!text`. |
| `/` (alone) | `PaletteTriggerInput` | Command palette completion trigger / command listing. |
| `/command [args]` | `SlashCommandInput` | Typed slash command intent with parsed args and kwargs. |
| `!command [args]` | `ShellEscapeInput` | Immediate shell escape execution routed through `ShellExecutor`. |
| `text @path` | `AtMentionInput` | Prompt containing one or more workspace file/directory mentions. |
| `text` | `NormalPromptInput` | Standard natural language prompt to autonomous agent. |

*Note: Email addresses (e.g. `user@example.com`) are automatically excluded from `@` mention extraction.*

---

## 3. Command Registry & Built-in Command Reference

Commands are catalogued in `core/commands/registry.py` with typed metadata and strict execution policies:

| Command | Aliases | Execution Class | LLM Policy | Headless | Replay | Description |
|---|---|---|---|---|---|---|
| `/status` | `/st` | `PURE_QUERY` | `NEVER` | Yes | Yes | Authoritative mission, session, task, and network status. |
| `/context` | `/ctx` | `PURE_QUERY` | `NEVER` | Yes | Yes | Token budget allocation, health, and section breakdown. |
| `/cost` | `/usage` | `PURE_QUERY` | `NEVER` | Yes | Yes | Truthful token accounting and cost breakdown across T1/T2/T3. |
| `/doctor` | `/diag` | `PURE_QUERY` | `NEVER` | Yes | No | System, environment, disk, and permission diagnostics. |
| `/diff` | `/changes`| `PURE_QUERY` | `NEVER` | Yes | Yes | Git diff inspection and uncommitted change preview. |
| `/tasks` | `/todos` | `PURE_QUERY` | `NEVER` | Yes | Yes | Task DAG state and active background job queues. |
| `/plan` | | `CONTROL_OPERATION` | `NEVER` | Yes | No | Enter plan mode (read-only) or set planned goal. |
| `/compact` | | `CONTROL_OPERATION` | `NEVER` | Yes | No | Directed context compaction and cache pruning. |
| `/rewind` | `/revert`| `CONTROL_OPERATION` | `NEVER` | Yes | No | Safe checkpoint rewind with user change conflict protection. |
| `/resume` | | `CONTROL_OPERATION` | `NEVER` | Yes | No | 16-step deterministic session recovery protocol. |
| `/clear` | `/reset` | `STATE_MUTATION` | `NEVER` | Yes | No | Establish fresh context epoch preserving durable checkpoints. |
| `/goal` | | `STATE_MUTATION` | `NEVER` | Yes | Yes | Set or inspect authoritative mission goal. |
| `/btw` | `/ask` | `MODEL_OPERATION` | `REQUIRED`| Yes | No | Ephemeral side query with zero main context pollution. |
| `/help` | `/?` | `PURE_QUERY` | `NEVER` | Yes | Yes | Command catalog and detailed usage manual. |

---

## 4. Workspace Mentions (@) & Prompt Injection Defense

All `@path` mentions are verified by `core/commands/mentions.py`:
1. **Workspace Boundary Enforcement**: Paths attempting directory traversal (`../`, absolute paths outside workspace, symlink escapes) are denied with `is_contained = False`.
2. **Context Budgeting**:
   - Small files (< 100 KB): Full content inlined.
   - Large files (≥ 100 KB): Bounded preview (head 25 lines + tail 25 lines) with truncation notice.
   - Binary files: Metadata summary only (size, MIME type, binary warning).
   - Directories: Formatted tree listing with item count.
3. **Prompt Injection Quarantine**: Referenced file contents are wrapped inside secure data envelopes through `ContentBoundary`. Malicious directives inside files remain inert data and are never interpreted as agent instructions.

---

## 5. Host OS Shell Escape (!)

The `!` prefix executes shell commands locally through `core/commands/shell.py`:
1. **Security Gating**: Evaluated against Prompt 13 `SecurityService`. Unsafe operations trigger `PermissionOutcome.DENY` or `PermissionOutcome.ASK`.
2. **Headless Fail-Closed**: In headless execution (`SurfaceMode.HEADLESS`), any command resulting in `ASK` fails closed immediately with exit code 3, preventing unmonitored hangs.
3. **Terminal Safety**: Standard output and error streams are cleaned through `sanitize_terminal_text`, stripping ANSI escape bombs, control sequences, and bells.
