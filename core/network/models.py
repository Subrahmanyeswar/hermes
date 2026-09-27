# core/network/models.py
"""
Data models, enums, classifications, and contracts for HERMES 2.x
Network and Provider Resilience layer.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class RequestPhase(str, Enum):
    CREATED = "CREATED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    STREAMING = "STREAMING"
    STALLING = "STALLING"
    RECONNECTING = "RECONNECTING"
    RECOVERED = "RECOVERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class FailureClassification(str, Enum):
    # Network / Transport failures
    DNS_ERROR = "DNS_ERROR"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    CONNECTION_RESET = "CONNECTION_RESET"
    TLS_ERROR = "TLS_ERROR"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    STREAM_STALL = "STREAM_STALL"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"

    # HTTP / Service failures
    HTTP_429 = "HTTP_429"  # Rate limit / Quota
    HTTP_5XX = "HTTP_5XX"  # Provider internal / Bad Gateway / Unavailable
    HTTP_4XX = "HTTP_4XX"  # Client Error (unauthorized, bad request, not found)
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    AUTH_FAILURE = "AUTH_FAILURE"
    INVALID_REQUEST = "INVALID_REQUEST"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"

    # Execution / Control failures
    CANCELLED = "CANCELLED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    UNKNOWN_NETWORK_ERROR = "UNKNOWN_NETWORK_ERROR"


RETRYABLE_FAILURES = {
    FailureClassification.CONNECT_TIMEOUT,
    FailureClassification.READ_TIMEOUT,
    FailureClassification.STREAM_STALL,
    FailureClassification.CONNECTION_RESET,
    FailureClassification.CONNECTION_REFUSED,
    FailureClassification.HTTP_5XX,
    FailureClassification.HTTP_429,
    FailureClassification.PROVIDER_UNAVAILABLE,
    FailureClassification.PROTOCOL_ERROR,
}

NON_RETRYABLE_FAILURES = {
    FailureClassification.AUTH_FAILURE,
    FailureClassification.INVALID_REQUEST,
    FailureClassification.MODEL_NOT_FOUND,
    FailureClassification.HTTP_4XX,
    FailureClassification.CANCELLED,
    FailureClassification.DEADLINE_EXCEEDED,
}


def is_retryable_failure(classification: FailureClassification) -> bool:
    """Return True if the failure classification is eligible for bounded retry."""
    return classification in RETRYABLE_FAILURES


class ProviderType(str, Enum):
    NVIDIA_NIM = "nvidia_nim"
    OLLAMA = "ollama"
    MOCK = "mock"
    CUSTOM = "custom"


@dataclass
class ProviderCapabilities:
    """Declared capabilities and behavior switches for a model provider."""
    provider_name: str
    streaming: bool = True
    non_streaming_fallback: bool = True
    server_health_check: bool = True
    cancellation_supported: bool = True
    resumable_stream: bool = False
    tool_call_streaming: bool = True
    keep_alive_param: bool = False
    requires_api_key: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StreamDelta:
    """A single incremental chunk received during streaming."""
    content: str = ""
    reasoning_content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw_chunk: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class RequestAttempt:
    """A physical HTTP / stream connection attempt under a logical request."""
    attempt_id: str = field(default_factory=lambda: f"att_{uuid.uuid4().hex[:8]}")
    attempt_index: int = 1
    started_at: float = field(default_factory=time.monotonic)
    ended_at: Optional[float] = None
    phase: RequestPhase = RequestPhase.CONNECTING
    is_streaming: bool = True
    bytes_received: int = 0
    deltas_received: int = 0
    first_delta_at: Optional[float] = None
    last_delta_at: Optional[float] = None
    time_to_first_delta: Optional[float] = None
    error: Optional[str] = None
    failure_classification: Optional[FailureClassification] = None

    def mark_first_delta(self) -> None:
        now = time.monotonic()
        self.first_delta_at = now
        self.time_to_first_delta = now - self.started_at
        self.last_delta_at = now
        self.phase = RequestPhase.STREAMING

    def record_delta(self, delta_bytes: int = 0) -> None:
        self.last_delta_at = time.monotonic()
        self.deltas_received += 1
        self.bytes_received += delta_bytes

    def complete(self) -> None:
        self.ended_at = time.monotonic()
        self.phase = RequestPhase.COMPLETED

    def fail(self, classification: FailureClassification, error_msg: str) -> None:
        self.ended_at = time.monotonic()
        self.phase = RequestPhase.FAILED
        self.failure_classification = classification
        self.error = error_msg

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["phase"] = self.phase.value
        d["failure_classification"] = self.failure_classification.value if self.failure_classification else None
        return d


@dataclass
class LogicalRequest:
    """
    A high-level model generation request spanning zero or more physical attempts.
    Preserves prompt context, accumulators, and executed tools across retries.
    """
    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    turn_id: Optional[str] = None
    mission_id: Optional[str] = None
    provider: str = ""
    model: str = ""
    prompt: str = ""
    system: str = ""
    temperature: float = 0.1
    max_tokens: Optional[int] = None
    total_timeout: float = 90.0
    created_at: float = field(default_factory=time.monotonic)
    completed_at: Optional[float] = None
    status: RequestPhase = RequestPhase.CREATED
    attempts: List[RequestAttempt] = field(default_factory=list)
    active_attempt_index: int = 0
    accumulated_content: str = ""
    accumulated_reasoning: str = ""
    accumulated_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[str] = None
    executed_tool_call_ids: List[str] = field(default_factory=list)
    final_error: Optional[str] = None
    failure_classification: Optional[FailureClassification] = None

    def start_new_attempt(self, is_streaming: bool = True) -> RequestAttempt:
        self.active_attempt_index += 1
        att = RequestAttempt(
            attempt_index=self.active_attempt_index,
            is_streaming=is_streaming,
        )
        self.attempts.append(att)
        self.status = RequestPhase.CONNECTING
        return att

    @property
    def current_attempt(self) -> Optional[RequestAttempt]:
        return self.attempts[-1] if self.attempts else None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            RequestPhase.COMPLETED,
            RequestPhase.FAILED,
            RequestPhase.TIMED_OUT,
            RequestPhase.CANCELLED,
            RequestPhase.ABORTED,
        )

    def mark_completed(self) -> None:
        if self.is_terminal:
            return  # Terminal lock: cannot reopen or alter terminal state
        self.completed_at = time.monotonic()
        self.status = RequestPhase.COMPLETED
        if self.current_attempt and self.current_attempt.phase != RequestPhase.COMPLETED:
            self.current_attempt.complete()

    def mark_failed(self, classification: FailureClassification, error_msg: str) -> None:
        if self.is_terminal:
            return  # Terminal lock: cannot alter terminal state
        self.completed_at = time.monotonic()
        self.status = RequestPhase.FAILED
        self.failure_classification = classification
        self.final_error = error_msg
        if self.current_attempt and self.current_attempt.phase not in (RequestPhase.COMPLETED, RequestPhase.FAILED):
            self.current_attempt.fail(classification, error_msg)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["failure_classification"] = self.failure_classification.value if self.failure_classification else None
        d["attempts"] = [a.to_dict() for a in self.attempts]
        return d


@dataclass
class DeadlineBudget:
    """
    Hierarchical deadlines ensuring no infinite wait and strict deadline containment:
    Mission Deadline >= Turn Deadline >= Logical Request Deadline >= Attempt Timeout.
    """
    connect_timeout: float = 10.0
    first_delta_timeout: float = 15.0
    idle_timeout: float = 15.0
    attempt_timeout: float = 45.0
    logical_request_timeout: float = 90.0
    turn_deadline_monotonic: Optional[float] = None
    mission_deadline_monotonic: Optional[float] = None
    start_time_monotonic: float = field(default_factory=time.monotonic)

    def remaining_budget(self, now: Optional[float] = None) -> float:
        """Return the maximum allowed time in seconds remaining for this request."""
        now = now if now is not None else time.monotonic()
        elapsed = now - self.start_time_monotonic
        remaining_logical = max(0.0, self.logical_request_timeout - elapsed)

        remaining_candidates = [remaining_logical]
        if self.turn_deadline_monotonic is not None:
            remaining_candidates.append(max(0.0, self.turn_deadline_monotonic - now))
        if self.mission_deadline_monotonic is not None:
            remaining_candidates.append(max(0.0, self.mission_deadline_monotonic - now))

        return min(remaining_candidates)

    def is_expired(self, now: Optional[float] = None) -> bool:
        return self.remaining_budget(now) <= 0.0

    def effective_attempt_timeout(self, now: Optional[float] = None) -> float:
        """Attempt timeout bounded by remaining logical/turn/mission budget."""
        remaining = self.remaining_budget(now)
        return min(self.attempt_timeout, remaining)
