# HERMES Phase 9 — Initial Inspection Report
## Testing, Debugging, Security, Developer Workflows & Truthful Mission Orchestration

**Phase:** 9  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Branch:** `hermes-2.x`  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Host Operating System:** Windows  
**Inspection Date:** 2026-10-22  
**Status:** **INSPECTION COMPLETE — STAGE 1 PASSED**

---

## 1. Environment & Baseline Invariants

1. **Python Interpreter Truth:**
   - Canonical Executable: `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`
   - Verified Version: `Python 3.12.0 (tags/v3.12.0:0fb18b0)`
   - Environment Status: Intact, no rebuilds or silent package upgrades.
2. **Model Stack Truth (`config/model_config.py`):**
   - Tier 1: NVIDIA NIM — `z-ai/glm-5.3-flash`
   - Tier 2: Ollama — `gpt-oss:120b-cloud`
   - Tier 3: Ollama — `nemotron-3-ultra:cloud`
   - Tier 4: `null` (Has TIER4: False)
   - Status: Unaltered, preserved.
3. **Canonical Skill Inventory (23 Baseline Skills):**
   - Phase 6 (13 skills): `auto-docs`, `bash-scripting`, `code-review`, `database-design`, `debugging`, `flask-rest-api`, `git-workflow`, `pytest-generation`, `react-frontend`, `refactoring`, `screenshot-to-code`, `security-audit`, `vanilla-web`.
   - Phase 7 (7 skills): `react-best-practices`, `react-composition-patterns`, `design-engineering`, `web-design-guidelines`, `taste-design`, `design-system`, `shadcn-ui`.
   - Phase 8 (3 skills): `fastapi-backend`, `software-architecture`, `project-context`.
   - All 23 skill manifests match their locked SHA-256 baselines 100% byte-for-byte.

---

## 2. Functional Scope Classification & Gap Analysis

Per Section 3 of the Phase 9 Directive, every requested capability is classified as:
- **Category A (Existing and Locked):** Canonical skill already exists and must remain untouched.
- **Category B (Platform / Runtime Capability):** Behavior implemented in runtime contracts/engines.
- **Category C (Genuine Skill Gap):** Missing capability with clear repository/workflow justification.
- **Category D (Unjustified / Redundant):** Duplicates another system or unsupported stack.

| Functional Area | Classification | Existing Capability / Location | Phase 9 Decision |
|---|---|---|---|
| 1. Systematic Debugging & Root-Cause | **Category A** | `skills/debugging/SKILL.md` (Phase 6, 34 lines) | Locked; verify via routing & integration tests |
| 2. Pytest Generation & Regression Design | **Category A** | `skills/pytest-generation/SKILL.md` (Phase 6, 40 lines) | Locked; verify via routing & fixture tests |
| 3. Code Review & Severity Classification | **Category A** | `skills/code-review/SKILL.md` (Phase 6, 52 lines) | Locked; verify via routing & evaluation tests |
| 4. Security Auditing (FS/API/Injection) | **Category A** | `skills/security-audit/SKILL.md` (Phase 6, 44 lines) | Locked; verify via routing & containment tests |
| 5. Git Workflow & Merge Conflicts | **Category A** | `skills/git-workflow/SKILL.md` (Phase 6, 31 lines) | Locked; verify via routing & conflict tests |
| 6. Bash Scripting | **Category A** | `skills/bash-scripting/SKILL.md` (Phase 6, 40 lines) | Locked; verify via routing & syntax tests |
| 7. PowerShell Scripting (Windows-First) | **Category C** | *None* (Only `bash-scripting` existed) | **GENUINE GAP:** Implement `powershell-scripting` |
| 8. Mission Orchestration & Acceptance Gates | **Category B** | `core/alignment_verifier.py`, `core/evaluation/functional/`, `core/verification_gate.py` | Platform runtime capability; test existing contracts, no duplicate skill |

---

## 3. Discovered Routing & False-Positive Vulnerabilities

Empirical probing of the current router (`core/project_intelligence/skills.py`) revealed that purely informational or definitional questions without actionable tasks trigger false-positive activations:
- `"Explain what a code review is and why teams do it"` currently activates `['code-review', 'auto-docs']`.
- `"What does a security audit mean in software development?"` currently activates `['security-audit', 'code-review', 'web-design-guidelines']`.
- `"What is the definition of Git and version control?"` currently activates `['git-workflow']`.
- `"What is the difference between an exception and an error in theory?"` currently activates `['debugging']`.

### Root Cause:
Trigger phrase matching and keyword matching fire without checking whether the task is a purely conceptual explanation inquiry versus an active engineering assignment, and without workspace signals indicating an active codebase problem.

### Phase 9 Remediation Target:
Enhance `core/project_intelligence/skills.py` to recognize purely definitional / theoretical inquiries (`is_conceptual_inquiry`) so that conceptual explanations return legitimate no-skill fallbacks (`[]`) unless an actionable engineering task ("review this", "audit endpoint", "debug crash", "resolve conflict") or active workspace signals exist.

---

## 4. Proposed Phase 9 Changes

1. **New Canonical Skill (1 skill):** `skills/powershell-scripting/SKILL.md`
   - Focused on Windows-first scripting: `$LASTEXITCODE`, `$ErrorActionPreference`, literal vs wildcard paths (`-LiteralPath`), safe path construction (`Join-Path`), parameter validation, encoding, and non-destructive dry-run patterns.
   - Allowed tools: `fs.read`, `fs.write`, `fs.edit`, `shell.bash`, `search.glob`, `search.grep`.
2. **Router Discrimination Upgrade:**
   - Add `powershell-scripting` intent detection and routing.
   - Add conceptual inquiry detection to prevent false-positive reliability skill activation on purely definitional questions.
3. **Dedicated Test Suites:**
   - `tests/test_phase9_reliability_routing.py` (positive and negative routing test matrix).
   - `tests/test_phase9_powershell_skill.py` (metadata, tools, content, and routing tests).
   - `tests/test_phase9_security_and_mission_gates.py` (filesystem isolation, run fencing, acceptance gates).
