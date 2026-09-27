# tests/test_persistence_adversarial.py
import os
import pytest
from core.checkpoints.engine import CheckpointEngine
from core.checkpoints.env_snapshot import EnvironmentSnapshotter
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import CheckpointCorrupt, CheckpointReason, SessionStatus
from core.runtime_state.models import HermesRuntimeState
from core.sessions.manager import SessionManager


def test_adversarial_environment_secret_redaction(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-secret12345678901234567890")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secrettokenvalue123456789012345678")
    monkeypatch.setenv("HERMES_MODE", "autonomous")

    snap = EnvironmentSnapshotter.create_snapshot(tmp_path)

    # Allowlisted variable should be present
    assert snap.allowlisted_env.get("HERMES_MODE") == "autonomous"
    # Secrets MUST NOT be present
    assert "OPENAI_API_KEY" not in snap.allowlisted_env
    assert "GITHUB_TOKEN" not in snap.allowlisted_env
    assert "sk-" not in str(snap.to_dict())
    assert "ghp_" not in str(snap.to_dict())


def test_adversarial_symlink_escape_blocked(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("SUPER_SECRET_HOST_KEY", encoding="utf-8")

    # Attempt to create a symlink inside workspace pointing outside
    symlink_path = workspace / "escape_link.txt"
    try:
        symlink_path.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not supported without admin on this OS")

    hermes_dir = tmp_path / ".hermes"
    db = SQLiteDatabase(hermes_dir / "test.db")
    db.save_session("sess_sym", "m_1", str(workspace), SessionStatus.RUNNING, 0.0, 0.0)
    blob_store = BlobStore(hermes_dir)

    engine = CheckpointEngine(
        base_dir=hermes_dir,
        workspace_root=workspace,
        db=db,
        blob_store=blob_store,
    )

    state = HermesRuntimeState.create_empty("m_1", "sess_sym")
    chk = engine.create_checkpoint(
        session_id="sess_sym",
        mission_id="m_1",
        runtime_state=state,
        reason=CheckpointReason.MANUAL,
    )

    # The outside secret must not be snapshotted
    for rel_path in chk.workspace.files.keys():
        assert "outside_secret" not in rel_path


def test_adversarial_tampered_manifest_detected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    hermes_dir = tmp_path / ".hermes"

    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    session = mgr.create_session("m_tamper")
    state = HermesRuntimeState.create_empty("m_tamper", session.session_id)

    chk = mgr.create_checkpoint(session.session_id, state, reason=CheckpointReason.MANUAL)

    # Tamper with the checkpoint row in SQLite directly
    with mgr.db.transaction() as cur:
        cur.execute("UPDATE checkpoints SET state_hash = 'corrupt_hash_00000000000000000000000000000000' WHERE checkpoint_id = ?", (chk.checkpoint_id,))

    # Resume must detect corruption and fail safely
    from core.recovery.engine import RecoveryEngine
    recovery = RecoveryEngine(session_manager=mgr, workspace_root=workspace)
    with pytest.raises(CheckpointCorrupt):
        recovery.resume_session(session.session_id)
