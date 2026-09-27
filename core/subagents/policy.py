# core/subagents/policy.py
"""
Subagent Tool & Security Policy Engine for HERMES 2.x.

Core Invariants:
1. A subagent is NOT another copy of the main agent; it gets a restricted toolset.
2. Principle of Least Privilege: Explorer and Reviewer are strictly read-only.
3. Ceiling Precedence: A child can NEVER escalate permissions beyond its parent.
4. Anti-Recursion: can_delegate=False by default; max delegation depth is strictly enforced.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set, Tuple

from core.runtime_state.models import (
    AgentType,
    SubagentBudget,
    SubagentToolPolicy,
)


# Standard tool bundles
READ_ONLY_EXPLORATION_TOOLS: List[str] = [
    "fs.read",
    "search.glob",
    "search.grep",
    "tool.search",
    "code.outline",
]

REVIEW_TOOLS: List[str] = [
    "fs.read",
    "search.glob",
    "search.grep",
    "git.diff",
]

TEST_TOOLS: List[str] = [
    "fs.read",
    "fs.write",
    "fs.edit",
    "shell.bash",
    "search.glob",
    "search.grep",
]

IMPLEMENTATION_TOOLS: List[str] = [
    "fs.read",
    "fs.write",
    "fs.edit",
    "shell.bash",
    "search.glob",
    "search.grep",
    "task.todo",
]


class SubagentPolicyEngine:
    """
    Authoritative policy engine for subagent capability configuration,
    permission enforcement, and ceiling inheritance.
    """

    @classmethod
    def get_preset_policy(cls, role: AgentType | str) -> Tuple[SubagentToolPolicy, SubagentBudget]:
        """
        Returns the authoritative default (ToolPolicy, Budget) for a specific agent role.
        """
        if isinstance(role, str):
            try:
                role_enum = AgentType(role.upper())
            except ValueError:
                role_enum = AgentType.CUSTOM
        else:
            role_enum = role

        if role_enum == AgentType.EXPLORER:
            policy = SubagentToolPolicy(
                allowed_tools=list(READ_ONLY_EXPLORATION_TOOLS),
                denied_tools=["fs.write", "fs.edit", "shell.bash", "task.delegate"],
                read_only=True,
                can_mutate=False,
                can_shell=False,
                can_network=False,
                can_delegate=False,
            )
            budget = SubagentBudget(
                max_turns=10,
                max_tool_calls=20,
                max_runtime_seconds=60.0,
                max_output_bytes=50_000,
            )
            return policy, budget

        elif role_enum == AgentType.REVIEWER:
            policy = SubagentToolPolicy(
                allowed_tools=list(REVIEW_TOOLS),
                denied_tools=["fs.write", "fs.edit", "shell.bash", "task.delegate"],
                read_only=True,
                can_mutate=False,
                can_shell=False,
                can_network=False,
                can_delegate=False,
            )
            budget = SubagentBudget(
                max_turns=10,
                max_tool_calls=20,
                max_runtime_seconds=60.0,
                max_output_bytes=50_000,
            )
            return policy, budget

        elif role_enum == AgentType.ANALYST:
            policy = SubagentToolPolicy(
                allowed_tools=list(READ_ONLY_EXPLORATION_TOOLS),
                denied_tools=["fs.write", "fs.edit", "shell.bash", "task.delegate"],
                read_only=True,
                can_mutate=False,
                can_shell=False,
                can_network=False,
                can_delegate=False,
            )
            budget = SubagentBudget(
                max_turns=10,
                max_tool_calls=25,
                max_runtime_seconds=90.0,
                max_output_bytes=60_000,
            )
            return policy, budget

        elif role_enum == AgentType.TESTER:
            policy = SubagentToolPolicy(
                allowed_tools=list(TEST_TOOLS),
                denied_tools=["task.delegate"],
                read_only=False,
                can_mutate=True,
                can_shell=True,
                can_network=False,
                can_delegate=False,
            )
            budget = SubagentBudget(
                max_turns=15,
                max_tool_calls=30,
                max_runtime_seconds=120.0,
                max_output_bytes=100_000,
            )
            return policy, budget

        elif role_enum == AgentType.IMPLEMENTER:
            policy = SubagentToolPolicy(
                allowed_tools=list(IMPLEMENTATION_TOOLS),
                denied_tools=["task.delegate"],
                read_only=False,
                can_mutate=True,
                can_shell=True,
                can_network=False,
                can_delegate=False,
            )
            budget = SubagentBudget(
                max_turns=20,
                max_tool_calls=40,
                max_runtime_seconds=180.0,
                max_output_bytes=100_000,
            )
            return policy, budget

        else:  # CUSTOM or PRIMARY
            policy = SubagentToolPolicy(
                allowed_tools=list(READ_ONLY_EXPLORATION_TOOLS),
                denied_tools=["task.delegate"],
                read_only=True,
                can_mutate=False,
                can_shell=False,
                can_network=False,
                can_delegate=False,
            )
            budget = SubagentBudget()
            return policy, budget

    @classmethod
    def enforce_ceiling(
        cls,
        child_policy: SubagentToolPolicy,
        parent_policy: Optional[SubagentToolPolicy] = None,
        max_depth: int = 1,
        current_depth: int = 0,
    ) -> SubagentToolPolicy:
        """
        Enforce that a child policy cannot escalate privileges beyond parent policy or system ceiling.
        Returns a sanitized, clamped SubagentToolPolicy copy.
        """
        effective = copy.deepcopy(child_policy)

        # 1. Depth & Recursive Delegation Ceiling
        if current_depth >= max_depth:
            effective.can_delegate = False
            if "task.delegate" not in [d.lower() for d in effective.denied_tools]:
                effective.denied_tools.append("task.delegate")
            effective.allowed_tools = [t for t in effective.allowed_tools if t.lower() != "task.delegate"]

        if parent_policy is not None:
            # 2. Mutation Ceiling
            if parent_policy.read_only or not parent_policy.can_mutate:
                effective.read_only = True
                effective.can_mutate = False
                for m_tool in ("fs.write", "fs.edit"):
                    if m_tool not in [d.lower() for d in effective.denied_tools]:
                        effective.denied_tools.append(m_tool)
                    effective.allowed_tools = [t for t in effective.allowed_tools if t.lower() != m_tool]

            # 3. Shell Ceiling
            if not parent_policy.can_shell:
                effective.can_shell = False
                if "shell.bash" not in [d.lower() for d in effective.denied_tools]:
                    effective.denied_tools.append("shell.bash")
                effective.allowed_tools = [t for t in effective.allowed_tools if t.lower() != "shell.bash"]

            # 4. Network Ceiling
            if not parent_policy.can_network:
                effective.can_network = False

            # 5. Delegation Ceiling
            if not parent_policy.can_delegate:
                effective.can_delegate = False
                if "task.delegate" not in [d.lower() for d in effective.denied_tools]:
                    effective.denied_tools.append("task.delegate")
                effective.allowed_tools = [t for t in effective.allowed_tools if t.lower() != "task.delegate"]

            # 6. Inherit Parent Denied Tools
            for denied in parent_policy.denied_tools:
                if denied.lower() not in [d.lower() for d in effective.denied_tools]:
                    effective.denied_tools.append(denied)
                effective.allowed_tools = [t for t in effective.allowed_tools if t.lower() != denied.lower()]

        return effective

    @classmethod
    def validate_tool_access(
        cls,
        tool_name: str,
        policy: SubagentToolPolicy,
    ) -> Tuple[bool, str]:
        """
        Validate whether the given tool is authorized under the given subagent tool policy.
        """
        return policy.is_tool_allowed(tool_name)
