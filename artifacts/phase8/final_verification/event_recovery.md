# HERMES Phase 8 — Ordered Event Recovery, Snapshot Watermarks & Stale Event Protection

## 1. Problem Statement & Audit Reconciliation

In distributed client-server applications with server-sent events (SSE) and snapshot polling, race conditions arise when:
1. **Delayed Snapshot Regression:** Snapshot request $A$ is sent at sequence $S=10$. Before $A$ returns, a newer real-time event $E$ at sequence $S=11$ arrives and is applied by the client. When $A$ returns later, it must NOT roll back the client's state to sequence 10 or erase event $E$.
2. **Duplicate Events:** SSE reconnects or query cursors replay events that the client already applied.
3. **Stale / Old-Run Events:** After cold recovery (attempt $N+1$), events from attempt $N$ or prior runs could arrive and corrupt state.
4. **Cross-Mission Leakage:** Events or snapshots from another mission could leak into the active view during project switching.

## 2. Hardened Architecture & Client Synchronization

### 2.1 Pure Synchronization Layer (`gui/src/sync.ts`)

To ensure deterministic verification without browser dependency, synchronization logic was extracted into a pure TypeScript module (`gui/src/sync.ts`):
- `ClientSyncState`: Maintains `snapshot`, `events`, and `lastWatermark: { state_version, last_sequence }`.
- `processIncomingSnapshot(currentState, incomingSnapshot)`:
  - **Guard 1 (Mission Isolation):** Rejects snapshots where `incomingSnapshot.mission_id !== currentState.snapshot.mission_id`.
  - **Guard 2 (Monotonic Watermark):** Rejects snapshots where `state_version < watermark.state_version` or `last_sequence < watermark.last_sequence`.
  - **Reconciliation:** Updates watermark and retains real-time events whose sequence exceeds `incomingSnapshot.last_sequence`.
- `processIncomingEvent(currentState, incomingEvent)`:
  - **Guard 1 (Mission Isolation):** Rejects events with mismatched `mission_id`.
  - **Guard 2 (Stale Attempt):** Rejects events where `event.attempt_number < snapshot.attempt_number`.
  - **Guard 3 (Deduplication):** Discards events matching an existing sequence or `event_id`.
  - **Guard 4 (Monotonicity):** Advances sequence watermark monotonically.

### 2.2 Proof of the Delayed-Snapshot Race Condition

The 5-step scenario specified in Section 4 was verified by `gui/test_snapshot_race.mjs`:
1. **Step 1:** Frontend has established state at sequence $S = 10, \text{state\_version} = 10$.
2. **Step 2:** Snapshot request $A$ is in flight (capturing state at $S = 10, \text{ver} = 10$).
3. **Step 3:** Live event arrives via SSE at sequence $S = 11$, advancing client watermark to $S = 11, \text{ver} = 11$.
4. **Step 4:** Delayed snapshot $A$ returns later ($S = 10, \text{ver} = 10$).
5. **Step 5:** Delayed snapshot $A$ is evaluated:
   - Rejected by monotonic watermark check (`10 < 11`).
   - Client state is **not** rolled back.
   - Sequence watermark remains at 11.
   - Event at sequence 11 is **not** erased.

### 2.3 Backend Invariants & Event Deduplication

- `EventBus.publish()` assigns monotonic sequence numbers and deduplicates events by `event_id`.
- `StateStore` tracks `state_version` and `last_event_sequence` monotonically (`test_15`).
- `StateReducer` drops events from prior attempts or mismatched run IDs (`test_10`).

## 3. Verification Evidence

- `gui/test_snapshot_race.mjs`: Node.js test script proving:
  - Delayed snapshot rejection against live event (Step 1–5 proof).
  - Stale attempt number rejection.
  - Duplicate event deduplication.
  - Cross-mission event and snapshot isolation.
  - Newer snapshot acceptance and proper buffer reconciliation.
- `tests/test_phase8_gui_integration.py::test_6_ordered_event_replay_and_cursor_tracking`: Verifies sequence ordering and replay from cursor.
- `tests/test_phase8_gui_integration.py::test_10_stale_and_old_run_event_rejection`: Verifies StateReducer drops stale attempt events.
- `tests/test_phase8_gui_integration.py::test_15_delayed_snapshot_watermark_invariants`: Verifies backend store and snapshot API monotonic watermark invariants and deduplication.
