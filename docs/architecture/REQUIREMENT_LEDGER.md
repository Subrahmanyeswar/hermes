# Requirement Ledger & Acceptance Contract Engine

## Overview

The **Requirement Ledger** is the authoritative ledger governing the status of all mission requirements and their acceptance criteria in HERMES 2.x. It replaces ungrounded model self-evaluations with an evidence-driven verification ledger.

## The Acceptance Contract: "No Evidence = No Verified"

In HERMES 2.x, an agent cannot self-certify completion merely by claiming "Everything works." The transition from `PENDING` / `IN_PROGRESS` to `VERIFIED` is governed by the [`AcceptanceManager`](file:///c:/Users/SUBBU/Downloads/hermes/core/planning/acceptance.py):

1. **Every requirement must link to concrete AcceptanceChecks**.
2. **Every AcceptanceCheck requires physical evidence references** (e.g. test execution output, compiler logs, structural verifier diffs).
3. **If a check is marked `PASS` but contains no evidence refs, status remains `IN_PROGRESS`**.
4. **Any critical check failure immediately blocks requirement verification**, transitioning the requirement to `FAILED`.

## Stale Evidence Detection & Regression Reopening

Acceptance checks track file dependencies and version fingerprints:
```python
@dataclass
class AcceptanceCheck:
    check_id: str
    requirement_id: str
    description: str
    critical: bool = True
    status: AcceptanceCheckStatus = AcceptanceCheckStatus.NOT_RUN
    evidence_refs: List[str] = field(default_factory=list)
    source_file_versions: Dict[str, str] = field(default_factory=dict)
```

When any file cited in `source_file_versions` is subsequently modified (e.g., via `fs.edit`, `fs.write`, or build steps):
1. `AcceptanceLedger.mark_stale_for_files(modified_files)` invalidates associated checks (`status = NOT_RUN`, evidence cleared).
2. Previously `VERIFIED` requirements that depended on those checks are automatically **reopened** to `PENDING` or `IN_PROGRESS`.
3. An audit trail records the regression, notifying the agent and user that re-verification is required.

## Explicit Waiver Mechanism

When a requirement cannot or should not be satisfied (e.g. out of scope, environment constraint, user preference), it cannot be silently ignored:
- Requirements must be explicitly waived via `waive_requirement(requirement_id, reason, actor)`.
- The ledger records the `waiver_actor`, `waiver_reason`, and `waiver_timestamp`.
- The requirement transitions to `RequirementStatus.WAIVED`, allowing goal completion without compromising audit integrity.

## Todo vs. Requirement Invariant

- `Todo`: Small, mutable, mechanical work item (e.g., "Add import statement", "Run linter").
- `Requirement`: Contractual feature or specification outcome.
- **Rule**: Completing a Todo (`TodoStatus.DONE`) does **not** verify the Requirement. Verification requires acceptance check evidence.
