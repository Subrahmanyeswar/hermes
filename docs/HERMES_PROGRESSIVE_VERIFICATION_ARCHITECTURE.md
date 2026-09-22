# HERMES Progressive Verification + Repair Architecture
======================================================

**Module:** `core.progressive_verifier`  
**Date:** September 1, 2026  
**Status:** PRODUCTION READY  

---

## 1. 6-Level Verification Hierarchy

```
  LEVEL 0 ──► STRUCTURAL VALIDATION (Files exist, non-empty, symbols exist)
  LEVEL 1 ──► SYNTAX VALIDATION (AST parsing check, py_compile)
  LEVEL 2 ──► TARGETED TESTS (Unit test execution for modified scope)
  LEVEL 3 ──► INTEGRATION VERIFICATION (Service and component interaction)
  LEVEL 4 ──► FULL VERIFICATION (Full test suite, build, lint when required)
  LEVEL 5 ──► ACCEPTANCE VERIFICATION (Phase 12 criteria verification with evidence)
```

---

## 2. Invariant Rules

1. **Implementation success != Verification success.**
2. **Verification success != Mission success.** (Phase 12 remains the final authority).
3. **Cheap checks first:** Never run heavy tests if syntax parsing fails.
4. **Environment failures are never treated as code bugs.**
5. **Every repair must be re-verified.**
