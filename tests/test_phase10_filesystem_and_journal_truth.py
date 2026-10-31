# tests/test_phase10_filesystem_and_journal_truth.py
"""
HERMES Phase 10 — Filesystem Boundaries, Journal Atomicity & 4-Tier Truthfulness Tests.

Stages Tested:
- Stage H: Uncertain filesystem operations (Path escape prevention, partial write detection, disk-ledger reconciliation).
- Stage I: Journal consistency & transaction truth (SQLite transaction atomicity, monotonic sequences, replay determinism).
- Stage J: Truthful provider outcomes across transport, journal, snapshot, and API (Complete 4-tier reconciliation).
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.recovery import RecoveryEngine, ReconciliationDiscrepancyType
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionStatus, WaitReason
from core.runtime_state.store import StateStore
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.transport.types import ErrorCategory, StructuredTransportError
from core.workspace import WorkspaceBoundaryError, WorkspaceManager


@pytest.fixture
def truth_env(tmp_path):
    """Fixture providing isolated database, blob store, event bus, and runtime adapter."""
    ws = tmp_path / "workspace_truth"
    ws.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "test_truth.db"
    db = SQLiteDatabase(db_path)
    blob_store = BlobStore(tmp_path / "blobs")
    bus = EventBus(enabled=True, db=db)
    adapter = RuntimeAdapter(event_bus=bus)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    return {
        "workspace": ws,
        "db": db,
        "blob_store": blob_store,
        "bus": bus,
        "adapter": adapter,
        "app": app,
        "client": client,
        "tmp_path": tmp_path,
    }


# ── Stage H: Uncertain Filesystem Operations & Boundary Security ──────────────

def test_filesystem_boundary_escape_strictly_prevented(truth_env):
    """
    Stage H.1: Traversal attacks, sibling folder attacks, and absolute escape attempts
    are strictly rejected with WorkspaceBoundaryError.
    """
    ws = truth_env["workspace"]
    wm = WorkspaceManager()
    wm.lock(ws)

    # 1. Parent traversal escape
    with pytest.raises(WorkspaceBoundaryError):
        wm.validate_path("../outside_file.txt")

    # 2. Sibling folder prefix collision attack
    sibling = truth_env["tmp_path"] / f"{ws.name}-evil" / "exploit.py"
    with pytest.raises(WorkspaceBoundaryError):
        wm.validate_path(sibling)

    # 3. Legitimate internal path is permitted
    safe_path = ws / "src" / "module.py"
    resolved = wm.validate_path(safe_path)
    assert resolved == safe_path.resolve()


def test_uncertain_partial_file_write_reconciliation(truth_env):
    """
    Stage H.2: When a file write is interrupted or tampered externally,
    RecoveryEngine detects the hash discrepancy against the operations ledger.
    """
    db = truth_env["db"]
    blob_store = truth_env["blob_store"]
    ws = truth_env["workspace"]
    recovery = RecoveryEngine(db=db, blob_store=blob_store)

    mission_id = "m_file_reconcile"
    target_file = ws / "critical.py"
    target_file.write_text("corrupted content modified outside hermes", encoding="utf-8")

    # Record ledger operation with expected hash
    expected_hash = "abc123expectedhash"
    from core.persistence.models import OperationStatus
    db.record_tool_intent(
        operation_id="op_write_1",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path="critical.py",
        workspace_root=str(ws),
        prior_hash="none",
    )
    db.record_tool_result(
        operation_id="op_write_1",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=expected_hash,
    )

    discrepancies = recovery.reconcile_disk_with_ledger(mission_id=mission_id, workspace_root=ws)
    assert len(discrepancies) > 0
    disc = discrepancies[0]
    assert disc.discrepancy_type in (ReconciliationDiscrepancyType.USER_MODIFIED, ReconciliationDiscrepancyType.HASH_MISMATCH)
    assert "critical.py" in str(disc.path)
    assert disc.blocking is True


def test_real_subprocess_termination_uncertainty_reconciliation(truth_env):
    """
    Stage H.3: Real disposable process executes filesystem side-effects and crashes
    at the controlled window (after disk mutation, before durable result commit).
    Validates complete 8-step reconciliation and invariant preservation.
    """
    db = truth_env["db"]
    blob_store = truth_env["blob_store"]
    ws = truth_env["workspace"]
    tmp_path = truth_env["tmp_path"]
    recovery = RecoveryEngine(db=db, blob_store=blob_store)

    mission_id = "m_subproc_crash_win"
    op_id = "op_crash_window_01"
    target_rel = "critical_worker_output.py"
    target_file = ws / target_rel
    payload_content = "def execute_task():\n    return 'CRITICAL_PAYLOAD_SUCCESS'\n"
    expected_payload_bytes = payload_content.encode("utf-8")
    expected_hash = hashlib.sha256(expected_payload_bytes).hexdigest()

    # Step 8 prep: Create an unrelated workspace & file to verify untouched invariant
    unrelated_ws = tmp_path / "unrelated_workspace"
    unrelated_ws.mkdir(parents=True, exist_ok=True)
    unrelated_file = unrelated_ws / "unrelated_code.py"
    unrelated_initial_content = "# Unrelated original content\n"
    unrelated_file.write_text(unrelated_initial_content, encoding="utf-8")
    unrelated_mtime = unrelated_file.stat().st_mtime

    # Register mission in persistent database
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws),
        status="RUNNING",
        prompt="Execute critical worker mission",
    )

    # Disposable process script: records intent in SQLite, writes side effect, crashes before result record
    root_dir = str(Path(__file__).resolve().parent.parent)
    db_path_str = str(db.db_path)
    target_file_str = str(target_file)
    ws_str = str(ws)

    worker_script = (
        "import sys, pathlib\n"
        f"sys.path.insert(0, r'{root_dir}')\n"
        "from core.persistence.database import SQLiteDatabase\n"
        f"db = SQLiteDatabase(r'{db_path_str}')\n"
        # 1. Record durable operation intent in database
        f"db.record_tool_intent(\n"
        f"    operation_id='{op_id}',\n"
        f"    mission_id='{mission_id}',\n"
        f"    tool_name='write_file',\n"
        f"    intent_seq=1,\n"
        f"    target_path='{target_rel}',\n"
        f"    workspace_root=r'{ws_str}',\n"
        f"    arguments_summary='Worker writing critical code',\n"
        f"    arguments={{'path': '{target_rel}', 'content': {repr(payload_content)}}},\n"
        f"    prior_hash=None,\n"
        f")\n"
        # 2. Execute real filesystem side effect
        f"p = pathlib.Path(r'{target_file_str}')\n"
        f"p.write_bytes({repr(expected_payload_bytes)})\n"
        # Signal ready then wait for termination at the exact crash boundary
        "print('SIDE_EFFECT_EXECUTED', flush=True)\n"
        "import time\n"
        "time.sleep(30)\n"
    )

    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", worker_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait until child outputs SIDE_EFFECT_EXECUTED
    line = proc.stdout.readline()
    assert "SIDE_EFFECT_EXECUTED" in line, f"Disposable process failed before side effect: {proc.stderr.read()}"

    # 3. Terminate disposable process at controlled boundary (after side effect, before result commit)
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3.0)

    assert proc.poll() is not None, "Disposable worker process must be dead"

    # 4. Host restart recovery sequence
    # Simulate RuntimeAdapter restart reconciliation: scan interrupted operations
    from core.persistence.models import OperationStatus
    interrupted_ops = db.list_tool_operations(mission_id)
    assert len(interrupted_ops) == 1
    assert interrupted_ops[0]["status"] == OperationStatus.INTENT_COMMITTED.value
    # Transition interrupted uncommitted intent to OUTCOME_UNKNOWN
    db.update_operation_status(
        operation_id=op_id,
        status=OperationStatus.OUTCOME_UNKNOWN,
        error_message="INTERRUPTED_BY_CRASH: Process terminated before result record",
    )

    # 5. Inspect target bytes, existence, hash, operation record
    assert target_file.exists() is True
    actual_bytes = target_file.read_bytes()
    assert actual_bytes == expected_payload_bytes
    actual_hash = hashlib.sha256(actual_bytes).hexdigest()
    assert actual_hash == expected_hash

    persisted_op = db.get_tool_operation(op_id)
    assert persisted_op["status"] == OperationStatus.OUTCOME_UNKNOWN.value
    assert persisted_op["result_seq"] is None  # Result record was NEVER written

    # 6. Verify outcome is marked uncertain according to contract
    discrepancies = recovery.reconcile_disk_with_ledger(mission_id=mission_id, workspace_root=ws)
    assert len(discrepancies) == 1
    disc = discrepancies[0]
    assert disc.discrepancy_type == ReconciliationDiscrepancyType.OPERATION_UNCERTAIN
    assert disc.blocking is True
    assert disc.operation_id == op_id

    # 7. Verify no duplicate destructive side effect can execute (resume plan blocks)
    plan = recovery.formulate_resume_plan(mission_id)
    assert plan.can_resume is False
    assert "uncertain" in plan.reason.lower() or len(plan.discrepancies) > 0

    # 8. Confirm unrelated files and workspaces are 100% untouched
    assert unrelated_file.exists() is True
    assert unrelated_file.read_text(encoding="utf-8") == unrelated_initial_content
    assert unrelated_file.stat().st_mtime == unrelated_mtime


def test_partial_write_byte_length_and_hash_reconciliation(truth_env):
    """
    Stage H.4: Byte reconciliation detects truncated / partial writes where disk bytes
    and hash diverge from settled post_hash metadata.
    """
    db = truth_env["db"]
    blob_store = truth_env["blob_store"]
    ws = truth_env["workspace"]
    recovery = RecoveryEngine(db=db, blob_store=blob_store)

    mission_id = "m_partial_bytes"
    target_file = ws / "data_payload.bin"

    full_payload = b"A" * 1024
    expected_hash = hashlib.sha256(full_payload).hexdigest()

    # Simulate truncated write on disk: only 256 bytes written
    partial_payload = b"A" * 256
    target_file.write_bytes(partial_payload)
    actual_hash = hashlib.sha256(partial_payload).hexdigest()

    from core.persistence.models import OperationStatus
    db.record_tool_intent(
        operation_id="op_byte_recon",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path="data_payload.bin",
        workspace_root=str(ws),
        prior_hash="none",
    )
    db.record_tool_result(
        operation_id="op_byte_recon",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=expected_hash,
    )

    discrepancies = recovery.reconcile_disk_with_ledger(mission_id=mission_id, workspace_root=ws)
    assert len(discrepancies) > 0
    disc = discrepancies[0]
    assert disc.discrepancy_type == ReconciliationDiscrepancyType.USER_MODIFIED
    assert disc.blocking is True
    assert disc.expected_hash == expected_hash
    assert disc.actual_hash == actual_hash


def test_uncertain_move_and_delete_operations_reconciliation(truth_env):
    """
    Stage H.5: Uncertain move and delete operations are safely flagged
    prior to any mission resumption.
    """
    db = truth_env["db"]
    blob_store = truth_env["blob_store"]
    ws = truth_env["workspace"]
    recovery = RecoveryEngine(db=db, blob_store=blob_store)

    mission_id = "m_move_delete_recon"

    from core.persistence.models import OperationStatus
    # 1. Uncertain delete
    db.record_tool_intent(
        operation_id="op_del_uncertain",
        mission_id=mission_id,
        tool_name="delete_file",
        intent_seq=1,
        target_path="stale_file.py",
        workspace_root=str(ws),
        prior_hash="hash_old",
    )
    db.update_operation_status("op_del_uncertain", OperationStatus.OUTCOME_UNKNOWN)

    # 2. Uncertain move
    db.record_tool_intent(
        operation_id="op_move_uncertain",
        mission_id=mission_id,
        tool_name="move_file",
        intent_seq=2,
        target_path="migrated_file.py",
        workspace_root=str(ws),
        prior_hash="hash_src",
    )
    db.update_operation_status("op_move_uncertain", OperationStatus.OUTCOME_UNKNOWN)

    discrepancies = recovery.reconcile_disk_with_ledger(mission_id=mission_id, workspace_root=ws)
    assert len(discrepancies) >= 2
    op_ids = {d.operation_id for d in discrepancies}
    assert "op_del_uncertain" in op_ids
    assert "op_move_uncertain" in op_ids
    for d in discrepancies:
        assert d.discrepancy_type == ReconciliationDiscrepancyType.OPERATION_UNCERTAIN
        assert d.blocking is True


# ── Stage I: Journal Consistency & SQLite Transaction Atomicity ───────────────

def test_journal_transaction_atomicity_and_rollback(truth_env):
    """
    Stage I.1: SQLite transactions guarantee ACID atomicity.
    A failure halfway through an atomic block completely rolls back, leaving no partial state.
    """
    db = truth_env["db"]

    with pytest.raises(RuntimeError):
        with db.transaction() as cur:
            cur.execute("""
                INSERT INTO missions (mission_id, workspace_path, status, created_at, updated_at)
                VALUES ('m_atomic_fail', 'C:/dummy', 'RUNNING', 1.0, 1.0)
            """)
            # Simulate unexpected crash or failure halfway through transaction
            raise RuntimeError("Mid-transaction power loss")

    # Verify mission was rolled back and does not exist
    mission = db.get_mission("m_atomic_fail")
    assert mission is None


def test_event_journal_monotonic_sequences_and_replay_truth(truth_env):
    """
    Stage I.2: EventBus persists strictly monotonic sequences, and replaying
    events into StateStore deterministically reconstructs exact runtime state.
    """
    db = truth_env["db"]
    bus = truth_env["bus"]
    mission_id = "m_journal_seq"

    # Publish 20 events
    for i in range(1, 21):
        bus.publish_durable(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id=mission_id,
            payload={"progress_step": i},
        ))

    # Fetch ordered journal events
    events = db.get_mission_events(mission_id)
    assert len(events) == 20

    sequences = [evt["sequence"] for evt in events]
    assert sequences == list(range(1, 21))
    assert sequences == sorted(sequences)

    # Replay through fresh StateStore
    store = StateStore(mission_id=mission_id)
    for evt_row in events:
        store.apply_event(HermesEvent(
            event_type=EventType(evt_row["event_type"]),
            mission_id=evt_row["mission_id"],
            sequence=evt_row["sequence"],
            payload=json.loads(evt_row.get("payload_json", "{}")),
        ))

    snap = store.get_snapshot()
    assert snap.state_version == 20


# ── Stage J: Truthful Provider Outcomes Across 4 Tiers ────────────────────────

def test_four_tier_truthfulness_reconciliation(truth_env):
    """
    Stage J.1: Complete reconciliation across all 4 architectural tiers:
    1. Transport: StructuredTransportError(category=PROVIDER_UNAVAILABLE, status_code=503)
    2. Journal: EventBus records durable MISSION_WAITING event
    3. Database: SQLite record stores status=WAITING, wait_reason=WAITING_FOR_PROVIDER
    4. API & GUI: GET /api/missions/{id} returns truthful status and reason
    """
    db = truth_env["db"]
    bus = truth_env["bus"]
    client = truth_env["client"]
    ws = truth_env["workspace"]
    mission_id = "m_truth_4tier"

    # Tier 1: Transport Error definition
    transport_err = StructuredTransportError(
        category=ErrorCategory.PROVIDER_UNAVAILABLE,
        message="NVIDIA NIM 503 Service Unavailable",
        provider="nvidia",
        model="z-ai/glm-5.3-flash",
        status_code=503,
    )

    # Tier 2: Journal Events recorded (Mission started, then waiting)
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"workspace_root": str(ws), "prompt": "Task"},
    ))
    evt = HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id=mission_id,
        payload={
            "provider": transport_err.provider,
            "status_code": transport_err.status_code,
            "category": transport_err.category.value,
            "wait_reason": WaitReason.WAITING_FOR_PROVIDER.value,
        },
    )
    bus.publish_durable(evt)

    # Tier 3: Database state recorded
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws),
        status="WAITING",
        wait_reason=WaitReason.WAITING_FOR_PROVIDER.value,
        error_json=transport_err.to_dict(),
        recovery_required=True,
    )

    # Tier 4: API snapshot presentation
    resp = client.get(f"/api/missions/{mission_id}")
    assert resp.status_code == 200
    snap = resp.json()

    # Verify 4-tier agreement
    assert snap["mission_id"] == mission_id
    assert snap["status"] == "WAITING"
    assert snap["wait_reason"] == "WAITING_FOR_PROVIDER"
    assert snap["recovery_required"] is True
    assert snap["workspace_root"] == str(ws)

    # Check journal truth matches
    journal_events = db.get_mission_events(mission_id)
    assert len(journal_events) >= 1
    last_evt = journal_events[-1]
    assert last_evt["event_type"] == EventType.MISSION_WAITING.value
    event_data = json.loads(last_evt["payload_json"])
    payload = event_data.get("payload", {})
    assert payload["category"] == ErrorCategory.PROVIDER_UNAVAILABLE.value
    assert payload["wait_reason"] == WaitReason.WAITING_FOR_PROVIDER.value
