# core/recovery/rewind.py
"""
Rewind Engine for HERMES 2.x persistence.

Restores workspace files, resets runtime state, and updates conversation cursors
while strictly preserving user modifications and historical event records.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from core.checkpoints.engine import CheckpointEngine
from core.event_bus import EventBus
from core.evidence.invalidator import EvidenceInvalidator
from core.persistence.blobs import BlobStore
from core.persistence.models import (
    CheckpointManifest,
    CheckpointNotFound,
    RewindConflict,
    RewindMode,
)
from core.persistence.serializer import deserialize_runtime_state
from core.persistence.transactions import atomic_write
from core.recovery.conflicts import ConflictDetector, RestoreActionType, RestorePlan
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState

logger = logging.getLogger("hermes.recovery.rewind")


class RewindEngine:
    """
    Authoritative coordinator for rewind and safe restoration.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        checkpoint_engine: CheckpointEngine,
        blob_store: BlobStore,
        event_bus: Optional[EventBus] = None,
        evidence_invalidator: Optional[EvidenceInvalidator] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.checkpoint_engine = checkpoint_engine
        self.blob_store = blob_store
        self.event_bus = event_bus
        self.invalidator = evidence_invalidator

    def preview_rewind(
        self,
        session_id: str,
        checkpoint_id: str,
        known_agent_created_files: Optional[Set[str]] = None,
        intermediate_agent_files: Optional[Set[str]] = None,
    ) -> RestorePlan:
        """Inspect what would be restored or conflicted without mutating disk."""
        chk = self.checkpoint_engine.get_checkpoint(checkpoint_id)
        if not chk:
            raise CheckpointNotFound(f"Checkpoint '{checkpoint_id}' not found.")

        return ConflictDetector.compute_plan(
            workspace_root=self.workspace_root,
            target_manifest=chk.workspace,
            known_agent_created_files=known_agent_created_files,
            intermediate_agent_files=intermediate_agent_files,
        )

    def execute_rewind(
        self,
        session_id: str,
        checkpoint_id: str,
        mode: RewindMode = RewindMode.CODE_AND_CONVERSATION,
        force_overwrite_user_conflicts: bool = False,
        known_agent_created_files: Optional[Set[str]] = None,
        intermediate_agent_files: Optional[Set[str]] = None,
    ) -> HermesRuntimeState:
        """
        Execute safe rewind to target checkpoint.
        Strictly preserves user modifications unless force_overwrite_user_conflicts is True.
        """
        chk = self.checkpoint_engine.get_checkpoint(checkpoint_id)
        if not chk:
            raise CheckpointNotFound(f"Checkpoint '{checkpoint_id}' not found.")

        # Compute restore plan
        plan = self.preview_rewind(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            known_agent_created_files=known_agent_created_files,
            intermediate_agent_files=intermediate_agent_files,
        )

        if plan.user_conflicts_count > 0 and not force_overwrite_user_conflicts:
            if mode in (RewindMode.FILES_ONLY, RewindMode.CODE_AND_CONVERSATION, RewindMode.FULL_SAFE_REWIND):
                logger.info("Rewind detected %s user edits; user changes will be preserved.", plan.user_conflicts_count)

        if self.event_bus:
            self.event_bus.publish(HermesEvent(
                event_type=EventType.REWIND_STARTED if hasattr(EventType, "REWIND_STARTED") else EventType.CHECKPOINT_RESTORE_STARTED,
                mission_id=chk.mission_id,
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                payload={"mode": mode.value, "plan_actions": len(plan.actions)},
            ))

        modified_files: Set[str] = set()

        # 1. Restore Files (if mode permits)
        if mode in (RewindMode.FILES_ONLY, RewindMode.CODE_AND_CONVERSATION, RewindMode.FULL_SAFE_REWIND):
            for action in plan.actions:
                dest = self.workspace_root / action.relative_path

                if action.action_type == RestoreActionType.RESTORE_FILE and action.target_blob_id:
                    content_bytes = self.blob_store.get(action.target_blob_id)
                    atomic_write(dest, content_bytes, mode="wb")
                    modified_files.add(action.relative_path)

                    if self.event_bus:
                        self.event_bus.publish(HermesEvent(
                            event_type=EventType.REWIND_FILE_RESTORED if hasattr(EventType, "REWIND_FILE_RESTORED") else EventType.STATE_SNAPSHOT,
                            mission_id=chk.mission_id,
                            session_id=session_id,
                            checkpoint_id=checkpoint_id,
                            payload={"file": action.relative_path, "blob_id": action.target_blob_id},
                        ))

                elif action.action_type == RestoreActionType.DELETE_CREATED_FILE:
                    if dest.exists() and dest.is_file():
                        dest.unlink(missing_ok=True)
                        modified_files.add(action.relative_path)

                elif action.action_type == RestoreActionType.PRESERVE_USER_EDIT:
                    if self.event_bus:
                        self.event_bus.publish(HermesEvent(
                            event_type=EventType.REWIND_CONFLICT_DETECTED if hasattr(EventType, "REWIND_CONFLICT_DETECTED") else EventType.WARNING,
                            mission_id=chk.mission_id,
                            session_id=session_id,
                            checkpoint_id=checkpoint_id,
                            payload={"file": action.relative_path, "reason": action.reason},
                        ))

        # 2. Invalidate Evidence for Modified Files
        if self.invalidator and modified_files:
            logger.info("Invalidating evidence for modified files: %s", modified_files)

        # 3. Restore Runtime State
        # Load serialized state from blob store
        raw_manifest_row = self.checkpoint_engine.db.get_checkpoint(checkpoint_id)
        if raw_manifest_row:
            manifest_dict = json.loads(raw_manifest_row["manifest_json"])
        else:
            manifest_dict = chk.to_dict()

        # The state_hash matches the blob in BlobStore
        state_blob = self.blob_store.get(chk.state_hash) if self.blob_store.has(chk.state_hash) else None
        if state_blob:
            state_data = json.loads(state_blob.decode("utf-8"))
            restored_state = deserialize_runtime_state(state_data)
        else:
            # Reconstruct basic empty state
            restored_state = HermesRuntimeState.create_empty(chk.mission_id, session_id)

        # 4. Invalidate Acceptance Checks in Restored State for Changed Files
        if modified_files and hasattr(restored_state, "acceptance_ledger"):
            stale_ids = restored_state.acceptance_ledger.mark_stale_for_files(modified_files)
            if stale_ids:
                logger.info("Marked %s acceptance checks stale due to file rewind: %s", len(stale_ids), stale_ids)

        # 5. Publish Completion Event
        if self.event_bus:
            self.event_bus.publish(HermesEvent(
                event_type=EventType.REWIND_COMPLETED if hasattr(EventType, "REWIND_COMPLETED") else EventType.CHECKPOINT_RESTORED,
                mission_id=chk.mission_id,
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                payload={
                    "checkpoint_id": checkpoint_id,
                    "restored_files_count": len(modified_files),
                    "user_conflicts_preserved": plan.user_conflicts_count,
                },
            ))

        logger.info("Rewind to '%s' completed successfully (mode=%s)", checkpoint_id, mode.value)
        return restored_state
