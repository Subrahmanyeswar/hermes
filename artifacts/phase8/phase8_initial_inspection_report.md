# HERMES Phase 8 — Initial Codebase Inspection & Skills Architecture Scope

**Phase:** 8  
**Title:** Backend, Architecture and Documentation Skills  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Branch:** `hermes-2.x`  
**Canonical Skills Root:** `C:\Users\SUBBU\Downloads\hermes\skills`  
**Canonical Python:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Date:** 2026-10-22

---

## 1. Executive Summary

Phase 8 extends the HERMES skills architecture into backend frameworks, system architecture, and repository context documentation while strictly preserving all 20 existing skills from Phase 6 (13 skills) and Phase 7 (7 skills).

An audit of the codebase, runtime environment, and dependency tree reveals:
1. **Installed Backend Stack:** `fastapi` (0.143.0), `uvicorn` (0.54.0), `pydantic` (2.13.5), `httpx` (0.28.1). HERMES's own server (`core/server/app.py`, 1022 lines) is an asynchronous FastAPI application with APIRouters, Pydantic v2 schemas, and SSE streams.
2. **Current API Skills Gap:** HERMES currently only has `flask-rest-api` (Phase 6). A dedicated, production-grade `fastapi-backend` skill is justified by both the platform's internal stack and modern Python backend ecosystem requirements.
3. **Database Architecture:** HERMES uses SQLite 3 with Write-Ahead Logging (`WAL`), serial transactions, and durable journal recovery (`core/persistence/`). There is no Prisma or SQLAlchemy runtime. ORM/Prisma migrations are deferred to avoid speculative bloat.
4. **Node Architecture:** Node/npm tooling exists exclusively in `gui/` for Vite/TypeScript bundling of the GUI. No Node backend runtime exists in HERMES. `node-rest-api` is formally deferred with documented justification.
5. **Architecture & Documentation Skills Gap:**
   - `refactoring` (Phase 6) handles function-level and file-level code cleanup, but lacks system-level boundary design, ADR creation, and C4 architectural modeling. A `software-architecture` skill is justified.
   - `auto-docs` (Phase 6) handles code docstrings and API reference documentation, but lacks project-level operational context, `HERMES.md` / `AGENTS.md` rules maintenance, and agent alignment. A `project-context` skill is justified.

---

## 2. Baseline Skills Inventory (20 Locked Skills)

| Phase | Skill Name | Frontmatter | Tool Contracts Valid |
|---|---|---|---|
| Phase 6 | `auto-docs` | Valid | Yes |
| Phase 6 | `bash-scripting` | Valid | Yes |
| Phase 6 | `code-review` | Valid | Yes |
| Phase 6 | `database-design` | Valid | Yes |
| Phase 6 | `debugging` | Valid | Yes |
| Phase 6 | `flask-rest-api` | Valid | Yes |
| Phase 6 | `git-workflow` | Valid | Yes |
| Phase 6 | `pytest-generation` | Valid | Yes |
| Phase 6 | `react-frontend` | Valid | Yes |
| Phase 6 | `refactoring` | Valid | Yes |
| Phase 6 | `screenshot-to-code` | Valid | Yes |
| Phase 6 | `security-audit` | Valid | Yes |
| Phase 6 | `vanilla-web` | Valid | Yes |
| Phase 7 | `design-engineering` | Valid | Yes |
| Phase 7 | `design-system` | Valid | Yes |
| Phase 7 | `react-best-practices` | Valid | Yes |
| Phase 7 | `react-composition-patterns` | Valid | Yes |
| Phase 7 | `shadcn-ui` | Valid | Yes |
| Phase 7 | `taste-design` | Valid | Yes |
| Phase 7 | `web-design-guidelines` | Valid | Yes |

All 20 baseline skills will be preserved with exact line counts and metadata integrity.

---

## 3. Phase 8 Scope & Technology Justification

### Justified Production Skills:
1. **`fastapi-backend`**
   - **Rationale:** Supported directly by installed libraries (`fastapi`, `pydantic`, `uvicorn`, `httpx`) and HERMES's internal server architecture (`core/server/app.py`). Distinct from `flask-rest-api`.
   - **Scope:** Lifespan context managers (`@asynccontextmanager`), `APIRouter` modular design, Pydantic v2 validation models, dependency injection (`Depends`), async path operations, error handlers (`HTTPException`), and integration testing with `httpx.AsyncClient`.
   - **Allowed Tools:** `fs.read`, `fs.write`, `fs.edit`, `shell.bash`, `search.glob`, `search.grep`.

2. **`software-architecture`**
   - **Rationale:** Fills the gap between code-level refactoring (`refactoring`) and system-level structural design.
   - **Scope:** System decomposition, module boundaries, C4 model documentation (Context, Container, Component, Code), Architecture Decision Records (ADRs), interface contracts, dependency direction, avoidance of premature microservices/dogmatic enterprise bloat.
   - **Allowed Tools:** `fs.read`, `fs.write`, `fs.edit`, `search.glob`, `search.grep`.

3. **`project-context`**
   - **Rationale:** Fills the gap between code-level documentation (`auto-docs`) and repository-level operational guidelines (`HERMES.md`, `AGENTS.md`, system rules).
   - **Scope:** Generating and maintaining high-leverage agent instructions, architectural invariants, environment contracts, avoiding token bloat, and synchronizing context files with evolving implementation truth.
   - **Allowed Tools:** `fs.read`, `fs.write`, `fs.edit`, `search.glob`, `search.grep`.

### Formal Deferrals:
1. **`node-rest-api` — DEFERRED:**
   - **Reasoning:** HERMES runtime has no Node.js backend. `gui/` is purely static client bundling. Introducing Node backend skills without runtime support violates the evidence-first policy.
2. **`database-migrations` / Prisma ORM — DEFERRED:**
   - **Reasoning:** HERMES persistence is SQLite3 + WAL with custom transactional recovery (`core/persistence/`). Prisma is not present. `database-design` already covers relational SQL schema design.

---

## 4. Phase 8 Execution Plan

Each skill is implemented and verified sequentially:
1. **Skill 1:** `fastapi-backend` (Implementation -> Router update -> Focused unit test -> Phase 6/7 regression).
2. **Skill 2:** `software-architecture` (Implementation -> Router update -> Focused unit test -> Phase 6/7 regression).
3. **Skill 3:** `project-context` (Implementation -> Router update -> Focused unit test -> Phase 6/7 regression).
4. **Integration Verification:** Multi-skill composition, router discrimination tests, and full regression battery.
5. **Phase 8 Closure:** Evidence JSON, closure report, and lock.
