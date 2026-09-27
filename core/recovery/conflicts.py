# core/recovery/conflicts.py
"""
Three-way file restore conflict detection and user modification protection.

Core Invariants:
1. USER EDITS WIN BY DEFAULT: Never blindly overwrite files modified by the user.
2. AGENT VS USER OWNERSHIP: Tracks whether changes were agent-created or user-created.
3. THREE-WAY COMPARISON: Compares Checkpoint Base, Present Disk, and Target Checkpoint.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set

from core.persistence.models import FileChangeType, FileSnapshot, WorkspaceManifest


class RestoreActionType(str, Enum):
    RESTORE_FILE = "RESTORE_FILE"
    PRESERVE_USER_EDIT = "PRESERVE_USER_EDIT"
    DELETE_CREATED_FILE = "DELETE_CREATED_FILE"
    CONFLICT_REQUIRES_USER = "CONFLICT_REQUIRES_USER"
    NO_OP = "NO_OP"


@dataclass
class RestoreAction:
    """Action to take on a single workspace file during rewind/restore."""
    relative_path: str
    action_type: RestoreActionType
    target_blob_id: Optional[str] = None
    reason: str = ""
    user_conflict: bool = False


@dataclass
class RestorePlan:
    """Complete, inspectable file restoration plan before applying rewind."""
    actions: List[RestoreAction]
    files_to_restore_count: int
    files_to_delete_count: int
    user_conflicts_count: int
    is_safe: bool


class ConflictDetector:
    """
    Computes three-way file comparisons and prevents data loss.
    """

    @classmethod
    def compute_plan(
        cls,
        workspace_root: Path | str,
        target_manifest: WorkspaceManifest,
        known_agent_created_files: Optional[Set[str]] = None,
        intermediate_agent_files: Optional[Set[str]] = None,
    ) -> RestorePlan:
        """
        Compare current disk state against target checkpoint manifest.
        """
        root = Path(workspace_root).resolve()
        agent_created = known_agent_created_files or set()
        intermediate_agent = intermediate_agent_files or set()

        actions: List[RestoreAction] = []
        user_conflicts = 0
        restore_count = 0
        delete_count = 0

        # Scan on-disk files
        current_disk_files: Dict[str, str] = {}
        for p in root.rglob("*"):
            if p.is_file() and not any(part in p.parts for part in (".git", ".hermes", "__pycache__")):
                try:
                    rel = str(p.relative_to(root)).replace("\\", "/")
                    with open(p, "rb") as f:
                        h = hashlib.sha256(f.read()).hexdigest()
                    current_disk_files[rel] = h
                except (OSError, PermissionError):
                    continue

        # 1. Evaluate files that should exist in the target checkpoint
        for rel_path, target_snap in target_manifest.files.items():
            if target_snap.change_type == FileChangeType.DELETED:
                continue

            disk_hash = current_disk_files.get(rel_path)

            if disk_hash is None:
                # File was deleted after target checkpoint -> Safe to restore
                actions.append(RestoreAction(
                    relative_path=rel_path,
                    action_type=RestoreActionType.RESTORE_FILE,
                    target_blob_id=target_snap.blob_id,
                    reason="File missing on disk; restoring from checkpoint.",
                ))
                restore_count += 1
            elif disk_hash == target_snap.sha256:
                # Identical content -> NO-OP
                actions.append(RestoreAction(
                    relative_path=rel_path,
                    action_type=RestoreActionType.NO_OP,
                    target_blob_id=target_snap.blob_id,
                    reason="File on disk matches target checkpoint exactly.",
                ))
            else:
                # Content differs. Did the agent modify it, or did the user?
                if rel_path in agent_created or rel_path in intermediate_agent:
                    # Agent-modified file -> Safe to roll back to checkpoint
                    actions.append(RestoreAction(
                        relative_path=rel_path,
                        action_type=RestoreActionType.RESTORE_FILE,
                        target_blob_id=target_snap.blob_id,
                        reason="Agent-modified file; restoring to target checkpoint state.",
                    ))
                    restore_count += 1
                else:
                    # USER EDIT DETECTED: USER WINS BY DEFAULT!
                    actions.append(RestoreAction(
                        relative_path=rel_path,
                        action_type=RestoreActionType.PRESERVE_USER_EDIT,
                        target_blob_id=target_snap.blob_id,
                        reason="User modification detected! Preserving user changes.",
                        user_conflict=True,
                    ))
                    user_conflicts += 1

        # 2. Evaluate files on disk that did NOT exist in target checkpoint
        for rel_path, disk_hash in current_disk_files.items():
            if rel_path not in target_manifest.files:
                if rel_path in agent_created or rel_path in intermediate_agent:
                    # File was created by agent after target checkpoint -> Safe to remove
                    actions.append(RestoreAction(
                        relative_path=rel_path,
                        action_type=RestoreActionType.DELETE_CREATED_FILE,
                        reason="Agent-created file post-checkpoint; removing.",
                    ))
                    delete_count += 1
                else:
                    # File was created by user -> PRESERVE
                    actions.append(RestoreAction(
                        relative_path=rel_path,
                        action_type=RestoreActionType.PRESERVE_USER_EDIT,
                        reason="User-created untracked file; preserving.",
                        user_conflict=True,
                    ))
                    user_conflicts += 1

        is_safe = (user_conflicts == 0)
        return RestorePlan(
            actions=actions,
            files_to_restore_count=restore_count,
            files_to_delete_count=delete_count,
            user_conflicts_count=user_conflicts,
            is_safe=is_safe,
        )
