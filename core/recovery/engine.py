# core/recovery/engine.py
"""
Recovery Engine for HERMES 2.x session resume.

Executes the deterministic 16-step startup and recovery sequence.
Guarantees zero duplicate tool executions and safe cross-domain reconciliation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.checkpoints.engine import CheckpointEngine
from core.event_bus import EventBus
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.journal import EventJournal
from core.persistence.models import (
    CheckpointCorrupt,
    CheckpointNotFound,
    RecoveryBlocked,
    ResumeConflict,
    SessionStatus,
)
from core.persistence.serializer import deserialize_runtime_state
from core.recovery.gate import RecoveryGate, RecoveryVerdict
from core.recovery.reconcile import DomainReconciler
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState
from core.sessions.manager import SessionManager

logger = logging.getLogger("hermes.recovery.engine")


class RecoveryEngine:
    """
    Authoritative coordinator for resuming interrupted or paused HERMES sessions.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        workspace_root: Path | str,
        event_bus: Optional[EventBus] = None,
    ):
        self.session_manager = session_manager
        self.workspace_root = Path(workspace_root).resolve()
        self.event_bus = event_bus
        self.reconciler = DomainReconciler(self.workspace_root)

    def resume_session(
        self,
        session_id: str,
        is_headless: bool = False,
    ) -> Tuple[HermesRuntimeState, RecoveryVerdict]:
        """
        Resume an existing session through the 16-step deterministic protocol.
        """
        # Step 1: Acquire exclusive session lock
        lock = self.session_manager.acquire_session_lock(session_id)

        try:
            # Step 2: Load session metadata
            session = self.session_manager.get_session(session_id)
            if not session:
                raise ValueError(f"Session '{session_id}' not found.")

            # Mark session as recovering
            session.status = SessionStatus.RECOVERING
            self.session_manager._persist_session(session)

            if self.event_bus:
                self.event_bus.publish(HermesEvent(
                    event_type=EventType.RECOVERY_STARTED if hasattr(EventType, "RECOVERY_STARTED") else EventType.SESSION_RESUMED,
                    mission_id=session.mission_id,
                    session_id=session_id,
                    payload={"session_id": session_id},
                ))

            # Step 3 & 4: Locate latest durable checkpoint
            checkpoint_id = session.current_checkpoint_id
            if not checkpoint_id:
                checkpoints = self.session_manager.checkpoint_engine.list_checkpoints(session_id)
                if checkpoints:
                    checkpoint_id = checkpoints[-1].checkpoint_id

            if not checkpoint_id:
                # No checkpoints yet -> construct fresh initial state and replay all journal events
                initial_state = HermesRuntimeState.create_empty(session.mission_id, session_id)
                replayed_state = self.session_manager.journal.replay(session_id, initial_state, from_seq=1)
                verdict = RecoveryGate.evaluate({}, {}, {}, {}, is_headless=is_headless)
                session.status = SessionStatus.RUNNING
                self.session_manager._persist_session(session)
                return replayed_state, verdict

            # Step 5: Load checkpoint manifest
            chk = self.session_manager.checkpoint_engine.get_checkpoint(checkpoint_id)
            if not chk:
                raise CheckpointNotFound(f"Checkpoint '{checkpoint_id}' could not be loaded.")

            # Step 6: Validate blob hashes
            if not self.session_manager.checkpoint_engine.verify_checkpoint_integrity(checkpoint_id):
                raise CheckpointCorrupt(f"Integrity check failed for checkpoint '{checkpoint_id}'.")

            # Step 7: Load state bytes from CAS
            if chk.state_hash:
                if not self.session_manager.blob_store.has(chk.state_hash):
                    raise CheckpointCorrupt(f"State blob missing for checkpoint '{checkpoint_id}'.")
                state_blob = self.session_manager.blob_store.get(chk.state_hash)
                state_data = json.loads(state_blob.decode("utf-8"))
                checkpoint_state = deserialize_runtime_state(state_data)
            else:
                checkpoint_state = HermesRuntimeState.create_empty(session.mission_id, session_id)

            # Step 8: Replay journal after checkpoint sequence (ZERO tool execution)
            post_seq = chk.sequence + 1
            reconstructed_state = self.session_manager.journal.replay(
                session_id=session_id,
                initial_state=checkpoint_state,
                from_seq=post_seq,
            )

            # Step 9: Reconcile filesystem drift
            fs_reconcile = self.reconciler.reconcile_filesystem(chk)

            # Step 10: Reconcile Git drift
            git_reconcile = self.reconciler.reconcile_git(chk)

            # Step 11: Reconcile background jobs
            jobs_reconcile = self.reconciler.reconcile_background_jobs(chk)

            # Step 12: Reinitialize provider
            prov_reconcile = self.reconciler.reconcile_provider(chk)

            # Step 13: Reconcile security
            sec_reconcile = self.reconciler.reconcile_security(chk)

            # Step 14: Evaluate RecoveryGate
            verdict = RecoveryGate.evaluate(
                fs_reconcile=fs_reconcile,
                git_reconcile=git_reconcile,
                jobs_reconcile=jobs_reconcile,
                security_reconcile=sec_reconcile,
                is_headless=is_headless,
            )

            if not verdict.can_proceed:
                session.status = SessionStatus.INTERRUPTED
                self.session_manager._persist_session(session)
                raise RecoveryBlocked(f"Recovery blocked by gate: {verdict.warnings}")

            # Step 15: Mark session RUNNING and persist
            session.status = SessionStatus.RUNNING
            self.session_manager._persist_session(session)

            # Step 16: Emit Recovery Completed Event
            if self.event_bus:
                self.event_bus.publish(HermesEvent(
                    event_type=EventType.RECOVERY_COMPLETED if hasattr(EventType, "RECOVERY_COMPLETED") else EventType.SESSION_RESUMED,
                    mission_id=session.mission_id,
                    session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    payload={
                        "decision": verdict.decision.value,
                        "warnings": verdict.warnings,
                        "replayed_from_seq": post_seq,
                    },
                ))

            logger.info("Session '%s' resumed successfully (decision=%s)", session_id, verdict.decision.value)
            return reconstructed_state, verdict

        except Exception as e:
            logger.error("Session recovery failed for '%s': %s", session_id, e)
            self.session_manager.release_session_lock(session_id)
            raise
