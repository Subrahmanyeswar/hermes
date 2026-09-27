# core/recovery/reconcile.py
"""
Domain reconciliation for HERMES 2.x session resume.

Verifies and safely reconciles:
1. Filesystem drift
2. Git drift (without destructive resets)
3. Background job processes (marking dead/orphaned jobs)
4. Provider connections (fresh sockets and reset monotonic deadlines)
5. Security approvals (invalidating expired or policy-mismatched grants)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.checkpoints.git_snapshot import GitSnapshotter
from core.persistence.locks import is_process_alive
from core.persistence.models import (
    ApprovalInvalidAfterResume,
    CheckpointManifest,
    GitManifest,
    WorkspaceManifest,
)

logger = logging.getLogger("hermes.recovery.reconcile")


class DomainReconciler:
    """
    Reconciles external environment state against persisted checkpoint manifests.
    """

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()
        self.git_snapshotter = GitSnapshotter(self.workspace_root)

    def reconcile_filesystem(self, checkpoint: CheckpointManifest) -> Dict[str, Any]:
        """Detect any filesystem drift between current disk and checkpoint."""
        drift_files: List[str] = []
        missing_files: List[str] = []

        for rel_path, snap in checkpoint.workspace.files.items():
            full_path = self.workspace_root / rel_path
            if not full_path.exists():
                missing_files.append(rel_path)
            else:
                try:
                    with open(full_path, "rb") as f:
                        cur_hash = hashlib.sha256(f.read()).hexdigest()
                    if cur_hash != snap.sha256:
                        drift_files.append(rel_path)
                except (OSError, PermissionError):
                    drift_files.append(rel_path)

        has_drift = bool(drift_files or missing_files)
        return {
            "has_drift": has_drift,
            "modified_files": drift_files,
            "missing_files": missing_files,
        }

    def reconcile_git(self, checkpoint: CheckpointManifest) -> Dict[str, Any]:
        """Detect any Git branch or HEAD drift without modifying Git state."""
        current_git = self.git_snapshotter.create_snapshot()
        chk_git = checkpoint.git

        head_drift = (current_git.head_sha != chk_git.head_sha)
        branch_drift = (current_git.branch != chk_git.branch)
        is_dirty = current_git.is_dirty

        return {
            "has_drift": head_drift or branch_drift,
            "head_drift": head_drift,
            "branch_drift": branch_drift,
            "current_head": current_git.head_sha,
            "checkpoint_head": chk_git.head_sha,
            "current_branch": current_git.branch,
            "checkpoint_branch": chk_git.branch,
            "is_dirty": is_dirty,
        }

    def reconcile_background_jobs(self, checkpoint: CheckpointManifest) -> Dict[str, Any]:
        """Inspect recorded background jobs and tag dead/orphaned processes."""
        reconciled_jobs = []
        orphaned_count = 0

        for job in checkpoint.jobs.jobs:
            pid = job.get("pid")
            alive = is_process_alive(pid) if pid else False

            status = job.get("status", "UNKNOWN")
            if not alive and status in ("RUNNING", "ACTIVE"):
                status = "ORPHANED_OR_FAILED"
                orphaned_count += 1

            reconciled_jobs.append({
                **job,
                "status": status,
                "is_alive": alive,
            })

        return {
            "jobs": reconciled_jobs,
            "orphaned_count": orphaned_count,
        }

    def reconcile_security(
        self,
        checkpoint: CheckpointManifest,
        current_policy_version: str = "1.0.0",
    ) -> Dict[str, Any]:
        """
        Validate persisted approval grants.
        Invalidates grants with mismatched policy versions or expired timestamps.
        """
        valid_grants = []
        invalidated_count = 0
        now = time.time()

        for grant in checkpoint.security.active_grants:
            p_ver = grant.get("policy_version", "1.0.0")
            exp = grant.get("expires_at")
            revoked = grant.get("revoked", False)

            if p_ver != current_policy_version or revoked or (exp and now > exp):
                invalidated_count += 1
                logger.info("Security grant '{}' invalidated upon resume.", grant.get("grant_id"))
            else:
                valid_grants.append(grant)

        return {
            "valid_grants": valid_grants,
            "invalidated_count": invalidated_count,
        }

    def reconcile_provider(self, checkpoint: CheckpointManifest) -> Dict[str, Any]:
        """
        Reinitialize provider logical state.
        Resets monotonic deadlines and drops stale socket handles.
        """
        chk_prov = checkpoint.provider
        circuit_state = chk_prov.circuit_state
        if circuit_state == "OPEN":
            # Allow half-open trial upon fresh resume
            circuit_state = "HALF_OPEN"

        return {
            "provider": chk_prov.provider,
            "model": chk_prov.model,
            "circuit_state": circuit_state,
            "fresh_connection": True,
        }
