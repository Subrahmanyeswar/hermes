# HERMES 2.x Deterministic Verification Engine (Prompt 11)

## Executive Summary
The HERMES 2.x Verification Subsystem provides deterministic, reproducible validation of acceptance checks against durable evidence. It completely replaces heuristic string-matching and legacy keyword checks with robust environment verifiers.

---

## 1. Core Invariants
1. **Deterministic & Hermetic:** Evaluating the same evidence bundle with the same verifier produces the exact same verdict across machines and platforms.
2. **Confined Static Analysis:** Code structure is analyzed via Python AST (`ast.parse`) without executing untrusted arbitrary code in the host process.
3. **Fingerprinted Evaluation Cache:** Evaluation results are cached by SHA-256 fingerprint:
   $$\text{Fingerprint} = \text{hash}(\text{check\_id}, \text{evidence\_digests})$$
   Avoiding redundant verification when no underlying artifacts have changed.
4. **Quarantine of Legacy Heuristics:** The Prompt 1 keyword verifier (`len(kw) > 4` in `core/quality_verifier.py`) is completely quarantined from the authoritative completion path.

---

## 2. Deterministic Verifier Adapters
HERMES 2.x includes specialized verifiers:
1. `FilesystemVerifier`:
   - Checks file existence, non-emptiness, size thresholds.
   - Verifies required regex or substring patterns.
   - Enforces absence of forbidden patterns.
2. `PythonAstVerifier`:
   - Validates syntax validity without executing code.
   - Verifies existence of required classes, functions, and async definitions.
   - Catches syntax errors statically with line number attribution.
3. `JsonSchemaVerifier`:
   - Validates JSON well-formedness and structural schema.
   - Enforces required keys and primitive data types.
4. `TestResultVerifier`:
   - Inspects test execution evidence (exit code == 0, failures == 0, passed count >= threshold).
5. `CompositeVerifier`:
   - Chains multiple verifiers in sequence with AND semantics.

---

## 3. Verification Verdicts
Every verification evaluation yields an authoritative verdict:
- `PASS`: All assertions satisfied by fresh, valid evidence.
- `FAIL`: One or more assertions objectively violated.
- `INCONCLUSIVE`: Evidence missing, corrupt, or insufficient to reach determination.
- `BLOCKED`: Environment or dependency failure prevented evaluation.
