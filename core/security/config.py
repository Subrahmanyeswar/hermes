# core/security/config.py
"""
Configuration and policy definitions for HERMES 2.x Security Architecture.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.security.enums import HeadlessBehavior, RiskLevel


DEFAULT_SENSITIVE_PATHS: List[str] = [
    ".env",
    ".env.*",
    "*.env",
    "*id_rsa*",
    "*.pem",
    "*.key",
    "*credentials*",
    "*secret*",
    "*secrets*",
    ".git/*",
    "*/.git/*",
    "*shadow*",
    "*passwd*",
    "*authorized_keys*",
]

DEFAULT_HARD_DENIED_PATTERNS: List[str] = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "mkfs",
    "format c:",
    "format d:",
    "dd if=",
    ":(){ :|:& };:",
    "> /dev/sda",
    "chmod -R 777 /",
    "powershell -enc",
    "core/security/*",
    "core\\security\\*",
]

DEFAULT_TRUSTED_DOMAINS: List[str] = [
    "localhost",
    "127.0.0.1",
    "::1",
    "pypi.org",
    "github.com",
    "api.github.com",
]


@dataclass
class SecurityPolicy:
    """Authoritative, versioned security policy."""
    policy_version: str = "1.0.0"
    workspace_root: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)
    sensitive_paths: List[str] = field(default_factory=lambda: list(DEFAULT_SENSITIVE_PATHS))
    trusted_domains: List[str] = field(default_factory=lambda: list(DEFAULT_TRUSTED_DOMAINS))
    denied_domains: List[str] = field(default_factory=list)
    hard_denied_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_HARD_DENIED_PATTERNS))
    headless_behavior: HeadlessBehavior = HeadlessBehavior.FAIL_CLOSED
    max_consecutive_denials: int = 3
    max_total_denials: int = 20
    max_identical_attempts: int = 3
    auto_allow_safe_reads: bool = True
    auto_allow_workspace_edits: bool = True
    ask_on_shell: bool = True
    ask_on_network: bool = True
    deny_credential_access: bool = True
    deny_destructive_external: bool = True
    approval_cache_ttl_seconds: float = 3600.0
    max_subagent_depth: int = 2
    allow_network: bool = True
    blocked_tools: List[str] = field(default_factory=list)
    headless_mode: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["headless_behavior"] = self.headless_behavior.value
        return d


def validate_security_policy(policy: SecurityPolicy) -> Tuple[bool, List[str]]:
    """
    Validate that a SecurityPolicy has valid syntax and does not contain
    insecure contradictions (e.g. attempting to override hard denies).
    """
    errors: List[str] = []
    if not policy.policy_version:
        errors.append("policy_version cannot be empty")

    # Hard denies cannot be in allowed_tools or allowed by wildcard
    for pattern in policy.hard_denied_patterns:
        if pattern in policy.allowed_tools:
            errors.append(f"Insecure policy: hard denied pattern '{pattern}' cannot be in allowed_tools")

    if policy.max_consecutive_denials < 1:
        errors.append("max_consecutive_denials must be >= 1")

    return len(errors) == 0, errors


def get_default_security_policy(workspace_root: Optional[str] = None) -> SecurityPolicy:
    """Create default conservative policy."""
    ws = str(Path(workspace_root).resolve()) if workspace_root else ""
    return SecurityPolicy(
        policy_version="1.0.0",
        workspace_root=ws,
        allowed_tools=[],  # Empty means rely on risk assessment & allowlist
        denied_tools=[],
    )
