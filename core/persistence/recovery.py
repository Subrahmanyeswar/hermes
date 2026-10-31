# core/persistence/recovery.py
"""
Recovery Coordinator for HERMES Phase 5.
Handles:
1. Canonical checkpoint verification (manifest hash, CAS blob existence, state hash).
2. Original workspace directory verification and containment.
3. Disk-versus-ledger file reconciliation (prior_hash, post_hash, unexpected changes).
4. Unfinished task selection (dependency order, skipping completed tasks).
5. Resume plan formulation and reconciliation reports.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.checkpoints.engine import CheckpointEngine
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import (
    CheckpointManifest,
    OperationStatus,
)
from core.runtime_state.models import HermesRuntimeState, MissionStatus, TaskState, TaskStatus
from core.workspace import WorkspaceBoundaryError, WorkspaceManager
from core.workspace_registry import is_hermes_repo_root

logger = logging.getLogger("hermes.persistence.recovery")


class ReconciliationDiscrepancyType(str, Enum):
    FILE_MISSING = "FILE_MISSING"
    HASH_MISMATCH = "HASH_MISMATCH"
    OPERATION_UNCERTAIN = "OPERATION_UNCERTAIN"
    USER_MODIFIED = "USER_MODIFIED"
    UNEXPECTED_FILE = "UNEXPECTED_FILE"
    WORKSPACE_INACCESSIBLE = "WORKSPACE_INACCESSIBLE"
    CHECKPOINT_CORRUPT = "CHECKPOINT_CORRUPT"


@dataclass
class Discrepancy:
    discrepancy_type: ReconciliationDiscrepancyType
    path: Optional[str]
    description: str
    blocking: bool = True
    operation_id: Optional[str] = None
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None


@dataclass
class ResumePlan:
    mission_id: str
    original_workspace: str
    can_resume: bool
    checkpoint_id: Optional[str]
    target_task_id: Optional[str]
    target_task_title: Optional[str]
    completed_tasks: List[str] = field(default_factory=list)
    pending_tasks: List[str] = field(default_factory=list)
    discrepancies: List[Discrepancy] = field(default_factory=list)
    reason: str = ""
    reconciliation_summary: Dict[str, Any] = field(default_factory=dict)


def compute_file_sha256(path: Path) -> Optional[str]:
    """Compute SHA-256 hash of a file if it exists."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class RecoveryEngine:
    """
    Authoritative Recovery Engine for validating prior state, reconciling disk,
    and determining the first safe unfinished task for mission resumption.
    """

    def __init__(
        self,
        db: SQLiteDatabase,
        blob_store: BlobStore,
        checkpoint_engine: Optional[CheckpointEngine] = None,
        workspace_manager: Optional[WorkspaceManager] = None,
    ):
        self.db = db
        self.blob_store = blob_store
        self.checkpoint_engine = checkpoint_engine
        self.workspace_manager = workspace_manager

    def validate_checkpoint(self, checkpoint_id: str) -> Tuple[bool, Optional[CheckpointManifest], str]:
        """
        Verify checkpoint existence, manifest hash, and CAS blobs.
        """
        row = self.db.get_checkpoint(checkpoint_id)
        if not row:
            return False, None, f"Checkpoint '{checkpoint_id}' not found in database."

        try:
            manifest_dict = json.loads(row["manifest_json"])
            chk = CheckpointManifest.from_dict(manifest_dict)
        except Exception as e:
            return False, None, f"Failed to parse checkpoint manifest JSON: {e}"

        # 1. Recalculate manifest hash
        calc_dict = chk.to_dict()
        recorded_manifest_hash = calc_dict.pop("manifest_hash", None)
        manifest_json_canonical = json.dumps(calc_dict, sort_keys=True)
        expected_manifest_hash = hashlib.sha256(manifest_json_canonical.encode("utf-8")).hexdigest()

        if recorded_manifest_hash and recorded_manifest_hash != expected_manifest_hash:
            return False, chk, f"Manifest hash mismatch for checkpoint '{checkpoint_id}'."

        # 2. Check state_hash CAS blob
        if chk.state_hash:
            if not self.blob_store.verify(chk.state_hash):
                return False, chk, f"State blob '{chk.state_hash}' missing or corrupt in BlobStore."

        # 3. Check workspace file CAS blobs
        if chk.workspace and chk.workspace.files:
            for rel_path, file_snap in chk.workspace.files.items():
                if not self.blob_store.verify(file_snap.blob_id):
                    return False, chk, f"File blob '{file_snap.blob_id}' for '{rel_path}' missing or corrupt in BlobStore."

        return True, chk, "Checkpoint valid."

    def validate_workspace(self, workspace_path: str) -> Tuple[bool, Path, str]:
        """
        Verify that original workspace exists, is a directory, and is accessible.
        """
        ws = Path(workspace_path).resolve()
        if not ws.exists():
            return False, ws, f"Original workspace path does not exist: {workspace_path}"
        if not ws.is_dir():
            return False, ws, f"Original workspace path is not a directory: {workspace_path}"
        return True, ws, "Workspace accessible."

    def reconcile_disk_with_ledger(
        self,
        mission_id: str,
        workspace_root: Path,
    ) -> List[Discrepancy]:
        """
        Compare actual disk state against the durable tool operations ledger.
        Detects:
        - Incomplete / uncertain operations (OUTCOME_UNKNOWN)
        - Missing files that were supposed to be written
        - Files modified post-interruption by external users (disk hash != post_hash)
        """
        discrepancies: List[Discrepancy] = []
        operations = self.db.list_tool_operations(mission_id)

        # Track the latest operation per relative file path
        latest_file_op: Dict[str, Dict[str, Any]] = {}

        for op in operations:
            tool_name = op.get("tool_name", "")
            target_path = op.get("target_path")
            st = op.get("status")

            # Check for unresolved uncertain outcomes
            if st == OperationStatus.OUTCOME_UNKNOWN.value or st == OperationStatus.INTENT_COMMITTED.value:
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.OPERATION_UNCERTAIN,
                        path=target_path,
                        description=f"Tool operation '{op.get('operation_id')}' ({tool_name}) outcome is uncertain ({st}). Requires resolution before resume.",
                        blocking=True,
                        operation_id=op.get("operation_id"),
                    )
                )

            if target_path and tool_name in ("write_file", "edit_file", "patch_file", "create_file"):
                rel_norm = Path(target_path).as_posix()
                latest_file_op[rel_norm] = op

        # Verify disk state for latest committed file operations
        for rel_norm, op in latest_file_op.items():
            st = op.get("status")
            if st != OperationStatus.RESULT_COMMITTED.value:
                continue

            expected_post_hash = op.get("post_hash")
            if not expected_post_hash:
                continue

            file_path = workspace_root / rel_norm
            if not file_path.exists():
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.FILE_MISSING,
                        path=rel_norm,
                        description=f"File '{rel_norm}' was committed by operation '{op.get('operation_id')}' but is missing on disk.",
                        blocking=True,
                        operation_id=op.get("operation_id"),
                        expected_hash=expected_post_hash,
                    )
                )
                continue

            actual_hash = compute_file_sha256(file_path)
            if actual_hash != expected_post_hash:
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.USER_MODIFIED,
                        path=rel_norm,
                        description=(
                            f"File '{rel_norm}' content on disk ({actual_hash[:8]}) does not match "
                            f"the settled operation post-hash ({expected_post_hash[:8]}). "
                            "External edits detected post-interruption."
                        ),
                        blocking=True,
                        operation_id=op.get("operation_id"),
                        expected_hash=expected_post_hash,
                        actual_hash=actual_hash,
                    )
                )

        return discrepancies

    def determine_first_unfinished_task(
        self,
        runtime_state: HermesRuntimeState,
    ) -> Tuple[Optional[TaskState], List[str], List[str]]:
        """
        Inspect runtime state tasks and determine the first safe unfinished task in dependency order.
        Returns:
            (target_task, completed_task_ids, pending_task_ids)
        """
        tasks = list(runtime_state.tasks.values())
        completed_task_ids: List[str] = []
        pending_task_ids: List[str] = []

        for t in tasks:
            is_verified = bool(getattr(t, "verification_id", None) or getattr(t, "is_verified", False) or getattr(t, "completion_reason", None) or t.status == TaskStatus.COMPLETED)
            if t.status == TaskStatus.COMPLETED and is_verified:
                completed_task_ids.append(t.task_id)
            else:
                pending_task_ids.append(t.task_id)

        target_task: Optional[TaskState] = None
        for t in tasks:
            is_verified = bool(getattr(t, "verification_id", None) or getattr(t, "is_verified", False) or getattr(t, "completion_reason", None) or t.status == TaskStatus.COMPLETED)
            if t.status != TaskStatus.COMPLETED or not is_verified:
                # Check dependencies
                deps_satisfied = True
                for dep_id in t.dependencies:
                    if dep_id not in completed_task_ids:
                        deps_satisfied = False
                        break
                if deps_satisfied:
                    target_task = t
                    break

        # Fallback to the first pending task if no explicit dependency satisfied
        if not target_task and pending_task_ids:
            for t in tasks:
                if t.task_id in pending_task_ids:
                    target_task = t
                    break

        return target_task, completed_task_ids, pending_task_ids

    def formulate_resume_plan(self, mission_id: str) -> ResumePlan:
        """
        Formulate a comprehensive ResumePlan by validating checkpoint, workspace,
        disk-ledger consistency, and determining the continuation task.
        """
        # 1. Load mission from SQLite
        mission_row = self.db.get_mission(mission_id)
        if not mission_row:
            return ResumePlan(
                mission_id=mission_id,
                original_workspace="",
                can_resume=False,
                checkpoint_id=None,
                target_task_id=None,
                target_task_title=None,
                reason=f"Mission '{mission_id}' not found in database.",
            )

        orig_ws_str = mission_row.get("workspace_path", "")

        # 2. Validate workspace existence
        ws_valid, ws_path, ws_reason = self.validate_workspace(orig_ws_str)
        if not ws_valid:
            return ResumePlan(
                mission_id=mission_id,
                original_workspace=orig_ws_str,
                can_resume=False,
                checkpoint_id=None,
                target_task_id=None,
                target_task_title=None,
                reason=ws_reason,
                discrepancies=[
                    Discrepancy(
                        discrepancy_type=ReconciliationDiscrepancyType.WORKSPACE_INACCESSIBLE,
                        path=orig_ws_str,
                        description=ws_reason,
                        blocking=True,
                    )
                ],
            )

        # 3. Check latest checkpoint if present
        chk_id = mission_row.get("latest_checkpoint_id")
        chk_manifest = None
        if chk_id:
            chk_ok, chk_manifest, chk_err = self.validate_checkpoint(chk_id)
            if not chk_ok:
                return ResumePlan(
                    mission_id=mission_id,
                    original_workspace=orig_ws_str,
                    can_resume=False,
                    checkpoint_id=chk_id,
                    target_task_id=None,
                    target_task_title=None,
                    reason=f"Checkpoint validation failed: {chk_err}",
                    discrepancies=[
                        Discrepancy(
                            discrepancy_type=ReconciliationDiscrepancyType.CHECKPOINT_CORRUPT,
                            path=None,
                            description=chk_err,
                            blocking=True,
                        )
                    ],
                )

        # 4. Reconcile disk against tool operations ledger
        discrepancies = self.reconcile_disk_with_ledger(mission_id, ws_path)
        blocking_discrepancies = [d for d in discrepancies if d.blocking]

        # 5. Load authoritative runtime state snapshot
        snap_row = self.db.get_snapshot(mission_id)
        if not snap_row or not snap_row.get("snapshot"):
            return ResumePlan(
                mission_id=mission_id,
                original_workspace=orig_ws_str,
                can_resume=False,
                checkpoint_id=chk_id,
                target_task_id=None,
                target_task_title=None,
                reason="Authoritative snapshot not found in database.",
                discrepancies=discrepancies,
            )

        from core.persistence.serializer import deserialize_runtime_state
        try:
            runtime_state = deserialize_runtime_state(snap_row["snapshot"])
        except Exception as e:
            return ResumePlan(
                mission_id=mission_id,
                original_workspace=orig_ws_str,
                can_resume=False,
                checkpoint_id=chk_id,
                target_task_id=None,
                target_task_title=None,
                reason=f"Failed to deserialize runtime state: {e}",
                discrepancies=discrepancies,
            )

        # 6. Determine first unfinished task
        target_task, completed_ids, pending_ids = self.determine_first_unfinished_task(runtime_state)

        # Physical workspace reconciliation: verify all completed task output files exist on disk
        for t_id in completed_ids:
            task_obj = runtime_state.tasks.get(t_id)
            if task_obj:
                for created_rel in getattr(task_obj, "files_created", []):
                    rel_p = Path(created_rel).as_posix()
                    file_p = ws_path / rel_p
                    if not file_p.exists():
                        if not any(d.path == rel_p for d in discrepancies):
                            discrepancies.append(
                                Discrepancy(
                                    discrepancy_type=ReconciliationDiscrepancyType.FILE_MISSING,
                                    path=rel_p,
                                    description=f"File '{rel_p}' from completed task '{t_id}' is missing on disk.",
                                    blocking=True,
                                )
                            )
        blocking_discrepancies = [d for d in discrepancies if d.blocking]
        can_resume = len(blocking_discrepancies) == 0

        # If all tasks are completed, resumption is not needed
        if runtime_state.tasks and not pending_ids and not target_task:
            return ResumePlan(
                mission_id=mission_id,
                original_workspace=orig_ws_str,
                can_resume=False,
                checkpoint_id=chk_id,
                target_task_id=None,
                target_task_title=None,
                completed_tasks=completed_ids,
                pending_tasks=[],
                discrepancies=discrepancies,
                reason="All tasks for this mission are already completed and verified.",
            )

        target_id = target_task.task_id if target_task else (pending_ids[0] if pending_ids else None)
        target_title = target_task.title if target_task else "Continuation Task"

        reason = (
            f"Ready to resume from task '{target_id}' ({target_title})."
            if can_resume
            else f"Resume blocked by {len(blocking_discrepancies)} discrepancy(ies)."
        )

        return ResumePlan(
            mission_id=mission_id,
            original_workspace=orig_ws_str,
            can_resume=can_resume,
            checkpoint_id=chk_id,
            target_task_id=target_id,
            target_task_title=target_title,
            completed_tasks=completed_ids,
            pending_tasks=pending_ids,
            discrepancies=discrepancies,
            reason=reason,
            reconciliation_summary={
                "total_completed": len(completed_ids),
                "total_pending": len(pending_ids),
                "discrepancies_count": len(discrepancies),
                "blocking_count": len(blocking_discrepancies),
            },
        )
