# Plan Mode Architecture

## Overview

**Plan Mode** allows HERMES 2.x to inspect the workspace, analyze requirements, and draft a structured implementation strategy before mutating any files or executing side-effecting commands.

## Safety Invariant: Strictly Non-Mutating

In Plan Mode, the agent is mathematically and operationally constrained from modifying the project state:
- **Allowed Safe Tools**:
  - `fs.read`: Read file contents, lines, and metadata.
  - `search.glob`: Find files and directory structure.
  - `search.grep`: Search file contents using regex.
  - `task.todo`: Formulate internal work items and task lists.
  - `user.ask`: Solicit user input or clarify specifications.
  - `tool_search`: Query tool catalog for available capabilities.
- **Prohibited Mutating Tools**:
  - `fs.write`: Blocked with `PlanModeViolationError` / `PLAN_MODE_MUTATION_DENIED`.
  - `fs.edit`: Blocked with `PlanModeViolationError` / `PLAN_MODE_MUTATION_DENIED`.
  - `shell.bash` (destructive/mutating): Commands with `rm`, `del`, `git commit`, `npm install`, `pip install`, or redirect operators (`>`, `>>`) are strictly blocked.

### Two-Layer Enforcement Gate

1. **PlanController Authorization**: Evaluates tool calls before execution via [`PlanController.authorize_tool_call()`](file:///c:/Users/SUBBU/Downloads/hermes/core/planning/plan_mode.py).
2. **Platform PermissionPolicy**: Enforced at the harness level via [`PermissionPolicy(mode="plan")`](file:///c:/Users/SUBBU/Downloads/hermes/tools/platform/permissions.py), guaranteeing zero side effects even if an action bypasses higher layers.

## Plan Lifecycle

A plan transitions through explicit lifecycle states:
```
DRAFT → REVIEW_REQUIRED → APPROVED → (STALE / SUPERSEDED)
                       ↘ REJECTED
```

1. **Proposal**: `PlanController.create_plan_proposal()` builds ordered execution steps (`PlanStep`) from the requirement DAG, sorting dependencies topologically.
2. **Review & Approval**: The plan is presented to the user or operator. Once confirmed, `approve_plan(actor)` transitions the plan to `APPROVED`.
3. **Execution Mode Transition**: Upon approval, the agent exits Plan Mode (`exit_plan_mode()`) and enters `EXECUTION_MODE`, unlocking mutation and build tools.
4. **Staleness Invalidation**: If requirements are added or modified during execution, `check_staleness()` marks the plan `STALE`, prompting a re-plan.

## Disk Persistence

Plan state is persisted to disk at:
`.artifacts/missions/<mission_id>/plan.json`
Ensuring full reproducibility and auditability across restarts.
