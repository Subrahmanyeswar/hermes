# HERMES 2.x — Recovery, Replay & Rewind Model

## 1. Overview & Operational Philosophy

The HERMES 2.x recovery model guarantees deterministic resumption after interruption and clean rollback when an agent pursues a defective repair strategy.

```text
INTERRUPTED RUNTIME
       ↓
[1. Lock Validation] (Stale PID check, mutual exclusion)
       ↓
[2. Checkpoint Manifest & CAS Integrity] (SHA-256 cross-validation)
       ↓
[3. Pure State Deserialization] (Zero tool execution)
       ↓
[4. Event Journal Replay] (Deterministic mathematical reduction)
       ↓
[5. Multi-Domain Reconciliation] (FS drift, Git drift, background jobs, provider sockets)
       ↓
[6. Security & Evidence Invalidation] (Stale grants cleared, tainted checks set to NOT_RUN)
       ↓
RECONSTRUCTED AUTHORITATIVE STATE
```

---

## 2. The 16-Step Deterministic Resume Sequence

When `RecoveryEngine.resume_session(session_id)` is invoked, it strictly executes this sequence:

1. **Session Lookup:** Fetch `DurableSession` record from SQLite.
2. **Mutual Exclusion:** Acquire `SessionLock`. If held by an active process, verify PID liveness (Windows `OpenProcess` / Unix `os.kill`). If active on another host/PID, fail cleanly with `ResumeConflict`.
3. **Session Status Validation:** Ensure session is `PAUSED`, `INTERRUPTED`, or `CREATED`.
4. **Identify Checkpoint:** Locate target checkpoint manifest (either latest or specified).
5. **CAS Integrity Verification:** Check SHA-256 hash of all referenced file blobs in `BlobStore`.
6. **State Hash Verification:** Verify state blob hash against SQLite row and manifest.
7. **Load Base State:** Reconstruct typed `HermesRuntimeState` using `deserialize_runtime_state()`.
8. **Journal Replay:** Replay uncommitted events sequence $> \text{checkpoint.sequence}$ using `StateReducer.reduce()`. **Zero tool execution.**
9. **Reconcile Filesystem Drift:** Compare actual disk state against target checkpoint manifest.
10. **Reconcile Git Drift:** Inspect current Git HEAD SHA and working tree without running destructive resets.
11. **Reconcile Background Jobs:** Reconnect to running processes; mark orphaned jobs as `ORPHANED`.
12. **Reinitialize Provider Sockets:** Reset network transport client sockets with fresh monotonic deadlines.
13. **Expire Stale Security Grants:** Revoke single-use or expired approval grants.
14. **Invalidate Tainted Evidence:** If files changed during offline drift, mark dependent acceptance checks as `NOT_RUN`.
15. **Status Transition:** Set session status to `RUNNING` and record monotonic timestamp.
16. **Emit Lifecycle Event:** Publish `SESSION_RESUMED` event to the EventBus.

---

## 3. Rewind Engine & Conflict Ownership Semantics

When rewinding to a known-good checkpoint, HERMES strictly enforces:

> **USER CHANGES MUST WIN BY DEFAULT**
> An automated agent must never overwrite human edits simply because a rollback was requested.

### 3-Way Conflict Classification:
`ConflictDetector.compute_plan()` analyzes:
- **Base Checkpoint:** The target state to restore.
- **Disk Current:** The actual filesystem state.
- **Agent Attribution:** The set of files created or mutated by the agent.

| Scenario | Disk vs Checkpoint | Ownership | Plan Action |
|---|---|---|---|
| File modified by agent | Differs | Agent Created/Edited | `OVERWRITE_FROM_BLOB` |
| File modified by user | Differs | User Modified | `PRESERVE_USER_EDIT` (Conflict warning) |
| File created by agent | In Disk, Not in Checkpoint | Agent Created | `DELETE_ORPHANED_AGENT_FILE` |
| File created by user | In Disk, Not in Checkpoint | User Created | `PRESERVE_USER_EDIT` |
| File deleted on disk | In Checkpoint, Not on Disk | Agent Deleted | `RESTORE_DELETED_FILE` |

### Rewind Modes:
- **`CODE_ONLY`:** Workspace files restored from CAS blobs; conversation transcript and session history are untouched.
- **`CONVERSATION_ONLY`:** Workspace left as-is; conversation truncated back to checkpoint sequence.
- **`CODE_AND_CONVERSATION`:** Full logical rollback. Files restored, state restored, stale acceptance checks invalidated.

---

## 4. Evidence Invalidation & Re-verification

When a rewind or offline drift modifies workspace files:
1. `EvidenceInvalidator` computes the exact set of altered files.
2. `AcceptanceLedger.mark_stale_for_files(modified_files)` marks all checks referencing those files as `NOT_RUN`.
3. Cached verification digests are cleared.
4. T1 self-repair or execution must re-prove passing status by running real deterministic tests.

---

## 5. "Where Was I?" Selector

HERMES provides complete introspective state projection via `get_where_was_i(state, session)`:
- **`what_completed`**: List of passing acceptance checks and verified requirements.
- **`what_failed`**: Outstanding failing checks and known errors.
- **`what_changed`**: Modified files relative to last checkpoint.
- **`next_action`**: Authoritative next step from `ProgressState.next_action`.
- **`recommended_rewind`**: ID of the latest known-good checkpoint if current progress is failing.
