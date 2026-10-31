# HERMES — Stage 9 Acceptance Report
**Antigravity-Inspired Project Hub, Native Folder Picker, and Safe Workspace Switching**

**Status:** COMPLETE & VERIFIED  
**Date:** 2026-10-12  
**Canonical Environment:** `C:\Users\SUBBU\Downloads\hermes`  
**Python Executable:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`  
**Frontend Bundle:** `gui/dist` (Vite production build verified clean)

---

## 1. Executive Summary

In Stage 9, the HERMES graphical interface was upgraded with a Google Antigravity-inspired **Project Hub** that allows users to:
1. Open and browse arbitrary local directories on Windows via a **native Windows folder picker** (`POST /api/workspaces/pick-folder`) running non-blocking background threads.
2. Select, register, and switch between project workspaces dynamically (`POST /api/workspaces/select`) with persistent history in `data/recent_workspaces.json`.
3. Retain **immutable workspace binding** per mission: tasks created under Project A execute, record diffs, run verification checks, and log artifacts strictly inside Project A, regardless of subsequent GUI project switches.
4. Prevent accidental execution against the HERMES runtime repository itself via the **HERMES Root Guard**, displaying an amber warning badge in the header/sidebar and requiring explicit modal confirmation before task submission.

All 8 scenarios and regression suites (87/87 tests across Stages 0–7.2 + Stage 9) passed 100%.

---

## 2. Core Architectural Components Implemented

### 2.1 Persistent Workspace Registry (`core/workspace_registry.py`)
- Thread-safe (`threading.RLock`) registry persisting recent workspaces to `data/recent_workspaces.json`.
- Automatic light directory inspection (up to 1,000 files) detecting framework (Node/Web, Python, Rust) and top programming language.
- Pruning mechanism that automatically removes non-existent or temporary directories from the active list.
- Authoritative `is_hermes_repo_root()` check resolving symlinks and casing to identify if a path is the HERMES engine codebase itself.

### 2.2 Backend Workspace Hub APIs (`core/server/app.py`, `core/server/models.py`)
- `GET /api/workspaces`: Lists registered workspaces with name, active flag, file count, detected framework, and HERMES root indicator.
- `POST /api/workspaces/select`: Sets active project folder, validates existence and directory type, re-locks workspace manager.
- `POST /api/workspaces/pick-folder`: Uses Windows native Tkinter dialog (`filedialog.askdirectory`) offloaded via `asyncio.to_thread` with concurrency locks to prevent overlapping dialogs and thread blocking.
- `DELETE /api/workspaces/recent`: Removes a project from recent history without modifying or deleting files on disk.

### 2.3 Antigravity-Inspired Frontend Project Hub
- **Sidebar Project Hub** (`gui/src/components/LeftPane.tsx`):
  - Prominent `+ New Task` button scoped to active project.
  - `+ Open Project` button launching native Windows folder picker.
  - Searchable list of recent projects with active checkmark badge, file counts, and tooltip showing canonical Windows absolute path.
  - Remove button (`trash`) to drop from recents list without touching disk files.
  - Mission history filtered to past missions.
- **Header Project Display** (`gui/src/components/TopBar.tsx`):
  - Active project name badge with folder icon.
  - Quick-switch action icon and click-to-copy canonical path pill.
  - `HERMES ROOT` amber warning badge when targeting the runtime engine.
- **HERMES Root Guard Modal** (`gui/src/components/HermesRootModal.tsx`):
  - Triggered automatically if a user attempts to submit a task while the active project is the HERMES repository root.
  - Explains risks to agent core files and offers 1-click **Cancel (Switch Project)** or explicit **Proceed Against HERMES Root**.

---

## 3. Verification & Acceptance Results

### 3.1 Stage 9 Acceptance Suite (`tests/test_stage9_workspace_hub.py`)
| Test ID | Scenario Description | Status |
| :--- | :--- | :--- |
| `test_scenario_a` | Initial project discovery and active project presentation | **PASSED** |
| `test_scenario_b` | Native folder picker execution and safe cancellation handling | **PASSED** |
| `test_scenario_c` | Selecting arbitrary local folder updates active project and recents | **PASSED** |
| `test_scenario_d_and_e` | Immutable task workspace binding and cross-switching isolation | **PASSED** |
| `test_scenario_f` | Historic mission snapshots remain bound to creation workspace | **PASSED** |
| `test_scenario_g` | HERMES repository root detection flags protected guard | **PASSED** |
| `test_scenario_h` | Security & boundary validation: non-existent/file paths rejected (400) | **PASSED** |
| `test_scenario_i` | Removing from recent workspaces preserves disk content | **PASSED** |

### 3.2 Full Repository Regression Baseline
- **Files executed:** 13 test files (`test_stage2` through `test_stage7_2` + `test_stage9`)
- **Total tests executed:** 87
- **Total passed:** 87 (100% pass rate in 22.09s)

### 3.3 Production GUI Build
- Command: `npm run build` in `gui/`
- Result: Clean build with 0 TypeScript errors (`tsc && vite build` succeeded in 1.90s).

---

## 4. Evidence Artifacts Generated

The following artifacts have been generated in `artifacts/stage9/`:
- `artifacts/stage9/stage9_project_hub_initial.png`: Browser capture showing initial Project Hub sidebar with projects list, active indicator, and New Task button.
- `artifacts/stage9/stage9_project_hub_switched.png`: Browser capture showing dynamic project switch to external project `smoke_test_ws`.
- `artifacts/stage9/stage9_hermes_root_guard_active.png`: Browser capture showing `HERMES ROOT` amber protection badge in Header and LeftPane.
- `artifacts/stage9/workspace_switching_evidence.json`: Detailed registry switching audit log.
- `artifacts/stage9/mission_workspace_binding.json`: Immutable binding verification record.
- `artifacts/stage9/security_and_path_tests.json`: Security, traversal, and validation summary.
