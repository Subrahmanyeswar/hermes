# HERMES Tool-Call Reliability Hardening Walkthrough
=====================================================

**Project:** HERMES vNext  
**Phase:** Tool-Call Reliability Hardening  
**Date:** September 1, 2026  
**Status:** COMPLETED & VERIFIED (135/135 Tests Passing)  

---

## 1. Root Cause of the `{}` Problem

Historically, when DeepSeek-R1 produced an empty argument dictionary `{}` for a tool requiring required fields (e.g. `write_file({})`), the pipeline lacked deterministic pre-execution normalization and schema enforcement. As a result, the unvalidated dictionary would either silently fail inside the tool executor or trigger unconstrained 180s timeout loops.

---

## 2. Architectural Solution: Layered Tool Reliability

```
                         MODEL TOOL REQUEST
                                 │
                                 ▼
                     Deterministic Normalizer
                   (Alias mapping, trim, defaults)
                                 │
                                 ▼
                         Schema Validator
                 (Pydantic required fields, types)
                                 │
                         ┌───────┴───────┐
                         │               │
                       VALID          INVALID
                         │               │
                         │               ▼
                         │         [Repair Engine]
                         │         1. Deterministic extraction
                         │         2. T1 structured correction (L1 Budget)
                         │         3. T2 escalation
                         │               │
                         │               ▼
                         │        Re-validate Schema
                         │               │
                         └───────┬───────┘
                                 │
                                 ▼
                           Security Gate
               (Workspace boundary, path traversal, commands)
                                 │
                         ┌───────┴───────┐
                         │               │
                       PASS            FAIL
                         │               │
                         ▼               ▼
                   Tool Execution     REJECTED
```

---

## 3. Verification & Regression Suite

All 135 unit, integration, and security tests passed:
- `tests/test_tool_reliability.py` (10 tests):
  1. `test_empty_arguments_on_write_file_fails_validation` — PASSED
  2. `test_alias_normalization` — PASSED
  3. `test_default_injection_for_list_directory` — PASSED
  4. `test_contextual_path_repair` — PASSED
  5. `test_type_validation_failure` — PASSED
  6. `test_path_traversal_security_blocked` — PASSED
  7. `test_forbidden_command_security_blocked` — PASSED
  8. `test_unknown_tool_rejection` — PASSED
  9. `test_t1_model_correction_recovery` — PASSED
  10. `test_feature_flag_rollback` — PASSED
- Full core test suite: **135 passed / 0 failed in 7.31s**

---

## 4. Rollback Instructions

To roll back to legacy tool processing without code changes:
Set `ROBUST_TOOL_VALIDATION_ENABLED=false` in `.env` or system environment variables.
