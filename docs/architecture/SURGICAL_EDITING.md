# HERMES 2.x — Surgical Editing Architectural Specification

**Status:** Authoritative Runtime Contract  
**Version:** HERMES 2.x (`Prompt 6`)  
**Anchor Baseline:** `3ce8f81` (`Prompt 2`)  
**State Architecture Baseline:** `712a84b` (`Prompt 3`)  
**Agent Loop Baseline:** `d68ecd7` (`Prompt 4`)  
**Tool Platform Baseline:** `1080eb2` (`Prompt 5`)  
**Reference Tag:** `v1.0.0-rc3` (`da30412b...`)  

---

## 1. Executive Mission & Core Invariants

In HERMES 1.x and many naive coding agents, code modifications frequently defaulted to whole-file overwrites or loose heuristic edits. When an agent attempted a 2-line change (such as updating a configuration timeout or modifying a single route handler), it would rewrite all 500 lines of the file. This introduced silent regressions: lost comments, normalized line endings (converting CRLF to LF across the entire file), broken indentation, corrupted formatting, and unintended modifications to unrelated functions.

Prompt 6 establishes **Surgical Editing** as the primary code mutation contract for HERMES 2.x. It enforces the fundamental rule:

```
old_string  ──►  exact match  ──►  unique match  ──►  atomic replacement
```

### The Invariants of Surgical Editing
1. **Zero Fuzzy Mutation:** `old_string` must match the file content character-for-character. No silent whitespace stripping, no indentation reformatting, and no target approximation.
2. **Ambiguity Rejection:** By default, `expected_occurrences = 1`. If `old_string` matches 0 times or >1 times, the edit is aborted without touching the disk.
3. **No Accidental Broad Rewrites:** A 2-line edit must produce a 2-line diff. Edits generating suspiciously broad diffs are blocked by `EDIT_SUSPICIOUS_LARGE_DIFF`.
4. **Stale File Protection:** Target files are tracked via `FileIdentityCache`. If a file was modified externally between the agent's read and its edit attempt, the edit is rejected with `EDIT_FILE_CHANGED`.
5. **Atomic Write & Rollback:** File writes are executed via temporary files, explicit `os.fsync`, and atomic renaming. If postcondition syntax validation (e.g. Python AST parsing) fails, the file is immediately rolled back to its original state.
6. **Platform-Aware Newline Preservation:** Editing a CRLF file on Windows or Linux preserves native CRLF line endings throughout the file.

---

## 2. The Edit Execution Lifecycle

Every execution of `fs.edit` executes the following transactional lifecycle:

```
                     ┌───────────────────────────────┐
                     │    fs.edit Request Inbound    │
                     └───────────────┬───────────────┘
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │     1. Security & Boundary    │
                     │    _resolve_safe_path() check │
                     └───────────────┬───────────────┘
                                     │ Safe path resolved
                                     ▼
                     ┌───────────────────────────────┐
                     │    2. Freshness Verification  │
                     │   file_identity_cache check   │
                     └───────────────┬───────────────┘
                                     │ File matches last read
                                     ▼
                     ┌───────────────────────────────┐
                     │    3. Exact Match Validation  │
                     │   count == expected_occurrences│
                     └───────────────┬───────────────┘
                                     │ Unique match confirmed
                                     ▼
                     ┌───────────────────────────────┐
                     │   4. Diff & Minimality Check  │
                     │  unified_diff & delta safety  │
                     └───────────────┬───────────────┘
                                     │ Minimality verified
                                     ▼
                     ┌───────────────────────────────┐
                     │       5. Atomic Write         │
                     │  tempfile -> fsync -> replace │
                     └───────────────┬───────────────┘
                                     │ Disk mutated atomically
                                     ▼
                     ┌───────────────────────────────┐
                     │  6. Postcondition Verification│
                     │   AST parse / JSON validation │
                     └───────┬───────────────┬───────┘
                             │ Valid         │ Syntax Error
                             ▼               ▼
                ┌──────────────────┐ ┌──────────────────┐
                │ 7. Success Emit  │ │ 8. Auto Rollback │
                │ Update Identity  │ │ Restore Original │
                │ Emit Observation │ │ Return Error     │
                └──────────────────┘ └──────────────────┘
```

---

## 3. Strict Occurrence Semantics

When the model calls `fs.edit`, the occurrence behavior is strictly governed by `expected_occurrences` (default: 1) and `replace_all` (default: False):

| Matches Found | `expected_occurrences` | `replace_all` | Outcome | Diagnostics Provided |
| :---: | :---: | :---: | :--- | :--- |
| **0** | 1 | False | **FAIL (`EDIT_TARGET_NOT_FOUND`)** | Guidance directs model to inspect current lines with `fs.read`. |
| **1** | 1 | False | **APPLY** | Minimal surgical replacement applied atomically. |
| **>1** | 1 | False | **FAIL (`EDIT_TARGET_NOT_UNIQUE`)** | Returns exact 1-based line numbers for all matches (e.g. `lines 14, 42, 88`). Guides model to include surrounding context lines. |
| **N** | N | False | **APPLY** | Applies replacement to exactly N occurrences. |
| **N** | M (M != N) | False | **FAIL (`EDIT_EXPECTED_COUNT_MISMATCH`)** | Reports actual count vs expected count. |
| **N** | Any | True | **APPLY** | Replaces all N occurrences across the file. |

---

## 4. Stale-Read Detection (`FileIdentityModel`)

The platform implements [`FileIdentity`](file:///c:/Users/SUBBU/Downloads/hermes/tools/platform/file_identity.py) and [`FileIdentityCache`](file:///c:/Users/SUBBU/Downloads/hermes/tools/platform/file_identity.py):
- When an agent reads a file using `fs.read`, the system records:
  - Absolute path & normalized path
  - File size (bytes)
  - Modification timestamp in nanoseconds (`mtime_ns`)
  - SHA-256 content hash
  - Detected encoding & newline style (`\r\n` vs `\n`)
- When `fs.edit` is subsequently invoked on that path, the target's current on-disk size, mtime, and hash are compared against the recorded identity.
- If an external process, background worker, or user editor modified the file in the interim, the edit is aborted with `EDIT_FILE_CHANGED`. The model receives an observation explaining that the file changed and advising a fresh `fs.read`.

---

## 5. Postcondition Verification & Automatic Rollback

To ensure edits never leave the codebase in a syntactically invalid state:
1. **Python Files (`*.py`):** After writing the prospective content, `ast.parse` is executed on the updated content. If a `SyntaxError` is detected (such as an unclosed parenthesis or indentation error), the file is immediately restored from its pre-edit byte snapshot, and `EDIT_POSTCONDITION_FAILED` is returned with the exact line number and syntax error message.
2. **JSON Files (`*.json`):** Decoded via `json.loads`. If syntax errors or trailing commas invalidate the document, the file is rolled back immediately.
3. **Empty File Check:** If an edit accidentally truncates a file to 0 bytes, it is aborted and restored.

---

## 6. Diff Minimality & Safety Limits

To protect against accidental global replacements:
- The diff ratio `lines_changed / original_lines` is monitored.
- If `old_string` consists of 5 or fewer lines, but the resulting diff mutates more than 200 lines or >50% of a substantial file (>20 lines), the operation is halted under `EDIT_SUSPICIOUS_LARGE_DIFF`.
- Intentional broad rewrites must explicitly supply `allow_large_diff=True` or use `fs.write`.

---

## 7. Performance Benchmarks

Measured on the development environment across 20 iterations:
- **`fs.edit` (Exact Replacement + Tempfile + Fsync + AST Parse):** `p50: 11.51 ms`, `p95: 17.71 ms`
- **Diff Calculation & Verification Overhead:** `< 1.2 ms`
- **Freshness Check Overhead:** `< 0.3 ms`
