"""
Phase 2 Test Suite: SQLite WAL Mode, Integrity Check & Concurrent Write Durability.

Verifies:
- Task 2.23: SQLite WAL mode enabled
- PRAGMA integrity_check == 'ok'
- Foreign key constraints enforced
- Multi-threaded concurrent writes with transactional integrity
"""

import uuid
import tempfile
import threading
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase


def test_wal_mode_and_pragma_integrity_check():
    """Verify that file-backed SQLite databases initialize in WAL mode and pass PRAGMA integrity_check."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_wal_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "hermes_wal_test.db"
    db = SQLiteDatabase(db_path)

    conn = db._get_connection()
    # Check journal mode
    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0].upper()
    assert journal_mode == "WAL", f"Expected WAL mode, got {journal_mode}"

    # Check foreign keys
    foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert foreign_keys == 1, "Expected foreign keys enabled"

    # Check integrity
    integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    assert integrity == "ok", f"Integrity check failed: {integrity}"


def test_concurrent_multithreaded_writes_wal_integrity():
    """Verify that concurrent writes from multiple threads do not corrupt the database or lose transactions."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_wal_concurrent_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "hermes_wal_concurrent.db"
    db = SQLiteDatabase(db_path)

    num_threads = 5
    writes_per_thread = 20
    errors = []

    def worker_writer(thread_idx: int):
        try:
            for i in range(writes_per_thread):
                m_id = f"m_{thread_idx}_{i}_{test_id}"
                with db.transaction():
                    db.save_mission(
                        mission_id=m_id,
                        workspace_path=str(tmp_dir),
                        status="RUNNING",
                        attempt_number=1,
                    )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker_writer, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent writing produced errors: {errors}"

    # Verify all written missions exist
    conn = db._get_connection()
    count = conn.execute("SELECT count(*) FROM missions WHERE mission_id LIKE ?", (f"%{test_id}%",)).fetchone()[0]
    assert count == num_threads * writes_per_thread

    # Verify integrity post-concurrent writes
    integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    assert integrity == "ok"
