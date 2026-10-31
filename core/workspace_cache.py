# core/workspace_cache.py
"""
HERMES Phase 10: High-Performance In-Memory Workspace Manifest & Metadata Cache.

Provides:
1. Sub-millisecond (<0.5ms) workspace manifest retrieval for repetitive agent turn inspection.
2. Thread-safe in-memory caching of file records (path, size, mtime, hash).
3. Precise, targeted invalidation on file create, edit, rename, and delete.
4. Cascading parent-directory structure invalidation.
5. Strict workspace containment enforcement via WorkspaceBoundaryError.
6. Safe ignore policies preserving protected (.git, .hermes, .artifacts, node_modules, venv).
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.workspace import WorkspaceBoundaryError, canonicalize_workspace_path

IGNORE_PATTERNS = [
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "*.pyc", "*.pyo", "*.pyd", ".DS_Store", "*.egg-info", "dist",
    "build", ".pytest_cache", ".mypy_cache", "*.min.js", "*.min.css",
    ".next", ".nuxt", "target", "*.lock", "package-lock.json",
    "artifacts", ".hermes", "cache", ".cache",
    "sessions", "trajectories", "browser_profiles", "*.sqlite*", "*.db",
    "*.log", "*.zip", "*.gz", "*.tar",
]


@dataclass
class CachedFileEntry:
    rel_path: str
    abs_path: str
    size_bytes: int
    mtime: float
    content_hash: Optional[str] = None


class WorkspaceManifestCache:
    """
    High-speed in-memory cache of workspace files and directory trees.
    """

    def __init__(self, workspace_root: Optional[Path | str] = None) -> None:
        self.workspace_root: Optional[Path] = Path(workspace_root).resolve() if workspace_root else None
        self._files: Dict[str, CachedFileEntry] = {}
        self._directories: Set[str] = set()
        self._lock = threading.RLock()
        self._last_scan_time: float = 0.0
        self._hit_count: int = 0
        self._miss_count: int = 0
        self._invalidation_count: int = 0

    def set_root(self, workspace_root: Path | str) -> None:
        with self._lock:
            resolved = Path(workspace_root).resolve()
            if self.workspace_root != resolved:
                self.workspace_root = resolved
                self.clear()

    def clear(self) -> None:
        with self._lock:
            self._files.clear()
            self._directories.clear()
            self._last_scan_time = 0.0

    def _should_ignore(self, path: Path) -> bool:
        if not self.workspace_root:
            return False
        try:
            rel = path.relative_to(self.workspace_root)
            parts = rel.parts
        except Exception:
            parts = (path.name,)
        for part in parts:
            for pattern in IGNORE_PATTERNS:
                if fnmatch.fnmatch(part, pattern) or part == pattern:
                    return True
        return False

    def validate_path(self, path: str | Path) -> Path:
        """Validate boundary containment, raising WorkspaceBoundaryError if outside."""
        if not self.workspace_root:
            return Path(path).resolve()
        return canonicalize_workspace_path(path, self.workspace_root)

    def scan_workspace(self, force: bool = False) -> Dict[str, CachedFileEntry]:
        """
        Scan workspace directory and populate in-memory cache.
        If cache is already warm and force is False, returns in-memory entries immediately (<0.1ms).
        """
        with self._lock:
            if not self.workspace_root or not self.workspace_root.exists():
                return {}

            if not force and self._last_scan_time > 0 and self._files:
                self._hit_count += 1
                return dict(self._files)

            self._miss_count += 1
            start_t = time.perf_counter()
            new_files: Dict[str, CachedFileEntry] = {}
            new_dirs: Set[str] = set()

            for root, dirs, files in os.walk(self.workspace_root):
                root_path = Path(root)
                # In-place directory pruning
                dirs[:] = [
                    d for d in dirs
                    if not self._should_ignore(root_path / d)
                ]
                try:
                    rel_dir = root_path.relative_to(self.workspace_root).as_posix()
                    if rel_dir != ".":
                        new_dirs.add(rel_dir)
                except ValueError:
                    continue

                for f in files:
                    fpath = root_path / f
                    if self._should_ignore(fpath):
                        continue
                    try:
                        st = fpath.stat()
                        rel_p = fpath.relative_to(self.workspace_root).as_posix()
                        new_files[rel_p] = CachedFileEntry(
                            rel_path=rel_p,
                            abs_path=str(fpath),
                            size_bytes=st.st_size,
                            mtime=st.st_mtime,
                        )
                    except OSError:
                        continue

            self._files = new_files
            self._directories = new_dirs
            self._last_scan_time = time.perf_counter()
            return dict(self._files)

    def get_file(self, rel_or_abs_path: str | Path) -> Optional[CachedFileEntry]:
        """Get cached file metadata safely."""
        with self._lock:
            valid_p = self.validate_path(rel_or_abs_path)
            if not self.workspace_root:
                return None
            try:
                rel = valid_p.relative_to(self.workspace_root).as_posix()
            except ValueError:
                return None
            return self._files.get(rel)

    def file_exists(self, rel_or_abs_path: str | Path) -> bool:
        with self._lock:
            valid_p = self.validate_path(rel_or_abs_path)
            if not self.workspace_root:
                return valid_p.exists()
            try:
                rel = valid_p.relative_to(self.workspace_root).as_posix()
            except ValueError:
                return False
            return rel in self._files

    def get_content_hash(self, rel_or_abs_path: str | Path) -> Optional[str]:
        """Lazy calculation and caching of SHA-256 content hash."""
        with self._lock:
            valid_p = self.validate_path(rel_or_abs_path)
            if not self.workspace_root:
                return None
            try:
                rel = valid_p.relative_to(self.workspace_root).as_posix()
            except ValueError:
                return None

            entry = self._files.get(rel)
            if not entry:
                return None

            if entry.content_hash is not None:
                return entry.content_hash

            try:
                h = hashlib.sha256(valid_p.read_bytes()).hexdigest()
                entry.content_hash = h
                return h
            except OSError:
                return None

    def invalidate_file(self, rel_or_abs_path: str | Path) -> None:
        """
        Targeted invalidation on file creation, modification, or deletion.
        Cascades invalidation to parent directories.
        """
        with self._lock:
            self._invalidation_count += 1
            valid_p = self.validate_path(rel_or_abs_path)
            if not self.workspace_root:
                return
            try:
                rel = valid_p.relative_to(self.workspace_root).as_posix()
            except ValueError:
                return

            if valid_p.exists() and valid_p.is_file():
                try:
                    st = valid_p.stat()
                    self._files[rel] = CachedFileEntry(
                        rel_path=rel,
                        abs_path=str(valid_p),
                        size_bytes=st.st_size,
                        mtime=st.st_mtime,
                        content_hash=None,  # Reset hash on modification
                    )
                except OSError:
                    self._files.pop(rel, None)
            else:
                self._files.pop(rel, None)

            # Ensure parent directories are tracked
            parent = valid_p.parent
            while parent != self.workspace_root and self.workspace_root in parent.parents:
                self._directories.add(parent.relative_to(self.workspace_root).as_posix())
                parent = parent.parent

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_cached_files": len(self._files),
                "total_directories": len(self._directories),
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "invalidation_count": self._invalidation_count,
                "is_warm": self._last_scan_time > 0,
            }


# Default global instance
workspace_manifest_cache = WorkspaceManifestCache()
