import pytest
import sqlite3
from pathlib import Path
from kairos.db import (
    init_db,
    get_connection,
    execute_write,
    execute_read,
    get_total_api_cost,
    record_api_cost,
)


@pytest.fixture
def test_db(tmp_path):
    """Fresh database for each test."""
    db = tmp_path / "test.db"
    init_db(db_path=db)
    return db


def test_init_db_creates_all_tables(test_db):
    rows = execute_read(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        db_path=test_db,
    )
    table_names = {r["name"] for r in rows}
    assert "tasks" in table_names
    assert "api_costs" in table_names
    assert "sessions" in table_names
    assert "kairos_state" in table_names


def test_init_db_is_idempotent(test_db):
    """Calling init_db twice should not raise or create duplicate tables."""
    init_db(db_path=test_db)  # Call again
    init_db(db_path=test_db)  # And again
    rows = execute_read(
        "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        db_path=test_db,
    )
    assert rows[0]["cnt"] == 4  # Exactly 4 user-defined tables, not 8 or 12


def test_kairos_state_has_single_row(test_db):
    rows = execute_read("SELECT * FROM kairos_state", db_path=test_db)
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["tasks_since_consolidation"] == 0


def test_execute_write_returns_lastrowid(test_db):
    row_id = execute_write(
        "INSERT INTO tasks (session_id, title, status) VALUES (?, ?, ?)",
        ("sess_001", "Test task", "PENDING"),
        db_path=test_db,
    )
    assert row_id > 0


def test_execute_read_returns_rows(test_db):
    execute_write(
        "INSERT INTO tasks (session_id, title) VALUES (?, ?)",
        ("sess_001", "Task A"),
        db_path=test_db,
    )
    rows = execute_read(
        "SELECT * FROM tasks WHERE session_id = ?",
        ("sess_001",),
        db_path=test_db,
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "Task A"


def test_row_accessible_as_dict(test_db):
    """Rows should be accessible by column name like a dict."""
    execute_write(
        "INSERT INTO tasks (session_id, title, priority) VALUES (?, ?, ?)",
        ("s1", "My Task", 3),
        db_path=test_db,
    )
    rows = execute_read("SELECT * FROM tasks", db_path=test_db)
    assert rows[0]["title"] == "My Task"
    assert rows[0]["priority"] == 3


def test_get_total_api_cost_empty(test_db):
    assert get_total_api_cost(db_path=test_db) == 0.0


def test_record_api_cost_and_sum(test_db):
    record_api_cost("claude-sonnet-4-6", 1000, 500, 0.0135, db_path=test_db)
    record_api_cost("claude-sonnet-4-6", 2000, 800, 0.0180, db_path=test_db)
    total = get_total_api_cost(db_path=test_db)
    assert abs(total - 0.0315) < 0.0001


def test_tasks_status_constraint(test_db):
    """Only valid status values should be accepted."""
    with pytest.raises(sqlite3.IntegrityError):
        execute_write(
            "INSERT INTO tasks (session_id, title, status) VALUES (?, ?, ?)",
            ("s1", "Bad task", "INVALID_STATUS"),
            db_path=test_db,
        )


def test_wal_mode_enabled(test_db):
    rows = execute_read("PRAGMA journal_mode", db_path=test_db)
    assert rows[0][0] == "wal"
