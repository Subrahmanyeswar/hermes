# HERMES v1.0.0-rc1 (Architecture Phase 4) — Operator Guide & Launch Manual

This guide provides operational instructions for running, operating, diagnosing, and maintaining the HERMES Release Candidate (`v1.0.0-rc1`, Phase 4) in day-to-day software engineering workflows.

---

## 1. Prerequisites & Environment

HERMES requires **Python 3.12.x** installed inside its canonical virtual environment.

- **Canonical Repository Root**: `C:\Users\SUBBU\Downloads\hermes`
- **Canonical Python Interpreter**: `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`
- **Python Version**: Verified target `3.12.0`

> [!IMPORTANT]
> Never launch HERMES using a global Python 3.10, 3.11, or 3.13 installation. Launching outside the canonical Python 3.12 virtualenv triggers an immediate runtime guard exit.

---

## 2. Launching HERMES

### Windows Batch Launcher (`hermes.bat`)

HERMES includes a single-entry launcher that resolves directory contexts and sets `PYTHONPATH`:

```cmd
:: 1. Launch interactive TUI (default when no args provided)
.\hermes.bat

:: 2. Launch system health & environment diagnostics
.\hermes.bat doctor

:: 3. Run a direct headless engineering mission
.\hermes.bat run "Build an analytics dashboard with FastAPI and pytest" --workspace "C:\path\to\workspace"

:: 4. Explicit UI launch
.\hermes.bat ui
```

---

## 3. The Qualified Model Stack

HERMES uses a three-tier model hierarchy with zero-wait adaptive failover:

| Tier | Role | Provider | Model | Failure Policy |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | Fast Generation | NVIDIA NIM | `z-ai/glm-5.3-flash` | SSE streaming with fast-failover & circuit breaker |
| **Tier 2** | Verification | Ollama Cloud | `gpt-oss:120b-cloud` | Fast-path verifier & fallback generation |
| **Tier 3** | Arbitration | Ollama Cloud | `nemotron-3-ultra:cloud` | Escalation on semantic disagreement |

All API credentials (`NVIDIA_API_KEY`, etc.) are automatically redacted from console output and JSONL logs.

---

## 4. TUI Operation: Submitting Work, Observing Progress, and STOP

### Submitting Work
1. Launch `.\hermes.bat`.
2. In the bottom input bar, type your engineering request and press `Enter` or click `SEND`.
3. The UI state immediately transitions to `is_processing = True` within sub-10ms latency. The input box is non-blocking.

### Observing Progress
- **Status Bar**: Displays active model tier (`T1: z-ai/glm-5.3-flash`), spinner state, token budget, and provider health.
- **Provider Health Badges**:
  - `T1:OPEN` (Red): Tier 1 circuit is open due to upstream outage; work routes to Tier 2 without stall.
  - `T1:PROBING` (Blue): Background probe actively evaluating Tier 1 recovery.
  - `T1:RECOVERED` (Green): Tier 1 restored as primary engine.
  - `T2:FAILOVER` (Amber): Operating under secondary tier.
  - `T3:ARBITRATION` (Purple): Tier 3 arbitrating high-risk disagreement.
- **Progress Panel**: Displays live DAG execution milestones, current step, and verification results.

### Safely Stopping & Resuming
- **STOP Button**: Clicking `STOP` (or pressing `Escape` / `Ctrl+C`) signals cooperative cancellation (`abort_event.set()`). The runner halts the active task cleanly at the next checkpoint without leaving corrupted partial files or orphan processes.
- **Session Resumption**: Re-launching with `--session <session_id>` triggers physical filesystem reconciliation. Tasks whose output artifacts exist and are valid are satisfied; incomplete tasks resume execution.

---

## 5. Diagnosing Provider & Environment Failures

If you encounter network or provider errors:

```cmd
.\hermes.bat doctor
```

Or for verbose system diagnostics:

```cmd
.\venv\Scripts\python.exe main.py diagnostics
```

**Common issues & resolutions:**
- **Tier 1 Circuit Open**: If NVIDIA NIM experiences upstream rate-limits or network degradation, HERMES automatically opens the circuit and diverts to Tier 2. No operator intervention is required.
- **Ollama Gateway Unreachable**: Ensure the local Ollama daemon is running (`ollama serve`) if relying on local fallback endpoints.

---

## 6. Running Regressions & Verifications

### Canonical Stage 0–7.2 Release Acceptance Suites (13 files, 85 tests)
To verify the complete acceptance baseline across runtime reliability, event streaming, workspace security, process safety, real file execution, and concurrent isolation:

```cmd
.\venv\Scripts\python.exe -m pytest tests/test_runtime_reliability_gate.py tests/test_stage2_server_and_event_stream.py tests/test_stage3_gui_prototype_acceptance.py tests/test_stage4_review_and_diff_acceptance.py tests/test_stage4_1_audit_acceptance.py tests/test_stage5_launch_lifecycle.py tests/test_stage5_1_process_safety.py tests/test_stage6_real_execution.py tests/test_stage6_1_browser_correlation.py tests/test_stage6_2_goal_fulfillment.py tests/test_stage7_reliability_and_recovery.py tests/test_stage7_1_stalled_finalization.py tests/test_stage7_2_concurrent_isolation.py -v
```
All 85 tests should pass cleanly in ~20 seconds.

### Legacy Phase 4 Qualification Suites (11 files, 132 tests)
To verify legacy qualification criteria:

```cmd
.\venv\Scripts\python.exe -m pytest tests/test_phase4h_release_candidate.py tests/test_phase4g_acceptance_audit.py tests/test_phase4f_generalization.py tests/test_closure_regressions.py tests/test_forensic_regressions.py tests/test_mission_planner.py tests/test_phase4b_action_discipline.py tests/test_phase4c_fastpath.py tests/test_phase4d_adaptive_routing.py tests/test_phase4e_mission_optimization.py tests/test_phase4i_operational_release.py -v
```
All 132 tests should pass cleanly in ~35-40 seconds.

> [!NOTE]
> The backend `/api/health` endpoint verifies that the local server is alive and configured. It does not ping remote LLM providers or guarantee cloud quota. Provider connectivity is verified during actual mission execution or via `python main.py doctor`.

---

## 7. Graphical User Interface (Browser Harness)

HERMES features a modern React/Vite browser GUI backed by a FastAPI runtime server with live SSE streaming (`core.server`).

### Starting the GUI
In PowerShell:
```powershell
.\scripts\launch_gui.ps1
```
Or start in headless/background mode without automatically opening a browser:
```powershell
.\scripts\launch_gui.ps1 -NoBrowser
```
Or via Python CLI:
```powershell
.\venv\Scripts\python.exe -m core.server.launcher launch
```
The interface is served on `http://127.0.0.1:8765/`.

### Checking GUI Status
```powershell
.\venv\Scripts\python.exe -m core.server.launcher status
```

### Stopping the GUI
To cleanly stop the running server and release port 8765 without affecting any unrelated processes:
```powershell
.\scripts\stop_gui.ps1
```
Or via Python CLI:
```powershell
.\venv\Scripts\python.exe -m core.server.launcher stop
```
