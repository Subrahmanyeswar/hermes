# core/persistence/database.py
"""
Transactional SQLite Persistence Layer for HERMES 2.x.

Configured with WAL mode, foreign keys enabled, and Windows-safe busy timeouts.
Provides ACID transactions for sessions, checkpoints, journals, transcripts, and locks.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from core.persistence.models import SessionStatus, CheckpointReason, CheckpointTrigger


def get_canonical_database_path() -> Path:
    """
    Resolve the canonical HERMES runtime SQLite database path.
    Resides outside every selected project workspace to prevent data loss or contamination.
    Precedence:
    1. HERMES_DATABASE_PATH environment variable (if specified)
    2. %LOCALAPPDATA%\\HERMES\\hermes_runtime.db (on Windows)
    3. ~/.hermes/hermes_runtime.db (fallback / non-Windows)
    """
    env_path = os.environ.get("HERMES_DATABASE_PATH")
    if env_path:
        return Path(env_path).resolve()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data) / "HERMES"
    else:
        base_dir = Path.home() / ".hermes"

    base_dir.mkdir(parents=True, exist_ok=True)
    return (base_dir / "hermes_runtime.db").resolve()


class SQLiteDatabase:
    """
    Authoritative SQLite Metadata Database.
    Thread-safe connection management with WAL mode and resilient concurrency.
    """

    def __init__(self, db_path: Optional[Path | str] = None):
        self._shared_conn: Optional[sqlite3.Connection] = None
        self._shared_lock = threading.Lock()
        if db_path == ":memory:":
            self.db_path = ":memory:"
            # For in-memory database shared across threads (e.g. background persist worker),
            # maintain a single shared connection with check_same_thread=False
            self._shared_conn = sqlite3.connect(
                ":memory:",
                timeout=10.0,
                check_same_thread=False,
            )
            self._shared_conn.row_factory = sqlite3.Row
            self._shared_conn.execute("PRAGMA foreign_keys = ON;")
            self._shared_conn.execute("PRAGMA synchronous = NORMAL;")
        else:
            self.db_path = Path(db_path).resolve() if db_path is not None else get_canonical_database_path()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and foreign keys for durability and concurrent reads
            if str(self.db_path) != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager providing an atomic database transaction."""
        if self._shared_conn is not None:
            with self._shared_lock:
                cursor = self._shared_conn.cursor()
                try:
                    yield cursor
                    self._shared_conn.commit()
                except Exception:
                    self._shared_conn.rollback()
                    raise
                finally:
                    cursor.close()
            return

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

    CURRENT_SCHEMA_VERSION = 3

    def _init_schema(self) -> None:
        """Create canonical tables, indices, and apply schema migrations if not present."""
        with self.transaction() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL,
                    description TEXT NOT NULL
                );
            """)

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

            # ── Phase 2 Canonical Persistence Extensions ──────────────────────

            # Canonical Missions Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    run_id TEXT,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    workspace_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    wait_reason TEXT NOT NULL DEFAULT 'NONE',
                    prompt TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    state_version INTEGER NOT NULL DEFAULT 0,
                    last_event_sequence INTEGER NOT NULL DEFAULT 0,
                    latest_checkpoint_id TEXT,
                    execution_active INTEGER NOT NULL DEFAULT 0,
                    recovery_required INTEGER NOT NULL DEFAULT 0,
                    error_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
            """)

            # Canonical Snapshots Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    mission_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    run_id TEXT,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    state_version INTEGER NOT NULL DEFAULT 0,
                    last_event_sequence INTEGER NOT NULL DEFAULT 0,
                    workspace_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    state_hash TEXT NOT NULL
                );
            """)

            # Canonical Verification Evidence Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verification_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    run_id TEXT,
                    command TEXT NOT NULL,
                    working_dir TEXT NOT NULL,
                    interpreter TEXT NOT NULL,
                    exit_code INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL DEFAULT 0.0,
                    output_summary TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
            """)

            # Canonical Monotonic Global Sequence Generator
            cur.execute("""
                CREATE TABLE IF NOT EXISTS global_sequences (
                    generator_key TEXT PRIMARY KEY,
                    current_sequence INTEGER NOT NULL DEFAULT 0
                );
            """)
            cur.execute("""
                INSERT OR IGNORE INTO global_sequences (generator_key, current_sequence)
                VALUES ('event_sequence', 0);
            """)

            # Canonical Mission Event Journal
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mission_events (
                    sequence INTEGER PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    session_id TEXT,
                    run_id TEXT,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1
                );
            """)

            # Phase 3 Canonical Tool Operations Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tool_operations (
                    operation_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    intent_seq INTEGER NOT NULL DEFAULT 0,
                    result_seq INTEGER,
                    task_id TEXT,
                    turn_id TEXT,
                    run_id TEXT,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    session_id TEXT,
                    target_path TEXT,
                    workspace_root TEXT NOT NULL DEFAULT '',
                    arguments_summary TEXT NOT NULL DEFAULT '',
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    prior_hash TEXT,
                    post_hash TEXT,
                    exit_code INTEGER,
                    output_summary TEXT,
                    error_message TEXT,
                    duration_seconds REAL,
                    side_effects_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    committed_at REAL
                );
            """)

            # Checkpoints Mission-level Index & Columns if missing
            cur.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id, sequence);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_session ON journal(session_id, sequence);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transcripts_session ON transcripts(session_id, sequence);")

            # Phase 2 Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mission_events_mission ON mission_events(mission_id, sequence);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mission_events_run ON mission_events(run_id, sequence);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_verification_mission ON verification_evidence(mission_id);")

            # Phase 3 Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_operations_mission ON tool_operations(mission_id, status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_operations_intent_seq ON tool_operations(intent_seq);")

            # Check and record schema version
            cur.execute("SELECT MAX(version) FROM schema_version;")
            row = cur.fetchone()
            current_ver = row[0] if (row and row[0] is not None) else 0
            if current_ver < self.CURRENT_SCHEMA_VERSION:
                import time
                cur.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?);",
                    (self.CURRENT_SCHEMA_VERSION, time.time(), "Phase 3 durable tool operations and write-ahead protocol")
                )


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
            status_val = status.value if hasattr(status, "value") else str(status)
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
                workspace_root, status_val, current_checkpoint_id, current_sequence,
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
            reason_val = reason.value if hasattr(reason, "value") else str(reason)
            trigger_val = trigger.value if hasattr(trigger, "value") else str(trigger)
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
                reason_val, trigger_val, created_at, state_hash, manifest_hash, manifest_json
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

    # ── Phase 2 Canonical Persistence Operations ──────────────────────────────

    def allocate_next_sequence(self, generator_key: str = "event_sequence") -> int:
        """
        Atomically allocate the next monotonic sequence number.
        Safe across threads and process restarts.
        """
        with self.transaction() as cur:
            cur.execute("""
                UPDATE global_sequences
                SET current_sequence = current_sequence + 1
                WHERE generator_key = ?
            """, (generator_key,))
            cur.execute("""
                SELECT current_sequence FROM global_sequences WHERE generator_key = ?
            """, (generator_key,))
            row = cur.fetchone()
            if row:
                return int(row[0])
            # Fallback if key missing
            cur.execute("""
                INSERT INTO global_sequences (generator_key, current_sequence)
                VALUES (?, 1)
            """, (generator_key,))
            return 1

    def get_max_event_sequence(self) -> int:
        """Return the maximum sequence recorded across global sequence table and mission_events table."""
        with self.transaction() as cur:
            cur.execute("SELECT current_sequence FROM global_sequences WHERE generator_key = 'event_sequence'")
            row_seq = cur.fetchone()
            seq_val = int(row_seq[0]) if (row_seq and row_seq[0] is not None) else 0

            cur.execute("SELECT MAX(sequence) FROM mission_events")
            row_ev = cur.fetchone()
            ev_val = int(row_ev[0]) if (row_ev and row_ev[0] is not None) else 0

            return max(seq_val, ev_val)

    def append_mission_event(
        self,
        event_or_dict: Any,
        session_id: Optional[str] = None,
    ) -> int:
        """
        Append a single canonical mission event to mission_events table.
        Returns the committed sequence number.
        """
        from core.runtime_state.events import HermesEvent
        import hashlib

        if isinstance(event_or_dict, HermesEvent):
            seq = event_or_dict.sequence
            mission_id = event_or_dict.mission_id or "default"
            s_id = session_id or event_or_dict.session_id
            run_id = event_or_dict.run_id
            attempt_number = event_or_dict.attempt_number or 1
            event_id = event_or_dict.event_id
            event_type = event_or_dict.event_type.value if hasattr(event_or_dict.event_type, "value") else str(event_or_dict.event_type)
            timestamp = event_or_dict.timestamp or time.time()
            schema_version = event_or_dict.schema_version or 1
            payload_json = json.dumps(event_or_dict.to_dict(), sort_keys=True)
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        elif isinstance(event_or_dict, dict):
            seq = int(event_or_dict.get("sequence", 0))
            mission_id = event_or_dict.get("mission_id", "default")
            s_id = session_id or event_or_dict.get("session_id")
            run_id = event_or_dict.get("run_id")
            attempt_number = int(event_or_dict.get("attempt_number", 1))
            event_id = event_or_dict.get("event_id", "")
            event_type = event_or_dict.get("event_type", "GENERIC_EVENT")
            timestamp = float(event_or_dict.get("timestamp", time.time()))
            schema_version = int(event_or_dict.get("schema_version", 1))
            payload_json = json.dumps(event_or_dict, sort_keys=True)
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        else:
            raise ValueError(f"Unsupported event type: {type(event_or_dict)}")

        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO mission_events (
                    sequence, mission_id, session_id, run_id, attempt_number,
                    event_id, event_type, timestamp, payload_hash, payload_json, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sequence) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    payload_hash = excluded.payload_hash;
            """, (
                seq, mission_id, s_id, run_id, attempt_number,
                event_id, event_type, timestamp, payload_hash, payload_json, schema_version
            ))
            # Also update last_event_sequence on mission record if it exists
            cur.execute("""
                UPDATE missions
                SET last_event_sequence = max(last_event_sequence, ?),
                    updated_at = ?
                WHERE mission_id = ?
            """, (seq, timestamp, mission_id))

        return seq

    def append_mission_events_batch(
        self,
        events: List[Any],
        session_id: Optional[str] = None,
    ) -> int:
        """
        Append a batch of canonical mission events to mission_events table inside a single transaction.
        Returns the maximum committed sequence number.
        """
        if not events:
            return 0

        from core.runtime_state.events import HermesEvent
        import hashlib

        parsed_rows = []
        mission_updates: Dict[str, Tuple[int, float]] = {}

        for event_or_dict in events:
            if isinstance(event_or_dict, HermesEvent):
                seq = event_or_dict.sequence
                mission_id = event_or_dict.mission_id or "default"
                s_id = session_id or event_or_dict.session_id
                run_id = event_or_dict.run_id
                attempt_number = event_or_dict.attempt_number or 1
                event_id = event_or_dict.event_id
                event_type = event_or_dict.event_type.value if hasattr(event_or_dict.event_type, "value") else str(event_or_dict.event_type)
                timestamp = event_or_dict.timestamp or time.time()
                schema_version = event_or_dict.schema_version or 1
                payload_json = json.dumps(event_or_dict.to_dict(), sort_keys=True)
                payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            elif isinstance(event_or_dict, dict):
                seq = int(event_or_dict.get("sequence", 0))
                mission_id = event_or_dict.get("mission_id", "default")
                s_id = session_id or event_or_dict.get("session_id")
                run_id = event_or_dict.get("run_id")
                attempt_number = int(event_or_dict.get("attempt_number", 1))
                event_id = event_or_dict.get("event_id", "")
                event_type = event_or_dict.get("event_type", "GENERIC_EVENT")
                timestamp = float(event_or_dict.get("timestamp", time.time()))
                schema_version = int(event_or_dict.get("schema_version", 1))
                payload_json = json.dumps(event_or_dict, sort_keys=True)
                payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            else:
                continue

            parsed_rows.append((
                seq, mission_id, s_id, run_id, attempt_number,
                event_id, event_type, timestamp, payload_hash, payload_json, schema_version
            ))

            curr_seq, curr_ts = mission_updates.get(mission_id, (0, 0.0))
            mission_updates[mission_id] = (max(curr_seq, seq), max(curr_ts, timestamp))

        if not parsed_rows:
            return 0

        # Ensure strict monotonic sequence order for SQLite batch insertion
        parsed_rows.sort(key=lambda r: r[0])

        with self.transaction() as cur:
            cur.executemany("""
                INSERT INTO mission_events (
                    sequence, mission_id, session_id, run_id, attempt_number,
                    event_id, event_type, timestamp, payload_hash, payload_json, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sequence) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    payload_hash = excluded.payload_hash;
            """, parsed_rows)

            for m_id, (m_seq, m_ts) in mission_updates.items():
                cur.execute("""
                    UPDATE missions
                    SET last_event_sequence = max(last_event_sequence, ?),
                        updated_at = ?
                    WHERE mission_id = ?
                """, (m_seq, m_ts, m_id))

        return max(r[0] for r in parsed_rows)

    def get_mission_events(
        self,
        mission_id: str,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve journaled mission events ordered by monotonic sequence."""
        with self.transaction() as cur:
            if to_seq is not None:
                cur.execute("""
                    SELECT * FROM mission_events
                    WHERE mission_id = ? AND sequence >= ? AND sequence <= ?
                    ORDER BY sequence ASC
                """, (mission_id, from_seq, to_seq))
            else:
                cur.execute("""
                    SELECT * FROM mission_events
                    WHERE mission_id = ? AND sequence >= ?
                    ORDER BY sequence ASC
                """, (mission_id, from_seq))
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["payload"] = json.loads(d.get("payload_json", "{}"))
                results.append(d)
            return results

    def save_mission(
        self,
        mission_id: str,
        workspace_path: str,
        status: str,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        attempt_number: int = 1,
        wait_reason: str = "NONE",
        prompt: str = "",
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        state_version: int = 0,
        last_event_sequence: int = 0,
        latest_checkpoint_id: Optional[str] = None,
        execution_active: bool = False,
        recovery_required: bool = False,
        error: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error_json: Optional[Any] = None,
    ) -> None:
        """Save or update canonical mission record."""
        now = time.time()
        c_at = created_at if created_at is not None else now
        u_at = updated_at if updated_at is not None else now
        eff_err = error if error is not None else error_json
        if isinstance(eff_err, str):
            try:
                eff_err = json.loads(eff_err)
            except Exception:
                eff_err = {"message": eff_err}
        err_json = json.dumps(eff_err or {}, sort_keys=True)
        meta_json = json.dumps(metadata or {}, sort_keys=True)

        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO missions (
                    mission_id, session_id, run_id, attempt_number,
                    workspace_path, status, wait_reason, prompt,
                    created_at, updated_at, state_version, last_event_sequence,
                    latest_checkpoint_id, execution_active, recovery_required,
                    error_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mission_id) DO UPDATE SET
                    session_id = COALESCE(excluded.session_id, missions.session_id),
                    run_id = COALESCE(excluded.run_id, missions.run_id),
                    attempt_number = excluded.attempt_number,
                    workspace_path = excluded.workspace_path,
                    status = excluded.status,
                    wait_reason = excluded.wait_reason,
                    prompt = CASE WHEN excluded.prompt != '' THEN excluded.prompt ELSE missions.prompt END,
                    updated_at = excluded.updated_at,
                    state_version = excluded.state_version,
                    last_event_sequence = max(missions.last_event_sequence, excluded.last_event_sequence),
                    latest_checkpoint_id = COALESCE(excluded.latest_checkpoint_id, missions.latest_checkpoint_id),
                    execution_active = excluded.execution_active,
                    recovery_required = excluded.recovery_required,
                    error_json = excluded.error_json,
                    metadata_json = excluded.metadata_json;
            """, (
                mission_id, session_id, run_id, attempt_number,
                workspace_path, status, wait_reason, prompt,
                c_at, u_at, state_version, last_event_sequence,
                latest_checkpoint_id, 1 if execution_active else 0, 1 if recovery_required else 0,
                err_json, meta_json
            ))

    def get_mission(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve canonical mission record."""
        with self.transaction() as cur:
            cur.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["execution_active"] = bool(d.get("execution_active", 0))
            d["recovery_required"] = bool(d.get("recovery_required", 0))
            d["error"] = json.loads(d.pop("error_json", "{}"))
            d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
            return d

    def list_missions(self) -> List[Dict[str, Any]]:
        """List all canonical missions ordered by updated_at descending."""
        with self.transaction() as cur:
            cur.execute("SELECT * FROM missions ORDER BY updated_at DESC")
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["execution_active"] = bool(d.get("execution_active", 0))
                d["recovery_required"] = bool(d.get("recovery_required", 0))
                d["error"] = json.loads(d.pop("error_json", "{}"))
                d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                results.append(d)
            return results

    def save_snapshot(
        self,
        mission_id: str,
        workspace_path: str,
        status: str,
        snapshot_dict: Dict[str, Any],
        state_hash: str,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        attempt_number: int = 1,
        schema_version: int = 1,
        state_version: int = 0,
        last_event_sequence: int = 0,
        created_at: Optional[float] = None,
    ) -> None:
        """Persist authoritative mission runtime snapshot."""
        now = created_at if created_at is not None else time.time()
        snap_json = json.dumps(snapshot_dict, sort_keys=True)

        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO snapshots (
                    mission_id, session_id, run_id, attempt_number,
                    schema_version, state_version, last_event_sequence,
                    workspace_path, status, snapshot_json, created_at, state_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mission_id) DO UPDATE SET
                    session_id = COALESCE(excluded.session_id, snapshots.session_id),
                    run_id = COALESCE(excluded.run_id, snapshots.run_id),
                    attempt_number = excluded.attempt_number,
                    schema_version = excluded.schema_version,
                    state_version = excluded.state_version,
                    last_event_sequence = excluded.last_event_sequence,
                    workspace_path = excluded.workspace_path,
                    status = excluded.status,
                    snapshot_json = excluded.snapshot_json,
                    created_at = excluded.created_at,
                    state_hash = excluded.state_hash;
            """, (
                mission_id, session_id, run_id, attempt_number,
                schema_version, state_version, last_event_sequence,
                workspace_path, status, snap_json, now, state_hash
            ))

    def get_snapshot(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve authoritative mission runtime snapshot."""
        with self.transaction() as cur:
            cur.execute("SELECT * FROM snapshots WHERE mission_id = ?", (mission_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["snapshot"] = json.loads(d.pop("snapshot_json", "{}"))
            return d

    def save_verification_evidence(
        self,
        evidence_id: str,
        mission_id: str,
        command: str,
        working_dir: str,
        interpreter: str,
        exit_code: int,
        status: str,
        run_id: Optional[str] = None,
        duration_seconds: float = 0.0,
        output_summary: str = "",
        rationale: str = "",
        created_at: Optional[float] = None,
    ) -> None:
        """Persist verification run evidence."""
        now = created_at if created_at is not None else time.time()
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO verification_evidence (
                    evidence_id, mission_id, run_id, command, working_dir,
                    interpreter, exit_code, duration_seconds, output_summary,
                    status, rationale, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    exit_code = excluded.exit_code,
                    duration_seconds = excluded.duration_seconds,
                    output_summary = excluded.output_summary,
                    status = excluded.status,
                    rationale = excluded.rationale;
            """, (
                evidence_id, mission_id, run_id, command, working_dir,
                interpreter, exit_code, duration_seconds, output_summary,
                status, rationale, now
            ))

    def list_verification_evidence(self, mission_id: str) -> List[Dict[str, Any]]:
        """List verification evidence records for a mission."""
        with self.transaction() as cur:
            cur.execute("""
                SELECT * FROM verification_evidence
                WHERE mission_id = ?
                ORDER BY created_at ASC
            """, (mission_id,))
            return [dict(r) for r in cur.fetchall()]

    # ── Phase 3 Tool Operation Persistence Methods ────────────────────────────

    def record_tool_intent(
        self,
        operation_id: str,
        mission_id: str,
        tool_name: str,
        intent_seq: int,
        task_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        run_id: Optional[str] = None,
        attempt_number: int = 1,
        session_id: Optional[str] = None,
        target_path: Optional[str] = None,
        workspace_root: str = "",
        arguments_summary: str = "",
        arguments: Optional[Dict[str, Any]] = None,
        prior_hash: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> None:
        """
        Durably record write-ahead tool intent.
        Raises OperationAlreadyCommittedError if operation_id already exists.
        """
        from core.persistence.models import OperationAlreadyCommittedError, OperationStatus
        now = created_at if created_at is not None else time.time()
        args_json = json.dumps(arguments or {}, sort_keys=True)

        with self.transaction() as cur:
            cur.execute("SELECT status FROM tool_operations WHERE operation_id = ?", (operation_id,))
            existing = cur.fetchone()
            if existing:
                raise OperationAlreadyCommittedError(
                    f"Operation '{operation_id}' is already recorded with status '{existing[0]}'."
                )

            cur.execute("""
                INSERT INTO tool_operations (
                    operation_id, mission_id, tool_name, status,
                    intent_seq, task_id, turn_id, run_id, attempt_number,
                    session_id, target_path, workspace_root,
                    arguments_summary, arguments_json, prior_hash,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                operation_id, mission_id, tool_name, OperationStatus.INTENT_COMMITTED.value,
                intent_seq, task_id, turn_id, run_id, attempt_number,
                session_id, target_path, workspace_root,
                arguments_summary, args_json, prior_hash,
                now
            ))

    def record_tool_result(
        self,
        operation_id: str,
        result_seq: int,
        status: Any,  # OperationStatus or str
        exit_code: int = 0,
        post_hash: Optional[str] = None,
        output_summary: Optional[str] = None,
        error_message: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        side_effects: Optional[Dict[str, Any]] = None,
        committed_at: Optional[float] = None,
    ) -> None:
        """Durably record the execution result for an existing operation intent."""
        from core.persistence.models import OperationStatus
        now = committed_at if committed_at is not None else time.time()
        st_val = status.value if hasattr(status, "value") else str(status)
        side_effects_json = json.dumps(side_effects or {}, sort_keys=True)

        with self.transaction() as cur:
            cur.execute("""
                UPDATE tool_operations
                SET result_seq = ?,
                    status = ?,
                    exit_code = ?,
                    post_hash = ?,
                    output_summary = ?,
                    error_message = ?,
                    duration_seconds = ?,
                    side_effects_json = ?,
                    committed_at = ?
                WHERE operation_id = ?;
            """, (
                result_seq, st_val, exit_code, post_hash,
                output_summary, error_message, duration_seconds,
                side_effects_json, now, operation_id
            ))

    def update_operation_status(
        self,
        operation_id: str,
        status: Any,  # OperationStatus or str
        error_message: Optional[str] = None,
    ) -> None:
        """Update operation status (e.g. OUTCOME_UNKNOWN or REQUIRES_RECONCILIATION)."""
        st_val = status.value if hasattr(status, "value") else str(status)
        with self.transaction() as cur:
            if error_message:
                cur.execute("""
                    UPDATE tool_operations
                    SET status = ?, error_message = ?
                    WHERE operation_id = ?;
                """, (st_val, error_message, operation_id))
            else:
                cur.execute("""
                    UPDATE tool_operations
                    SET status = ?
                    WHERE operation_id = ?;
                """, (st_val, operation_id))

    def get_tool_operation(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve authoritative tool operation record."""
        with self.transaction() as cur:
            cur.execute("SELECT * FROM tool_operations WHERE operation_id = ?", (operation_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["arguments"] = json.loads(d.pop("arguments_json", "{}"))
            d["side_effects"] = json.loads(d.pop("side_effects_json", "{}"))
            return d

    def list_tool_operations(
        self,
        mission_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List tool operations for a mission, optionally filtered by status."""
        with self.transaction() as cur:
            if status is not None:
                cur.execute("""
                    SELECT * FROM tool_operations
                    WHERE mission_id = ? AND status = ?
                    ORDER BY intent_seq ASC
                """, (mission_id, status))
            else:
                cur.execute("""
                    SELECT * FROM tool_operations
                    WHERE mission_id = ?
                    ORDER BY intent_seq ASC
                """, (mission_id,))
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["arguments"] = json.loads(d.pop("arguments_json", "{}"))
                d["side_effects"] = json.loads(d.pop("side_effects_json", "{}"))
                results.append(d)
            return results

