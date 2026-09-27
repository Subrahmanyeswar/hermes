# core/persistence/locks.py
"""
Process and session mutual exclusion locks for HERMES 2.x persistence.

Guarantees:
1. EXCLUSIVE WRITER: Exactly one active runtime engine may mutate a session.
2. STALE LOCK DETECTION: Automatically detects dead process owners via OS process queries and heartbeats.
3. CROSS-PLATFORM: Resilient on Windows, Linux, and macOS.
"""

from __future__ import annotations

import os
import platform
import socket
import time
from typing import Optional

from core.persistence.database import SQLiteDatabase


def is_process_alive(pid: int) -> bool:
    """Check if process with given PID is currently running."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    system = platform.system()
    if system == "Windows":
        try:
            import ctypes
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000, SYNCHRONIZE = 0x00100000
            SYNCHRONIZE = 0x00100000
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
            )
            if handle == 0:
                return False
            # Check exit code
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            # STILL_ACTIVE = 259
            return exit_code.value == 259
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


class SessionLock:
    """
    Acquires and maintains exclusive write ownership over a specific session_id.
    """

    def __init__(
        self,
        db: SQLiteDatabase,
        session_id: str,
        heartbeat_timeout_seconds: float = 30.0,
    ):
        self.db = db
        self.session_id = session_id
        self.timeout = heartbeat_timeout_seconds
        self.host = socket.gethostname()
        self.pid = os.getpid()
        self.is_held = False

    def acquire(self) -> bool:
        """
        Attempt to acquire session lock.
        Breaks lock safely if owner process is dead or heartbeat has timed out.
        """
        now = time.time()
        existing = self.db.get_lock(self.session_id)

        if existing:
            owner_pid = existing["pid"]
            owner_host = existing["host"]
            last_hb = existing["heartbeat_at"]

            # If it's already our process, renew
            if owner_pid == self.pid and owner_host == self.host:
                self.db.update_heartbeat(self.session_id, now)
                self.is_held = True
                return True

            # Check if stale
            is_same_host = (owner_host == self.host)
            alive = is_process_alive(owner_pid) if is_same_host else True
            stale_timeout = (now - last_hb) > self.timeout

            if not alive or stale_timeout:
                # Safe to steal/break stale lock
                self.db.release_lock(self.session_id)
            else:
                return False

        # Attempt atomic insert
        acquired = self.db.acquire_lock(self.session_id, self.pid, self.host, now)
        if acquired:
            self.is_held = True
        return acquired

    def heartbeat(self) -> None:
        """Update heartbeat timestamp for the currently held lock."""
        if self.is_held:
            self.db.update_heartbeat(self.session_id, time.time())

    def release(self) -> None:
        """Release session lock cleanly."""
        if self.is_held:
            existing = self.db.get_lock(self.session_id)
            if existing and existing["pid"] == self.pid:
                self.db.release_lock(self.session_id)
            self.is_held = False
