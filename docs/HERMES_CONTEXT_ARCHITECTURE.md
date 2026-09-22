# HERMES Context Engine Architecture
====================================

**Module:** `core.context_engine`  
**Date:** September 1, 2026  
**Status:** PRODUCTION READY  

---

## 1. Core Classes & Data Models

### `ContextItem`
Encapsulates individual context units with metadata for ranking, budgeting, and telemetry:
- `id`: Stable identifier (e.g. `workspace:file:backend/auth.py`, `memory:fact_0`, `skill:python-dev`).
- `source`: `ContextSource` enum (`SYSTEM_CORE`, `USER_TASK`, `WORKSPACE_STRUCTURE`, `WORKSPACE_FILE`, `MEMORY`, `SKILL`, `TOOL_SCHEMA`, `TASK_STATE`).
- `content`: Exact text payload.
- `relevance_score`: Float ranking score (0.0 to 100.0).
- `is_hard_required`: Boolean flag (if True, item can never be dropped by the budgeter).
- `token_estimate`: Approximate token cost (~1 token per 4 characters).

### `ContextRanker`
Deterministically orders items:
1. Hard-required items first.
2. Optional items sorted by `relevance_score` descending.

### `ContextBudgeter`
Manages context ceiling and generation headroom:
- `available_budget = max_context_tokens - generation_reserve`
- Retains hard-required items unconditionally.
- Selects top-scoring optional items until available budget is filled.
- Deduplicates identical content hashes.

### `ContextPack`
Assembled structured package ready for model execution:
- Labeled sections: `[WORKSPACE]`, `[SYMBOL]`, `[MEMORY]`, `[SKILL]`, `[TASK STATE]`.
- Telemetry: `total_tokens`, `items_included`, `items_dropped`, `build_duration_ms`.
