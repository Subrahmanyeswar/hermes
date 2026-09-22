# HERMES Gate 11 — Context Pipeline Map & Architecture Audit

## 1. Context Pipeline Diagram

```
USER REQUEST (CLI / API / Webhook)
       │
       ▼
MISSION PLANNER / CONTROLLER (`core/mission_runner.py`, `core/orchestrator.py`)
       │  [Sanitization, Intent Classification, Reasoning Budget]
       ▼
ACTIVE TASK DEFINITION (`core/orchestrator.py`)
       │
       ├──────────────────────────────────────────────┐
       ▼                                              ▼
WORKSPACE MANAGER (`core/workspace.py`)       MEMORY WORKER (`memory/extractor.py`)
       │  [Boundary Check, Skeleton Cache]            │  [Key-value / Episodic Facts]
       ▼                                              ▼
WORKSPACE INDEXER (`core/workspace_indexer.py`)  FILTERED MEMORY
       │  [SQLite Schema, AST Symbols, Imports]       │
       ▼                                              │
WORKSPACE RETRIEVER (`core/workspace_retriever.py`)   │
       │  [Multi-Signal Ranking, Dependency Hop, Tests]│
       ▼                                              ▼
CONTEXT ENGINE (`core/context_engine.py`) ◄───────────┴── TASK STATE (`TASK_STATE`)
       │
       ├─► CONTEXT RANKER (`ContextRanker.rank`)
       │     [Hard Required First, Relevance Score Descending]
       │
       ├─► CONTEXT BUDGETER (`ContextBudgeter.budget`)
       │     [Max Token Cap, Headroom Reserve, SHA256 Deduplication]
       │
       ▼
CONTEXT PACK (`core/context_engine.py:ContextPack`)
       │
       ├─► SYSTEM PROMPT ([SYSTEM_CORE] + [WORKSPACE] + [MEMORY] + [TASK_STATE] + [SKILL])
       ├─► USER MESSAGE (Structured Task Format)
       │
       ▼
PLANNER / INFERENCE ENGINE (T1 / Ollama / Fast Model Execution)
```

---

## 2. Boundary Identification & Component Map

| Pipeline Boundary | Producer | Consumer | Data Structure | Ranking / Scoring Info | Provenance | Freshness Mechanism | Failure Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. User Request $\rightarrow$ Mission Task** | User Interface / Orchestrator | Mission Planner / Orchestrator | `Task` object, `task_text: str` | Intent complexity score (0.0–1.0) | User input string | Ephemeral per turn | Rejects empty strings, sanitizes control chars |
| **2. Mission $\rightarrow$ Workspace Root** | Orchestrator | `WorkspaceManager` | `workspace_root: Path` | N/A (root lock) | Locked workspace path | Validates root directory existence on disk | Raises `WorkspaceBoundaryError` if outside boundary |
| **3. Workspace $\rightarrow$ Index Store** | Filesystem | `WorkspaceIndexer` | SQLite DB (`files`, `symbols`, `imports`) | Content hash (SHA256), mtime | Ground-truth disk files | Incremental mtime + SHA256 hashing; PRAGMA check | Quarantines corrupt DB, rebuilds cleanly from disk |
| **4. Task Query $\rightarrow$ Workspace Retriever** | Orchestrator / ContextEngine | `WorkspaceRetriever` | `query: str`, `List[RetrievedFile]` | Multi-signal score: Mention (10.0), Filename (4.0), Symbol (3.0), Test (3.5), Dep (2.5) | SQLite index queries | Real-time SQLite query against latest index | Falls back to empty list on zero matches |
| **5. Dependency / Test Expansion** | `WorkspaceRetriever` | `WorkspaceRetriever` | `imports_by_file`, `RetrievedFile` | 1st hop (2.5), 2nd hop (1.8), Test pairing (3.5) | AST `imports` table & file stem pairing | Dynamically traversed from top candidate files | Bypasses unresolvable imports gracefully |
| **6. Memory Retrieval** | Episodic Memory | `ContextEngine` | `memory_context: str` | Keyword overlap score ($10.0 + \text{overlap} \times 2.0$) | Memory background worker | Evaluated per request; cannot override disk truth | Falls back to empty string if no memory exists |
| **7. Task State Retrieval** | Orchestrator / DAG | `ContextEngine` | `task_state: str` | Hardcoded relevance score ($40.0$) | Mission runner DAG lifecycle | Checked against active running task ID | Ignored if no task state provided |
| **8. Context Pack Assembly** | `ContextEngine` | `ContextPack` | `ContextItem` list, `ContextPack` | Hard-required flag + Float relevance score | Multi-source aggregate | Fresh assembly on every model call (zero stale cache) | Drops lowest-scoring non-required items on budget breach |
| **9. Token Budgeting & Deduplication** | `ContextBudgeter` | Inference Engine | `ContextPack.system_prompt`, `user_message` | Headroom reserve ($1024$ tokens), SHA256 content dedup | String token estimation (~4 chars/token) | Real-time byte calculation | Drops over-budget non-required items with logging |
