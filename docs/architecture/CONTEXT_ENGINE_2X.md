# CONTEXT ENGINE 2.x ARCHITECTURE SPECIFICATION

**Branch:** `hermes-2.x`  
**Milestone:** Prompt 7 — Context Engine 2.x  
**Status:** COMPLETE / GREEN  

---

## 1. Core Mission & Architectural Anchors

Long-running agentic coding missions degrade when the agent accumulates unbounded historical tool logs, redundant file reads, and superseded reasoning chains. Prompt 7 establishes **Context Engine 2.x** (`core/context/`), a model-agnostic, state-aware, cache-aware context coordinator for HERMES missions.

The fundamental contract is:
> **Give T1 the smallest high-signal context that is sufficient for the next decision while preserving enough state, evidence, history, and references to continue the mission correctly.**

```
                     AUTHORITATIVE STATE (StateStore)
                                    │ (Truth)
                                    ▼
                          ┌───────────────────┐
                          │   ContextEngine   │
                          └─────────┬─────────┘
                                    │ (Projection)
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   ContextBudgeter           Context Sources           ToolResultStore
(Headroom & Partitions)      (Memory/Files/Ev)      (History & Retrievability)
          │                         │                         │
          │                         │                         ▼
          │                         │              ExternalizedOutputStore
          │                         │              (File-backed + SHA-256)
          │                         │                         │
          └─────────────────────────┼─────────────────────────┘
                                    ▼
                               ContextPack
                     (Strict Canonical Ordering)
                                    │
                                    ▼
                         CacheAwarePromptBuilder
                     (STABLE_PREFIX vs DYNAMIC)
                                    │
                                    ▼
                                   T1
```

---

## 2. Distinction Between the Four Survival Layers

A critical architectural principle of HERMES 2.x is recognizing the differing semantics of information survival:

| Layer | System Component | Durability & Role |
| :--- | :--- | :--- |
| **STATE** | `StateStore` (`core/runtime_state/`) | **Authoritative truth**: Never lost, immutable event-sourced state. |
| **MEMORY** | Knowledge Base (`docs/`, `memory/`) | **Durable knowledge**: Architectural decisions, patterns, conventions. |
| **TOOL RESULTS** | `ToolResultStore` + `ExternalizedOutputStore` | **Retrievable artifacts**: Logical history, external file-backed outputs. |
| **CONTEXT** | `ContextPack` (`core/context/`) | **Ephemeral projection**: Budgeted, high-signal slice for the current turn. |

---

## 3. The 11 Canonical Sections

Sections in every assembled `ContextPack` appear in this strict order:
1. `SYSTEM`: Minimal invariant system instructions for T1.
2. `PROJECT_RULES`: Invariant project rules, standards, and guidelines.
3. `SCOPED_RULES`: Rules scoped to active directories, components, or tasks.
4. `CURRENT_GOAL`: Unambiguous primary user objective and success conditions.
5. `ACTIVE_REQUIREMENTS`: Itemized requirement statuses.
6. `RELEVANT_FILES`: Line-addressable active file snippets.
7. `RECENT_CHANGES`: Meaningful modifications made during the mission.
8. `RELEVANT_MEMORY`: Architectural decisions, known blockers, conventions.
9. `ACTIVE_TOOLS`: Core 9 tool schemas + mission-discovered tools.
10. `EVIDENCE`: Deterministic verification evidence (`PASS`/`FAIL` hashes).
11. `RECENT_OBSERVATIONS`: Bounded recent tool execution observations.

---

## 4. Graduated 3-Tier Context Pressure Management

Instead of immediately compacting the entire session whenever token counts grow, the engine applies the least destructive intervention required to restore healthy budget utilization:

```
Context Token Pressure
        │
        ├── Level 1: Light (< 75% Usable)
        │     └── Tool Result Trimming & Externalization (Cheap, zero LLM calls)
        │
        ├── Level 2: Medium (75% - 85% Usable)
        │     └── Microcompaction (Collapse duplicate reads & passing test logs)
        │
        └── Level 3: Heavy (> 85% Usable / Emergency)
              └── Full Compaction (Structured CompactionSummary + Fallback snapshot)
```

### Level 1: Tool Result Trimming (`trim_tool_results`)
- Strips bulky inline tool output older than 2 turns.
- Preserves the `summary` and `external_ref`.
- Execution time: **0.00 ms** (sub-microsecond memory pointer swap).

### Level 2: Microcompaction (`microcompact`)
- Collapses repeated reads of the same file into a single reference pointer.
- Compresses passing test logs into single-line summaries.
- Execution time: **0.00 ms**.

### Level 3: Full Compaction (`full_compact`)
- Generates a canonical `CompactionSummary` preserving:
  - `mission_goal`
  - `important_decisions`
  - `files_modified`
  - `known_failures` and active `blockers`
  - `important_evidence`
  - `next_action`
- Retains invariant system and project rules.
- Replaces transient history with the compact summary item.
- Execution time: **0.02 ms**.

---

## 5. File Freshness & Concurrency Guards

- Integrates directly with Prompt 6's `FileIdentityCache`.
- File snippets retain path, line ranges, and SHA-256 content hashes.
- If a file on disk is modified externally, `FreshnessChecker.check_file_freshness` detects the change and marks the context item `ContextFreshness.STALE`.
- The `ContextPackValidator` prevents stale file snippets from being presented as current truth.

---

## 6. Prompt Caching Partitioning

`CacheAwarePromptBuilder` segments the prompt into:
1. **`STABLE_PREFIX`** (`SYSTEM`, `PROJECT_RULES`, `ACTIVE_TOOLS`): Invariant turn-to-turn. Zero random timestamps or unordered dictionaries. Marked `CACHE_PREFERRED` on providers supporting KV caching.
2. **`SEMI_STABLE`** (`SCOPED_RULES`, `RELEVANT_MEMORY`): Slowly changing architectural context.
3. **`DYNAMIC_SUFFIX`** (`CURRENT_GOAL`, `RELEVANT_FILES`, `EVIDENCE`, `OBSERVATIONS`): Dynamic per-turn state.

**Provider Independence:** If `cache_supported=False` (e.g. NVIDIA NIM), the prompt builder operates seamlessly with zero warnings or errors.
