# HERMES Phase 10 — Release Invariant Matrix

**Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 10 — Fault Injection, End-to-End Recovery & Release Acceptance Gate  
**Execution Date:** 2026-10-13  
**Status:** PASS — ALL 10 INVARIANTS SATISFIED & LOCKED

---

## 1. System Invariants Audit

| Invariant ID | Domain | Invariant Definition | Enforcement Mechanism | Verification Evidence | Status |
|:---:|:---|:---|:---|:---|:---:|
| **INV-01** | Workspace Boundary | A mission can NEVER read, write, or execute commands outside its locked workspace root. | Component-aware path resolution, symlink/junction rejection, `WorkspaceBoundaryError`. | `tests/test_phase10_filesystem_and_journal_truth.py`<br>`tests/test_phase9_path_containment.py` | **LOCKED** |
| **INV-02** | Workspace Binding | An existing mission's workspace binding is permanently immutable; it cannot silently switch to another selected project. | SQLite `workspace_path` schema constraint, `save_mission` conflict protection, API resolver. | `test_duplicate_mission_creation_preserves_binding`<br>`test_scenario_b_original_workspace_binding...` | **LOCKED** |
| **INV-03** | Terminal Protection | Terminal states (`CANCELLED`, `COMPLETED`) are permanent and immutable. They cannot be paused, resumed, or overridden by delayed events. | `is_terminal` state machine checks, HTTP 409 fencing, reducer terminal lock. | `test_terminal_mission_cannot_be_resumed_or_paused`<br>`test_stop_racing_with_pending_pause_terminal_wins` | **LOCKED** |
| **INV-04** | Pause Safety | Pause is never confirmed before execution actually pauses; Resume clears pending pause without deadlocks. | Explicit `confirm_pause` handshake, `pause_event` cooperative interruption. | `test_resume_racing_with_pause_no_deadlock`<br>`test_2_pause_endpoint_and_event_publishing` | **LOCKED** |
| **INV-05** | Truthful Waiting | Network loss transitions to `WAITING` with accurate reasons (`WAITING_FOR_NETWORK` vs `WAITING_FOR_PROVIDER`); never reports false success. | Reducer status transition checks, `ConnectivityMonitor` hysteresis, `NetworkRecoveryCoordinator`. | `test_global_internet_loss_transitions_to_waiting`<br>`test_provider_outage_distinguished_from_internet_loss` | **LOCKED** |
| **INV-06** | Bounded Retries | Transport failures must not cause endless retries or resource exhaustion. | Route-scoped circuit breakers (`CircuitBreakerRegistry`), 3-failure threshold, cooldown windows. | `test_circuit_breaker_trips_and_prevents_endless_retry` | **LOCKED** |
| **INV-07** | Secret Protection | Authentication tokens and API keys are strictly redacted from logs, errors, journals, and API payloads. | `sanitize_error_text`, regex token scrubbers (`nvapi-*`, `sk-*`, `Bearer`). | `test_secret_redaction_in_transport_errors` | **LOCKED** |
| **INV-08** | Transaction Atomicity | SQLite persistence operations must be atomic; interrupted operations roll back cleanly without partial writes. | Explicit `with db.transaction():` context manager, write-ahead logging (WAL). | `test_journal_transaction_atomicity_and_rollback` | **LOCKED** |
| **INV-09** | Monotonic Ordering | Event sequences are strictly monotonic and gapless; client rejects out-of-order, stale, or duplicate events. | Central atomic sequence counter in `EventBus`, client-side watermark checks (`gui/test_snapshot_race.mjs`). | `test_event_journal_monotonic_sequences_and_replay_truth`<br>`test_snapshot_race.mjs` (5/5 PASS) | **LOCKED** |
| **INV-10** | 4-Tier Coherence | Transport, journal, persistence, and presentation layers must agree on mission status, wait reason, and recovery state. | Cross-layer reconciliation pipeline, canonical snapshots. | `test_four_tier_truthfulness_reconciliation` | **LOCKED** |

---

## 2. Release Acceptance Summary

All 10 critical system invariants are covered by automated fault-injection and regression tests. No contradictions, memory leaks, or race conditions remain.
