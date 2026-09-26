# HERMES 2.x — Tool Platform Architectural Specification

**Status:** Authoritative Runtime Contract  
**Version:** HERMES 2.x (`Prompt 5`)  
**Anchor Baseline:** `3ce8f81` (`Prompt 2`)  
**State Architecture Baseline:** `712a84b` (`Prompt 3`)  
**Agent Loop Baseline:** `d68ecd7` (`Prompt 4`)  
**Reference Tag:** `v1.0.0-rc3` (`da30412b...`)  

---

## 1. Executive Mission & Core Invariants

Prompt 5 establishes the **HERMES 2.x Tool Platform** (`tools/platform/`). It upgrades HERMES from a collection of ad-hoc tool functions into a unified, Claude-Code-class agent-facing tool operating system.

### Core Principle: Tools are Agent Interfaces
An agent-facing tool is not merely a Python function wrapped in a docstring; it is the sensor and actuator interface through which the reasoning model perceives and mutates the environment. Every tool in HERMES 2.x explicitly answers:
1. **What to do:** Crisp semantic purpose with bounded scope.
2. **When to use (and when NOT to use):** Clear operational conditions, preventing misapplication.
3. **Parameter contracts:** Typed, validated parameters with automatic alias normalization and default handling.
4. **Concrete examples:** Grounded usage examples demonstrating both success and failure conditions.
5. **Success and failure semantics:** Structured diagnostic payloads explaining what failed, why it failed, what was left unchanged, and actionable recovery guidance.
6. **Workspace side effects & risk:** Explicit accounting of risk scores, filesystem modifications, process executions, network access, and idempotency.

### Non-Negotiable Invariants
- **No Duplicate Registries:** The existing `tools/registry.py` is evolved and wrapped by `ToolCatalog`; no competing tool registration mechanisms are permitted.
- **Unified Security & Validation:** All tool calls undergo centralized parameter normalization, workspace containment verification, and shell command security checks via `Validator`.
- **Model Independence:** Tool schemas can be serialized to OpenAI / NVIDIA NIM, Ollama, Anthropic, or raw JSON Schema formats without altering implementation logic.
- **Immutable Historical Baselines:** Full backward compatibility is maintained for legacy tool names (`read_file`, `write_file`, `bash_exec`, `list_directory`, etc.) and all existing test baselines.

---

## 2. Platform Architecture Diagram

```
                    ┌───────────────────────────────┐
                    │       Model / AgentLoop       │
                    └───────────────┬───────────────┘
                                    │ Tool Call Propose
                                    ▼
                    ┌───────────────────────────────┐
                    │         ToolExecutor          │
                    └───────┬───────────────┬───────┘
                            │               │
      Pre-Execution Check   │               │ Validation & Normalization
                            ▼               ▼
                ┌──────────────────┐ ┌──────────────────┐
                │ PermissionPolicy │ │    Validator     │
                │ (Risk / Mode)    │ │ (Alias/Path/Sec) │
                └──────────────────┘ └──────────────────┘
                            │               │
                            └───────┬───────┘
                                    │ Authorized & Validated
                                    ▼
                    ┌───────────────────────────────┐
                    │      Core / Bridged Tool      │
                    │  (e.g., fs.read, shell.bash)  │
                    └───────┬───────────────┬───────┘
                            │               │
        Success / Raw Data  │               │ Failure / Exception
                            ▼               ▼
                ┌──────────────────┐ ┌──────────────────┐
                │   OutputShaper   │ │    ToolError     │
                │   + OutputStore  │ │ + ErrorGuidance  │
                └───────────┬──────┘ └──────────┬───────┘
                            │                   │
                            └─────────┬─────────┘
                                      │ Emits Events
                                      ▼
                    ┌───────────────────────────────┐
                    │     EventBus (Prompt 3)       │
                    │ TOOL_STARTED / COMPLETED / etc│
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │   StateStore & ViewModels     │
                    └───────────────────────────────┘
```

---

## 3. Directory Layout & Module Responsibilities

The tool platform is located entirely within `tools/platform/`:

| Module | Responsibility |
| :--- | :--- |
| `specs.py` | Canonical `ToolSpec`, `ToolSchema`, `RiskMetadata`, `ToolExample`, and enum definitions (`RiskLevel`, `ToolAvailability`, `ResponseFormat`). |
| `catalog.py` | `ToolCatalog` managing canonical core tools, bridging legacy tools from `tools.registry._REGISTRY`, and resolving aliases. |
| `core_tools.py` | Implementations of the 9 canonical core tools (`fs.read`, `fs.edit`, `fs.write`, `shell.bash`, `search.glob`, `search.grep`, `task.todo`, `task.delegate`, `user.ask`). |
| `validator.py` | `Validator` performing parameter alias normalization, required argument enforcement, workspace boundary checks, and shell security gating. |
| `permissions.py` | `PermissionPolicy` enforcing runtime modes (`auto`, `plan`, `safe`), risk score thresholds, and user confirmations. |
| `output.py` | `OutputShaper` formatting results into `concise`, `normal`, or `detailed` views with line slicing and summaries; `OutputStore` for thread-safe external retention of oversized outputs. |
| `errors.py` | Standardized `ToolError` diagnostic payloads across 14 `ToolErrorCode` values, and `ErrorGuidance` offering cross-platform remediation suggestions. |
| `retry.py` | `RetryPolicy` classifying tool outcomes into `SAFE_TO_RETRY`, `RETRY_WITH_MODIFIED_INPUT`, `DO_NOT_RETRY`, `ASK_USER`, and `ESCALATE`. |
| `search.py` | `ToolSearch` providing fast token and stem-based lexical discovery for specialized tools outside the core 9 working set. |
| `executor.py` | `ToolExecutor` coordinating the complete execution lifecycle, timing, event emission to `EventBus`, and exception handling. |
| `batch.py` | `ToolBatchExecutor` formal interface (declared deferred per Prompt 5 spec). |
| `linter.py` | `ToolSpecLinter` validating completeness, example quality, schema integrity, and description lengths of all registered tools. |
| `evaluation.py` | `ToolEvaluationSuite` providing standard development and held-out benchmark tasks to assess tool ergonomics and discovery accuracy. |

---

## 4. The 9 Canonical Core Tools

HERMES 2.x standardizes on 9 foundational core tools that form the default active prompt context:

| Tool Name | Category | Primary Purpose | Risk Level | Idempotent | Canonical Aliases |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `fs.read` | `fs` | Read file contents or bounded line ranges (`start_line`, `end_line`) | `READ_ONLY` (0.1) | Yes | `read_file`, `read`, `view_file` |
| `fs.edit` | `fs` | Exact surgical string replacement with occurrence validation | `LOW` (0.3) | No | `edit`, `edit_file`, `replace_file_content` |
| `fs.write` | `fs` | Atomic file creation or complete overwrite with parent creation | `MEDIUM` (0.4) | Yes (deterministic) | `write_file`, `write` |
| `shell.bash` | `shell` | Sandboxed shell command execution under 15 security gates | `HIGH` (0.7) | No | `bash_exec`, `bash`, `shell`, `exec_command` |
| `search.glob` | `search` | Find workspace files matching glob patterns (e.g. `**/*.py`) | `READ_ONLY` (0.1) | Yes | `glob`, `list_directory`, `list_dir` |
| `search.grep` | `search` | Regex/text content search returning matching lines with context | `READ_ONLY` (0.1) | Yes | `grep`, `search_files` |
| `task.todo` | `task` | Manage visible planned checklist items without state mutation | `READ_ONLY` (0.1) | Yes | `todo` |
| `task.delegate` | `task` | Formal contract for subagent delegation (deferred to Prompt 10) | `LOW` (0.2) | No | `delegate` |
| `user.ask` | `user` | Solicit clarifying answers or multiple-choice inputs from user | `READ_ONLY` (0.1) | No | `ask_user`, `ask` |

---

## 5. Context Optimization & Token Compression

In previous versions, registering new tools directly bloated the system prompt for every turn. In HERMES 2.x:
- **Core Working Set:** Only the 9 core tools are injected into the active prompt schema, consuming only ~1,133 tokens (OpenAI format).
- **Tool Search on Demand:** Specialized tools (git operations, web fetch, memory, vision) are discovered dynamically via `ToolSearch` using a lightweight 120-token search interface.
- **Quantified Reduction:**
  - Full catalog schema size: 14,438 bytes (~3,609 tokens)
  - Core working set schema size: 4,534 bytes (~1,133 tokens)
  - **Net Reduction:** **68.61% token reduction per model turn** (~2,476 tokens saved per turn).

---

## 6. Standardized Error Payloads & Remediation Guidance

When a tool fails, the model receives a structured `ToolError` representation:
```json
{
  "error": true,
  "code": "VALIDATION_FAILED",
  "what_failed": "Validation of parameters for fs.read failed",
  "why_it_failed": "File path 'missing.txt' does not exist in workspace",
  "what_was_not_changed": "Workspace filesystem was not modified",
  "actionable_guidance": "Use search.glob or search.grep to verify the correct filename before reading."
}
```

### Platform-Aware Command Guidance
`ErrorGuidance` detects command incompatibilities (such as running Linux-specific commands on Windows):
- `wc` on Windows: Suggests PowerShell `(Get-Content file | Measure-Object -Line).Lines` or `fs.read`.
- `ls` / `dir`: Directs to `search.glob`.
- `grep` / `findstr`: Directs to `search.grep`.
- `touch`: Suggests `fs.write`.

---

## 7. Security Gates & Workspace Containment

All tool executions are governed by strict security policies before any OS interaction:
1. **Workspace Boundary Enforcement:** Paths are verified via `_resolve_safe_path`. Any path escaping the workspace (e.g. `../../etc/passwd` or absolute paths outside the designated root) triggers immediate `PATH_OUTSIDE_WORKSPACE` denial.
2. **15 Shell Security Gates:** Inherited directly from `tools/security.py`, blocking dangerous commands (e.g. `rm -rf /`, `mkfs`, raw partition manipulation, fork bombs).
3. **Execution Modes:**
   - `safe` mode: Blocks all `shell.bash` executions and any tool with risk score > 0.5.
   - `plan` mode: Blocks all mutations (`fs.edit`, `fs.write`, `shell.bash`).
   - `auto` mode: Permits execution under standard confirmation and validation rules.

---

## 8. Output Shaping & External Storage Engine

To prevent context overflow from large command outputs or file reads:
1. **Response Formats:** Callers can request `concise` (truncated summary), `normal` (balanced view), or `detailed` (full content up to buffer limit).
2. **Line Slicing:** Files and command outputs support `start_line`, `end_line`, and `max_lines` slicing.
3. **External Output Store (`OutputStore`):** Outputs exceeding buffer thresholds are retained in thread-safe external memory with unique content-addressable IDs (`store:<hash>`). Agents can inspect slices or search through stored content without re-executing expensive operations.

---

## 9. Integration with AgentLoop & StateStore

The Tool Platform integrates directly with the Prompt 4 `AgentLoop` and Prompt 3 `EventBus`:
- `core/agent_loop/actions.py` routes all tool actions through `tool_catalog`, `Validator`, `PermissionPolicy`, and `ToolExecutor`.
- The executor emits canonical events:
  - `TOOL_STARTED`: Captures tool name, input arguments, execution ID, and timestamp.
  - `TOOL_COMPLETED`: Captures duration, shaped output, and success status.
  - `TOOL_FAILED`: Captures structured `ToolError` and duration.
  - `TOOL_CANCELLED`: Emitted when mission cancellation or timeout interrupts execution.
- Events reduce deterministically into `StateStore`, updating the TUI in real time with zero renderer side effects.

---

## 10. Backward Compatibility & Migration Strategy

Legacy tools continue to operate seamlessly:
- All tools in `tools/registry.py` are automatically bridged into `ToolCatalog` with generated schemas and risk ratings.
- Parameter aliases are mapped bidirectionally (e.g., `file_path` and `TargetFile` are mapped to `path`).
- Legacy tool names (`read_file`, `write_file`, `bash_exec`, etc.) resolve directly to canonical core implementations.
- Existing test suites remain 100% functional without modification.
