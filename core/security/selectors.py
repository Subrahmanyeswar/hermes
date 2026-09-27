# core/security/selectors.py
"""
HERMES 2.x - Security Selectors (Prompt 13)
Pure query functions for reading security state from runtime state models.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List
from core.runtime_state.models import HermesRuntimeState, PermissionStatus


def select_permission_state(state: HermesRuntimeState) -> Dict[str, Any]:
    """Extract dict view of permission state."""
    return state.permission.to_dict()


def select_has_pending_permission(state: HermesRuntimeState) -> bool:
    """True if system is waiting for user permission."""
    return state.permission.status == PermissionStatus.REQUESTED


def select_active_permission_request_id(state: HermesRuntimeState) -> Optional[str]:
    """Get active permission request ID if pending."""
    if state.permission.status == PermissionStatus.REQUESTED:
        return state.permission.permission_request_id
    return None
