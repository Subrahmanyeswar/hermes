# Goals Architecture 2.x

## Overview

In HERMES 2.x, a **Goal** represents the high-level objective requested by the user. Unlike legacy task sequences ("Task 1/7 → Evaluating..."), the Goal Architecture decouples user intent from mechanical tool executions. It decomposes the unstructured mission prompt into a directed acyclic graph (DAG) of testable requirements and acceptance contracts.

## Core Architectural Invariants

1. **State Invariant**:
   `User Request → GoalState → RequirementGraph → AcceptanceLedger → Evidence → ProgressState → Goal Completion`
2. **Separation of Concerns**:
   - `Goal`: What the user wants to achieve and why.
   - `Requirements`: The discrete capabilities, contracts, or properties that must be true for the goal to be satisfied.
   - `Acceptance Checks`: Concrete, testable verification steps with deterministic pass/fail criteria.
   - `Todos`: Actionable engineering work items (e.g., "Add CSS media query") supporting a requirement.
3. **Completion Rule**:
   `Todo DONE ≠ Requirement VERIFIED`
   `Requirement VERIFIED ≠ Goal COMPLETE`
   A Goal is complete if and only if:
   - All non-cancelled requirements are `VERIFIED` or explicitly `WAIVED`.
   - All critical acceptance checks have `PASS` status with active, non-stale evidence references.
   - There are zero unresolved blocking failures.

## GoalState Data Model

Located in [`core.runtime_state.models.GoalState`](file:///c:/Users/SUBBU/Downloads/hermes/core/runtime_state/models.py):

```python
@dataclass
class GoalState:
    goal_id: str
    mission_id: str
    title: str = ""
    description: str = ""
    user_request: str = ""
    explicit_constraints: List[str] = field(default_factory=list)
    explicit_preferences: List[str] = field(default_factory=list)
    clarifications: List[Dict[str, str]] = field(default_factory=list)
    success_condition: Optional[str] = None
    status: GoalStatus = GoalStatus.NOT_STARTED
    goal_version: int = 1
    blocked_reason: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
```

## Decomposition & Cycle Detection

The [`GoalDecomposer`](file:///c:/Users/SUBBU/Downloads/hermes/core/planning/decomposer.py) analyzes the user prompt and constraints to generate discrete `RequirementState` instances and corresponding `AcceptanceCheck` items.

### Topological Cycle Detection

Every requirement declares its prerequisites via `dependencies: List[str]`. Before any execution or plan formation, `GoalDecomposer.validate_dependencies()` executes depth-first search cycle detection. If a cycle such as $A \to B \to C \to A$ is detected, execution fails fast by raising `DependencyCycleError` (`REQUIREMENT_DEPENDENCY_CYCLE`), preventing infinite circular planning deadlocks.
