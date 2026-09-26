# tools/platform/permissions.py
"""
Unified Permission Policy Architecture for HERMES 2.x Tool Platform.
Evolves PermissionGate to enforce pre-execution authorization across
all operating modes, risk tiers, and workspace boundaries.
"""

from __future__ import annotations

import enum
from typing import Any, Dict, Optional, Tuple

from tools.platform.specs import ToolSpec, RiskLevel, RiskMetadata
from tools.registry import PermissionGate


class PermissionDecision(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK = "ASK"
    MODIFY = "MODIFY"


class PermissionPolicy:
    """
    Authoritative permission policy evaluation engine.
    Ensures that no physical action executes without explicit mode and risk clearance.
    """

    VALID_MODES: frozenset[str] = frozenset({"auto", "plan", "safe"})

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode if (isinstance(mode, str) and mode in self.VALID_MODES) else "auto"
        self._gate = PermissionGate(self.mode)

    def authorize(
        self,
        spec: ToolSpec,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Tuple[PermissionDecision, str]:
        """
        Evaluate authorization for a tool call.
        Returns: (decision, reason)
        """
        args = arguments or {}

        # 1. Mode-based blocklist evaluation
        if self.mode in spec.risk.blocked_in:
            return (
                PermissionDecision.DENY,
                f"Tool '{spec.canonical_name}' is explicitly blocked in '{self.mode}' mode.",
            )

        # 2. Safe mode risk threshold evaluation
        if self.mode == "safe":
            if spec.risk.risk_score > 0.5 or spec.risk.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                return (
                    PermissionDecision.DENY,
                    f"Tool '{spec.canonical_name}' has risk_score={spec.risk.risk_score} "
                    f"({spec.risk.risk_level.value}) which exceeds 0.5 threshold for 'safe' mode.",
                )
            if spec.risk.destructive or spec.risk.executes_commands:
                return (
                    PermissionDecision.DENY,
                    f"Mutating or command execution tool '{spec.canonical_name}' is restricted in 'safe' mode.",
                )

        # 3. Plan mode restriction (plan mode prohibits filesystem mutations or system commands)
        if self.mode == "plan":
            if spec.risk.writes_files or spec.risk.executes_commands or spec.risk.destructive:
                return (
                    PermissionDecision.DENY,
                    f"Tool '{spec.canonical_name}' modifies environment and is prohibited in 'plan' mode.",
                )

        # 4. Confirmation requirement check
        if spec.risk.requires_confirmation:
            return (
                PermissionDecision.ASK,
                f"Tool '{spec.canonical_name}' requires explicit user confirmation before execution.",
            )

        # 5. Legacy implementation gate check if available
        if spec.implementation_cls is not None:
            allowed, gate_reason = self._gate.check(spec.implementation_cls)
            if not allowed:
                return PermissionDecision.DENY, gate_reason

        return PermissionDecision.ALLOW, "Authorized"
