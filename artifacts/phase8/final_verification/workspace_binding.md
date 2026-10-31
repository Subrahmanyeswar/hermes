# HERMES Phase 8 — Immutable Workspace Binding & Project Hub Integrity

## 1. Problem Statement & Audit Reconciliation

A critical safety invariant in multi-workspace environments is preventing "silent fallback":
- If an existing mission is inspected while the user has switched the Project Hub to a different active workspace, or if the original workspace directory is deleted or missing, the system must **never** silently fall back to `workspace_manager.workspace_root` or `Path.cwd()`.
- Silent fallback would cause reads, modifications, diff calculations, or resumed operations to execute against the wrong workspace directory, corrupting files.

## 2. Hardened Architecture & Binding Invariants

### 2.1 Elimination of Silent Fallbacks

In `core/server/app.py:get_mission_snapshot()`:
```python
raw_ws = state.mission.workspace_root or (m_row.get("workspace_path") if (m_row and isinstance(m_row, dict)) else None)
if not raw_ws:
    ws_val = "UNRESOLVED_WORKSPACE"
    recovery_req_val = True
    wait_reason_val = "MISSING_WORKSPACE"
else:
    ws_val = str(raw_ws)
    try:
        if not Path(raw_ws).exists():
            recovery_req_val = True
            wait_reason_val = "WORKSPACE_NOT_FOUND"
    except Exception:
        recovery_req_val = True
        wait_reason_val = "WORKSPACE_NOT_FOUND"
```
And in `resume_mission_endpoint`:
```python
ws_root = m_row.get("workspace_path", "") if m_row else (control.workspace_root or "")
```
No fallback to `Path.cwd()` or `current_workspace` exists.

### 2.2 Invariant Guarantees

1. **Original Binding Preservation:** An existing mission always retains the absolute workspace path allocated at its creation (`MISSION_CREATED` event and `missions` database record).
2. **Project Switch Independence:** Switching the active workspace via `POST /api/workspaces/select` alters the hub state for *new* missions only. Any historical or in-flight mission snapshot continues to report and bind to its original directory.
3. **Explicit Blocking on Inaccessible Workspace:** If the directory bound to a mission is deleted, moved, or missing on disk:
   - Snapshot explicitly returns `recovery_required = True`.
   - Snapshot sets `wait_reason = "WORKSPACE_NOT_FOUND"` (or `"MISSING_WORKSPACE"`).
   - Resumption is blocked until the workspace path is reconciled or restored.

## 3. Verification Evidence

- `tests/test_phase8_gui_integration.py::test_7_project_hub_immutable_mission_workspace_binding`: Starts Mission A bound to Workspace $\alpha$, selects Workspace $\beta$ via `POST /api/workspaces/select`, and verifies Mission A's snapshot remains strictly bound to Workspace $\alpha$.
- `tests/test_phase8_gui_integration.py::test_11_immutable_workspace_missing_or_unresolved_reports_blocking`: Configures a mission bound to a non-existent directory; verifies `GET /api/missions/{id}` reports `workspace_root` preserved, `recovery_required=True`, and `wait_reason="WORKSPACE_NOT_FOUND"` with zero silent redirection.
- `tests/test_stage9_workspace_hub.py::test_scenario_f_immutable_mission_workspace_snapshot`: Verifies workspace binding across session switching.
