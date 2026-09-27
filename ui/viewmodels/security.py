# ui/viewmodels/security.py
"""Security and Permission ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ApprovalModalViewModel:
    visible: bool = False
    request_id: str = ""
    action_summary: str = ""
    risk_level: str = "NORMAL"
    tool_name: str = ""
    target_summary: str = ""
    explanation: str = ""


@dataclass(frozen=True)
class SecurityViewModel:
    status: str = "NONE"   # NONE, REQUESTED, APPROVED, DENIED, EXPIRED, CANCELLED
    action: str = ""
    risk_level: str = "NORMAL"
    decision: str = "ALLOWED"
    pending_approval: bool = False
    prompt_injection_warning: Optional[str] = None
    approval_scope: str = ""
    modal: Optional[ApprovalModalViewModel] = None
