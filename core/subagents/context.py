# core/subagents/context.py
"""
Subagent Context Isolation & Construction for HERMES 2.x.

Core Invariants:
1. Fresh Context Window: Subagents start with a clean context, NOT a copy of the parent transcript.
2. Injected Constraints: Receives only assigned goals, requirements, path constraints, and tool schemas.
3. Structured Handoff Contract: Instructs subagent to return structured summary, evidence, and diffs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.runtime_state.models import (
    AgentType,
    SubagentHandoff,
    SubagentToolPolicy,
    SubagentBudget,
)


@dataclass
class SubagentPromptContext:
    """The complete constructed prompt and parameter envelope for a subagent."""
    system_prompt: str
    initial_user_prompt: str
    workspace_path: str
    allowed_tools: List[str]
    budget: SubagentBudget
    metadata: Dict[str, Any] = field(default_factory=dict)


class SubagentContextBuilder:
    """
    Constructs isolated, purpose-built prompt contexts for subagents.
    Ensures zero pollution from parent conversation transcripts.
    """

    @classmethod
    def build_context(
        cls,
        handoff: SubagentHandoff,
        role: AgentType | str,
        tool_policy: SubagentToolPolicy,
        rules: Optional[Sequence[str]] = None,
        skills: Optional[Sequence[str]] = None,
    ) -> SubagentPromptContext:
        """
        Build a completely fresh context envelope for the subagent.
        """
        role_str = role.value if isinstance(role, AgentType) else str(role).upper()

        # 1. System Prompt
        system_lines = [
            f"# HERMES SUBAGENT — ROLE: {role_str}",
            "",
            "You are an isolated, specialized subagent executing a dedicated task for the primary agent.",
            f"You are operating in workspace: {handoff.workspace_path or 'current workspace'}",
            "",
            "## CONSTRAINTS & LIMITS",
            f"- Role Type: {role_str}",
            f"- Read Only: {tool_policy.read_only}",
            f"- Can Mutate Files: {tool_policy.can_mutate}",
            f"- Can Execute Shell: {tool_policy.can_shell}",
            f"- Max Turns: {handoff.budget.max_turns}",
            f"- Max Tool Calls: {handoff.budget.max_tool_calls}",
            f"- Output Limit: {handoff.budget.max_output_bytes} bytes",
            "",
            "## EXECUTION GUIDELINES",
            "1. Focus strictly on your assigned objective. Do not wander or expand scope.",
            "2. When your task is finished, or if you encounter an unrecoverable blocker, finalize immediately.",
            "3. Provide deterministic, high-signal evidence for every finding or mutation.",
            "4. Format your final response with structured sections:",
            "   - SUMMARY: Brief 1-2 sentence overview of what was accomplished.",
            "   - FINDINGS: Bulleted list of key discoveries or observations.",
            "   - MODIFIED FILES: List of any files created or modified.",
            "   - TEST RESULTS: Results of any tests or verifications executed.",
            "   - RECOMMENDATIONS: Recommended next steps for the primary agent.",
        ]

        if rules:
            system_lines.append("")
            system_lines.append("## ACTIVE RULES")
            for r in rules:
                system_lines.append(f"- {r}")

        if skills:
            system_lines.append("")
            system_lines.append("## AVAILABLE SKILLS")
            for s in skills:
                system_lines.append(f"- {s}")

        system_prompt = "\n".join(system_lines)

        # 2. Initial User Prompt (Delegation Envelope)
        user_lines = [
            f"### ASSIGNED TASK: {handoff.goal}",
            "",
        ]

        if handoff.requirements:
            user_lines.append("#### Specific Requirements to Address:")
            for req in handoff.requirements:
                user_lines.append(f"- {req}")
            user_lines.append("")

        if handoff.scope_paths:
            user_lines.append("#### Scope Boundary Paths:")
            for p in handoff.scope_paths:
                user_lines.append(f"- `{p}`")
            user_lines.append("")

        if handoff.constraints:
            user_lines.append("#### Explicit Constraints:")
            for c in handoff.constraints:
                user_lines.append(f"- {c}")
            user_lines.append("")

        if handoff.expected_output:
            user_lines.append(f"#### Expected Deliverable:\n{handoff.expected_output}\n")

        user_lines.append("Please execute the necessary actions and report back with your findings and evidence.")

        initial_user_prompt = "\n".join(user_lines)

        return SubagentPromptContext(
            system_prompt=system_prompt,
            initial_user_prompt=initial_user_prompt,
            workspace_path=handoff.workspace_path,
            allowed_tools=tool_policy.allowed_tools,
            budget=handoff.budget,
            metadata={
                "task_id": handoff.task_id,
                "agent_id": handoff.agent_id,
                "role": role_str,
                "worktree_id": handoff.worktree_id,
            },
        )
