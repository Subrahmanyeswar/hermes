# core/security/viewmodels.py
"""
HERMES 2.x - Security ViewModels (Prompt 13)
Structured presentation models for TUI, UI, and external consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ApprovalPromptViewModel:
    request_id: str
    tool_name: str
    arguments_summary: str
    risk_level: str
    risk_score: float
    reasons: List[str]
    allowed_scopes: List[str]
    is_headless: bool = False


@dataclass
class SecurityStatusViewModel:
    permission_status: str
    active_grants_count: int
    pending_requests_count: int
    consecutive_denials: int
    is_escalated: bool = False
    last_violation: Optional[str] = None
