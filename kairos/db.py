# kairos/db.py
# HERMES SQLite database manager — the single source of truth for all schemas.
# Every table in tasks.db is created here. No other module creates tables.
# Connection management: all modules call get_connection() from here.
# Never import sqlite3 directly in any other kairos module — always use this module.
# Thread safety: SQLite in WAL mode handles concurrent reads safely.
# Write serialisation: all writes go through the execute_write() helper.

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from loguru import logger

DB_PATH: Path = Path("data/tasks.db")
_lock = threading.Lock()  # Write lock for serialising concurrent writes


def init_db(db_path: Path = DB_PATH) -> None:
    """Create all HERMES tables if they do not exist.

    Safe to call multiple times — uses IF NOT EXISTS.
    Called once at startup.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")    # Write-Ahead Logging for concurrent access
        conn.execute("PRAGMA foreign_keys=ON")      # Enforce foreign key constraints

        # ── Tasks table ──────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT    NOT NULL,
                title           TEXT    NOT NULL,
                description     TEXT    DEFAULT '',
                status          TEXT    NOT NULL DEFAULT 'PENDING'
                                CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED','STUCK')),
                priority        INTEGER NOT NULL DEFAULT 5
                                CHECK(priority BETWEEN 1 AND 10),
                complexity      REAL    NOT NULL DEFAULT 0.5,
                retry_count     INTEGER NOT NULL DEFAULT 0,
                max_retries     INTEGER NOT NULL DEFAULT 3,
                last_error      TEXT    DEFAULT NULL,
                tool_name       TEXT    DEFAULT NULL,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                started_at      TEXT    DEFAULT NULL,
                completed_at    TEXT    DEFAULT NULL
            )
        """)

        # ── API costs table ───────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_costs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL DEFAULT (datetime('now')),
                model           TEXT    NOT NULL,
                input_tokens    INTEGER NOT NULL DEFAULT 0,
                output_tokens   INTEGER NOT NULL DEFAULT 0,
                cost_usd        REAL    NOT NULL DEFAULT 0.0,
                task_id         INTEGER DEFAULT NULL REFERENCES tasks(id),
                task_description TEXT   DEFAULT '',
                escalation_reason TEXT  DEFAULT ''
            )
        """)

        # ── Session metadata table ────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT    NOT NULL UNIQUE,
                project         TEXT    NOT NULL DEFAULT 'default',
                started_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                ended_at        TEXT    DEFAULT NULL,
                total_tasks     INTEGER NOT NULL DEFAULT 0,
                total_cost_usd  REAL    NOT NULL DEFAULT 0.0,
                status          TEXT    NOT NULL DEFAULT 'active'
                                CHECK(status IN ('active', 'completed', 'interrupted'))
            )
        """)

        # ── KAIROS state table (single row) ──────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kairos_state (
                id                    INTEGER PRIMARY KEY CHECK(id = 1),
                last_consolidation_at TEXT    DEFAULT NULL,
                tasks_since_consolidation INTEGER NOT NULL DEFAULT 0,
                total_consolidations  INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO kairos_state (id, tasks_since_consolidation, total_consolidations)
            VALUES (1, 0, 0)
        """)

        # ── Indexes for performance ───────────────────────────────────────
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_costs_timestamp ON api_costs(timestamp)")

        conn.commit()

    logger.info(f"Database initialised: {db_path}")


@contextmanager
def get_connection(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a SQLite connection with row_factory=sqlite3.Row set.

    Handles commit and rollback automatically.
    """
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row   # Rows accessible as dicts
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_write(sql: str, params: tuple = (), db_path: Path = DB_PATH) -> int:
    """Execute a write operation (INSERT/UPDATE/DELETE) with thread-safe locking.

    Returns lastrowid for INSERT, rowcount for UPDATE/DELETE.
    """
    with _lock:
        with get_connection(db_path) as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid or cursor.rowcount


def execute_read(sql: str, params: tuple = (), db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    """Execute a read operation (SELECT).

    Returns list of Row objects. Thread-safe — SQLite WAL mode handles concurrent reads.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchall()


def get_total_api_cost(db_path: Path = DB_PATH) -> float:
    """Sum all cost_usd values from api_costs table.

    Returns 0.0 if table is empty.
    """
    rows = execute_read(
        "SELECT COALESCE(SUM(cost_usd), 0.0) as total FROM api_costs",
        db_path=db_path,
    )
    return float(rows[0]["total"]) if rows else 0.0


def record_api_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    task_id: int | None = None,
    task_description: str = "",
    escalation_reason: str = "",
    db_path: Path = DB_PATH,
) -> int:
    """Insert a new row into api_costs and return the new row ID."""
    return execute_write(
        """INSERT INTO api_costs (model, input_tokens, output_tokens, cost_usd, task_id, task_description, escalation_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (model, input_tokens, output_tokens, cost_usd, task_id, task_description, escalation_reason),
        db_path=db_path,
    )
