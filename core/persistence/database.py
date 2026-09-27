# core/persistence/database.py
"""
Transactional SQLite Persistence Layer for HERMES 2.x.

Configured with WAL mode, foreign keys enabled, and Windows-safe busy timeouts.
Provides ACID transactions for sessions, checkpoints, journals, transcripts, and locks.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from core.persistence.models import SessionStatus, CheckpointReason, CheckpointTrigger


class SQLiteDatabase:
    """
    Authoritative SQLite Metadata Database.
    Thread-safe connection management with WAL mode and resilient concurrency.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and foreign keys for durability and concurrent reads
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager providing an atomic database transaction."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _init_schema(self) -> None:
        """Create canonical tables and indices if not present."""
        with self.transaction() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    parent_session_id TEXT,
                    root_session_id TEXT,
                    mission_id TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_checkpoint_id TEXT,
                    current_sequence INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    branch_name TEXT NOT NULL DEFAULT 'main',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    sequence INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    state_hash TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS journal (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    PRIMARY KEY (session_id, sequence),
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    parent_message_id TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS locks (
                    session_id TEXT PRIMARY KEY,
                    pid INTEGER NOT NULL,
                    host TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
            """)

            # Helpful indices for fast querying
            cur.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id, sequence);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_session ON journal(session_id, sequence);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transcripts_session ON transcripts(session_id, sequence);")

    # ── Session Operations ────────────────────────────────────────────────────

    def save_session(
        self,
        session_id: str,
        mission_id: str,
        workspace_root: str,
        status: SessionStatus,
        created_at: float,
        updated_at: float,
        parent_session_id: Optional[str] = None,
        root_session_id: Optional[str] = None,
        current_checkpoint_id: Optional[str] = None,
        current_sequence: int = 0,
        branch_name: str = "main",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta_json = json.dumps(metadata or {}, sort_keys=True)
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO sessions (
                    session_id, parent_session_id, root_session_id, mission_id,
                    workspace_root, status, current_checkpoint_id, current_sequence,
                    created_at, updated_at, branch_name, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status=excluded.status,
                    current_checkpoint_id=excluded.current_checkpoint_id,
                    current_sequence=excluded.current_sequence,
                    updated_at=excluded.updated_at,
                    branch_name=excluded.branch_name,
                    metadata_json=excluded.metadata_json;
            """, (
                session_id, parent_session_id, root_session_id or session_id, mission_id,
                workspace_root, status.value, current_checkpoint_id, current_sequence,
                created_at, updated_at, branch_name, meta_json
            ))

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["metadata"] = json.loads(res.pop("metadata_json", "{}"))
            res["status"] = SessionStatus(res["status"])
            return res

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                d["status"] = SessionStatus(d["status"])
                results.append(d)
            return results

    # ── Checkpoint Operations ─────────────────────────────────────────────────

    def save_checkpoint(
        self,
        checkpoint_id: str,
        session_id: str,
        sequence: int,
        reason: CheckpointReason,
        trigger: CheckpointTrigger,
        created_at: float,
        state_hash: str,
        manifest_hash: str,
        manifest_json: str,
        parent_checkpoint_id: Optional[str] = None,
    ) -> None:
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO checkpoints (
                    checkpoint_id, session_id, parent_checkpoint_id, sequence,
                    reason, trigger, created_at, state_hash, manifest_hash, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    manifest_hash=excluded.manifest_hash,
                    manifest_json=excluded.manifest_json;
            """, (
                checkpoint_id, session_id, parent_checkpoint_id, sequence,
                reason.value, trigger.value, created_at, state_hash, manifest_hash, manifest_json
            ))

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["reason"] = CheckpointReason(res["reason"])
            res["trigger"] = CheckpointTrigger(res["trigger"])
            return res

    def list_checkpoints_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        with self.transaction() as cur:
            cur.execute("""
                SELECT * FROM checkpoints
                WHERE session_id = ?
                ORDER BY sequence ASC, created_at ASC
            """, (session_id,))
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["reason"] = CheckpointReason(d["reason"])
                d["trigger"] = CheckpointTrigger(d["trigger"])
                results.append(d)
            return results

    # ── Journal Operations ────────────────────────────────────────────────────

    def append_journal_entry(
        self,
        session_id: str,
        sequence: int,
        event_id: str,
        event_type: str,
        payload_hash: str,
        payload_json: str,
        timestamp: float,
    ) -> None:
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO journal (
                    session_id, sequence, event_id, event_type,
                    payload_hash, payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (session_id, sequence, event_id, event_type, payload_hash, payload_json, timestamp))

    def get_journal_entries(
        self,
        session_id: str,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        with self.transaction() as cur:
            if to_seq is not None:
                cur.execute("""
                    SELECT * FROM journal
                    WHERE session_id = ? AND sequence >= ? AND sequence <= ?
                    ORDER BY sequence ASC
                """, (session_id, from_seq, to_seq))
            else:
                cur.execute("""
                    SELECT * FROM journal
                    WHERE session_id = ? AND sequence >= ?
                    ORDER BY sequence ASC
                """, (session_id, from_seq))
            return [dict(r) for r in cur.fetchall()]

    def get_max_journal_sequence(self, session_id: str) -> int:
        with self.transaction() as cur:
            cur.execute("SELECT MAX(sequence) FROM journal WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            return row[0] if (row and row[0] is not None) else 0

    # ── Transcript Operations ─────────────────────────────────────────────────

    def append_transcript_entry(
        self,
        message_id: str,
        session_id: str,
        sequence: int,
        role: str,
        message_type: str,
        timestamp: float,
        content: str,
        turn_id: Optional[str] = None,
        parent_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta_json = json.dumps(metadata or {}, sort_keys=True)
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO transcripts (
                    message_id, session_id, turn_id, sequence, role,
                    message_type, timestamp, content, metadata_json, parent_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    content=excluded.content,
                    metadata_json=excluded.metadata_json;
            """, (
                message_id, session_id, turn_id, sequence, role,
                message_type, timestamp, content, meta_json, parent_message_id
            ))

    def get_transcript_entries(
        self,
        session_id: str,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        with self.transaction() as cur:
            if to_seq is not None:
                cur.execute("""
                    SELECT * FROM transcripts
                    WHERE session_id = ? AND sequence >= ? AND sequence <= ?
                    ORDER BY sequence ASC
                """, (session_id, from_seq, to_seq))
            else:
                cur.execute("""
                    SELECT * FROM transcripts
                    WHERE session_id = ? AND sequence >= ?
                    ORDER BY sequence ASC
                """, (session_id, from_seq))
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                results.append(d)
            return results

    # ── Locks Operations ──────────────────────────────────────────────────────

    def acquire_lock(self, session_id: str, pid: int, host: str, now: float) -> bool:
        """Attempt to acquire a session lock atomically."""
        with self.transaction() as cur:
            cur.execute("SELECT * FROM locks WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            if row:
                return False
            cur.execute("""
                INSERT INTO locks (session_id, pid, host, acquired_at, heartbeat_at)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, pid, host, now, now))
            return True

    def get_lock(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM locks WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def update_heartbeat(self, session_id: str, now: float) -> None:
        with self.transaction() as cur:
            cur.execute("UPDATE locks SET heartbeat_at = ? WHERE session_id = ?", (now, session_id))

    def release_lock(self, session_id: str) -> None:
        with self.transaction() as cur:
            cur.execute("DELETE FROM locks WHERE session_id = ?", (session_id,))
