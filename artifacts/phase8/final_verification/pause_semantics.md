# HERMES Phase 8 — Pause Semantics, Lifecycle & Boundary Confirmation

## 1. Problem Statement & Audit Reconciliation

In distributed execution architectures, race conditions can occur between Pause, Resume, and Stop:
1. **Resume-before-Confirmation Race:** Pause is requested while a task is running. While the executor approaches its safe checkpoint boundary, the user clicks Resume. The delayed pause confirmation must not subsequently pause the mission or emit a spurious `MISSION_PAUSED` event.
2. **Stop-before-Confirmation Race:** Pause is requested. Before confirmation occurs, the user clicks Stop. The delayed pause confirmation must not resurrect the stopped mission or emit `MISSION_PAUSED`.
3. **Terminal Immunity:** Terminal missions (`is_terminal = True`) must never be paused, and requests to pause them must be rejected immediately.

## 2. Hardened Architecture & Formal Invariants

### 2.1 State Invariant Definition

1. **Pause Pending:**
   - Invariant: `pause_requested = True`, `is_paused = False`.
   - `pause_event.clear()` signals the executing loop to pause upon reaching its boundary.
   - Endpoint returns `status = "PAUSE_REQUESTED", paused = False`.
   - Snapshot exposes `pause_pending = True, is_paused = False`.
   - UI reflects `PAUSE PENDING` badge and disables Pause button with `Pausing…`.

2. **Pause Confirmed:**
   - Invariant: `is_paused = True`, `pause_requested = False`.
   - Transition occurs exclusively at the defined loop checkpoint boundary (`core/agent_loop/loop.py:291-329`).
   - `ctrl.confirm_pause()` is guarded by: `if self.is_terminal or not self.pause_requested: return`.
   - `MISSION_PAUSED` is emitted exclusively upon confirmation.
   - Snapshot exposes `pause_pending = False, is_paused = True`.
   - UI reflects `PAUSED` badge and enables `Resume` button.

3. **Live Resume:**
   - Invariant: `is_paused = False`, `pause_requested = False`.
   - `ctrl.resume()` sets `pause_event.set()`.
   - If pause was pending (pre-boundary), Resume cancels the pending request without emitting spurious unpause events.
   - If pause was confirmed, `MISSION_RESUMED` is emitted.
   - Live `run_id` and `attempt_number` are strictly preserved without cold restarts.

4. **Terminal Stop:**
   - Invariant: `is_terminal = True`, `is_paused = False`, `pause_requested = False`.
   - `stop_mission()` triggers abort signal (`abort_event.set()`), cancels active tasks, and sets `ctrl.is_terminal = True`.
   - A subsequent delayed `confirm_pause()` or `request_pause()` is an immediate no-op.
   - Calling `/api/missions/{id}/pause` on a terminal mission returns HTTP `409 Conflict`.
   - Calling `/api/missions/{id}/resume` on a terminal mission returns HTTP `409 Conflict`.

## 3. Concurrency & Race Condition Proofs

### 3.1 Critical Interleaving 1 — Resume just before confirmation (`test_13`)
- **Ordering:**
  1. Mission is executing actively.
  2. Pause is requested (`POST /pause`) $\to$ `pause_requested = True`, `is_paused = False`.
  3. Executor reaches the safe boundary gate immediately before `confirm_pause()`.
  4. Resume is issued (`POST /resume`) $\to$ cancels pending pause: `pause_requested = False, is_paused = False, pause_event.set()`.
  5. Executor proceeds through the confirmation path:
     - Re-verifies condition: `elif pause_event.is_set() or not ctrl.pause_requested: pass`.
     - `confirm_pause()` is skipped (and guarded against `not pause_requested`).
     - `MISSION_PAUSED` is **not** emitted.
     - No blocking on `pause_event`.
  6. Final State:
     - `is_paused = False`, `pause_requested = False`.
     - No `MISSION_PAUSED` event exists in the history.
     - Live `run_id` and `attempt_number` are identical.
     - Snapshot reports `is_paused = False, pause_pending = False`.
     - Execution continues uninterrupted.

### 3.2 Critical Interleaving 2 — Stop just before confirmation (`test_12`)
- **Ordering:**
  1. Mission is executing actively.
  2. Pause is requested (`POST /pause`) $\to$ `pause_requested = True, is_paused = False`.
  3. Executor reaches the safe boundary gate immediately before `confirm_pause()`.
  4. Stop is issued (`POST /stop`) $\to$ abort signal set, active task cancelled, `control.is_terminal = True, pause_requested = False, is_paused = False`.
  5. Executor proceeds through the confirmation path:
     - Re-verifies condition: `if abort_event.is_set() or ctrl.is_terminal: break`.
     - `confirm_pause()` is skipped.
     - `MISSION_PAUSED` is **not** emitted.
     - Delayed `confirm_pause()` attempts return immediately due to `is_terminal == True`.
  6. Final State:
     - `is_terminal = True`, `is_paused = False`, `pause_requested = False`.
     - No `MISSION_PAUSED` event exists in the history.
     - Snapshot reports `is_terminal = True, is_paused = False, pause_pending = False`.
     - Calling Resume is rejected with HTTP `409 Conflict`.

## 4. Verification Evidence

- `tests/test_phase1_mission_lifecycle.py::test_scenario_g_run_control_pause_resume_contracts`: Lifecycle contract baseline (7/7 passed).
- `tests/test_phase4_stop_control.py`: Stop control and non-blocking cancellation (8/8 passed).
- `tests/test_phase8_gui_integration.py::test_9_pause_pending_vs_confirmed_lifecycle_boundary`: Two-stage pause lifecycle boundary.
- `tests/test_phase8_gui_integration.py::test_12_stop_races_with_pending_pause_cannot_be_overwritten`: Critical Interleaving 2 barrier test.
- `tests/test_phase8_gui_integration.py::test_13_resume_races_with_pending_pause_preserves_identity`: Critical Interleaving 1 barrier test.
- `tests/test_phase8_gui_integration.py::test_14_pause_idempotency_and_terminal_protection`: Pause idempotency and terminal mission rejection (409 Conflict).
