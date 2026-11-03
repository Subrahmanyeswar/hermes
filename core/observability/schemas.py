# core/observability/schemas.py
"""
Canonical Forensic Observability Schemas and Event Classifications for HERMES 2.x.
Ensures every operation is structured, traceable with correlation IDs, and safely redacted.
"""

from __future__ import annotations

import datetime
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Any, Optional, List


class TelemetrySeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class FailureClassification(str, Enum):
    PROVIDER_NETWORK_ERROR = "PROVIDER_NETWORK_ERROR"
    PROVIDER_TRANSIENT_ERROR = "PROVIDER_TRANSIENT_ERROR"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_AUTH_CONFIG_ERROR = "PROVIDER_AUTH_CONFIG_ERROR"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_TTFT_TIMEOUT = "MODEL_TTFT_TIMEOUT"
    MODEL_STREAM_STALL = "MODEL_STREAM_STALL"
    MODEL_OUTPUT_TRUNCATED = "MODEL_OUTPUT_TRUNCATED"
    MODEL_EMPTY_RESPONSE = "MODEL_EMPTY_RESPONSE"
    MODEL_MALFORMED_TOOL_OUTPUT = "MODEL_MALFORMED_TOOL_OUTPUT"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    APPLICATION_SYNTAX_ERROR = "APPLICATION_SYNTAX_ERROR"
    APPLICATION_RUNTIME_ERROR = "APPLICATION_RUNTIME_ERROR"
    HTML_ANALYSIS_ERROR = "HTML_ANALYSIS_ERROR"
    CSS_ANALYSIS_ERROR = "CSS_ANALYSIS_ERROR"
    ACCEPTANCE_VALIDATION_FAILED = "ACCEPTANCE_VALIDATION_FAILED"
    MISSING_REQUIRED_ARTIFACT = "MISSING_REQUIRED_ARTIFACT"
    NO_PROGRESS = "NO_PROGRESS"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INTERNAL_HERMES_EXCEPTION = "INTERNAL_HERMES_EXCEPTION"
    RUNTIME_FINGERPRINT_MISMATCH = "RUNTIME_FINGERPRINT_MISMATCH"


class TimingPhase(str, Enum):
    MODEL_QUEUE_WAIT = "MODEL_QUEUE_WAIT"
    MODEL_CONNECT = "MODEL_CONNECT"
    MODEL_TTFT = "MODEL_TTFT"
    MODEL_STREAM_PROGRESS = "MODEL_STREAM_PROGRESS"
    MODEL_RESPONSE_LATENCY = "MODEL_RESPONSE_LATENCY"
    MODEL_PARSE = "MODEL_PARSE"
    LOCAL_PROCESSING_LATENCY = "LOCAL_PROCESSING_LATENCY"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    RECOVERY_PROCESSING = "RECOVERY_PROCESSING"
    BROWSER_VERIFICATION = "BROWSER_VERIFICATION"


@dataclass
class CorrelationContext:
    run_id: str
    mission_id: str
    turn: Optional[int] = None
    event_seq: Optional[int] = None
    trace_id: str = field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:12]}")
    span_id: str = field(default_factory=lambda: f"sp_{uuid.uuid4().hex[:8]}")
    parent_span_id: Optional[str] = None


@dataclass
class ObservabilityEvent:
    event_type: str
    component: str
    severity: str
    message: str
    run_id: str
    mission_id: str
    timestamp_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    timestamp_local: str = field(
        default_factory=lambda: datetime.datetime.now().astimezone().isoformat()
    )
    monotonic_ns: int = field(default_factory=time.monotonic_ns)
    turn: Optional[int] = None
    event_seq: Optional[int] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    tier: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    duration_ms: Optional[float] = None
    status: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Prune None keys if desired, or keep standard schema
        return {k: v for k, v in d.items() if v is not None}
