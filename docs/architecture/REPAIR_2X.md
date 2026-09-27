# HERMES 2.x T1 Self-Repair Subsystem (Prompt 11)

## Executive Summary
The HERMES 2.x T1 Self-Repair Subsystem allows the primary model (T1) to recover from execution and verification failures through bounded, guided iterations while preventing infinite retry loops and prompt bloat.

---

## 1. Core Invariants
1. **Strictly Bounded Iterations:** Maximum 2–3 repair attempts per acceptance check; global repair budget enforced.
2. **Immediate Stall Detection:** Cryptographic fingerprinting detects recurring identical failures across 2 consecutive attempts, immediately halting self-repair and triggering escalation:
   $$\text{Fingerprint} = \text{hash}(\text{failure\_class}, \text{target\_path}, \text{error\_message}, \text{exit\_code})$$
3. **Compact Diagnostic Observations:** Injects concise, highly actionable root-cause observations into T1 context rather than regurgitating massive terminal logs.
4. **Canonical Event Tracing:** Emits `REPAIR_ATTEMPTED` and `REPAIR_STALLED` to maintain causal auditability.

---

## 2. Failure Classification
HERMES 2.x deterministically classifies failures into 18 standardized categories:
- `SYNTAX_ERROR`: Code fails AST parsing.
- `TYPE_ERROR`: Type mismatch or missing attribute.
- `TEST_FAILED`: Test runner reported failure or non-zero exit code.
- `BUILD_FAILURE`: Compilation or packaging error.
- `MISSING_ARTIFACT`: Required file missing from disk.
- `ASSERTION_FAILED`: Deterministic check condition unmet.
- `SCHEMA_VIOLATION`: JSON/YAML structure invalid.
- `MISSING_DEPENDENCY`: ImportError or ModuleNotFoundError.
- `PERMISSION_VIOLATION`: Unauthorized operation.
- `TIMEOUT`: Execution timed out.
- `ENVIRONMENT_ERROR`: Tool execution failure.

---

## 3. Lifecycle Flow
$$\text{Check Fails} \to \text{Classify Failure} \to \text{Check Stall \& Budget} \to \begin{cases} \text{Stalled/Exhausted} \to \text{Escalate to T2} \\ \text{Budget OK} \to \text{T1 Guided Repair} \end{cases}$$
