# tests/test_checkpoints.py
import pytest
from core.checkpoints.engine import CheckpointEngine
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import CheckpointReason, CheckpointTrigger, SessionStatus
from core.runtime_state.models import HermesRuntimeState


def test_checkpoint_creation_and_integrity(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "index.html").write_text("<h1>HERMES</h1>", encoding="utf-8")
    (workspace / "app.py").write_text("print('running')", encoding="utf-8")

    hermes_dir = tmp_path / ".hermes"
    db = SQLiteDatabase(hermes_dir / "test.db")
    db.save_session("sess_cp", "m_1", str(workspace), SessionStatus.RUNNING, 0.0, 0.0)
    blob_store = BlobStore(hermes_dir)

    engine = CheckpointEngine(
        base_dir=hermes_dir,
        workspace_root=workspace,
        db=db,
        blob_store=blob_store,
    )

    state = HermesRuntimeState.create_empty("m_1", "sess_cp")
    chk = engine.create_checkpoint(
        session_id="sess_cp",
        mission_id="m_1",
        runtime_state=state,
        reason=CheckpointReason.MANUAL,
        trigger=CheckpointTrigger.USER,
    )

    assert chk.checkpoint_id.startswith("chk_")
    assert chk.workspace.total_files == 2
    assert "index.html" in chk.workspace.files
    assert "app.py" in chk.workspace.files
    assert engine.verify_checkpoint_integrity(chk.checkpoint_id) is True

    # Mutate a blob in the store to verify integrity failure detection
    file_blob_id = chk.workspace.files["index.html"].blob_id
    blob_file = blob_store._blob_path(file_blob_id)
    with open(blob_file, "wb") as f:
        f.write(b"tampered")

    assert engine.verify_checkpoint_integrity(chk.checkpoint_id) is False
