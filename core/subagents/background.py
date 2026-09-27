# core/subagents/background.py
"""
Background Job Execution & Async Process Management for HERMES 2.x.

Core Invariants:
1. True Asynchrony: Non-blocking background jobs for shell, servers, tests, and subagents.
2. File-Backed Streams: stdout and stderr are continuously streamed to disk files under .hermes/jobs/.
3. Controlled Lifecycle: CHILD_BOUND jobs terminate when the owning agent finishes; DETACHED jobs persist.
4. Clean Process Termination: Integrated with CancellationController to eliminate orphan processes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from core.runtime_state.models import (
    BackgroundJobRecord,
    JobKind,
    JobStatus,
    JobLifecycle,
)
from core.subagents.cancellation import CancellationController, CancellationToken

logger = logging.getLogger("hermes.subagents.background")


class BackgroundJobManager:
    """
    Manages background OS processes and asynchronous subagent tasks.
    """

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()
        self.jobs_dir = self.workspace_root / ".hermes" / "jobs"
        self._records: Dict[str, BackgroundJobRecord] = {}
        self._processes: Dict[str, subprocess.Popen] = {}
        self._async_tasks: Dict[str, asyncio.Task] = {}
        self._cancellation_tokens: Dict[str, CancellationToken] = {}
        self._lock = threading.Lock()

    def start_process_job(
        self,
        job_id: str,
        owner_agent_id: str,
        task_id: str,
        command: str | List[str],
        cwd: Optional[Path | str] = None,
        env: Optional[Dict[str, str]] = None,
        kind: JobKind = JobKind.SHELL,
        lifecycle: JobLifecycle = JobLifecycle.CHILD_BOUND,
        worktree_id: Optional[str] = None,
    ) -> BackgroundJobRecord:
        """
        Start a background OS process with stdout and stderr directed to disk logs.
        """
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        work_dir = Path(cwd).resolve() if cwd else self.workspace_root

        out_path = self.jobs_dir / f"{job_id}.out"
        err_path = self.jobs_dir / f"{job_id}.err"

        out_file = open(out_path, "w", encoding="utf-8", buffering=1)
        err_file = open(err_path, "w", encoding="utf-8", buffering=1)

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        cmd_str = command if isinstance(command, str) else " ".join(command)

        proc = subprocess.Popen(
            command,
            cwd=str(work_dir),
            env=env,
            stdout=out_file,
            stderr=err_file,
            shell=isinstance(command, str),
            creationflags=creationflags,
        )

        record = BackgroundJobRecord(
            job_id=job_id,
            owner_agent_id=owner_agent_id,
            task_id=task_id,
            kind=kind,
            status=JobStatus.RUNNING,
            started_at=time.time(),
            pid=proc.pid,
            process_group=proc.pid,
            worktree_id=worktree_id,
            command=cmd_str,
            cwd=str(work_dir),
            lifecycle=lifecycle,
        )

        with self._lock:
            self._records[job_id] = record
            self._processes[job_id] = proc
            token = CancellationToken()
            self._cancellation_tokens[job_id] = token

        return record

    def start_async_subagent_job(
        self,
        job_id: str,
        owner_agent_id: str,
        task_id: str,
        coro: Coroutine[Any, Any, Any],
        lifecycle: JobLifecycle = JobLifecycle.CHILD_BOUND,
        worktree_id: Optional[str] = None,
    ) -> BackgroundJobRecord:
        """
        Start an asynchronous subagent coroutine as a background job.
        """
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        record = BackgroundJobRecord(
            job_id=job_id,
            owner_agent_id=owner_agent_id,
            task_id=task_id,
            kind=JobKind.SUBAGENT,
            status=JobStatus.RUNNING,
            started_at=time.time(),
            worktree_id=worktree_id,
            lifecycle=lifecycle,
        )

        token = CancellationToken()
        task = asyncio.create_task(coro)

        def _on_done(t: asyncio.Task) -> None:
            now = time.time()
            record.completed_at = now
            if t.cancelled():
                record.status = JobStatus.CANCELLED
            elif t.exception():
                record.status = JobStatus.FAILED
                record.error = str(t.exception())
                record.exit_code = 1
            else:
                record.status = JobStatus.SUCCEEDED
                record.exit_code = 0

        task.add_done_callback(_on_done)

        with self._lock:
            self._records[job_id] = record
            self._async_tasks[job_id] = task
            self._cancellation_tokens[job_id] = token

        return record

    def get_job_record(self, job_id: str) -> Optional[BackgroundJobRecord]:
        """Retrieve and update current status of a background job."""
        with self._lock:
            record = self._records.get(job_id)
            if not record:
                return None

            # Check OS process status if running
            if record.pid and job_id in self._processes:
                proc = self._processes[job_id]
                poll_res = proc.poll()
                if poll_res is not None:
                    record.completed_at = time.time()
                    record.exit_code = poll_res
                    if poll_res == 0:
                        record.status = JobStatus.SUCCEEDED
                    else:
                        record.status = JobStatus.FAILED
                        record.error = f"Process exited with code {poll_res}"

            return record

    def get_job_output(self, job_id: str, offset: int = 0, limit: int = 50_000) -> str:
        """Read stdout and stderr log files for a background job."""
        out_path = self.jobs_dir / f"{job_id}.out"
        err_path = self.jobs_dir / f"{job_id}.err"

        content_parts = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    content_parts.append(f.read(limit))
            except Exception as e:
                content_parts.append(f"[Error reading stdout: {e}]")

        if err_path.exists():
            try:
                with open(err_path, "r", encoding="utf-8", errors="replace") as f:
                    err_txt = f.read(limit)
                    if err_txt:
                        content_parts.append("\n--- STDERR ---\n" + err_txt)
            except Exception as e:
                content_parts.append(f"[Error reading stderr: {e}]")

        return "\n".join(content_parts)

    async def await_job(self, job_id: str, timeout: Optional[float] = None) -> BackgroundJobRecord:
        """
        Wait for a background job to finish or timeout.
        """
        start = time.time()
        while True:
            rec = self.get_job_record(job_id)
            if not rec:
                raise ValueError(f"Unknown background job: {job_id}")

            if rec.status.is_terminal:
                return rec

            if timeout is not None and (time.time() - start) > timeout:
                self.cancel_job(job_id, reason="Timeout exceeded")
                rec.status = JobStatus.TIMED_OUT
                rec.completed_at = time.time()
                rec.error = f"Awaiting job timed out after {timeout}s"
                return rec

            await asyncio.sleep(0.1)

    def cancel_job(self, job_id: str, reason: str = "User cancelled") -> bool:
        """Cancel an async task or terminate an OS process tree."""
        with self._lock:
            rec = self._records.get(job_id)
            if not rec or rec.status.is_terminal:
                return True

            rec.status = JobStatus.CANCEL_REQUESTED

            # 1. Trigger cooperative cancellation token
            token = self._cancellation_tokens.get(job_id)
            if token:
                token.cancel(reason)

            # 2. Cancel async task
            task = self._async_tasks.get(job_id)
            if task and not task.done():
                task.cancel()

            # 3. Kill OS process tree
            proc = self._processes.get(job_id)
            if proc and proc.poll() is None:
                CancellationController.kill_process_tree(proc.pid)

            rec.status = JobStatus.CANCELLED
            rec.completed_at = time.time()
            return True

    def cleanup_child_bound_jobs(self, owner_agent_id: str) -> List[str]:
        """Terminate all CHILD_BOUND jobs owned by the specified agent."""
        terminated: List[str] = []
        with self._lock:
            for job_id, rec in list(self._records.items()):
                if rec.owner_agent_id == owner_agent_id and rec.lifecycle == JobLifecycle.CHILD_BOUND:
                    if not rec.status.is_terminal:
                        self.cancel_job(job_id, reason=f"Owning agent {owner_agent_id} completed")
                        terminated.append(job_id)
        return terminated
