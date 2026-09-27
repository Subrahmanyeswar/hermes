# core/security/enums.py
"""
Enums and taxonomies for HERMES 2.x Security and Permission Architecture.
"""

from __future__ import annotations
from enum import Enum


class RiskLevel(str, Enum):
    """Categorical risk tiers for actions and operations."""
    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        order = {
            RiskLevel.SAFE: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }
        return order[self]


class RiskDimension(str, Enum):
    """Dimensions evaluated by the risk engine."""
    FILESYSTEM = "FILESYSTEM"
    SHELL = "SHELL"
    NETWORK = "NETWORK"
    CREDENTIALS = "CREDENTIALS"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    DESTRUCTIVE = "DESTRUCTIVE"
    GIT = "GIT"
    PROCESS_CONTROL = "PROCESS_CONTROL"
    PACKAGE_INSTALLATION = "PACKAGE_INSTALLATION"
    SYSTEM_CONFIGURATION = "SYSTEM_CONFIGURATION"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    SUBAGENT = "SUBAGENT"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    SECURITY_CONTROL_CHANGE = "SECURITY_CONTROL_CHANGE"

    # Convenience aliases
    SECURITY_TAMPERING = "SECURITY_CONTROL_CHANGE"
    COMMAND_EXECUTION = "SHELL"
    CREDENTIAL = "CREDENTIALS"
    FILESYSTEM_WRITE = "FILESYSTEM"
    FILESYSTEM_DELETE = "FILESYSTEM"


class PermissionOutcome(str, Enum):
    """The authoritative permission evaluation result."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK = "ASK"


class ApprovalScope(str, Enum):
    """Granularity of user authorization grants."""
    ONE_ACTION = "ONE_ACTION"
    ONE_TOOL_CALL = "ONE_TOOL_CALL"
    ACTION_PATTERN = "ACTION_PATTERN"
    TOOL_SCOPE = "TOOL_SCOPE"
    PATH_SCOPE = "PATH_SCOPE"
    SESSION_SCOPE = "SESSION_SCOPE"

    # Convenience aliases
    ONCE = "ONE_ACTION"
    EXACT_ACTION = "ONE_ACTION"
    TOOL_CALL = "ONE_TOOL_CALL"
    PATH_PREFIX = "PATH_SCOPE"
    COMMAND_PATTERN = "ACTION_PATTERN"
    SESSION = "SESSION_SCOPE"
    ALWAYS = "SESSION_SCOPE"


class ContentTrust(str, Enum):
    """Provenance and trust level of incoming content."""
    USER = "USER"
    PROJECT_RULE = "PROJECT_RULE"
    TRUSTED_POLICY = "TRUSTED_POLICY"
    MODEL_GENERATED = "MODEL_GENERATED"
    LOCAL_FILE = "LOCAL_FILE"
    EXTERNAL_FILE = "EXTERNAL_FILE"
    WEB = "WEB"
    SHELL_OUTPUT = "SHELL_OUTPUT"
    MCP = "MCP"
    SUBAGENT = "SUBAGENT"
    DATABASE = "DATABASE"

    # Convenience aliases
    TRUSTED_USER = "USER"
    TRUSTED_SYSTEM = "TRUSTED_POLICY"
    UNTRUSTED_EXTERNAL = "WEB"
    UNTRUSTED_FILE = "EXTERNAL_FILE"

    @property
    def is_external(self) -> bool:
        return self in (
            ContentTrust.WEB,
            ContentTrust.EXTERNAL_FILE,
            ContentTrust.SHELL_OUTPUT,
            ContentTrust.MCP,
            ContentTrust.DATABASE,
        )


class PromptInjectionStatus(str, Enum):
    """Classification returned by the prompt-injection probe."""
    NOT_DETECTED = "NOT_DETECTED"
    SUSPECTED = "SUSPECTED"
    HIGH_RISK = "HIGH_RISK"
    BLOCKED = "BLOCKED"

    # Convenience aliases
    SAFE = "NOT_DETECTED"
    SUSPICIOUS = "SUSPECTED"
    INJECTION_DETECTED = "HIGH_RISK"


class InjectionAttackFamily(str, Enum):
    """Taxonomy of prompt injection and manipulation techniques."""
    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
    AUTHORITY_SPOOFING = "AUTHORITY_SPOOFING"
    CREDENTIAL_REQUEST = "CREDENTIAL_REQUEST"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    SECURITY_BYPASS = "SECURITY_BYPASS"
    TOOL_REDIRECTION = "TOOL_REDIRECTION"
    USER_IMPERSONATION = "USER_IMPERSONATION"
    POLICY_MODIFICATION = "POLICY_MODIFICATION"
    SOCIAL_ENGINEERING = "SOCIAL_ENGINEERING"

    # Convenience aliases
    OVERRIDE_INSTRUCTION = "INSTRUCTION_OVERRIDE"
    SYSTEM_PROMPT_EXTRACTION = "CREDENTIAL_REQUEST"
    EXFILTRATION_TRIGGER = "DATA_EXFILTRATION"
    JAILBREAK_ATTEMPT = "SECURITY_BYPASS"
    DELIMITER_INJECTION = "TOOL_REDIRECTION"


class DenialReasonCode(str, Enum):
    """Machine-readable denial reasons."""
    HARD_SECURITY_DENY = "HARD_SECURITY_DENY"
    OUTSIDE_WORKSPACE = "OUTSIDE_WORKSPACE"
    SENSITIVE_RESOURCE = "SENSITIVE_RESOURCE"
    UNTRUSTED_NETWORK = "UNTRUSTED_NETWORK"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"
    UNAUTHORIZED_GIT_OPERATION = "UNAUTHORIZED_GIT_OPERATION"
    CREDENTIAL_ACCESS = "CREDENTIAL_ACCESS"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    SECURITY_POLICY_MODIFICATION = "SECURITY_POLICY_MODIFICATION"
    SUBAGENT_PERMISSION_ESCALATION = "SUBAGENT_PERMISSION_ESCALATION"
    CLASSIFIER_UNAVAILABLE = "CLASSIFIER_UNAVAILABLE"
    HEADLESS_APPROVAL_REQUIRED = "HEADLESS_APPROVAL_REQUIRED"
    DENIAL_LOOP = "DENIAL_LOOP"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    UNAUTHORIZED_EXECUTION = "UNAUTHORIZED_EXECUTION"

    # Convenience aliases
    USER_INTENT_PROHIBITED = "POLICY_VIOLATION"
    SUBAGENT_CEILING_VIOLATION = "SUBAGENT_PERMISSION_ESCALATION"
    HEADLESS_BLOCKED = "HEADLESS_APPROVAL_REQUIRED"


class HeadlessBehavior(str, Enum):
    """Behavior when ASK is triggered in headless/non-interactive mode."""
    FAIL_CLOSED = "FAIL_CLOSED"
    AUTO_DENY = "AUTO_DENY"
    PRE_APPROVED = "PRE_APPROVED"
