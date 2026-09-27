# core/security/classifier.py
"""
HERMES 2.x - Action Classifier (Prompt 13)
Multi-stage classifier:
  Stage 0: Deterministic Fast-Path (tool signatures, known read-only commands)
  Stage 1: Heuristic Risk Engine Evaluation (14 dimensions, path boundaries, destructive verbs)
  Stage 2: Advisory Evaluation (strictly bounded, fail-closed, cannot override hard denies)
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple

from core.security.action_fingerprint import compute_action_fingerprint, normalize_path
from core.security.config import SecurityPolicy, get_default_security_policy
from core.security.enums import RiskLevel
from core.security.models import ActionDescriptor, RiskAssessment, UserIntent
from core.security.risk import RiskEngine

logger = logging.getLogger("hermes.security.classifier")

READ_ONLY_TOOLS = {
    "read_file",
    "view_file",
    "list_directory",
    "search_files",
    "grep",
    "git_status",
    "git_diff",
    "git_log",
    "read_url_content",
}


class ActionClassifier:
    """
    Classifies tool actions by inspecting tool name, arguments, targets, and context.
    """

    def __init__(
        self,
        risk_engine: Optional[RiskEngine] = None,
        policy: Optional[SecurityPolicy] = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.policy = policy or get_default_security_policy()

    def build_descriptor(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        is_subagent: bool = False,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> ActionDescriptor:
        """Create a normalized ActionDescriptor with a cryptographic fingerprint."""
        # Detect canonical target path if present
        raw_path = (
            arguments.get("path")
            or arguments.get("file_path")
            or arguments.get("TargetFile")
            or arguments.get("AbsolutePath")
            or arguments.get("target")
        )
        canonical_path = normalize_path(str(raw_path)) if raw_path else None

        # Detect command string if present
        command_str = (
            arguments.get("command")
            or arguments.get("cmd")
            or arguments.get("CommandLine")
        )
        if command_str is not None:
            command_str = str(command_str)

        # Detect target URL if present
        target_url = arguments.get("url") or arguments.get("Url")
        if target_url is not None:
            target_url = str(target_url)

        # Determine read-only characteristic
        is_read_only = tool_name in READ_ONLY_TOOLS
        if tool_name in ("run_command", "bash", "execute_command") and command_str:
            # Check if command is strictly read-only
            first_word = command_str.strip().split()[0] if command_str.strip() else ""
            if first_word in ("cat", "ls", "dir", "pwd", "git", "grep", "echo", "head", "tail"):
                if "rm" not in command_str and ">" not in command_str and "mv" not in command_str:
                    is_read_only = True

        fingerprint = compute_action_fingerprint(
            tool_name=tool_name,
            arguments=arguments,
            canonical_path=canonical_path,
            command_str=command_str,
            target_url=target_url,
        )

        return ActionDescriptor(
            tool_name=tool_name,
            arguments=arguments,
            action_fingerprint=fingerprint,
            is_read_only=is_read_only,
            canonical_path=canonical_path,
            command_str=command_str,
            target_url=target_url,
            is_subagent_action=is_subagent,
            agent_id=agent_id,
            task_id=task_id,
        )

    def classify_action(
        self,
        action: ActionDescriptor,
        user_intent: Optional[UserIntent] = None,
    ) -> Tuple[ActionDescriptor, RiskAssessment]:
        """
        Execute Stage 0 and Stage 1 classification.
        Returns (action_descriptor, risk_assessment).
        """
        # Stage 0: Fast-path for known harmless read-only operations
        if action.is_read_only and not action.command_str and not action.target_url:
            # Check if accessing sensitive paths like .env even for read
            if action.canonical_path and (".env" in action.canonical_path or "id_rsa" in action.canonical_path):
                # Cannot fast-path sensitive files! Escalate to Stage 1.
                pass
            else:
                fast_assessment = RiskAssessment(
                    level=RiskLevel.SAFE,
                    score=0.0,
                    summary=f"Safe read-only operation: {action.tool_name}",
                )
                action.risk_assessment = fast_assessment
                return action, fast_assessment

        # Stage 1: Full heuristic risk engine evaluation
        assessment = self.risk_engine.assess_action(action, user_intent)
        action.risk_assessment = assessment

        return action, assessment
