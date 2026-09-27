# core/sessions/models.py
"""
Session models, ancestry tracking, and state definitions for HERMES 2.x persistence.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

from core.persistence.models import SessionStatus


@dataclass
class DurableSession:
    """
    Authoritative metadata and lifecycle record for a durable agent session.
    """
    session_id: str
    mission_id: str
    workspace_root: str
    status: SessionStatus = SessionStatus.CREATED
    parent_session_id: Optional[str] = None
    root_session_id: Optional[str] = None
    current_checkpoint_id: Optional[str] = None
    current_sequence: int = 0
    branch_name: str = "main"
    fork_sequence: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DurableSession:
        d = dict(data)
        d["status"] = SessionStatus(d.get("status", SessionStatus.CREATED.value))
        return cls(**d)
