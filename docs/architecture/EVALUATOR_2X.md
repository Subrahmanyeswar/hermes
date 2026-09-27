# HERMES 2.x Evaluator Architecture (T2 Critic & T3 Judge)

## Executive Summary
This document specifies the internal architecture, packet contracts, and behavioral boundaries of the T2 Independent Critic and T3 Supreme Judge.

---

## 1. T2 Independent Critic
### Purpose
An independent, skeptical evaluator that assesses whether a proposed change satisfies the requirement without introducing regressions, syntax defects, or unhandled edge cases.

### Bounded Evaluation Packet
The packet sent to T2 Critic contains:
- `goal`: High-level mission goal (truncated to 400 chars).
- `requirement`: Targeted requirement description (truncated to 400 chars).
- `verification_checks`: Summarized results of deterministic checks.
- `diff_excerpt`: Unified git diff (truncated to 2500 chars).
- `notes`: Relevant context notes.

### Structured Output Schema
T2 Critic emits strictly parsed JSON:
```json
{
  "approved": true,
  "confidence": 0.95,
  "critique": "All deterministic checks passed and implementation covers edge cases.",
  "identified_risks": [],
  "suggested_action": "Proceed to next requirement."
}
```

---

## 2. T3 Supreme Judge
### Purpose
The authoritative final arbiter for high-risk disputes, persistent disagreements between T1 and T2, or stalled repairs.

### Constitutional Fact Invariant
> **CONSTITUTIONAL RULE:** T3 Judge is strictly forbidden from approving or marking passed any requirement where objective environment verification failed.

If a model response attempts to approve a change that failed deterministic verification, the harness automatically overrules the decision:
```python
if has_failed_facts and decision == "APPROVE":
    decision = "REJECT"
    rationale = "OVERRULED BY FACT INVARIANT: T3 Judge cannot approve when objective facts failed."
```

### Binding Directives
T3 issues binding directives:
- `APPROVE`: Validates satisfaction of requirement.
- `REJECT`: Directs T1 to perform specific surgical repair.
- `ESCALATE_TO_USER`: Pauses mission and queries user for clarification.
- `WAIVE_OPTIONAL_REQUIREMENT`: Waives non-critical requirement with audit trail.
