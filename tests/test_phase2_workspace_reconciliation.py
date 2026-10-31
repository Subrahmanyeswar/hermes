"""
Phase 2 Test Suite: Physical Workspace Reconciliation.

Verifies:
- Scenario G: External file deletion detected (Task 2.9, INV-08)
- Scenario H: External file modification detected (Task 2.9, INV-08)
- Prevents unsafe resume when physical workspace has drifted from settled ledger
"""

import uuid
import tempfile
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.persistence.blobs import BlobStore
from core.workspace import WorkspaceManager
from core.persistence.recovery import RecoveryEngine, ReconciliationDiscrepancyType, compute_file_sha256
from core.persistence.models import OperationStatus


def test_scenario_g_external_file_deletion_detected():
    """Verify that if a file committed by a tool operation is deleted externally, reconciliation detects FILE_MISSING and blocks resume."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_recon_del_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    blob_store = BlobStore(tmp_dir / "blobs")
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    recovery = RecoveryEngine(
        db=db,
        blob_store=blob_store,
        workspace_manager=ws_mgr,
    )

    mission_id = f"m_recon_del_{test_id}"
    rel_path = "important_source.py"
    full_path = tmp_dir / rel_path

    # Simulate tool committing the file to ledger
    content = "print('original')"
    full_path.write_text(content, encoding="utf-8")
    post_hash = compute_file_sha256(full_path)

    # Record settled operation in database
    op_id = f"op_del_{test_id}"
    db.record_tool_intent(
        operation_id=op_id,
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path=rel_path,
        workspace_root=str(tmp_dir),
    )
    db.record_tool_result(
        operation_id=op_id,
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=post_hash,
    )

    # External user / process deletes the file while HERMES was stopped
    full_path.unlink()

    # Reconcile disk with ledger
    discrepancies = recovery.reconcile_disk_with_ledger(mission_id, tmp_dir)
    assert len(discrepancies) == 1
    assert discrepancies[0].discrepancy_type == ReconciliationDiscrepancyType.FILE_MISSING
    assert discrepancies[0].blocking is True
    assert discrepancies[0].path == rel_path


def test_scenario_h_external_file_modification_detected():
    """Verify that if a committed file is edited externally post-interruption, reconciliation detects USER_MODIFIED and blocks resume."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_recon_mod_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    blob_store = BlobStore(tmp_dir / "blobs")
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    recovery = RecoveryEngine(
        db=db,
        blob_store=blob_store,
        workspace_manager=ws_mgr,
    )

    mission_id = f"m_recon_mod_{test_id}"
    rel_path = "config.json"
    full_path = tmp_dir / rel_path

    # Settle initial file
    full_path.write_text('{"mode": "auto"}', encoding="utf-8")
    post_hash = compute_file_sha256(full_path)

    # Record settled operation in database
    op_id = f"op_mod_{test_id}"
    db.record_tool_intent(
        operation_id=op_id,
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path=rel_path,
        workspace_root=str(tmp_dir),
    )
    db.record_tool_result(
        operation_id=op_id,
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=post_hash,
    )

    # External modification
    full_path.write_text('{"mode": "tampered_external_edit"}', encoding="utf-8")

    # Reconcile
    discrepancies = recovery.reconcile_disk_with_ledger(mission_id, tmp_dir)
    assert len(discrepancies) == 1
    assert discrepancies[0].discrepancy_type == ReconciliationDiscrepancyType.USER_MODIFIED
    assert discrepancies[0].blocking is True
    assert discrepancies[0].path == rel_path
    assert discrepancies[0].actual_hash is not None
    assert discrepancies[0].actual_hash != post_hash
