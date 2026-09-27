# core/security/subagent_security.py
"""
HERMES 2.x - Subagent Security Governor (Prompt 13)
Enforces strict hierarchical permission ceilings for subagents:
  child_permissions = child_requested ∩ parent_effective ∩ global_policy
Guarantees a child never gains more authority than its parent.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set, Tuple

from core.security.config import SecurityPolicy, get_default_security_policy
from core.security.enums import DenialReasonCode, PermissionOutcome
from core.security.models import (
    ActionDescriptor,
    PermissionDecision,
    SubagentSecurityContext,
)

logger = logging.getLogger("hermes.security.subagent")


class SubagentSecurityGovernor:
    """
    Enforces permission containment across parent and child agents.
    Prevents privilege escalation via delegation.
    """

    def __init__(self, policy: Optional[SecurityPolicy] = None) -> None:
        self.policy = policy or get_default_security_policy()

    def calculate_effective_permissions(
        self,
        parent_context: SubagentSecurityContext,
        requested_tools: List[str],
        requested_read_only: bool = False,
        requested_depth: int = 1,
    ) -> Tuple[SubagentSecurityContext, List[str]]:
        """
        Calculate intersection of permissions:
          effective = requested ∩ parent ∩ global_policy
        Returns (child_context, list_of_stripped_privileges).
        """
        stripped_reasons: List[str] = []

        # 1. Depth containment
        effective_depth = parent_context.depth + 1
        if effective_depth > self.policy.max_subagent_depth:
            stripped_reasons.append(
                f"Delegation depth {effective_depth} exceeds max permitted depth {self.policy.max_subagent_depth}"
            )

        # 2. Read-only containment:
        # If parent is read-only, child MUST be read-only regardless of request
        effective_read_only = parent_context.read_only or requested_read_only
        if parent_context.read_only and not requested_read_only:
            stripped_reasons.append("Parent is read-only; child forced to read-only")

        # 3. Tool containment:
        # Child tools must be a subset of parent tools, minus global blocklist
        effective_tools: List[str] = []
        for tool in requested_tools:
            # Check global blocklist
            if tool in self.policy.blocked_tools:
                stripped_reasons.append(f"Tool '{tool}' is globally blocked")
                continue

            # Check parent tools
            if parent_context.allowed_tools and tool not in parent_context.allowed_tools:
                stripped_reasons.append(f"Tool '{tool}' not held by parent agent '{parent_context.agent_id}'")
                continue

            # Check read-only constraint on mutating tools
            if effective_read_only and tool in ("write_file", "edit_file", "bash", "execute_command", "git_commit"):
                stripped_reasons.append(f"Mutating tool '{tool}' forbidden in read-only subagent")
                continue

            effective_tools.append(tool)

        # 4. Path boundary containment
        # Child path boundaries cannot be broader than parent
        child_paths = parent_context.path_boundaries.copy()

        child_context = SubagentSecurityContext(
            agent_id="",  # Populated upon instantiation
            parent_id=parent_context.agent_id,
            depth=effective_depth,
            read_only=effective_read_only,
            allowed_tools=effective_tools,
            path_boundaries=child_paths,
            can_spawn_subagents=(effective_depth < self.policy.max_subagent_depth) and parent_context.can_spawn_subagents,
            network_enabled=parent_context.network_enabled and self.policy.allow_network,
        )

        return child_context, stripped_reasons

    def authorize_delegation(
        self,
        parent_context: SubagentSecurityContext,
        requested_tools: List[str],
    ) -> Tuple[bool, Optional[str], SubagentSecurityContext]:
        """
        Authorize outbound delegation request.
        Returns (is_authorized, reason_if_denied, child_context).
        """
        child_context, stripped = self.calculate_effective_permissions(
            parent_context, requested_tools
        )

        if child_context.depth > self.policy.max_subagent_depth:
            return False, f"Maximum delegation depth ({self.policy.max_subagent_depth}) reached", child_context

        if not parent_context.can_spawn_subagents:
            return False, f"Parent agent '{parent_context.agent_id}' is not authorized to spawn subagents", child_context

        return True, None, child_context

    def check_child_action(
        self,
        child_context: SubagentSecurityContext,
        action: ActionDescriptor,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an action proposed by a subagent is within its security ceiling.
        Returns (allowed, denial_reason).
        """
        # 1. Tool allowlist
        if child_context.allowed_tools and action.tool_name not in child_context.allowed_tools:
            return False, f"Tool '{action.tool_name}' not in subagent permitted tools"

        # 2. Read-only enforcement
        if child_context.read_only and not action.is_read_only:
            return False, f"Subagent is restricted to read-only; cannot perform mutating '{action.tool_name}'"

        # 3. Path boundary enforcement
        if child_context.path_boundaries and action.canonical_path:
            is_within = any(
                action.canonical_path.startswith(boundary)
                for boundary in child_context.path_boundaries
            )
            if not is_within:
                return False, f"Path '{action.canonical_path}' is outside subagent path boundary"

        return True, None
