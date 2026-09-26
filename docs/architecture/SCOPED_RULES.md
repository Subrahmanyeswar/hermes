# HERMES 2.x Path-Scoped Rules Architecture

## 1. Motivation

Project-wide coding standards, framework idioms, and subsystem guidelines should not compete for context window when irrelevant. For example:
- React component rules should only load when touching frontend files (`src/frontend/**`).
- Migration guidelines should only load when modifying database schemas.
- Linter and type check guidelines should apply when editing Python files (`**/*.py`).

HERMES 2.x implements **Path-Scoped Rules** in `.hermes/rules/` with deterministic precedence and lazy body loading.

---

## 2. Scope Granularity & Precedence Hierarchy

When multiple rules match an active file, they are ordered deterministically by specificity and priority score:

```
Score   Scope Type       Pattern Example              Description
500     file_specific    src/auth/login.py            Exact file match
400     subsystem        src/backend/auth/**          Nested subsystem directory
300     directory        src/frontend/**, tests/**    Top-level directory
200     language         **/*.py, **/*.tsx            File extension glob
100     general          *                            Catch-all
```

Precedence Formula:
$$\text{Final Score} = \text{Scope Specificity Score} + \text{Priority Integer}$$

---

## 3. Cross-Platform Matching & Deduplication

1. **Path Normalization**:
   Windows paths with backslashes (`src\backend\auth\login.py`) are normalized to workspace-relative forward slashes (`src/backend/auth/login.py`) before glob translation.
2. **Recursive Globs**:
   `**` matches zero or more directory segments recursively, ensuring cross-platform predictability.
3. **Deduplication**:
   If an agent touches 10 Python files in a single turn, the matching `python.md` rule is loaded and included exactly once in `SCOPED_RULES`.
4. **Dynamic Context Eviction**:
   When active working files shift from frontend to backend during long-running missions, frontend scoped rules are automatically evicted from subsequent ContextPacks to conserve budget.
