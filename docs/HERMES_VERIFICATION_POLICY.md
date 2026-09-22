# HERMES Verification Policy Matrix
====================================

**Document:** Authoritative Verification & Escalation Policy  
**Phase:** Phase 6.2 — Progressive Verification & Intelligent Gating  
**Version:** 2.0  
**Status:** ACTIVE  

---

## 1. Core Verification Philosophy

HERMES follows the principle of **Adaptive Verification**:
> *"Use deterministic verification wherever deterministic verification is sufficient, use Qwen3 when genuine semantic verification is needed, and escalate to Ox Alpha only when disagreement or risk actually justifies it."*

---

## 2. Verification Hierarchy Levels

| Level | Name | Scope & Mechanism | Latency | VRAM Switch Cost |
|---|---|---|---|---|
| **Level 0** | **Deterministic Local Validation** | Filesystem checks, exit code verification, file existence, content size matching | < 2 ms | **0.00 s (Zero Switches)** |
| **Level 1** | **Structural / AST Validation** | Python `ast.parse()` syntax tree validation, JSON schema validation | < 5 ms | **0.00 s (Zero Switches)** |
| **Level 2** | **Tier 2 Qwen3 Semantic LLM** | Complex logic, bug fixing, refactoring, security reviews, diagnostic failures | 15s – 35s | **8.64 s (1 Full VRAM Reload)** |
| **Level 3** | **Tier 3 Ox Alpha Cloud Arbitration** | High-risk disagreement, destructive actions, security conflicts | 2s – 6s | **0.00 s (Cloud REST API)** |

---

## 3. Authoritative Verification Matrix

| Tool Category | Example Tools | Task Risk Profile | Deterministic / AST Checks | Tier 2 (Qwen3) Required? | Tier 3 (Ox Alpha) Escalation? |
|---|---|---|---|---|---|
| **READ_ONLY** | `list_directory`, `read_file`, `search_files`, `file_exists`, `git_status`, `git_log` | Low / Factual | Path existence, valid directory/file format, exit_code == 0 | **NO (Level 0)** | Only if local check fails unexpectedly |
| **READ_ONLY (Security Sensitive)** | `read_file`, `search_files` on credentials, tokens, passwords, private keys | **HIGH** | File existence, size | **YES (Level 2)** | If T2 flags policy violation |
| **LOW_RISK_WRITE** | `write_file` (simple utility / creation) | Low / Moderate | File exists on disk, size > 0, Python `ast.parse()` passes | **NO (Level 1 AST)** | Only if AST syntax fails or file missing |
| **MEDIUM_RISK_WRITE** | `write_file` (config, multi-file), `patch_file`, `git_commit` | Moderate | AST syntax, file integrity, git diff validation | **YES (Level 2)** | If semantic conflict or regression |
| **SEMANTIC CODING / REFACTOR** | `write_file`, `patch_file` for bug fixes, algorithms, refactoring | Moderate / High | AST syntax passes | **YES (Level 2)** | If T1 output does not meet semantic criteria |
| **HIGH_RISK_EXECUTION** | `execute_command`, `python_eval`, `package_install` | High | Exit code, stdout/stderr capture | **YES (Level 2)** | If execution has high risk score (> 0.70) |
| **DESTRUCTIVE** | `delete_file`, `git_push --force`, database drop | Critical | Artifact verification | **YES (Level 2)** | **ALWAYS (Level 3 or User Confirm)** |
| **UNKNOWN TOOL** | Any unregistered tool name | Unknown | Exit code | **YES (Level 2 Conservative)** | If risk > 0.70 |

---

## 4. Task-Level Risk Analysis

Even if a tool is technically `READ_ONLY`, the **Task Intent** dictates whether Tier 2 is mandatory.
If the user prompt contains any of the following security triggers:
- `credential`, `password`, `secret`, `token`, `api_key`, `private_key`
- `exfiltrate`, `drop table`, `drop database`, `rm -rf`, `delete database`
- `authentication`, `auth`, `exploit`, `vulnerability`, `bypass`

➔ The `VerificationGate` **automatically escalates to Level 2 (Tier 2 Qwen3)**.

---

## 5. Rollback & Feature Flag

If adaptive verification ever needs to be temporarily disabled:
```bash
# In .env or environment
PROGRESSIVE_VERIFICATION_ENABLED=false
```
Setting `PROGRESSIVE_VERIFICATION_ENABLED=false` immediately falls back 100% of all operations to the legacy Level 2 Qwen3 verification path.
