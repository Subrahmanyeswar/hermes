# core/sessions/manager.py
"""
Session Manager for HERMES 2.x persistence.

Coordinates session lifecycle, forks, branches, clear operations, and locks.
Preserves historical execution lineages without destructive mutations.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.checkpoints.engine import CheckpointEngine
from core.event_bus import EventBus
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.journal import EventJournal
from core.persistence.locks import SessionLock
from core.persistence.models import (
    CheckpointManifest,
    CheckpointReason,
    CheckpointTrigger,
    ResumeConflict,
    SessionStatus,
)
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState
from core.sessions.models import DurableSession
from core.sessions.transcript import TranscriptStore

logger = logging.getLogger("hermes.sessions.manager")


class SessionManager:
    """
    Authoritative manager for durable sessions, branches, and execution lineage.
    """

    def __init__(
        self,
        base_dir: Path | str,
        workspace_root: Path | str,
        event_bus: Optional[EventBus] = None,
    ):
        self.base_dir = Path(base_dir).resolve()
        self.workspace_root = Path(workspace_root).resolve()
        self.event_bus = event_bus

        # Initialize persistence primitives
        self.db = SQLiteDatabase(self.base_dir / "hermes_state.db")
        self.blob_store = BlobStore(self.base_dir)
        self.journal = EventJournal(self.db)
        self.transcript_store = TranscriptStore(self.db, self.blob_store)
        self.checkpoint_engine = CheckpointEngine(
            base_dir=self.base_dir,
            workspace_root=self.workspace_root,
            db=self.db,
            blob_store=self.blob_store,
            event_bus=self.event_bus,
        )
        self._active_locks: Dict[str, SessionLock] = {}

    def create_session(
        self,
        mission_id: str,
        branch_name: str = "main",
        parent_session_id: Optional[str] = None,
        root_session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DurableSession:
        """Create a new durable session."""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = time.time()
        session = DurableSession(
            session_id=session_id,
            mission_id=mission_id,
            workspace_root=str(self.workspace_root),
            status=SessionStatus.CREATED,
            parent_session_id=parent_session_id,
            root_session_id=root_session_id or session_id,
            branch_name=branch_name,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._persist_session(session)

        if self.event_bus:
            self.event_bus.publish(HermesEvent(
                event_type=EventType.SESSION_CREATED,
                mission_id=mission_id,
                session_id=session_id,
                payload={"session_id": session_id, "branch_name": branch_name},
            ))

        return session

    def get_session(self, session_id: str) -> Optional[DurableSession]:
        """Fetch session metadata."""
        row = self.db.get_session(session_id)
        if not row:
            return None
        return DurableSession.from_dict(row)

    def list_sessions(self) -> List[DurableSession]:
        """List all durable sessions."""
        rows = self.db.list_sessions()
        return [DurableSession.from_dict(r) for r in rows]

    def _persist_session(self, session: DurableSession) -> None:
        session.updated_at = time.time()
        self.db.save_session(
            session_id=session.session_id,
            parent_session_id=session.parent_session_id,
            root_session_id=session.root_session_id,
            mission_id=session.mission_id,
            workspace_root=session.workspace_root,
            status=session.status,
            current_checkpoint_id=session.current_checkpoint_id,
            current_sequence=session.current_sequence,
            created_at=session.created_at,
            updated_at=session.updated_at,
            branch_name=session.branch_name,
            metadata=session.metadata,
        )

    def acquire_session_lock(self, session_id: str) -> SessionLock:
        """Acquire mutual-exclusion lock for session."""
        lock = SessionLock(self.db, session_id)
        if not lock.acquire():
            raise ResumeConflict(f"Cannot acquire exclusive lock for session '{session_id}'. Another instance is active.")
        self._active_locks[session_id] = lock
        return lock

    def release_session_lock(self, session_id: str) -> None:
        """Release session lock."""
        lock = self._active_locks.pop(session_id, None)
        if lock:
            lock.release()

    def update_heartbeat(self, session_id: str) -> None:
        """Update session lock heartbeat."""
        lock = self._active_locks.get(session_id)
        if lock:
            lock.heartbeat()

    def pause_session(self, session_id: str) -> DurableSession:
        """Pause session execution cleanly."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")
        session.status = SessionStatus.PAUSED
        self._persist_session(session)
        self.release_session_lock(session_id)
        return session

    def clear_session(self, session_id: str, new_mission_id: Optional[str] = None) -> DurableSession:
        """
        Clear conversation: preserves prior session in durable history,
        and starts a fresh logical session on the same workspace.
        """
        old_session = self.get_session(session_id)
        if old_session:
            old_session.status = SessionStatus.PAUSED
            self._persist_session(old_session)
            self.release_session_lock(session_id)

        m_id = new_mission_id or f"mission_{uuid.uuid4().hex[:8]}"
        new_session = self.create_session(
            mission_id=m_id,
            branch_name="main",
            metadata={"cleared_from_session": session_id},
        )
        return new_session

    def fork_session(
        self,
        source_session_id: str,
        checkpoint_id: str,
        new_mission_id: Optional[str] = None,
        branch_name: Optional[str] = None,
    ) -> DurableSession:
        """
        Fork session from a specific checkpoint.
        Inherits historical transcript and state through copy-on-write without mutating the parent.
        """
        parent = self.get_session(source_session_id)
        if not parent:
            raise ValueError(f"Source session '{source_session_id}' does not exist.")

        checkpoint = self.checkpoint_engine.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint '{checkpoint_id}' not found.")

        fork_seq = checkpoint.sequence
        b_name = branch_name or f"fork_{checkpoint_id[:8]}"
        m_id = new_mission_id or parent.mission_id

        child_session = self.create_session(
            mission_id=m_id,
            branch_name=b_name,
            parent_session_id=source_session_id,
            root_session_id=parent.root_session_id or parent.session_id,
            metadata={
                "source_checkpoint_id": checkpoint_id,
                "forked_at_sequence": fork_seq,
            },
        )
        child_session.current_checkpoint_id = checkpoint_id
        child_session.current_sequence = fork_seq
        child_session.fork_sequence = fork_seq
        self._persist_session(child_session)

        if self.event_bus:
            self.event_bus.publish(HermesEvent(
                event_type=EventType.SESSION_FORKED if hasattr(EventType, "SESSION_FORKED") else EventType.SESSION_CREATED,
                mission_id=m_id,
                session_id=child_session.session_id,
                parent_agent_id=source_session_id,
                checkpoint_id=checkpoint_id,
                payload={
                    "child_session_id": child_session.session_id,
                    "parent_session_id": source_session_id,
                    "checkpoint_id": checkpoint_id,
                    "fork_sequence": fork_seq,
                },
            ))

        return child_session

    def branch_session(self, session_id: str, branch_name: str) -> DurableSession:
        """Create a named logical branch of the current session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        last_chk = session.current_checkpoint_id
        if not last_chk:
            checkpoints = self.checkpoint_engine.list_checkpoints(session_id)
            if checkpoints:
                last_chk = checkpoints[-1].checkpoint_id

        if not last_chk:
            raise ValueError("Cannot branch session without at least one checkpoint.")

        return self.fork_session(
            source_session_id=session_id,
            checkpoint_id=last_chk,
            branch_name=branch_name,
        )

    def create_checkpoint(
        self,
        session_id: str,
        runtime_state: HermesRuntimeState,
        reason: CheckpointReason = CheckpointReason.MANUAL,
        trigger: CheckpointTrigger = CheckpointTrigger.SYSTEM,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CheckpointManifest:
        """Create and record an immutable checkpoint for a session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        manifest = self.checkpoint_engine.create_checkpoint(
            session_id=session_id,
            mission_id=session.mission_id,
            runtime_state=runtime_state,
            reason=reason,
            trigger=trigger,
            sequence=runtime_state.last_event_sequence,
            parent_checkpoint_id=session.current_checkpoint_id,
            metadata=metadata,
        )

        session.current_checkpoint_id = manifest.checkpoint_id
        session.current_sequence = manifest.sequence
        session.updated_at = time.time()
        self._persist_session(session)

        return manifest

    def resume_session(
        self,
        session_id: str,
        is_headless: bool = False,
    ) -> Tuple[HermesRuntimeState, Any]:
        """Resume an interrupted or paused session."""
        from core.recovery.engine import RecoveryEngine
        engine = RecoveryEngine(session_manager=self, workspace_root=self.workspace_root, event_bus=self.event_bus)
        return engine.resume_session(session_id=session_id, is_headless=is_headless)

    def rewind_session(
        self,
        session_id: str,
        checkpoint_id: str,
        mode: Any = None,
        force_overwrite_user_conflicts: bool = False,
        known_agent_created_files: Optional[Set[str]] = None,
        intermediate_agent_files: Optional[Set[str]] = None,
    ) -> HermesRuntimeState:
        """Rewind a session to a target checkpoint."""
        from core.recovery.rewind import RewindEngine
        from core.persistence.models import RewindMode
        effective_mode = mode or RewindMode.CODE_AND_CONVERSATION
        engine = RewindEngine(
            workspace_root=self.workspace_root,
            checkpoint_engine=self.checkpoint_engine,
            blob_store=self.blob_store,
            event_bus=self.event_bus,
        )
        state = engine.execute_rewind(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            mode=effective_mode,
            force_overwrite_user_conflicts=force_overwrite_user_conflicts,
            known_agent_created_files=known_agent_created_files,
            intermediate_agent_files=intermediate_agent_files,
        )
        session = self.get_session(session_id)
        if session:
            session.current_checkpoint_id = checkpoint_id
            session.current_sequence = state.last_event_sequence
            self._persist_session(session)
        return state
