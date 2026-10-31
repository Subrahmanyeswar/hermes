# HERMES Phase 9 — Test Matrix Specification
## Testing, Debugging, Security, Developer Workflows & Truthful Mission Orchestration

**Phase:** 9  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Date:** 2026-10-22  

---

## 1. Skill Selection & Routing Test Matrix

### 1.1 Positive Activation Cases
| Intent / Request | Expected Activated Skill | Allowed Concurrent Skills |
|---|---|---|
| "Trace the root cause of this Python TypeError exception and fix the failing loop" | `debugging` | Any relevant domain skill |
| "Generate pytest test cases for the string parser function covering edge cases" | `pytest-generation` | `auto-docs` |
| "Review this pull request diff for security defects, memory leaks, and severity" | `code-review` | `security-audit` |
| "Audit this API endpoint for SQL injection, path traversal, and auth bypass" | `security-audit` | `code-review`, `database-design` |
| "Resolve a merge conflict between main and feature branch in git repository" | `git-workflow` | None |
| "Write a portable Bash script for log rotation with strict error checking" | `bash-scripting` | None |
| "Write a Windows PowerShell script to automate backup of logs with ErrorActionPreference Stop" | `powershell-scripting` | None |

### 1.2 Negative / False-Positive Discrimination Cases
| Query Text | Tested Intent | Expected Result | Reason |
|---|---|---|---|
| "Explain recursion conceptually in computer science" | Conceptual computer science inquiry | `[]` (No skill) | Purely conceptual, no execution required |
| "Explain what a code review is and why software teams do it" | Informational code review inquiry | `[]` (No skill) | Definitional question; no codebase review requested |
| "What does a security audit mean in software development?" | Informational security inquiry | `[]` (No skill) | Definitional question; no audit requested |
| "What is the definition of Git and version control in theory?" | Informational Git inquiry | `[]` (No skill) | Definitional question; no git operations requested |
| "Explain how to calculate 2 + 2 in arithmetic" | General arithmetic inquiry | `[]` (No skill) | General query; no automation skill needed |
| "What is the difference between an exception and an error in theory?" | Informational Python inquiry | `[]` (No skill) | Theoretical comparison; no active debugging task |
| "What is the Windows PowerShell command syntax for Get-Process?" | Simple command explanation | `[]` (No skill) | Simple command explanation; full scripting skill not warranted |
| "Describe the product features of an autonomous agent" | Generic product description | `[]` (No skill) | General prose inquiry; no orchestration skill |

---

## 2. PowerShell Skill Specification Matrix

| Metric / Check | Requirement | Verification Method |
|---|---|---|
| Manifest Path | `skills/powershell-scripting/SKILL.md` | Path existence check |
| YAML Frontmatter | Valid YAML, name `powershell-scripting`, category `scripting` | `SkillEngine.index_skills()` |
| Allowed Tools | `fs.read`, `fs.write`, `fs.edit`, `shell.bash`, `search.glob`, `search.grep` | `ToolCatalog.get()` resolution |
| `$LASTEXITCODE` Invariant | Explicit handling when calling native executables | Content assertion |
| `$ErrorActionPreference` Invariant | Explicit `Stop` preference for automated scripts | Content assertion |
| Path Construction Invariant | Use of `Join-Path` and `-LiteralPath` for safety | Content assertion |
| Encoding Invariant | UTF-8 output specification without BOM | Content assertion |
| Tool Invocation Safety | Does NOT execute scripts automatically on loading | Progressive disclosure test |

---

## 3. Security & Mission Orchestration Matrix

| Test ID | Safety / Orchestration Dimension | Expected Observable Behavior |
|---|---|---|
| SEC-01 | Path traversal containment (`../../etc/passwd`) | `PathContainmentError` / Rejected by tool gate |
| SEC-02 | Protected state directory containment (`.hermes/*`) | Access denied or isolated |
| SEC-03 | Skill script lazy isolation | Discovery & loading does NOT execute skill scripts |
| SEC-04 | Destructive Git commands (`git reset --hard`) | Identified as prohibited |
| ORCH-01 | Mandatory acceptance gate failure | Mission completion is BLOCKED; status remains non-completed |
| ORCH-02 | Stale run fencing | Events from older run IDs rejected by reducer |
| ORCH-03 | Truthful Stop control | Stop action requires explicit backend confirmation |
