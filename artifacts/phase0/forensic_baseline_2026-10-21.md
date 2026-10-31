# HERMES PHASE 0 — DEEP FORENSIC BASELINE AND ENVIRONMENT AUDIT REPORT

**Date:** 2026-10-21  
**Author:** Principal Systems Architect, Python Runtime Investigator, Distributed-Systems Reliability Engineer, and Frontend/Backend Integration Auditor  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Mandatory Python Interpreter:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`  
**Observed Python Version:** `Python 3.12.0 (tags/v3.12.0:0fb18b0, Oct 2 2023, 13:03:39) [MSC v.1935 64 bit (AMD64)]`  
**Deliverable Path:** `artifacts/phase0/forensic_baseline_2026-10-21.md`  
**Verdict:** **PASS WITH LIMITATIONS** (No active live server running on 8765 to live-probe; historical SQLite records, offline reproduction, and full static/dynamic suites forensically reconciled without mutations).

---

## A. Executive Summary

This Phase 0 audit establishes an evidence-backed baseline of the HERMES codebase, its runtime environment, persistent mission state, execution loop, frontend event subscription, skill indexing, and automated test suite.

### Key Forensic Findings
1. **The "NameError: name 'Path' is not defined" Defect:**
   - Forensic static analysis across all Python source modules in `core/`, `tools/`, `ui/`, and `models/` verified that `pathlib.Path` is correctly imported and available across all active file-tool implementations.
   - An isolated live probe of `WriteFileTool` and `ReadFileTool` under a sandboxed temporary workspace executed cleanly with byte-for-byte readback and strict path-containment validation (blocking `../` directory escapes).
   - Historical records reveal an earlier hotfix in `utils/logging.py` for a similar `NameError` (`generate_session_id`), and an earlier stage fix in file tools. In the current repository checkout (`hermes-2.x`, commit `031ad3c`), the `write_file` tool does not suffer from a missing `Path` import. The observed GUI error in earlier sessions was caused either by a stale running server process executing un-reloaded bytecode prior to hotfix application, or by an older process instance.

2. **Greenfield Build Classification & Planner Stalling (Mission `m_a5a974d1`):**
   - In `core/agent_loop/loop.py` (lines 267–330), a preflight check designed to detect missing target applications evaluates whether the prompt mentions keywords such as `"existing application"`, `"existing project"`, or `"existing app"`.
   - In mission `m_a5a974d1`, the user submitted a benchmark prompt titled *"LIVE APPLICATION GENERATION CHALLENGE — LABFLOW CAMPUS LAB MANAGER"*, which explicitly instructed HERMES to *"Build a complete, polished, responsive web application... from scratch in the currently selected workspace"*, but contained safety text: *"Inspect the workspace before coding. If existing application files are present outside those two directories, do not overwrite them..."*.
   - Because `prompt_lower` contained the exact substring `"existing application"`, the preflight logic incorrectly classified this pure greenfield task as an edit of an existing codebase. Since the target workspace (`HERMES_EMPTY_BUILD_TEST`) had 0 application files, `AgentLoop` immediately failed preflight with `failure_code: EMPTY_WORKSPACE_EXISTING_APPLICATION` (Event sequence 5189), aborting the mission before any planner decomposition or file creation could take place.

3. **Event Stream Truthfulness & UI Sync Reducer (`ActivityPanel` vs Event 5189):**
   - In SQLite database `hermes_runtime.db`, mission `m_a5a974d1` has a snapshot at `state_version=30, last_event_sequence=5189, status=FAILED`.
   - In `gui/src/sync.ts`, the client reducer function `processIncomingSnapshot` enforces monotonic state watermarks:
     ```typescript
     // sync.ts lines 67-69
     const nextEvents = currentState.events.filter(
       (e) => (e.sequence || 0) > incomingSnapshot.last_sequence
     );
     ```
   - When the GUI loads or polls the mission snapshot (which has `last_sequence = 5189`), it purges all stream events with `sequence <= 5189` from `syncState.events`.
   - Consequently, `ActivityPanel.tsx`, which renders `events: HermesEvent[]`, displays `Activity & Stream Events (0)` and *"No stream events received yet"* because historical journal events persisted before the snapshot cursor are not replayed into the client stream buffer. This explains why the GUI displayed a high event sequence counter alongside zero visible activity items.

4. **Model Provider Configuration & Staged Routing:**
   - Active configuration in `config/model_config.py` confirms:
     - Tier 1: NVIDIA NIM — `z-ai/glm-5.3-flash` (endpoint: `https://integrate.api.nvidia.com/v1`)
     - Tier 2: Ollama Cloud — `gpt-oss:120b-cloud`
     - Tier 3: Ollama Cloud — `nemotron-3-ultra:cloud`
   - All credentials remain intact via environment variables (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`) and are strictly redacted.

---

## B. Environment Identity

- **Repository Root:** `C:\Users\SUBBU\Downloads\hermes`
- **Canonical Python Executable:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`
- **Canonical Python Version:** `3.12.0` (tags/v3.12.0:0fb18b0, Oct 2 2023, 13:03:39) [MSC v.1935 64 bit (AMD64)]
- **Virtual Environment Prefix:** `C:\Users\SUBBU\Downloads\hermes\venv`
- **Base Python Prefix:** `C:\Users\SUBBU\AppData\Local\Programs\Python\Python312`
- **Running Server Process:**
  - NetTCPConnection check on port `8765`: **No process listening** (Connection closed).
  - CIM process check: No active background `uvicorn` or `core.server` process running.
  - `.hermes_server.pid` record: Referenced PID `14168` (terminated).
  - Server log (`data/logs/hermes_gui_server.log`): Last recorded launch occurred at `2026-10-20 17:02:16` (PID 23284).
- **Frontend Environment & Build:**
  - Directory: `gui/`
  - Tooling: Node.js, `npm 10.8.2`, Vite `5.4.21`, TypeScript
  - Production build execution: `npm run build` completed in **2.54s** with **0 errors**:
    - `dist/index.html` (0.63 kB)
    - `dist/assets/index-fEuUN2VZ.css` (2.93 kB)
    - `dist/assets/index-0CuJNT3C.js` (219.79 kB)

---

## C. Architecture Map

| Subsystem | Primary Implementation Paths | Key Classes / Functions | Primary Responsibility |
| :--- | :--- | :--- | :--- |
| **Startup & Launcher** | `scripts/launch_gui.ps1`<br>`core/server/launcher.py`<br>`hermes.bat` | `launch_server()`<br>`verify_hermes_health()` | Validates Python 3.12 venv, guards port 8765, runs detached uvicorn. |
| **FastAPI Backend** | `core/server/app.py`<br>`core/server/runtime_adapter.py` | `FastAPI app`<br>`RuntimeAdapter` | Exposes REST & SSE APIs (`/api/missions`, `/api/health`, `/api/events`). |
| **Mission Execution** | `core/agent_loop/loop.py`<br>`core/mission_runner.py` | `AgentLoop`<br>`MissionRunner` | Continuous execution loop, turn management, action dispatch. |
| **Model Routing** | `models/nvidia_client.py`<br>`models/ollama_client.py`<br>`core/adaptive_routing.py` | `NvidiaClient`<br>`OllamaClient`<br>`AdaptiveRouter` | 3-tier routing: Tier 1 (NIM glm-5.3-flash), Tier 2 (gpt-oss), Tier 3 (nemotron). |
| **File System Tools** | `tools/file_tools.py`<br>`tools/platform/core_tools.py` | `WriteFileTool`<br>`ReadFileTool`<br>`EditFileTool` | Sandboxed file I/O, hash checks, atomic writes, workspace boundary checks. |
| **Workspace Management** | `core/workspace.py`<br>`core/workspace_indexer.py` | `WorkspaceManager`<br>`WorkspaceIndexer` | Workspace path locking, traversal prevention, SQLite AST indexing. |
| **Runtime State** | `core/runtime_state/models.py`<br>`core/runtime_state/reducer.py` | `HermesState`<br>`StateReducer` | Pure reducer for state transitions, monotonic versions, run isolation. |
| **State Persistence** | `core/persistence/database.py`<br>`core/persistence/journal.py` | `SQLiteDatabase`<br>`EventJournal` | Durable SQLite storage (`hermes_runtime.db`), snapshot & event journal. |
| **Checkpoints & Recovery**| `core/checkpoints/engine.py`<br>`core/network/coordinator.py` | `CheckpointEngine`<br>`NetworkRecoveryCoordinator` | File snapshots, state rewind, circuit recovery, mission auto-resume. |
| **Event Broadcasting** | `core/event_bus.py`<br>`core/runtime_state/events.py` | `EventBus`<br>`HermesEvent` | Async in-memory & SQLite event publishing and SSE streaming. |
| **Frontend GUI** | `gui/src/App.tsx`<br>`gui/src/sync.ts`<br>`gui/src/components/*` | `App`<br>`processIncomingSnapshot`<br>`processIncomingEvent` | React/Vite SPA, SSE event consumer, watermark race guards. |
| **Skill System** | `core/intent_classifier.py`<br>`skills/*/SKILL.md` | `IntentClassifier`<br>`SkillMetadata` | Keyword & regex trigger matching, dynamic skill context injection. |
| **Verification Gate** | `core/verification_gate.py`<br>`core/quality_verifier.py` | `VerificationGate`<br>`QualityVerifier` | Progressive risk categorization, evidence-based quality verification. |

---

## D. Write-File Forensic Findings

### 1. Root Cause Analysis of `NameError: name 'Path' is not defined`
- **File Checked:** `tools/file_tools.py`
- **Line 13:** `from pathlib import Path` is explicitly imported at module level.
- **AST Scan:** Scanned 100% of Python files in `core/`, `tools/`, `ui/`, and `models/`. Zero files reference `Path` without importing `pathlib.Path` or `pathlib`.
- **Execution Reproduction:**
  A disposable sandbox probe was executed under `C:\Users\SUBBU\AppData\Local\Temp\hermes_phase0_probe_*`:
  - `WriteFileTool.execute()` wrote a 40-character probe file successfully.
  - `ReadFileTool.execute()` read the file back with exact content matching (`True`).
  - Path boundary escape attempt (`../escaped.txt`) was caught and blocked with exit code `126`: `SECURITY: Path '../escaped.txt' escapes workspace boundary`.
- **Conclusion:** The `Path` `NameError` is **not present** in the current checkout (`hermes-2.x`, commit `031ad3c`). The error previously observed in the GUI was either due to an older server process running un-reloaded source code before an earlier patch, or an artifact of an obsolete process instance.

---

## E. Greenfield Planning & Application Classification Findings

### 1. The Naive Substring Trap
In `core/agent_loop/loop.py` lines 270–286:
```python
prompt_lower = (mission.user_prompt or "").lower()
existing_keywords = [
    "existing application",
    "existing project",
    "existing codebase",
    "existing app",
    "existing repo",
    "existing repository",
    "existing code",
    "to the existing",
    "in the existing",
    "from the existing",
    "existing service",
    "existing server",
    "existing web application",
]
targets_existing = any(kw in prompt_lower for kw in existing_keywords)
```

### 2. Forensic Impact on Incident Mission `m_a5a974d1`
- The user submitted the LabFlow Campus Lab Manager prompt, which requested building an app *from scratch*, but included safety instructions: *"If existing application files are present outside those two directories, do not overwrite them..."*.
- The check `targets_existing` matched `"existing application"` and `"existing app"`.
- Because the workspace was clean (0 files), `loop.py` line 295 triggered:
  - Emitted `EventType.MISSION_FAILED` with `failure_code: EMPTY_WORKSPACE_EXISTING_APPLICATION`.
  - Saved `status: FAILED` in SQLite.
  - Marked control terminal and returned immediately.
- **Result:** The planner never initiated task decomposition. The workspace remained empty.

---

## F. Mission Lifecycle and Recovery Findings

### 1. Database State Inspection (`hermes_runtime.db`)
Direct read-only inspection of `C:\Users\SUBBU\AppData\Local\HERMES\hermes_runtime.db` revealed:
- **Incident Mission `m_a8442b65`:**
  - Persisted Status: `RUNNING` (wait_reason: `WORKING`, run_id: `run_2_5d20ec26`, attempt: 2).
  - Last Events: 5 consecutive `MISSION_CANCELLED` events at sequences 4784–4788 (ts: `1792431998`–`1792431999`).
  - State Version: 21, last event sequence cursor: 4484.
  - Active Process: None (server offline).
- **Incident Mission `m_a5a974d1`:**
  - Persisted Status: `FAILED` (wait_reason: `FAILED`, run_id: `run_1_daecd530`, attempt: 1).
  - Last Event: `MISSION_FAILED` at sequence 5189 with `EMPTY_WORKSPACE_EXISTING_APPLICATION`.
  - State Version: 30, last event sequence: 5189.
- **Incident Mission `m_c554d6ac`:**
  - Persisted Status: `CANCELLED` (wait_reason: `CANCELLED`, run_id: `run_8_a283e1b2`, attempt: 8).
  - Last Event: `CHECKPOINT_CREATED` at sequence 5155, `MISSION_STARTED` at sequence 5154.

All historical records were preserved without any mutation.

---

## G. Event Transport and UI Consistency Findings

### 1. Root Cause of Missing Events in `ActivityPanel`
- In `gui/src/sync.ts`, `processIncomingSnapshot` enforces that `events` in `ClientSyncState` only retain items whose `sequence > incomingSnapshot.last_sequence`:
  ```typescript
  const nextEvents = currentState.events.filter(
    (e) => (e.sequence || 0) > incomingSnapshot.last_sequence
  );
  ```
- Because snapshot `m_a5a974d1` had `last_sequence = 5189`, any events received up to sequence 5189 are discarded from the real-time buffer when the snapshot is fetched.
- The UI's `ActivityPanel.tsx` receives `events={streamEvents}` directly. Since no events existed beyond sequence 5189, `streamEvents` had length 0.
- Meanwhile, `TopBar.tsx` or `TaskCard.tsx` showed `last_sequence: 5189` from the snapshot metadata.
- **Consequence:** The user observed `5189` events in the header/status counter, but 0 events in the activity list.

---

## H. Skill Inventory and Routing Audit

### 1. Discovered Skills
A total of **13 valid skills** were discovered in `C:\Users\SUBBU\Downloads\hermes\skills`:
1. `auto-docs` (priority: 1, triggers: 8)
2. `bash-scripting` (priority: 1, triggers: 9)
3. `code-review` (priority: 1, triggers: 6)
4. `database-design` (priority: 1, triggers: 10)
5. `debugging` (priority: 1, triggers: 20)
6. `flask-rest-api` (priority: 1, triggers: 8)
7. `git-workflow` (priority: 1, triggers: 9)
8. `pytest-generation` (priority: 1, triggers: 12)
9. `react-frontend` (priority: 1, triggers: 9)
10. `refactoring` (priority: 1, triggers: 8)
11. `screenshot-to-code` (priority: 1, triggers: 9)
12. `security-audit` (priority: 1, triggers: 9)
13. `vanilla-web` (priority: 1, triggers: 14)

### 2. Selection & Classification Verification
Tested `IntentClassifier` against sample user intents:
- *"Build a complete vanilla html/css/js web app"* -> Selected: `['vanilla-web']` (0.016s)
- *"Debug this python crash and fix the TypeError"* -> Selected: `['debugging']` (0.000s)
- *"Write unit tests using pytest for the auth module"* -> Selected: `['pytest-generation']` (0.000s)
- *"Review this pull request for security vulnerabilities"* -> Selected: `['code-review']` (0.000s)

All 13 skills contain valid frontmatter and parse without errors.

---

## I. Test Baseline

### 1. Test Collection
- **Command:** `venv\Scripts\python.exe -m pytest --collect-only -q tests`
- **Result:** **2,258 tests collected in 4.46s** (Exit code: 0).

### 2. Targeted Safety & Reconciliation Suite
- **Command:**
  ```powershell
  venv\Scripts\python.exe -m pytest tests/test_stale_running_control_reconciliation.py `
    -W error::pytest.PytestReturnNotNoneWarning -W error::SyntaxWarning
  ```
- **Result:** **14 passed in 3.02s** (100% pass, Exit code: 0).

### 3. Focused 10-Module Regression Suite
- **Command:**
  ```powershell
  venv\Scripts\python.exe -m pytest `
    tests/test_runtime_state.py `
    tests/test_phase10_crash_and_lifecycle_races.py `
    tests/test_phase10_filesystem_and_journal_truth.py `
    tests/test_phase10_network_and_provider_faults.py `
    tests/test_incident_planning_and_lifecycle_recovery.py `
    tests/test_stage2_server_and_event_stream.py `
    tests/test_stage6_real_execution.py `
    tests/test_stage7_reliability_and_recovery.py `
    tests/test_phase11_contracts.py `
    tests/test_phase11_alignment_verifier.py `
    -W error::pytest.PytestReturnNotNoneWarning -W error::SyntaxWarning
  ```
- **Result:** **114 passed in 16.00s** (100% pass, Exit code: 0).

### 4. Frontend Build Check
- **Command:** `npm run build` in `gui/`
- **Result:** **Success in 2.54s** (0 TypeScript errors, Vite assets generated, Exit code: 0).

---

## J. Claim Reconciliation

| Historical Claim | Evidence / Inspection Status | Classification |
| :--- | :--- | :--- |
| **Stale Mission Stop/Pause Reconciliation** | Verified in `core/server/runtime_adapter.py` and `tests/test_stale_running_control_reconciliation.py` (14/14 passed). | **CONFIRMED BY TEST** |
| **NameError: Path is not defined in write_file** | Module inspection shows `from pathlib import Path` is present. Isolated probe wrote and read file successfully. | **CONTRADICTED BY CURRENT SOURCE** |
| **Greenfield Stalling in Empty Workspaces** | Traced to naive `"existing application"` substring check in `core/agent_loop/loop.py` line 286. | **CONFIRMED IN SOURCE** |
| **Event Stream UI Emptiness** | Traced to `sync.ts` filtering out all events `< last_sequence` upon snapshot arrival. | **CONFIRMED IN SOURCE** |
| **Canonical Python Interpreter Enforcement** | Verified in `scripts/launch_gui.ps1`, `hermes.bat`, `hermes.cmd`, and `core/server/launcher.py`. | **CONFIRMED IN SOURCE** |

---

## K. Prioritized Defect Register

### Defect 1: False-Positive Existing Codebase Classification
- **ID:** `DEFECT-P0-01`
- **Severity:** **Critical**
- **Location:** `core/agent_loop/loop.py` (lines 270–295)
- **Root Cause:** A prompt containing safety guidance (e.g. *"If existing application files are present..."*) triggers naive substring matching against `"existing application"`, causing greenfield tasks in empty directories to fail immediately with `EMPTY_WORKSPACE_EXISTING_APPLICATION`.
- **Consequence:** HERMES refuses to build applications from scratch in clean workspaces whenever standard safety instructions mention existing code.
- **Recommended Phase:** Phase 1
- **Safest Regression Test:** A deterministic unit test testing `AgentLoop` preflight with prompts specifying greenfield builds that contain negative/conditional references to existing code.

### Defect 2: Real-time Event Stream Purge on Snapshot Arrival
- **ID:** `DEFECT-P0-02`
- **Severity:** **High**
- **Location:** `gui/src/sync.ts` (lines 67–70) & `gui/src/components/ActivityPanel.tsx`
- **Root Cause:** `processIncomingSnapshot` discards all stream events whose sequence is less than or equal to `snapshot.last_sequence`. When reopening or inspecting completed/failed missions, the activity panel shows 0 events despite thousands of recorded sequence events.
- **Consequence:** The user sees a high event count in the header but an empty activity stream drawer.
- **Recommended Phase:** Phase 1 / Phase 2
- **Safest Regression Test:** Test `sync.ts` snapshot reconciliation to ensure a historical replay window or initial journal fetch is retained for UI display.

### Defect 3: Stale Server Process vs Disk Code Desynchronization
- **ID:** `DEFECT-P0-03`
- **Severity:** **High**
- **Location:** `core/server/launcher.py`
- **Root Cause:** When `launch_server()` detects an existing process on port 8765, it checks `verify_hermes_health()`. If healthy, it simply opens the browser without checking if the running server is executing out-of-date code.
- **Consequence:** Source fixes applied to disk are not loaded if an older server instance remains active in the background.
- **Recommended Phase:** Phase 1
- **Safest Regression Test:** Health endpoint and launcher version/timestamp handshake verification test.

---

## L. Proposed Next-Phase Order (Phase 1 Scope)

1. **Phase 1.1: Intelligent Intent & Greenfield Classification Refinement**
   - Refactor `core/agent_loop/loop.py` preflight check to use contextual intent classification rather than raw string matching.
   - Distinguish between requests to create a new project vs requests targeting an existing project.
2. **Phase 1.2: Event Journal Replay for Frontend Activity View**
   - Provide a safe REST endpoint (`/api/missions/{mission_id}/events`) to fetch the most recent N historical events on mission load so that `ActivityPanel` truthfully reflects historical progress.
3. **Phase 1.3: Launcher Build & Version Handshake**
   - Update launcher health checks to report code version/commit hash and detect stale running processes.

---

## M. Explicit Limitations

1. **No Live Server Running:** Port 8765 was unoccupied during this audit; live HTTP GET requests to a running instance could not be executed without starting the server (strictly prohibited by Phase 0 rules).
2. **Historical NameError Reproduction:** Because the current source code contains all necessary `pathlib.Path` imports and passed the probe, the previous `NameError: name 'Path' is not defined` could not be reproduced in the current checkout.
3. **No External Model Calls:** In accordance with safety rules, no live NVIDIA or Ollama model calls were initiated.
