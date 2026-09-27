# core/subagents/reconciler.py
"""
Orphan Recovery & Startup State Reconciler for HERMES 2.x.

Core Invariants:
1. Crash & Restart Resilience: Recovers or transitions non-terminal state records if HERMES restarts unexpectedly.
2. OS Process Verification: Verifies active PIDs using OS process probes before declaring background jobs alive.
3. Clean Git Working Tree: Detects and removes dangling worktrees in .hermes/worktrees/.
4. Deterministic State Updates: Emits canonical events to reconcile the authoritative state store.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

from core.runtime_state.events import EventType, HermesEvent
from core.event_bus import EventBus
from core.runtime_state.store import StateStore, ExecutionStateStore
from core.runtime_state.models import (
    SubagentStatus,
    JobStatus,
    WorktreeStatus,
)
from core.subagents.worktree import WorktreeManager

logger = logging.getLogger("hermes.subagents.reconciler")


class SubagentReconciler:
    """
    Reconciles in-flight subagents, background jobs, and git worktrees upon startup or recovery.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        state_store: Optional[ExecutionStateStore] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.state_store = state_store
        self.event_bus = event_bus
        self.worktree_mgr = WorktreeManager(self.workspace_root)

    def _is_pid_alive(self, pid: int) -> bool:
        """Check whether an OS process with this PID is currently running."""
        if pid <= 0:
            return False
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                try:
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False

    async def reconcile(self) -> Dict[str, Any]:
        """
        Execute full recovery scan across state store and file system.
        """
        report: Dict[str, Any] = {
            "orphaned_subagents": 0,
            "orphaned_jobs": 0,
            "cleaned_worktrees": 0,
        }

        active_worktree_ids: Set[str] = set()

        if self.state_store:
            state = self.state_store.get_state()

            # 1. Reconcile subagents
            for agent_id, agent_rec in list(state.agents.items()):
                if not agent_rec.status.is_terminal:
                    report["orphaned_subagents"] += 1
                    if self.event_bus:
                        self.event_bus.publish(
                            HermesEvent(
                                event_type=EventType.SUBAGENT_FAILED,
                                mission_id=agent_rec.mission_id or state.mission.mission_id,
                                source="reconciler",
                                agent_id=agent_id,
                                task_id=agent_rec.task_id,
                                payload={"error": "Orphaned subagent detected upon system restart"},
                            )
                        )

            # 2. Reconcile background jobs
            for job_id, job_rec in list(state.background_jobs.items()):
                if not job_rec.status.is_terminal:
                    pid_alive = job_rec.pid and self._is_pid_alive(job_rec.pid)
                    if not pid_alive:
                        report["orphaned_jobs"] += 1
                        if self.event_bus:
                            self.event_bus.publish(
                                HermesEvent(
                                    event_type=EventType.BACKGROUND_JOB_ORPHANED,
                                    mission_id=state.mission.mission_id,
                                    source="reconciler",
                                    job_id=job_id,
                                    task_id=job_rec.task_id,
                                    payload={"error": f"Process {job_rec.pid} is no longer running"},
                                )
                            )
                    else:
                        if job_rec.worktree_id:
                            active_worktree_ids.add(job_rec.worktree_id)

        # 3. Clean up orphaned worktrees
        cleaned_paths = self.worktree_mgr.recover_orphaned_worktrees(active_worktree_ids)
        report["cleaned_worktrees"] = len(cleaned_paths)

        return report
