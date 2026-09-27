# ui/viewmodels/jobs.py
"""Background Jobs and Subagents ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class JobItemViewModel:
    job_id: str
    kind: str
    status: str
    owner: str
    pid_str: str = "N/A"
    command_summary: str = ""
    worktree_id: str = ""


@dataclass(frozen=True)
class JobViewModel:
    jobs: Tuple[JobItemViewModel, ...] = ()
    active_count: int = 0
    total_count: int = 0
