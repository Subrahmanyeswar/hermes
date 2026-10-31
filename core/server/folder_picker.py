# core/server/folder_picker.py
"""
Native Windows Folder Picker Service for HERMES.
Launches the genuine native Windows directory picker on the interactive desktop (WinSta0\\Default).
Provides strict singleton management, accurate active-process tracking, non-blocking async execution,
and guaranteed cleanup without stale locks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("hermes.server.folder_picker")


class FolderPickerManager:
    """Manages the lifecycle of native OS directory picker dialogs."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._active_proc: Optional[asyncio.subprocess.Process] = None
        self._request_counter: int = 0

    def is_dialog_active(self) -> bool:
        """Check whether a native folder picker is genuinely running."""
        if self._active_proc is not None:
            if self._active_proc.returncode is not None:
                self._active_proc = None
                return False
            # Verify liveness via psutil if pid is available
            pid = getattr(self._active_proc, "pid", None)
            if pid is not None:
                try:
                    import psutil
                    if not psutil.pid_exists(pid):
                        self._active_proc = None
                        return False
                    p = psutil.Process(pid)
                    if p.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                        self._active_proc = None
                        return False
                except Exception:
                    pass
            return True
        return False

    async def pick_directory(
        self,
        initial_dir: Optional[str] = None,
        title: str = "Select Project Directory for HERMES",
        timeout_seconds: float = 600.0,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Open the native folder picker and await the user's selection or cancellation.

        Returns:
            (cancelled: bool, selected_path: Optional[str], error_message: Optional[str])
        """
        async with self._lock:
            # If an existing dialog is still hanging or lost in background, terminate it
            if self.is_dialog_active():
                logger.info("Folder picker already active; terminating previous dialog to satisfy user request.")
                try:
                    if self._active_proc:
                        self._active_proc.terminate()
                        try:
                            await asyncio.wait_for(self._active_proc.wait(), timeout=1.0)
                        except Exception:
                            self._active_proc.kill()
                except Exception:
                    pass
                self._active_proc = None

            self._request_counter += 1
            req_id = self._request_counter
            logger.info(f"Launching native folder picker (req_id={req_id}, initial_dir={initial_dir})")

            # Resolve python executable and runner arguments
            python_exe = sys.executable
            runner_script = Path(__file__).resolve()

            init_dir_arg = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else ""

            try:
                proc = await asyncio.create_subprocess_exec(
                    python_exe,
                    str(runner_script),
                    "--run-dialog",
                    init_dir_arg,
                    title,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._active_proc = proc

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Folder picker (req_id={req_id}) timed out after {timeout_seconds}s; terminating process.")
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                    return True, None, "Folder picker timed out."

                stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
                stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

                if stderr_text:
                    logger.debug(f"Folder picker runner stderr: {stderr_text}")

                if not stdout_text:
                    logger.warning(f"Folder picker exited with code {proc.returncode} but produced no output.")
                    return True, None, None

                # Find the JSON output line
                payload = None
                for line in stdout_text.splitlines():
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            payload = json.loads(line)
                            break
                        except Exception:
                            continue

                if not payload:
                    logger.warning(f"Failed to parse folder picker output: {stdout_text}")
                    return True, None, "Invalid response from folder picker."

                if payload.get("error"):
                    return True, None, payload["error"]

                if payload.get("cancelled", False):
                    return True, None, None

                selected = payload.get("path")
                if selected and os.path.isdir(selected):
                    return False, os.path.abspath(selected), None

                return True, None, None

            except Exception as exc:
                logger.error(f"Error launching folder picker process: {exc}")
                return True, None, f"Failed to open folder picker: {exc}"
            finally:
                if self._active_proc is not None:
                    if self._active_proc.returncode is None:
                        try:
                            self._active_proc.terminate()
                        except Exception:
                            pass
                    self._active_proc = None


# Singleton folder picker instance
folder_picker_manager = FolderPickerManager()


# ─────────────────────────────────────────────────────────────────────────────
# Subprocess Runner (Executed when called with --run-dialog)
# ─────────────────────────────────────────────────────────────────────────────
def _run_dialog_subprocess():
    """Child process entrypoint: runs Tkinter dialog on WinSta0\\Default."""
    initial_dir = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    title = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else "Select Project Directory for HERMES"

    # Switch thread desktop to Default interactive desktop if on Windows
    import ctypes
    user32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "user32", None)
    if user32:
        try:
            h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)
            user32.AllowSetForegroundWindow(ctypes.c_uint(-1))
        except Exception:
            pass

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.title(title)
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    root.update()

    try:
        init_path = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else os.path.expanduser("~")
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=init_path,
            title=title,
        )
        if selected and os.path.isdir(selected):
            print(json.dumps({"cancelled": False, "path": os.path.abspath(selected)}), flush=True)
        else:
            print(json.dumps({"cancelled": True, "path": None}), flush=True)
    except Exception as exc:
        err_msg = str(exc)
        # Handle user cancellation / window close gracefully
        if "cancel" in err_msg.lower() or "unspecified" in err_msg.lower():
            print(json.dumps({"cancelled": True, "path": None}), flush=True)
        else:
            print(json.dumps({"cancelled": True, "error": err_msg}), flush=True)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    if "--run-dialog" in sys.argv:
        _run_dialog_subprocess()
