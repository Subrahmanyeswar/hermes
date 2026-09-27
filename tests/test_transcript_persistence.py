# tests/test_transcript_persistence.py
import pytest
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import SessionStatus
from core.sessions.transcript import MessageType, TranscriptStore


def test_transcript_store_lifecycle_and_cow_branching(tmp_path):
    hermes_dir = tmp_path / ".hermes"
    db = SQLiteDatabase(hermes_dir / "test.db")
    db.save_session("parent_sess", "m_p", str(tmp_path), SessionStatus.RUNNING, 0.0, 0.0)
    db.save_session("child_sess", "m_c", str(tmp_path), SessionStatus.RUNNING, 0.0, 0.0)
    blob_store = BlobStore(hermes_dir)
    store = TranscriptStore(db, blob_store, large_payload_threshold=100)

    # 1. Parent messages
    store.append_message("parent_sess", "user", "Hello parent", MessageType.USER, sequence=1)
    store.append_message("parent_sess", "assistant", "I am HERMES", MessageType.ASSISTANT, sequence=2)

    # Large message that triggers CAS externalization
    large_text = "X" * 200
    m3 = store.append_message("parent_sess", "tool", large_text, MessageType.TOOL_RESULT, sequence=3)
    assert m3.blob_id is not None
    assert store.resolve_content(m3) == large_text

    # 2. Child branch inherits messages 1 & 2 through fork_sequence=2 without duplicating
    store.append_message("child_sess", "user", "Alternate turn from fork", MessageType.USER, sequence=3)

    child_messages = store.get_messages("child_sess", parent_session_id="parent_sess", fork_sequence=2)
    assert len(child_messages) == 3
    assert child_messages[0].content == "Hello parent"
    assert child_messages[1].content == "I am HERMES"
    assert child_messages[2].content == "Alternate turn from fork"

    # Parent transcript should be unchanged
    parent_messages = store.get_messages("parent_sess")
    assert len(parent_messages) == 3
