# HERMES Phase 8 — Context Engine Walkthrough
==============================================

**Project:** HERMES vNext  
**Phase:** Phase 8 — Context Engine  
**Date:** September 1, 2026  
**Status:** COMPLETED & VERIFIED (146/146 Tests Passing)  

---

## 1. Executive Summary

Phase 8 introduces a deterministic, token-budgeted **Context Engine** that assembles task-focused context packs before passing prompts to LLMs. It consumes Phase 7 workspace retrieval, filters project memory by relevance, bounds domain skills, protects hard constraints, deduplicates content, and reserves generation headroom.

---

## 2. Before vs. After Example

### User Query:
`"Fix authentication token validation in backend/auth.py and run test_auth.py"`

### Legacy Workflow (Unfiltered Dump):
- Raw workspace file list (100 files dumped).
- All 15 historical memory facts dumped.
- Full unbudgeted skill docs.
- **Prompt Size:** ~2,111 tokens.
- **Risk:** High prompt pollution and VRAM pressure on RTX 3050 6GB.

### Phase 8 Context Engine Workflow:
- Phase 7 retrieves `backend/auth.py` and paired `tests/test_auth.py`.
- Memory facts filtered by keyword overlap (only auth-related facts retained).
- Targeted `python-dev` skill loaded and bounded.
- Generation headroom strictly reserved for DeepSeek-R1 output.
- **Prompt Size:** ~1,742 tokens (17.5% reduction with higher density).
- **Assembly Latency:** 0.14 ms.

---

## 3. Test Verification Suite

All 146 unit, integration, and security tests passed:
- `tests/test_context_engine.py` (5 tests):
  1. `test_context_item_token_estimation` — PASSED
  2. `test_context_ranking_hard_required_priority` — PASSED
  3. `test_context_budgeter_enforces_limit_and_reserve` — PASSED
  4. `test_context_deduplication` — PASSED
  5. `test_context_engine_full_pack_assembly` — PASSED
- **Total Test Suite:** **146 passed / 0 failed in 7.66s**

---

## 4. Rollback Instructions

To roll back to legacy prompt concatenation without code changes:
Set `CONTEXT_ENGINE_ENABLED=false` in `.env` or system environment variables.
