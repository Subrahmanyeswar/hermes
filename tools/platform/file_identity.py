# tools/platform/file_identity.py
"""
File Identity and Freshness Model for HERMES 2.x Tool Platform.
Tracks file metadata, newline style, encoding, and content hashes to ensure
surgical edit freshness, detect external race conditions, and prevent stale overwrites.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass
class FileIdentity:
    """Lightweight immutable identity record for a workspace file."""
    path: str
    absolute_path: str
    size: int
    mtime_ns: int
    content_hash: str
    encoding: str = "utf-8"
    newline_style: str = "\n"  # "\n" (LF) or "\r\n" (CRLF)
    detected_at: float = field(default_factory=time.time)

    def is_stale(self, current_file: Path) -> bool:
        """Check whether the target file on disk differs from this identity snapshot."""
        if not current_file.exists():
            return True
        stat = current_file.stat()
        if stat.st_size != self.size or stat.st_mtime_ns != self.mtime_ns:
            return True
        return False


class FileIdentityCache:
    """
    Thread-safe workspace file identity tracker.
    Records file identity upon read and verifies freshness prior to surgical edits.
    """

    def __init__(self, max_entries: int = 2000) -> None:
        self._cache: Dict[str, FileIdentity] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def _normalize_key(self, path: Path | str) -> str:
        p = Path(path).resolve()
        return str(p).lower() if os.name == "nt" else str(p)

    def record(
        self,
        file_path: Path,
        content: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> FileIdentity:
        """Inspect and record the current identity of a file."""
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"Cannot record identity for missing file: {file_path}")

        stat = file_path.stat()
        raw_bytes = file_path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Detect newline style
        newline_style = "\r\n" if b"\r\n" in raw_bytes else "\n"

        identity = FileIdentity(
            path=str(file_path),
            absolute_path=str(file_path.resolve()),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            content_hash=content_hash,
            encoding=encoding,
            newline_style=newline_style,
        )

        key = self._normalize_key(file_path)
        with self._lock:
            if len(self._cache) >= self._max_entries:
                # Evict oldest entry
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[key] = identity

        return identity

    def get(self, file_path: Path | str) -> Optional[FileIdentity]:
        """Retrieve the recorded identity for a path."""
        key = self._normalize_key(file_path)
        with self._lock:
            return self._cache.get(key)

    def check_freshness(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Verify if current file on disk matches recorded identity.
        Returns: (is_fresh, failure_reason)
        """
        key = self._normalize_key(file_path)
        with self._lock:
            recorded = self._cache.get(key)

        if not recorded:
            # No prior read recorded; considered fresh
            return True, None

        if not file_path.exists():
            return False, f"File '{file_path}' was deleted after being read."

        current_stat = file_path.stat()
        if current_stat.st_size != recorded.size or current_stat.st_mtime_ns != recorded.mtime_ns:
            # Double check content hash in case mtime touched without content change
            current_bytes = file_path.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            if current_hash != recorded.content_hash:
                return (
                    False,
                    f"File '{file_path.name}' was modified externally since it was last inspected "
                    f"(size: {recorded.size} -> {current_stat.st_size} bytes, "
                    f"hash: {recorded.content_hash[:8]} -> {current_hash[:8]})."
                )

        return True, None

    def invalidate(self, file_path: Path | str) -> None:
        """Invalidate cached identity after write or external deletion."""
        key = self._normalize_key(file_path)
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()


# Global canonical identity tracker singleton
file_identity_cache = FileIdentityCache()
