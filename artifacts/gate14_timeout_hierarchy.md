# HERMES — TIMEOUT HIERARCHY & DEADLINE PROPAGATION MODEL
## Gate 14 Logical Architecture

```mermaid
graph TD
    User([User Request / Watchdog]) -->|Deadline: 1800s default| Mission[Mission Scope]
    
    Mission -->|Inherits Remaining Deadline| Kairos[KAIROS DAG Scheduler]
    Mission -->|Bounded 60s| MemoryWorker[Background Memory Manager]
    
    Kairos -->|min task_budget, remaining_mission| Task[Task Execution Scope]
    
    Task -->|Adaptive Budget: 45s-240s| T1[Tier 1 DeepSeek-R1 8B]
    Task -->|60s Default| T2[Tier 2 Qwen 8B Verifier]
    Task -->|180s Default| T3[Tier 3 OpenRouter Client]
    
    Task -->|Tool Timeout: 30s-120s| Tools[Tools Execution]
    Tools -->|SIGTERM -> 1.5s -> SIGKILL| Subprocess[OS Subprocess Tree]
    
    Task -->|30s Timeout| Verifier[Progressive Verification Engine]
    Task -->|Max 3 Attempts| Repair[Repair Engine]
    
    Mission -->|Mission Expiration| Cancel[CancellationController.cancel_mission]
    Cancel -->|Aborts All Active Operations| TerminalState[ExecutionStateStore: CANCELLED]
```

### Effective Deadline Propagation Rule:
`Effective Child Deadline = min(Configured Child Timeout, Parent Remaining Deadline)`

When the parent mission or task expires, `CancellationController.cancel_mission()` is immediately triggered, aborting in-flight child operations, terminating subprocess trees via `tools.shell_tools.terminate_active_subprocesses()`, and permanently locking the mission state to prevent late-result resurrection.
