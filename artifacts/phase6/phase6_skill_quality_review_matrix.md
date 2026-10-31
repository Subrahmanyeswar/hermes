# HERMES Phase 6: Skill Quality Review Matrix
## Comprehensive Forensic Assessment Across All 13 Live Production Skills

**Audit Date:** 2026-10-21  
**Audit Scope:** All 13 production skills located in canonical root `skills/`  
**Evaluation Standard:** Production-grade, adaptive, technically accurate, safe execution under HERMES platform capabilities (no arbitrary line-count or word-count standards).

---

## 1. Summary Matrix

| # | Skill Name | Current Manifest / Triggers | Domain / Scope | Tool Compatibility Issues | Over-Prescriptive / Rigid Rules | Safety & Verification Risks | Proposed Action & Upgrades | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | `auto-docs` | `docs`, `readme`, `api docs`, `docstring`... (8 triggers) | Documentation generation | References `read_file`, `list_directory`, `write_file` | Mandatory 7-section order; forced Config table & License section on all projects | May invent licenses, env vars, or dependencies not in project | Upgrade to HERMES tools (`fs.read`, `search.glob`, `fs.write`); adapt to existing project conventions; never fabricate licenses/deps | **NEEDS UPGRADE** |
| 2 | `bash-scripting` | `bash`, `shell script`, `terminal`, `automation`... (9 triggers) | POSIX shell and Bash scripts | Generic bash references | Lacks environment detection (POSIX vs Bash vs Windows/PowerShell) | `trap` cleanup risk; broad rm -rf guidance; doesn't reference HERMES safety bounds | Add platform detection; safe temporary file handling with single-target traps; enforce non-destructive shell boundaries | **NEEDS UPGRADE** |
| 3 | `code-review` | `code review`, `review`, `pull request`, `pr review`... (6 triggers) | Code inspection & review | References `read_file` | Review order rigid; lack of structured severity & remediation guidance | May confuse stylistic preferences with verified critical defects | Upgrade to `fs.read`; structure findings with severity (`[CRITICAL]`, `[MAJOR]`, `[MINOR]`), exact location, impact, and concrete remedy | **NEEDS UPGRADE** |
| 4 | `database-design` | `database`, `schema`, `sqlite`, `postgresql`... (10 triggers) | Relational schema & ORM design | References generic SQL files | Mandatory `id`, `created_at`, `updated_at` on every table; forced SQLite WAL mode in all contexts; mandatory SQL file naming | Rigid schema rules fail on junction/lookup tables; WAL mode unsuitable in some network or single-thread contexts | Relax table column mandates for junction tables; contextualize WAL mode; support existing project migration frameworks (Alembic/Flask-Migrate) | **NEEDS UPGRADE** |
| 5 | `debugging` | `debug`, `error`, `traceback`, `fix`... (20 triggers) | Bug analysis & error fixing | References `read_file`, `write_file (mode overwrite)`, `run_python`, `run_tests` | "Make exactly one hypothesis. Do not list multiple possibilities." | Premature commitment to single hypothesis; assumes error is always on final line of traceback | Upgrade to `fs.read`, `fs.edit`, `shell.bash`; allow systematic comparison of competing hypotheses; trace caller stack | **NEEDS UPGRADE** |
| 6 | `flask-rest-api` | `flask`, `rest api`, `backend`, `crud api`... (8 triggers) | Flask REST application development | References `write_file` | Mandatory `flask-jwt-extended` on all APIs; rigid 7-file folder layout | Forces unnecessary JWT dependencies and boilerplate on simple open/microservice endpoints | Make JWT conditional on auth requirements; adapt to existing project architecture; use `fs.write` | **NEEDS UPGRADE** |
| 7 | `git-workflow` | `git`, `commit`, `push`, `branch`... (9 triggers) | Git version control workflow | References non-existent tools: `git_init`, `git_add_commit`, `git_push` | "Always run git_init before any git_add_commit"; "Always stage all changes with add_all=True"; auto-push | **CRITICAL SAFETY VIOLATION:** Could re-initialize existing repos, stage unrelated user work, or push without authorization | Remove fake tools; mandate inspection (`git status`, `git diff`) before action; stage only intended files; require explicit authorization for commits/pushes; never run destructive commands (`reset`, `clean`) | **CRITICAL UPGRADE** |
| 8 | `pytest-generation` | `pytest`, `tests`, `unit test`... (12 triggers) | Pytest test generation | References `read_file`, `run_tests` | Enforces rigid 1-class-per-class structure regardless of functional style | May write tautological tests just to satisfy item counts | Upgrade to `fs.read`, `shell.bash` with canonical Python venv; focus on behavioral contracts, edge cases, exceptions, and `tmp_path` isolation | **NEEDS UPGRADE** |
| 9 | `react-frontend` | `react`, `jsx`, `tsx`, `nextjs`... (9 triggers) | React & TypeScript UI development | Generic tools | Mandatory Tailwind CSS on all projects; rigid file layout | Incompatible with projects using CSS Modules, Styled Components, or plain CSS | Make Tailwind conditional on project config; support Vite/CRA/Next conventions; ensure accessibility & error/loading states | **NEEDS UPGRADE** |
| 10 | `refactoring` | `refactor`, `clean code`, `solid`, `technical debt`... (8 triggers) | Code structure improvement | References `read_file`, `run_tests` | **Arbitrary thresholds:** "Functions longer than 20 lines need splitting"; "Functions with more than 3 parameters need dataclass" | Arbitrary splitting damages readability and cohesion; creates excessive indirection | Eliminate arbitrary line/param count rules; use observable maintainability signals (cohesion, coupling, duplication, nesting, side effects); verify behavioral preservation | **NEEDS UPGRADE** |
| 11 | `screenshot-to-code` | `screenshot`, `image`, `figma`, `html`... (9 triggers) | Visual design conversion | References fake tool `read_image`; references `write_file` | Trigger `html` causes false-positive selection on text landing pages; mandatory Tailwind; hardcoded output paths | Wrong routing on plain HTML tasks; rigid single-file output | Remove `html` from triggers; require vision/mockup intent; adapt to project tech stack; remove hardcoded destination paths | **NEEDS UPGRADE & ROUTING FIX** |
| 12 | `security-audit` | `security`, `vulnerability`, `owasp`, `injection`... (9 triggers) | Security review & vulnerability checks | Generic inspection | Generic checklist; assumes Python web app context | May claim full audit from superficial scan; lacks severity and exploitability context | Differentiate verified vulnerabilities from speculative risks; provide concrete preconditions, evidence, and remediation; clarify audit boundaries | **NEEDS UPGRADE** |
| 13 | `vanilla-web` | `html`, `css`, `javascript`, `vanilla`... (14 triggers) | Browser-native HTML5/CSS/JS | Generic file tools | Mandatory `localStorage` persistence on every site; mandatory form and select controls | Forces unnecessary storage and complex controls on static/informational landing pages | Make `localStorage` conditional on persistence requirement; emphasize semantic HTML, accessibility, responsive CSS Grid/Flexbox, safe DOM manipulation | **NEEDS UPGRADE** |

---

## 2. Detailed Findings by Skill

### 2.1 `auto-docs`
- **Current State:** Short 26-line prompt imposing a rigid 7-section README order (`Project Name`, `Features`, `Prerequisites`, `Installation`, `Usage`, `Configuration`, `License`).
- **Defects Identified:**
  - Hardcodes tool names `read_file`, `list_directory`, `write_file`.
  - Imposes a "Configuration table" and "License" section even if the project is a simple script with no environment variables and no chosen license.
  - Does not distinguish writing documentation files (`fs.write`) from answering documentation questions in the chat response.
- **Remediation:** Update tool references to `fs.read`, `search.glob`, `fs.write`. Instruct the agent to inspect existing documentation and structure before drafting. State that licenses and configuration sections must reflect verified project reality rather than being fabricated.

### 2.2 `bash-scripting`
- **Current State:** 27-line guide focused on `set -euo pipefail`, quoting, and `trap`.
- **Defects Identified:**
  - Assumes `/bin/bash` in all shell tasks without checking whether the user or environment is POSIX `/bin/sh`, macOS `zsh`, or Windows PowerShell.
  - Trap cleanup rule `trap 'rm -f /tmp/tempfile' EXIT` uses hardcoded path instead of the specific variable created by `mktemp`.
  - Does not reference HERMES safety bounds regarding non-destructive command execution.
- **Remediation:** Add environment detection; ensure trap removes only `${TMPFILE:-}` safely; add explicit warnings against destructive operations (`rm -rf /`, broad cleans, history rewriting).

### 2.3 `code-review`
- **Current State:** 30-line checklist for correctness, security, performance, and style.
- **Defects Identified:**
  - References `read_file`.
  - Severity categories (`[CRITICAL]`, `[MAJOR]`, `[MINOR]`) are defined without actionable criteria, leading to stylistic preferences being labeled as major issues.
  - Does not require citing exact file locations or providing concrete code remedies.
- **Remediation:** Update tool to `fs.read`. Define actionable severity guidelines based on functional impact and exploitability. Require exact line references and concrete replacement suggestions.

### 2.4 `database-design`
- **Current State:** 24-line guide enforcing specific columns, SQLAlchemy 2.0 syntax, SQLite WAL mode, and raw SQL migration files.
- **Defects Identified:**
  - Rule 1: "Every table must have id, created_at, updated_at" breaks standard associative/junction tables (e.g. `user_roles(user_id, role_id)`) and static lookup tables.
  - Rule 8: Enforces SQLite WAL mode universally, which can fail in certain networked filesystems or read-only deployments.
  - Rule 10: Mandates raw SQL migrations at `migrations/V{N}_{description}.sql`, ignoring existing migration frameworks like Alembic or Prisma.
- **Remediation:** Allow composite primary keys on junction tables; make timestamps optional where not appropriate; qualify SQLite WAL mode for concurrent write workloads; respect existing migration tooling. Add lazy-loaded supporting reference `references/schema_patterns.md`.

### 2.5 `debugging`
- **Current State:** 41-line 4-step debugging protocol.
- **Defects Identified:**
  - Rule 8: "Make exactly one hypothesis. Do not list multiple possibilities." In complex bugs (race conditions, subtle type coercions), prematurely locking into a single hypothesis prevents comparing plausible alternatives.
  - Rule 10 & 11: References `write_file with mode overwrite` (HERMES has surgical `fs.edit` and atomic `fs.write`) and non-existent `run_python` or `run_tests`.
  - Rule 3: "The last line of the traceback is always the actual error" ignores cases where the root cause is upstream in user code rather than inside third-party library internals.
- **Remediation:** Permit systematic comparison and falsification of competing hypotheses; update tool references to `fs.read`, `fs.edit`, and `shell.bash` with pytest/python; instruct tracing the user call stack.

### 2.6 `flask-rest-api`
- **Current State:** 40-line specification enforcing a 7-file folder layout and mandatory JWT.
- **Defects Identified:**
  - Rules 12-14: Forces `flask-jwt-extended` on every Flask API task, adding heavy dependencies and auth boilerplate even when the user requested a simple public API or CRUD service.
  - Rules 18-19: Enforces rigid file creation order and references `write_file`.
- **Remediation:** Make JWT authentication conditional on explicit user requirements; adapt to existing repository structures; update tool guidance to `fs.write` and `fs.edit`.

### 2.7 `git-workflow`
- **Current State:** 25-line guide with severe safety violations.
- **Defects Identified:**
  - Rule 1: "Always run git_init before any git_add_commit call" (risks re-initializing existing repositories).
  - Rule 4: "Always stage all changes with add_all=True" (violates safety: stages unrelated user files).
  - Rule 6 & 11: Auto-pushing to remote without explicit user authorization.
  - Tool names `git_init`, `git_add_commit`, `git_push` do not exist in HERMES platform tools.
- **Remediation:** Complete safety overhaul:
  - Remove all fake tool references; use `shell.bash` for read-only status and authorized Git operations.
  - Never run `git init` in existing workspaces unless explicitly directed.
  - Stage only specific target files; never run unconditional `git add -A` or `git add .`.
  - Require explicit operator authorization before committing or pushing.
  - Reiterate strict ban on destructive Git commands (`git reset`, `git clean`, `git restore`).
  - Add supporting reference `references/safety_rules.md`.

### 2.8 `pytest-generation`
- **Current State:** 43-line guide for generating pytest suites.
- **Defects Identified:**
  - Rule 6: "One test class per class under test" rigidly imposes OOP test structures on procedural or functional codebases.
  - Rule 15: Mentions non-existent `run_tests` tool.
  - Does not mention canonical Python interpreter path for test execution.
- **Remediation:** Update tool references to `fs.read`, `fs.write`, and `shell.bash` executing pytest via the active virtual environment; allow functional and class-based test layouts; emphasize `tmp_path` fixture isolation and meaningful error testing.

### 2.9 `react-frontend`
- **Current State:** 28-line guide for React 18 with Tailwind CSS.
- **Defects Identified:**
  - Rules 8-10: Mandates Tailwind CSS utility classes on all React projects, conflicting with projects using CSS Modules, Tailwind v4, Styled Components, or plain CSS.
  - Rule 12: Enforces Next.js App Router conventions even when building standalone Vite or CRA applications.
- **Remediation:** Detect and align with project's existing CSS strategy; support standard Vite and Next.js conventions; emphasize accessibility (ARIA), responsive layouts, and loading/error states.

### 2.10 `refactoring`
- **Current State:** 26-line guide for SOLID principles and clean code.
- **Defects Identified:**
  - Rule 7: "Functions longer than 20 lines need splitting" (Arbitrary line-count threshold).
  - Rule 8: "Functions with more than 3 parameters need a dataclass or config object" (Arbitrary parameter-count threshold).
  - Mentions `read_file` and `run_tests`.
- **Remediation:** Eliminate the 20-line and 3-parameter absolute thresholds; replace with observable maintainability indicators (mixed levels of abstraction, high cyclomatic complexity, deeply nested logic, hidden side effects, code duplication); require behavioral preservation verified by regression tests.

### 2.11 `screenshot-to-code`
- **Current State:** 29-line guide for converting screenshots to code.
- **Defects Identified:**
  - **Routing defect:** Manifest trigger list contains `html` and `visual`. This caused false-positive routing for plain HTML landing page requests (Scenario A discrepancy).
  - References fake tool `read_image`.
  - Mandates Tailwind CSS and hardcodes output to `generated_projects/screenshot_output.html`.
- **Remediation:**
  - Remove `html` and generic `visual` from triggers; use specific triggers (`screenshot`, `image to code`, `figma to code`, `ui mockup`, `design to code`, `wireframe`).
  - Update instructions to inspect image inputs using available modalities, adapt to project framework (vanilla HTML/CSS or React), and output to the user's requested path.

### 2.12 `security-audit`
- **Current State:** 25-line OWASP checklist for Python web apps.
- **Defects Identified:**
  - Assumes all projects are Python web applications.
  - Lacks structured reporting format distinguishing verified vulnerabilities from theoretical risks.
- **Remediation:** Broaden applicability across web and backend systems; structure findings with affected file/line, attack surface, preconditions, verified evidence, impact, and remediation; emphasize non-invasive, safe audit procedures. Add lazy-loaded supporting reference `references/owasp_checklist.md`.

### 2.13 `vanilla-web`
- **Current State:** 32-line specialist for HTML5, CSS3, and ES6+ JS.
- **Defects Identified:**
  - Rule 14: Mandates `localStorage` persistence on every application, even purely informational or static landing pages.
  - Rule 7: Mandates forms, inputs, and selects even if not required by the task.
- **Remediation:** Make client-side storage conditional on persistence requirements; emphasize semantic markup, accessible interactive elements, responsive CSS, and safe DOM manipulation.
