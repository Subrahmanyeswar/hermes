# HERMES Phase 9 — Bounded Implementation Plan
## Testing, Debugging, Security, Developer Workflows & Truthful Mission Orchestration

**Phase:** 9  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Branch:** `hermes-2.x`  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Date:** 2026-10-22  
**Status:** **PLAN READY FOR EXECUTION**

---

## 1. Incremental Execution Architecture

Phase 9 is structured into five strictly gated increments:

```
Increment A: Inspection & Baseline Lock Verification [COMPLETED]
     │
     ▼
Increment B: Positive & Negative Selection Tests for Locked Skills
     │
     ▼
Increment C: Genuine Skill Gap Implementation (powershell-scripting)
     │
     ▼
Increment D: Mission Orchestration, Truthful Progress & Security Gates
     │
     ▼
Increment E: Regression Battery, Evidence Synthesis & Final Lock
```

---

## 2. File Change Budget & Scope Boundaries

### A. New Production Skill to Add (1 file):
- `skills/powershell-scripting/SKILL.md`:
  - **Purpose:** Fills the Windows-first developer workflow gap.
  - **Content:** `$LASTEXITCODE`, `$ErrorActionPreference`, parameter validation, literal paths (`-LiteralPath`), safe path construction, encoding (`utf8NoBOM`), and dry-run safety.
  - **Allowed Tools:** `fs.read`, `fs.write`, `fs.edit`, `shell.bash`, `search.glob`, `search.grep`.

### B. Runtime Router Enhancement (1 file):
- `core/project_intelligence/skills.py`:
  - **Purpose:**
    1. Add `has_powershell_intent` detection to route `powershell-scripting` when Windows/PowerShell tasks are presented.
    2. Add conceptual inquiry discrimination (`is_conceptual_inquiry`) to suppress execution skills (`debugging`, `code-review`, `security-audit`, `git-workflow`) when questions are purely theoretical definitions without tasks or workspace signals.
  - **Budget:** Bounded surgical edit inside `route_skills()`. Zero changes to discovery architecture or progressive disclosure levels.

### C. New Dedicated Test Suites (3 files):
- `tests/test_phase9_reliability_routing.py`:
  - Validates positive activation of all 6 locked reliability skills + `powershell-scripting`.
  - Validates negative non-activation on conceptual / non-matching queries.
- `tests/test_phase9_powershell_skill.py`:
  - Validates `powershell-scripting` metadata, allowed tools conformance with `ToolCatalog`, and body invariants.
- `tests/test_phase9_security_and_mission_gates.py`:
  - Validates path traversal containment, workspace isolation, unexecutable lazy references, run fencing, and failed acceptance gate completion blocking.

### D. Locked Skills (Untouched - Zero Modifications):
- All 13 Phase 6 skills (`auto-docs`, `bash-scripting`, `code-review`, `database-design`, `debugging`, `flask-rest-api`, `git-workflow`, `pytest-generation`, `react-frontend`, `refactoring`, `screenshot-to-code`, `security-audit`, `vanilla-web`).
- All 7 Phase 7 skills (`react-best-practices`, `react-composition-patterns`, `design-engineering`, `web-design-guidelines`, `taste-design`, `design-system`, `shadcn-ui`).
- All 3 Phase 8 skills (`fastapi-backend`, `software-architecture`, `project-context`).

### E. Explicit Deferrals (Out of Scope):
- `mission-orchestration` skill: Deferred as redundant with core runtime orchestration engine (`core/mission_runner.py`, `core/alignment_verifier.py`, `core/verification_gate.py`).
- `node-rest-api` & `prisma-migrations`: Preserved deferred status from Phase 8.

---

## 3. Mandatory Acceptance Gates

- **Gate A (Environment & Baselines):** Verified Python 3.12.0, unchanged model configuration, 23 baseline skill SHA-256 hashes matching 100%. [PASSED]
- **Gate B (Routing Precision):** Positive selection routes correctly; negative conceptual queries avoid false positives.
- **Gate C (PowerShell Skill):** Valid YAML frontmatter, tools conform to `ToolCatalog`, comprehensive Windows guidance.
- **Gate D (Security & Orchestration Gates):** Path traversal blocked, failed gates block completion, run fencing intact.
- **Gate E (Regression & Lock):** Dedicated suites pass; Phase 5, 6, 7, 8 regressions pass (100% green); deliverables finalized.
