# core/checkpoints/file_snapshot.py
"""
Workspace file state snapshotting and containment validation for HERMES 2.x.

Core Invariants:
1. PATH CONTAINMENT: Refuses to follow symlinks or junctions escaping workspace_root.
2. CAS DEDUPLICATION: Content is stored in CAS BlobStore; identical files share blobs.
3. COMPREHENSIVE TRACKING: Tracks tracked, untracked, modified, and deleted files.
4. EXCLUSION RULES: Ignores internal VCS (.git), cache, and persistence dirs (.hermes).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from core.persistence.blobs import BlobStore
from core.persistence.models import FileChangeType, FileSnapshot, WorkspaceManifest


DEFAULT_IGNORED_DIRS: Set[str] = {
    ".git",
    ".hermes",
    ".pytest_cache",
    ".mypy_cache",
    "__pycache__",
    "venv",
    ".venv",
    "node_modules",
}

DEFAULT_IGNORED_FILES: Set[str] = {
    ".DS_Store",
    "thumbs.db",
}


class WorkspaceSnapshotter:
    """
    Captures exact filesystem snapshots of workspace files.
    Ensures safe boundary containment and stores files in the content-addressed BlobStore.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        blob_store: BlobStore,
        ignored_dirs: Optional[Set[str]] = None,
        ignored_files: Optional[Set[str]] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.blob_store = blob_store
        self.ignored_dirs = ignored_dirs or DEFAULT_IGNORED_DIRS
        self.ignored_files = ignored_files or DEFAULT_IGNORED_FILES

    def _is_safe_path(self, path: Path | str) -> bool:
        """
        Verify candidate path is strictly contained within workspace_root.
        Enforces component-aware canonical containment, resolves symlinks, junctions,
        and reparse points, handles case-insensitivity on Windows, and fails closed.
        """
        try:
            p = Path(path)
            if not p.is_absolute():
                p = self.workspace_root / p
            resolved = p.resolve()
            return resolved.is_relative_to(self.workspace_root)
        except Exception:
            return False

    def create_snapshot(
        self,
        known_agent_created_files: Optional[Set[str]] = None,
        prior_manifest: Optional[WorkspaceManifest] = None,
    ) -> WorkspaceManifest:
        """
        Scan workspace files, store contents in CAS, and generate a WorkspaceManifest.
        """
        agent_created = known_agent_created_files or set()
        file_snapshots: Dict[str, FileSnapshot] = {}
        total_bytes = 0

        if self.workspace_root.exists():
            ws_root_str = str(self.workspace_root)
            for root, dirs, files in os.walk(self.workspace_root, topdown=True, followlinks=False):
                # Filter out ignored directories, symlinks, and Windows directory junctions in-place
                dirs[:] = [
                    d for d in dirs
                    if d not in self.ignored_dirs
                    and not (Path(root) / d).is_symlink()
                    and not getattr(Path(root) / d, "is_junction", lambda: False)()
                ]

                for file_name in files:
                    if file_name in self.ignored_files or file_name.endswith(".tmp"):
                        continue

                    full_path = Path(root) / file_name

                    # Security containment check
                    if not self._is_safe_path(full_path):
                        continue

                    try:
                        stat = full_path.stat()
                        size = stat.st_size
                        mtime_ns = stat.st_mtime_ns
                        rel_path = os.path.relpath(os.path.join(root, file_name), ws_root_str).replace("\\", "/")

                        # Stream file into BlobStore (computes authoritative sha256 and dedups)
                        blob_id = self.blob_store.put_file(full_path)

                        # Concurrency check: verify file wasn't modified while reading
                        stat_after = full_path.stat()
                        if stat_after.st_mtime_ns != mtime_ns or stat_after.st_size != size:
                            blob_id = self.blob_store.put_file(full_path)
                            size = stat_after.st_size
                            mtime_ns = stat_after.st_mtime_ns

                        change_type = FileChangeType.TRACKED
                        if prior_manifest:
                            if rel_path not in prior_manifest.files:
                                change_type = FileChangeType.ADDED
                            elif prior_manifest.files[rel_path].sha256 != blob_id:
                                change_type = FileChangeType.MODIFIED

                        file_snapshots[rel_path] = FileSnapshot(
                            relative_path=rel_path,
                            sha256=blob_id,
                            size_bytes=size,
                            mtime_ns=mtime_ns,
                            blob_id=blob_id,
                            change_type=change_type,
                            is_agent_created=(rel_path in agent_created),
                        )
                        total_bytes += size
                    except (OSError, PermissionError):
                        continue

        # Check for deleted files relative to prior manifest
        if prior_manifest:
            for old_path, old_snap in prior_manifest.files.items():
                if old_path not in file_snapshots and not old_snap.change_type == FileChangeType.DELETED:
                    file_snapshots[old_path] = FileSnapshot(
                        relative_path=old_path,
                        sha256=old_snap.sha256,
                        size_bytes=0,
                        mtime_ns=0,
                        blob_id=old_snap.blob_id,
                        change_type=FileChangeType.DELETED,
                        is_agent_created=old_snap.is_agent_created,
                    )

        # Compute deterministic manifest hash
        hasher = hashlib.sha256()
        for rel_path in sorted(file_snapshots.keys()):
            snap = file_snapshots[rel_path]
            hasher.update(f"{rel_path}:{snap.sha256}:{snap.change_type.value}:{snap.size_bytes}".encode("utf-8"))
        manifest_hash = hasher.hexdigest()

        return WorkspaceManifest(
            workspace_root=str(self.workspace_root),
            files=file_snapshots,
            total_files=len([f for f in file_snapshots.values() if f.change_type != FileChangeType.DELETED]),
            total_bytes=total_bytes,
            manifest_hash=manifest_hash,
        )
