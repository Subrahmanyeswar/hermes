# HERMES 2.x Evidence Engine (Prompt 11)

## Executive Summary
The HERMES 2.x Evidence Engine implements a production-grade, append-only, durable evidence subsystem adhering to the fundamental invariant:
$$\text{AGENT CLAIM} \neq \text{EVIDENCE} \neq \text{VERIFICATION} \neq \text{GOAL COMPLETION}$$

Self-attestation by an LLM ("I created the file", "All tests passed") has zero evidentiary weight in HERMES 2.x. Only objective, physical environment observations and tool execution outputs are recorded as evidence.

---

## 1. Core Invariants
1. **Claims Are Not Evidence:** Model claims, subagent status reports, or user chat assertions are never treated as objective evidence.
2. **Deterministic Cryptographic Digests:** Every evidence record computes SHA-256 digests over inputs, outputs, file contents, and git diffs.
3. **Causal Traceability & Provenance:** Every evidence record is tied to its originating `agent_id`, `task_id`, `turn_id`, `tool_call_id`, and `worktree_id`.
4. **Append-Only Immutability:** Evidence records cannot be overwritten or mutated in place. If an environment mutation occurs, an invalidation event is emitted and new records are appended.
5. **Disk-Backed Persistence:** Stored under `.hermes/evidence/<mission_id>/<evidence_id>.json` to survive restarts and crashes.

---

## 2. Hierarchy of Evidence Trust Classes
Evidence in HERMES 2.x is categorized into strict trust tiers:
```
Tier 1: DIRECT_ENVIRONMENT_OBSERVATION (Highest: exit codes, disk files, AST trees)
Tier 2: TOOL_DERIVED_OBSERVATION       (Structured tool outputs, test metrics)
Tier 3: DERIVED_ASSERTION              (Composite evaluations)
Tier 4: SUBAGENT_REPORTED              (Handoff reports; requires re-verification)
Tier 5: MODEL_CLAIM                    (Zero trust; discarded from verification)
Tier 6: USER_ASSERTION                 (User input; requires verification)
```

---

## 3. Freshness & Invalidation
Evidence records transition through distinct freshness states:
- `FRESH`: Observation matches current disk and process state.
- `STALE`: A dependency or related file was modified after the observation was taken.
- `INVALIDATED`: Underlying physical artifact was modified, overwritten, or deleted.

The `EvidenceInvalidator` integrates directly with the workspace identity tracker to detect file mutations and cascade invalidations:
$$\text{FILE MODIFIED} \to \text{EVIDENCE INVALIDATED} \to \text{ACCEPTANCE CHECK REOPENED} \to \text{REQUIREMENT IN PROGRESS}$$

---

## 4. Key APIs
- `EvidenceRecord`: Authoritative dataclass representing an observed fact.
- `EvidenceBundle`: Collection of correlated evidence records supporting a check.
- `EvidenceStore`: Thread-safe, append-only storage engine with indexed lookups.
- `EvidenceCollector`: Extracts evidence from filesystem, tool runs, test executions, and subagent handoffs.
- `EvidenceInvalidator`: Scans workspace changes and invalidates stale evidence records.
