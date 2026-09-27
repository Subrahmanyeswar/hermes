# ui/viewmodels/mission.py
"""Mission and Progress ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class MissionViewModel:
    mission_id: str = "N/A"
    status: str = "IDLE"
    title: str = ""
    prompt_summary: str = ""
    start_time_str: str = "N/A"
    elapsed_time_str: str = "N/A"
    completed_tasks: int = 0
    total_tasks: int = 0
    is_terminal: bool = False
    abort_reason: Optional[str] = None


@dataclass(frozen=True)
class ProgressViewModel:
    overall_status: str = "IDLE"
    percentage_str: str = "0%"
    fraction: float = 0.0
    current_stage_name: str = "Idle"
    current_action: str = ""
    active_task_title: str = "None"
    next_action: str = "Awaiting instructions"
    waiting_reason: str = "NONE"
    blocked_reason: Optional[str] = None
    known_failures: Tuple[str, ...] = ()
