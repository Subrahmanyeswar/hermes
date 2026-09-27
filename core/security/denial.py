# core/security/denial.py
"""
HERMES 2.x - Denial Tracker & Loop Prevention (Prompt 13)
Tracks consecutive action denials, detects adversarial or confused loops,
suggests safe alternative actions, and triggers security escalation when loops persist.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from core.security.enums import DenialReasonCode, PermissionOutcome
from core.security.models import ActionDescriptor, PermissionDecision

logger = logging.getLogger("hermes.security.denial")

# Safe alternative suggestions for common denied actions
ALTERNATIVE_SUGGESTIONS: Dict[str, str] = {
    "rm -rf": "Consider inspecting targets first with read-only tools or moving files to a temporary directory.",
    "cat .env": "Do not read secrets directly; query required configuration names without inspecting secret values.",
    "curl": "Use authorized workspace APIs or mock dependencies locally.",
    "git push --force": "Avoid force-pushing; use a regular branch commit or create a review branch.",
    "chmod 777": "Use minimum necessary permissions (e.g. chmod 644 or 755).",
    "sudo": "HERMES operates in non-root user mode; run operations without administrative privileges.",
}


class DenialTracker:
    """
    Monitors consecutive security denials and prevents runaway loops.
    """

    def __init__(self, loop_threshold: int = 3) -> None:
        self.loop_threshold = loop_threshold
        self._consecutive_denials: int = 0
        self._denial_history: List[PermissionDecision] = []

    @property
    def consecutive_denials(self) -> int:
        return self._consecutive_denials

    def record_decision(self, decision: PermissionDecision) -> Tuple[bool, Optional[str]]:
        """
        Record a decision.
        Returns (is_loop_detected, escalation_message).
        """
        self._denial_history.append(decision)

        if decision.outcome == PermissionOutcome.ALLOW:
            self._consecutive_denials = 0
            return False, None

        if decision.outcome == PermissionOutcome.DENY:
            self._consecutive_denials += 1
            logger.warning(
                "Security denial recorded (count: %d/%d). Reason: %s",
                self._consecutive_denials,
                self.loop_threshold,
                decision.reason,
            )

            if self._consecutive_denials >= self.loop_threshold:
                msg = (
                    f"Security denial threshold reached ({self._consecutive_denials} consecutive denials). "
                    f"Agent loop halted to prevent repeated security violations."
                )
                logger.error(msg)
                return True, msg

        return False, None

    def suggest_alternative(self, action: ActionDescriptor) -> Optional[str]:
        """Provide a safe alternative recommendation for a denied action."""
        # Check command arguments
        cmd = str(action.arguments.get("command", "") or action.arguments.get("cmd", ""))
        for pattern, suggestion in ALTERNATIVE_SUGGESTIONS.items():
            if pattern in cmd:
                return suggestion

        # Path-based alternatives
        path = action.canonical_path or ""
        if ".env" in path or "secret" in path.lower():
            return "Avoid accessing sensitive credential files directly."

        if not action.is_read_only:
            return "Consider running a read-only inspection first before proposing state mutations."

        return None

    def reset(self) -> None:
        """Reset consecutive counter."""
        self._consecutive_denials = 0
