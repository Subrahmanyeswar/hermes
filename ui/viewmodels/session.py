# ui/viewmodels/session.py
"""Session Lineage and Persistence ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SessionViewModel:
    session_id: str = "N/A"
    mission_id: str = "N/A"
    status: str = "CREATED"
    branch_name: str = "main"
    current_checkpoint_id: Optional[str] = None
    parent_session_id: Optional[str] = None
    root_session_id: Optional[str] = None
    is_resumable: bool = True
    last_activity_str: str = "N/A"
