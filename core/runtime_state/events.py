# core/runtime_state/events.py
"""
Canonical Event Models and Taxonomy for HERMES 2.x.
Ensures every event carries causal identity, monotonic sequencing, and
safe payload representations with automatic redaction of sensitive credentials.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Any, Optional


# ── Sensitive Data Redaction Patterns ────────────────────────────────────────

_SECRET_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9_\-]{20,})"),               # OpenAI / NIM API keys
    re.compile(r"(ghp_[a-zA-Z0-9]{36,})"),                 # GitHub tokens
    re.compile(r"(password['\"]\s*[:=]\s*['\"])([^'\"]+)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([a-zA-Z0-9\._\-]{20,})", re.IGNORECASE),
    re.compile(r"(<think>.*?</think>)", re.DOTALL | re.IGNORECASE),  # Hidden chain-of-thought
]


def redact_sensitive_str(text: str) -> str:
    """Redact API keys, tokens, passwords, and chain-of-thought blocks."""
    if not isinstance(text, str):
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 1:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        elif pattern.groups == 2:
            redacted = pattern.sub(r"\1[REDACTED_SECRET]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_sensitive_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively redact strings and sensitive keys in dictionary payloads."""
    cleaned = {}
    sensitive_keys = {"password", "secret", "token", "api_key", "authorization", "auth", "private_key"}
    for k, v in payload.items():
        if k.lower() in sensitive_keys and isinstance(v, str):
            cleaned[k] = "[REDACTED_SECRET]"
        elif isinstance(v, str):
            cleaned[k] = redact_sensitive_str(v)
        elif isinstance(v, dict):
            cleaned[k] = redact_sensitive_payload(v)
        elif isinstance(v, list):
            cleaned[k] = [
                redact_sensitive_str(item) if isinstance(item, str)
                else (redact_sensitive_payload(item) if isinstance(item, dict) else item)
                for item in v
            ]
        else:
            cleaned[k] = v
    return cleaned


# ── Event Taxonomy ───────────────────────────────────────────────────────────

class EventType(str, Enum):
    # Mission Lifecycle
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_STATUS_CHANGED = "MISSION_STATUS_CHANGED"
    MISSION_PAUSED = "MISSION_RESUMED"
    MISSION_RESUMED = "MISSION_RESUMED"
    MISSION_COMPLETING = "MISSION_COMPLETING"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_FAILED = "MISSION_FAILED"
    MISSION_BLOCKED = "MISSION_BLOCKED"
    MISSION_CANCELLED = "MISSION_CANCELLED"
    MISSION_ABORTED = "MISSION_ABORTED"

    # Workspace & Context
    WORKSPACE_SCAN_STARTED = "WORKSPACE_SCAN_STARTED"
    WORKSPACE_SCAN_PROGRESS = "WORKSPACE_SCAN_PROGRESS"
    WORKSPACE_SCAN_COMPLETED = "WORKSPACE_SCAN_COMPLETED"

    # Skills & Planning
    SKILL_LOADING = "SKILL_LOADING"
    SKILL_LOADED = "SKILL_LOADED"
    PLANNING_STARTED = "PLANNING_STARTED"
    PLAN_CREATED = "PLAN_CREATED"

    # Goal Lifecycle
    GOAL_CREATED = "GOAL_CREATED"
    GOAL_UPDATED = "GOAL_UPDATED"
    GOAL_PROGRESS_CHANGED = "GOAL_PROGRESS_CHANGED"
    GOAL_COMPLETED = "GOAL_COMPLETED"

    # Task Lifecycle
    TASK_CREATED = "TASK_CREATED"
    TASK_READY = "TASK_READY"
    TASK_STARTED = "TASK_STARTED"
    TASK_PROGRESS = "TASK_PROGRESS"
    TASK_WAITING = "TASK_WAITING"
    TASK_VERIFYING = "TASK_VERIFYING"
    TASK_REPAIRING = "TASK_REPAIRING"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"

    # Model Lifecycle
    MODEL_REQUEST_STARTED = "MODEL_REQUEST_STARTED"
    MODEL_REQUESTED = "MODEL_REQUESTED"
    MODEL_CONNECTING = "MODEL_CONNECTING"
    MODEL_CONNECTED = "MODEL_CONNECTED"
    MODEL_STREAM_STARTED = "MODEL_STREAM_STARTED"
    MODEL_GENERATING = "MODEL_GENERATING"
    MODEL_TTFT = "MODEL_TTFT"
    MODEL_FIRST_TOKEN = "MODEL_FIRST_TOKEN"
    MODEL_COMPLETED = "MODEL_COMPLETED"
    MODEL_FAILED = "MODEL_FAILED"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_DISCONNECTED = "MODEL_DISCONNECTED"
    MODEL_RECONNECTING = "MODEL_RECONNECTING"
    MODEL_CANCELLED = "MODEL_CANCELLED"
    ROUTING_DECISION = "ROUTING_DECISION"

    # Tool Lifecycle
    TOOL_REQUESTED = "TOOL_REQUESTED"
    TOOL_VALIDATION_STARTED = "TOOL_VALIDATION_STARTED"
    TOOL_VALIDATION_FAILED = "TOOL_VALIDATION_FAILED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_PROGRESS = "TOOL_PROGRESS"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    TOOL_CANCELLED = "TOOL_CANCELLED"

    # Verification & Quality
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFICATION_NEEDS_IMPROVEMENT = "VERIFICATION_NEEDS_IMPROVEMENT"

    # Repair Lifecycle
    REPAIR_STARTED = "REPAIR_STARTED"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"
    REPAIR_FAILED = "REPAIR_FAILED"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"

    # Network Lifecycle
    NETWORK_CONNECTING = "NETWORK_CONNECTING"
    NETWORK_CONNECTED = "NETWORK_CONNECTED"
    NETWORK_DEGRADED = "NETWORK_DEGRADED"
    NETWORK_DISCONNECTED = "NETWORK_DISCONNECTED"
    NETWORK_RECONNECTING = "NETWORK_RECONNECTING"
    NETWORK_RESTORED = "NETWORK_RESTORED"
    NETWORK_FAILED = "NETWORK_FAILED"

    # Permission Lifecycle
    PERMISSION_REQUESTED = "PERMISSION_REQUESTED"
    PERMISSION_APPROVED = "PERMISSION_APPROVED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PERMISSION_EXPIRED = "PERMISSION_EXPIRED"
    PERMISSION_CANCELLED = "PERMISSION_CANCELLED"

    # Session Lifecycle
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_PAUSED = "SESSION_PAUSED"
    SESSION_RESUMED = "SESSION_RESUMED"
    SESSION_DISCONNECTED = "SESSION_DISCONNECTED"
    SESSION_CLOSED = "SESSION_CLOSED"

    # Evidence Lifecycle
    EVIDENCE_CREATED = "EVIDENCE_CREATED"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    EVIDENCE_INVALIDATED = "EVIDENCE_INVALIDATED"
    EVIDENCE_STALE = "EVIDENCE_STALE"

    # Checkpoint Lifecycle
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
    CHECKPOINT_AVAILABLE = "CHECKPOINT_AVAILABLE"
    CHECKPOINT_RESTORE_STARTED = "CHECKPOINT_RESTORE_STARTED"
    CHECKPOINT_RESTORED = "CHECKPOINT_RESTORED"
    CHECKPOINT_FAILED = "CHECKPOINT_FAILED"

    # KAIROS & Daemon
    KAIROS_STATE_CHANGED = "KAIROS_STATE_CHANGED"
    KAIROS_STUCK_DETECTED = "KAIROS_STUCK_DETECTED"
    KAIROS_REQUEUE_REQUESTED = "KAIROS_REQUEUE_REQUESTED"
    KAIROS_CONSOLIDATION_STARTED = "KAIROS_CONSOLIDATION_STARTED"
    KAIROS_CONSOLIDATION_COMPLETED = "KAIROS_CONSOLIDATION_COMPLETED"

    # Background Memory
    MEMORY_JOB_QUEUED = "MEMORY_JOB_QUEUED"
    MEMORY_JOB_STARTED = "MEMORY_JOB_STARTED"
    MEMORY_JOB_COMPLETED = "MEMORY_JOB_COMPLETED"
    MEMORY_JOB_FAILED = "MEMORY_JOB_FAILED"

    # System & Observability
    ERROR = "ERROR"
    WARNING = "WARNING"
    HEARTBEAT = "HEARTBEAT"
    STATE_SNAPSHOT = "STATE_SNAPSHOT"


class EventSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ── Canonical Event Envelope ─────────────────────────────────────────────────

@dataclass
class HermesEvent:
    """
    Canonical Event envelope for HERMES 2.x.
    Every event carries causal correlation identifiers, monotonic sequence numbers,
    and safe, redacted payloads.
    """
    event_type: EventType
    mission_id: str
    task_id: Optional[str] = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0
    source: str = "backend"
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    turn_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    verification_id: Optional[str] = None
    checkpoint_id: Optional[str] = None
    stage: str = "EXECUTION"
    payload: Dict[str, Any] = field(default_factory=dict)
    severity: EventSeverity = EventSeverity.INFO
    schema_version: int = 1

    def __post_init__(self):
        # Automatically redact secrets in payload upon event instantiation
        if self.payload:
            self.payload = redact_sensitive_payload(self.payload)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["severity"] = self.severity.value
        return d


# Type alias for clean imports
Event = HermesEvent
