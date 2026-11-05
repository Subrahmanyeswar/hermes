# core/file_locks.py
"""
HERMES 2.x — File-Level Concurrency & Integrity Lock Manager (Phase 2)
Provides fine-grained per-file write locks ensuring independent tasks or
streaming chunks cannot corrupt shared files concurrently.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Dict, Optional
from loguru import logger


class FileLockManager:
    """
    Manages per-file write locks using canonicalized file paths.
    Safe across async coroutines and background threads.
    """

    def __init__(self) -> None:
        self._async_locks: Dict[str, asyncio.Lock] = {}
        self._sync_locks: Dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()

    def _canonical_key(self, path: Path | str) -> str:
        return str(Path(path).resolve()).lower()

    def get_async_lock(self, path: Path | str) -> asyncio.Lock:
        key = self._canonical_key(path)
        with self._meta_lock:
            if key not in self._async_locks:
                self._async_locks[key] = asyncio.Lock()
            return self._async_locks[key]

    def get_sync_lock(self, path: Path | str) -> threading.Lock:
        key = self._canonical_key(path)
        with self._meta_lock:
            if key not in self._sync_locks:
                self._sync_locks[key] = threading.Lock()
            return self._sync_locks[key]

    async def write_file_safe(self, path: Path | str, content: str, encoding: str = "utf-8") -> int:
        """Atomically write content to file under per-file lock protection."""
        p = Path(path)
        lock = self.get_async_lock(p)
        async with lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            # Write to temporary file first then atomic replace
            tmp_path = p.with_name(f".{p.name}.tmp_{threading.get_ident()}")
            tmp_path.write_text(content, encoding=encoding)
            tmp_path.replace(p)
            return len(content)


# Global singleton
file_lock_manager = FileLockManager()
