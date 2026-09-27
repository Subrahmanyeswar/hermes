# core/subagents/cancellation.py
"""
Cooperative & Forced Cancellation Controller for HERMES 2.x.

Core Invariants:
1. Cooperative First: Tasks check cancellation tokens at each turn and tool execution boundary.
2. Graceful-to-Forced Hierarchy: Sends graceful signal (SIGTERM/terminate), waits bounded grace period, then force kills.
3. Windows Process Tree Cleanup: Uses psutil (with taskkill fallback) to ensure zero orphaned child processes.
4. Idempotent: Cancellation calls are safe to invoke multiple times concurrently or sequentially.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger("hermes.subagents.cancellation")


class SubagentCancelledException(Exception):
    """Raised when an agent or task execution is cancelled."""
    def __init__(self, reason: str = "Operation cancelled"):
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    """
    Thread-safe cooperative cancellation token.
    """

    def __init__(self):
        self._is_cancelled = False
        self._reason: Optional[str] = None
        self._callbacks: List[Callable[[str], None]] = []
        self._lock = threading.Lock()

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._is_cancelled

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason or "Cancelled"

    def cancel(self, reason: str = "Operation cancelled") -> None:
        """Trigger cancellation and invoke any registered callbacks."""
        callbacks_to_run = []
        with self._lock:
            if self._is_cancelled:
                return
            self._is_cancelled = True
            self._reason = reason
            callbacks_to_run = list(self._callbacks)

        for cb in callbacks_to_run:
            try:
                cb(reason)
            except Exception as e:
                logger.warning(f"Error in cancellation callback: {e}")

    def register(self, callback: Callable[[str], None]) -> None:
        """Register a callback to be invoked immediately if cancelled, or when cancelled."""
        already_cancelled = False
        reason = ""
        with self._lock:
            if self._is_cancelled:
                already_cancelled = True
                reason = self._reason or "Cancelled"
            else:
                self._callbacks.append(callback)

        if already_cancelled:
            try:
                callback(reason)
            except Exception as e:
                logger.warning(f"Error in immediate cancellation callback: {e}")

    def raise_if_cancelled(self) -> None:
        """Check if cancelled and raise SubagentCancelledException if so."""
        if self.is_cancelled:
            raise SubagentCancelledException(self.reason)


class CancellationController:
    """
    Manages process tree lifecycle and termination across operating systems.
    """

    @classmethod
    def kill_process_tree(cls, pid: int, grace_period_seconds: float = 2.0) -> bool:
        """
        Terminate an OS process and all of its descendants.
        Uses psutil if available; falls back to OS-specific primitives.
        """
        if pid <= 0:
            return False

        # Attempt with psutil first
        try:
            import psutil
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                procs = children + [parent]

                # 1. Graceful termination
                for p in procs:
                    try:
                        p.terminate()
                    except psutil.NoSuchProcess:
                        pass

                # 2. Wait bounded grace period
                _, still_alive = psutil.wait_procs(procs, timeout=grace_period_seconds)

                # 3. Force kill any remaining alive processes
                for p in still_alive:
                    try:
                        p.kill()
                    except psutil.NoSuchProcess:
                        pass

                return True
            except psutil.NoSuchProcess:
                return True
        except ImportError:
            pass

        # Fallback for Windows
        if sys.platform == "win32":
            try:
                # /T kills the process tree; /F forces termination
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    check=False,
                )
                return True
            except Exception as e:
                logger.warning(f"Windows taskkill failed for pid {pid}: {e}")
                return False
        else:
            # Fallback for Unix/Linux/macOS
            try:
                os.kill(pid, 15)  # SIGTERM
                time.sleep(grace_period_seconds)
                os.kill(pid, 9)   # SIGKILL
                return True
            except (ProcessLookupError, PermissionError):
                return True
            except Exception as e:
                logger.warning(f"Unix kill failed for pid {pid}: {e}")
                return False
