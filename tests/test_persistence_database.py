# tests/test_persistence_database.py
import time
import pytest
from core.persistence.database import SQLiteDatabase
from core.persistence.models import SessionStatus, CheckpointReason, CheckpointTrigger


def test_sqlite_database_lifecycle(tmp_path):
    db_file = tmp_path / "test.db"
    db = SQLiteDatabase(db_file)

    now = time.time()
    db.save_session(
        session_id="sess_1",
        mission_id="mission_1",
        workspace_root=str(tmp_path),
        status=SessionStatus.RUNNING,
        created_at=now,
        updated_at=now,
        branch_name="main",
        metadata={"author": "test"},
    )

    s = db.get_session("sess_1")
    assert s is not None
    assert s["session_id"] == "sess_1"
    assert s["status"] == SessionStatus.RUNNING
    assert s["branch_name"] == "main"
    assert s["metadata"]["author"] == "test"

    # Update session
    db.save_session(
        session_id="sess_1",
        mission_id="mission_1",
        workspace_root=str(tmp_path),
        status=SessionStatus.COMPLETED,
        created_at=now,
        updated_at=now + 10,
        current_sequence=5,
    )
    s2 = db.get_session("sess_1")
    assert s2["status"] == SessionStatus.COMPLETED
    assert s2["current_sequence"] == 5


def test_sqlite_checkpoints_query(tmp_path):
    db = SQLiteDatabase(tmp_path / "test.db")
    now = time.time()
    db.save_session(
        session_id="sess_chk",
        mission_id="m_1",
        workspace_root=str(tmp_path),
        status=SessionStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )

    db.save_checkpoint(
        checkpoint_id="chk_1",
        session_id="sess_chk",
        sequence=1,
        reason=CheckpointReason.PRE_ACTION,
        trigger=CheckpointTrigger.SYSTEM,
        created_at=now,
        state_hash="hash_state_1",
        manifest_hash="hash_man_1",
        manifest_json='{"checkpoint_id": "chk_1"}',
    )
    db.save_checkpoint(
        checkpoint_id="chk_2",
        session_id="sess_chk",
        sequence=2,
        reason=CheckpointReason.POST_VERIFICATION,
        trigger=CheckpointTrigger.USER,
        created_at=now + 5,
        state_hash="hash_state_2",
        manifest_hash="hash_man_2",
        manifest_json='{"checkpoint_id": "chk_2"}',
    )

    chks = db.list_checkpoints_for_session("sess_chk")
    assert len(chks) == 2
    assert chks[0]["checkpoint_id"] == "chk_1"
    assert chks[1]["checkpoint_id"] == "chk_2"


def test_sqlite_locks(tmp_path):
    db = SQLiteDatabase(tmp_path / "test.db")
    now = time.time()
    db.save_session("sess_lock", "m_1", str(tmp_path), SessionStatus.RUNNING, now, now)

    assert db.acquire_lock("sess_lock", 1234, "localhost", now) is True
    # Duplicate acquire must fail
    assert db.acquire_lock("sess_lock", 5678, "localhost", now) is False

    lock = db.get_lock("sess_lock")
    assert lock["pid"] == 1234

    db.release_lock("sess_lock")
    assert db.get_lock("sess_lock") is None
    # Now can re-acquire
    assert db.acquire_lock("sess_lock", 5678, "localhost", now) is True
