# HERMES — PERSISTENCE & DATA INTEGRITY INVENTORY
## Gate 15 Comprehensive Subsystem Persistence Inventory

**Generated**: September 3, 2026  
**Status**: **COMPLETE & VERIFIED**  

| Store Name | Path / Module | Database / Storage Type | Owner | Writers | Transaction Mechanism | Atomicity Guarantees |
|---|---|---|---|---|---|---|
| **MissionExecutionState** | `core/event_bus.py (ExecutionStateStore) & core/mission_runner.py` | `In-Memory Event-Derived State + Checkpoint JSON` | `MissionRunner / EventBus` | `EventBus.apply_event` | `Event-Driven Monotonic Sequencer` | Atomic event application with terminal state locking |
| **CompletionLedger** | `core/mission_completion.py` | `Structured In-Memory Ledger + Mission Evaluation Log` | `MissionCompletionEvaluator` | `CompletionLedger.update_criterion` | `Deterministic Criterion Ledger` | All criteria must be SATISFIED + PASSED for COMPLETE verdict |
| **WorkspaceIndexStore** | `core/workspace_indexer.py (.hermes/workspace_index.db)` | `SQLite3 (WAL mode)` | `WorkspaceIndexer / WorkspaceRetriever` | `WorkspaceIndexer._index_file_internal` | `SQLite Transactions with ContextManager (_get_conn)` | ACID transactional commits; quick_check integrity validation |
| **TrajectoryMemory** | `memory/trajectory_memory.py (.hermes/trajectories.json)` | `Atomic JSON File Store` | `TrajectoryMemory` | `TrajectoryMemory.record_trajectory` | `Atomic write via temporary file + atomic rename` | Atomic POSIX/Windows rename prevents partial records |
| **TelemetryCollector** | `core/telemetry.py (.hermes/telemetry.json)` | `JSON Observability Log` | `TelemetryCollector` | `TelemetryCollector.record` | `Append-only observability logging` | Non-authoritative (state is never reconstructed from telemetry) |
