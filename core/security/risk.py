# core/security/risk.py
"""
Deterministic Risk Engine for HERMES 2.x.
Evaluates proposed actions across 14 categorical risk dimensions
without premature reliance on heavy model calls.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.security.action_fingerprint import normalize_path
from core.security.config import SecurityPolicy, DEFAULT_HARD_DENIED_PATTERNS
from core.security.enums import RiskDimension, RiskLevel
from core.security.models import ActionDescriptor, RiskAssessment

CREDENTIAL_REGEXES = [
    re.compile(r"(sk-[a-zA-Z0-9_\-]{20,})"),               # OpenAI / NIM API keys
    re.compile(r"(ghp_[a-zA-Z0-9]{36,})"),                 # GitHub tokens
    re.compile(r"((?:password|secret|token|api_key)['\"]?\s*[:=]\s*['\"]?)([^'\"\s,;]+)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([a-zA-Z0-9\._\-]{20,})", re.IGNORECASE),
]


def redact_sensitive_text(text: str) -> str:
    """Redact API keys, tokens, passwords, and secrets."""
    if not isinstance(text, str):
        return text
    redacted = text
    for pattern in CREDENTIAL_REGEXES:
        if pattern.groups == 1:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        elif pattern.groups == 2:
            redacted = pattern.sub(r"\1[REDACTED_SECRET]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class RiskEngine:
    """
    Evaluates ActionDescriptor structures against multi-dimensional risk rules.
    Assigns explicit RiskLevel (SAFE, LOW, MEDIUM, HIGH, CRITICAL).
    """

    def __init__(self, policy: Optional[SecurityPolicy] = None):
        self.policy = policy or SecurityPolicy()

    def assess_action(
        self,
        action: ActionDescriptor,
        workspace_root: Optional[str] = None,
    ) -> RiskAssessment:
        """Evaluate an action across all risk dimensions."""
        ws_root = normalize_path(workspace_root or self.policy.workspace_root)
        dimensions: Set[RiskDimension] = set()
        reasons: List[str] = []
        highest_risk = RiskLevel.SAFE

        def raise_risk(level: RiskLevel, dim: RiskDimension, reason: str):
            nonlocal highest_risk
            dimensions.add(dim)
            reasons.append(reason)
            if level.rank > highest_risk.rank:
                highest_risk = level

        tool_name = (action.tool_name or "").lower().strip()
        op = (action.operation or "").lower().strip()
        args = action.arguments or {}

        # ── 1. Security Control / Self-Modification Check ────────────────────
        # Prevent any tool from modifying or tampering with core/security/ or security policy
        for p in action.target_paths:
            norm_p = normalize_path(p, ws_root)
            if any(marker in norm_p for marker in ("/core/security/", "\\core\\security\\", "core/security")):
                is_mutating = op in ("write", "edit", "delete", "create", "append") or action.destructive or (not action.is_read_only) or tool_name in ("write_file", "edit_file")
                if is_mutating:
                    raise_risk(
                        RiskLevel.CRITICAL,
                        RiskDimension.SECURITY_CONTROL_CHANGE,
                        f"Attempt to modify security subsystem at '{p}' is prohibited.",
                    )

        # ── 2. Filesystem & Sensitive Resource Assessment ────────────────────
        if action.target_paths or tool_name.startswith("fs.") or tool_name in ("write_file", "edit_file", "read_file", "delete_file"):
            dimensions.add(RiskDimension.FILESYSTEM)
            for path_str in action.target_paths:
                norm_p = normalize_path(path_str, ws_root)

                # Check for sensitive path patterns
                is_sensitive = False
                base_name = Path(norm_p).name
                for pattern in self.policy.sensitive_paths:
                    if fnmatch.fnmatch(base_name, pattern) or fnmatch.fnmatch(norm_p, f"*/{pattern}"):
                        is_sensitive = True
                        break

                if is_sensitive:
                    raise_risk(
                        RiskLevel.CRITICAL if op in ("write", "edit", "delete") else RiskLevel.HIGH,
                        RiskDimension.CREDENTIALS,
                        f"Access to sensitive credential path '{path_str}'.",
                    )

                # Check workspace boundary escape
                if ws_root and not norm_p.startswith(ws_root):
                    # Path is outside workspace
                    if op in ("write", "edit", "delete") or action.destructive:
                        raise_risk(
                            RiskLevel.CRITICAL,
                            RiskDimension.FILESYSTEM,
                            f"Mutating filesystem operation outside workspace: '{path_str}'.",
                        )
                    else:
                        raise_risk(
                            RiskLevel.HIGH,
                            RiskDimension.FILESYSTEM,
                            f"Read access outside workspace boundary: '{path_str}'.",
                        )

            # Destructive delete check
            if action.destructive or op == "delete":
                raise_risk(
                    RiskLevel.HIGH,
                    RiskDimension.DESTRUCTIVE,
                    f"Destructive deletion operation on {len(action.target_paths)} target(s).",
                )

            # Standard workspace edits
            if highest_risk == RiskLevel.SAFE and op in ("write", "edit"):
                raise_risk(
                    RiskLevel.LOW,
                    RiskDimension.FILESYSTEM,
                    f"Workspace file modification on {action.target_paths}.",
                )

        # ── 3. Shell Command Assessment ───────────────────────────────────────
        if tool_name in ("shell.bash", "bash_exec", "terminal", "exec") or "cmd" in args or "command" in args:
            dimensions.add(RiskDimension.SHELL)
            cmd = args.get("cmd") or args.get("command") or ""
            if isinstance(cmd, list):
                cmd_str = " ".join(str(c) for c in cmd)
            else:
                cmd_str = str(cmd)

            lower_cmd = cmd_str.lower().strip()

            # Hard denied command patterns
            for hard_pattern in self.policy.hard_denied_patterns:
                if hard_pattern.lower() in lower_cmd:
                    raise_risk(
                        RiskLevel.CRITICAL,
                        RiskDimension.DESTRUCTIVE,
                        f"Hard-denied destructive pattern '{hard_pattern}' in shell command: '{cmd_str[:80]}'.",
                    )

            # Dangerous shell constructs
            if any(term in lower_cmd for term in ("curl ", "wget ")) and ("| sh" in lower_cmd or "| bash" in lower_cmd):
                raise_risk(
                    RiskLevel.CRITICAL,
                    RiskDimension.SHELL,
                    "Piping remote web download directly into shell execution.",
                )

            # Sensitive credential access in shell
            if any(term in lower_cmd for term in (".env", "id_rsa", "id_ed25519", "shadow", "credentials")):
                raise_risk(
                    RiskLevel.HIGH,
                    RiskDimension.CREDENTIALS,
                    f"Shell command references sensitive credential files: '{cmd_str[:80]}'.",
                )

            # Package installation
            if any(cmd_prefix in lower_cmd for cmd_prefix in ("pip install", "npm install", "yarn add", "cargo install")):
                raise_risk(
                    RiskLevel.MEDIUM,
                    RiskDimension.PACKAGE_INSTALLATION,
                    f"Package installation command: '{cmd_str[:80]}'.",
                )

            # Command substitution check
            if "$(" in cmd_str or "`" in cmd_str:
                raise_risk(
                    RiskLevel.HIGH,
                    RiskDimension.SHELL,
                    f"Command substitution detected in shell command: '{cmd_str[:80]}'.",
                )

            # Benign / safe test commands
            is_test_command = any(
                lower_cmd.startswith(prefix) or f" {prefix}" in lower_cmd
                for prefix in ("pytest", "python -m pytest", "npm test", "cargo test", "go test")
            )
            is_info_command = any(
                lower_cmd.startswith(prefix) for prefix in ("git status", "git diff", "git log", "ls", "dir", "echo ")
            )

            if highest_risk == RiskLevel.SAFE:
                if is_test_command or is_info_command:
                    raise_risk(RiskLevel.LOW, RiskDimension.SHELL, f"Standard test or inspection command: '{cmd_str[:60]}'.")
                else:
                    raise_risk(RiskLevel.MEDIUM, RiskDimension.SHELL, f"Arbitrary shell command: '{cmd_str[:80]}'.")

        # ── 4. Git Operation Assessment ───────────────────────────────────────
        if tool_name.startswith("git.") or "git" in tool_name:
            dimensions.add(RiskDimension.GIT)
            subcmd = args.get("subcommand", "").lower() or op
            if any(term in subcmd for term in ("push --force", "push -f", "reset --hard", "branch -d", "branch -d")):
                raise_risk(
                    RiskLevel.HIGH,
                    RiskDimension.DESTRUCTIVE,
                    f"Destructive Git operation: '{subcmd}'.",
                )
            elif "push" in subcmd:
                raise_risk(
                    RiskLevel.MEDIUM,
                    RiskDimension.GIT,
                    f"External Git push operation: '{subcmd}'.",
                )
            elif subcmd in ("status", "diff", "log", "branch", "show"):
                if highest_risk == RiskLevel.SAFE:
                    raise_risk(RiskLevel.SAFE, RiskDimension.GIT, "Read-only Git inspection.")
            else:
                if highest_risk.rank < RiskLevel.LOW.rank:
                    raise_risk(RiskLevel.LOW, RiskDimension.GIT, f"Standard Git command: '{subcmd}'.")

        # ── 5. Network Destination Assessment ─────────────────────────────────
        if action.network_destinations or tool_name in ("http_request", "curl", "fetch", "web.get"):
            dimensions.add(RiskDimension.NETWORK)
            for dest in action.network_destinations:
                dest_lower = dest.lower().strip()
                is_trusted = any(dest_lower == td or dest_lower.endswith(f".{td}") for td in self.policy.trusted_domains)
                if not is_trusted:
                    raise_risk(
                        RiskLevel.HIGH,
                        RiskDimension.NETWORK,
                        f"External network connection to untrusted host '{dest}'.",
                    )
                else:
                    if highest_risk.rank < RiskLevel.LOW.rank:
                        raise_risk(RiskLevel.LOW, RiskDimension.NETWORK, f"Connection to trusted domain '{dest}'.")

        # ── 6. Subagent Delegation Assessment ─────────────────────────────────
        if tool_name in ("task.delegate", "delegate"):
            dimensions.add(RiskDimension.SUBAGENT)
            if highest_risk.rank < RiskLevel.LOW.rank:
                raise_risk(RiskLevel.LOW, RiskDimension.SUBAGENT, "Subagent task delegation.")

        # Default fallback
        if not reasons:
            reasons.append("Default safe local action")

        risk_scores = {
            RiskLevel.SAFE: 0.0,
            RiskLevel.LOW: 0.2,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.8,
            RiskLevel.CRITICAL: 1.0,
        }
        score = risk_scores.get(highest_risk, 0.0)

        return RiskAssessment(
            risk_level=highest_risk,
            dimensions=list(dimensions),
            reasons=reasons,
            confidence=score,
        )
