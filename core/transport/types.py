# core/transport/types.py
"""
HERMES Phase 6: Typed Error Classification and Transport Definitions.
Provides structured taxonomy for provider, HTTP, transport, and streaming errors.
Ensures secret redaction and deterministic retry/fallback classification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ErrorCategory(str, Enum):
    # Non-retryable configuration & access errors
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    AUTHORIZATION_RESTRICTION = "AUTHORIZATION_RESTRICTION"
    BILLING_FAILURE = "BILLING_FAILURE"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"

    # Temporary rate-limiting (bounded retryable)
    RATE_LIMITED = "RATE_LIMITED"

    # Transient provider & server issues (retryable)
    PROVIDER_SERVER_ERROR = "PROVIDER_SERVER_ERROR"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"

    # Transport & connection level
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    CONNECTION_RESET = "CONNECTION_RESET"
    POOL_TIMEOUT = "POOL_TIMEOUT"
    WRITE_TIMEOUT = "WRITE_TIMEOUT"

    # Streaming & reading timeouts
    READ_IDLE_TIMEOUT = "READ_IDLE_TIMEOUT"
    OVERALL_DEADLINE_EXCEEDED = "OVERALL_DEADLINE_EXCEEDED"

    # Streaming integrity & protocol
    STREAM_INCOMPLETE = "STREAM_INCOMPLETE"
    STREAM_PROTOCOL_ERROR = "STREAM_PROTOCOL_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"

    # Circuit breaker & mission control
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    CANCELLED_BY_STOP = "CANCELLED_BY_STOP"
    CANCELLED_BY_SHUTDOWN = "CANCELLED_BY_SHUTDOWN"

    # Ambiguous outcome (e.g. timeout after write or midstream drop)
    AMBIGUOUS_OUTCOME = "AMBIGUOUS_OUTCOME"

    # Generic
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class StructuredTransportError(Exception):
    """
    Authoritative structured representation of all model transport errors in HERMES.
    Carries classification, retry eligibility, fallback eligibility, and sanitized detail.
    """
    category: ErrorCategory
    message: str
    provider: str
    model: str
    status_code: Optional[int] = None
    retryable: bool = False
    fallback_eligible: bool = False
    retry_after: Optional[float] = None
    attempt: int = 1
    max_attempts: int = 3
    is_ambiguous: bool = False
    mission_id: Optional[str] = None
    run_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.sanitized_message)

    @property
    def sanitized_message(self) -> str:
        """Ensure no API keys, bearer tokens, or secrets leak through the message string."""
        return sanitize_error_text(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "message": self.sanitized_message,
            "provider": self.provider,
            "model": self.model,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "fallback_eligible": self.fallback_eligible,
            "retry_after": self.retry_after,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "is_ambiguous": self.is_ambiguous,
            "mission_id": self.mission_id,
            "run_id": self.run_id,
            "details": {k: (sanitize_error_text(str(v)) if isinstance(v, str) else v) for k, v in self.details.items()},
        }


def sanitize_error_text(text: str) -> str:
    """Redact API keys, tokens, authorization headers, and secrets from text."""
    if not text:
        return ""
    # Redact Bearer tokens
    text = re.sub(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{8,}', 'Bearer [REDACTED]', text)
    # Redact nvapi- / sk- / ollama keys
    text = re.sub(r'(?i)(nvapi-[a-zA-Z0-9_\-]{16,})', '[REDACTED_API_KEY]', text)
    text = re.sub(r'(?i)(sk-[a-zA-Z0-9_\-]{16,})', '[REDACTED_API_KEY]', text)
    # Redact key query params or json fields
    text = re.sub(r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)[a-zA-Z0-9_\-\.]{8,}', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(authorization["\']?\s*[:=]\s*["\']?)[^"\'\r\n]{8,}', r'\1[REDACTED]', text)
    return text


def classify_http_status(
    status_code: int,
    body_text: str = "",
    provider: str = "",
    model: str = "",
    is_streaming: bool = False,
    stream_started: bool = False,
) -> StructuredTransportError:
    """
    Authoritatively classify HTTP status codes and response bodies into ErrorCategory.
    Distinguishes temporary rate limiting (429) from quota exhaustion / billing issues.
    """
    clean_body = sanitize_error_text(body_text.lower())
    
    # 1. HTTP 401 Unauthorized
    if status_code == 401:
        return StructuredTransportError(
            category=ErrorCategory.AUTHENTICATION_FAILURE,
            message="Invalid or missing API credentials.",
            provider=provider,
            model=model,
            status_code=401,
            retryable=False,
            fallback_eligible=False,
        )

    # 2. HTTP 403 Forbidden
    if status_code == 403:
        if "billing" in clean_body or "credit" in clean_body or "balance" in clean_body:
            return StructuredTransportError(
                category=ErrorCategory.BILLING_FAILURE,
                message="Provider account billing restriction or insufficient balance.",
                provider=provider,
                model=model,
                status_code=403,
                retryable=False,
                fallback_eligible=True,
            )
        return StructuredTransportError(
            category=ErrorCategory.AUTHORIZATION_RESTRICTION,
            message="Access denied or forbidden by provider permissions.",
            provider=provider,
            model=model,
            status_code=403,
            retryable=False,
            fallback_eligible=False,
        )

    # 3. HTTP 429 Too Many Requests
    if status_code == 429:
        if any(w in clean_body for w in ("quota", "insufficient_quota", "credit", "billing", "exceeded your current quota")):
            return StructuredTransportError(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message="Hard quota or account credit exhausted.",
                provider=provider,
                model=model,
                status_code=429,
                retryable=False,
                fallback_eligible=True,
            )
        # Parse Retry-After if available in body or caller
        return StructuredTransportError(
            category=ErrorCategory.RATE_LIMITED,
            message="Provider rate limit encountered.",
            provider=provider,
            model=model,
            status_code=429,
            retryable=True,
            fallback_eligible=True,
        )

    # 4. HTTP 400 Bad Request / 404 Not Found / 422 Unprocessable
    if status_code == 404 and "model" in clean_body:
        return StructuredTransportError(
            category=ErrorCategory.UNSUPPORTED_MODEL,
            message=f"Model '{model}' not found or unsupported by provider.",
            provider=provider,
            model=model,
            status_code=404,
            retryable=False,
            fallback_eligible=True,
        )

    if status_code in (400, 422):
        if "model" in clean_body and ("unsupported" in clean_body or "not found" in clean_body or "invalid model" in clean_body):
            return StructuredTransportError(
                category=ErrorCategory.UNSUPPORTED_MODEL,
                message=f"Model '{model}' unsupported or invalid.",
                provider=provider,
                model=model,
                status_code=status_code,
                retryable=False,
                fallback_eligible=True,
            )
        return StructuredTransportError(
            category=ErrorCategory.INVALID_REQUEST,
            message=f"Invalid request parameters or payload (HTTP {status_code}).",
            provider=provider,
            model=model,
            status_code=status_code,
            retryable=False,
            fallback_eligible=False,
        )

    # 5. HTTP 5xx Server Errors
    if status_code in (500, 502, 503, 504):
        cat = ErrorCategory.PROVIDER_UNAVAILABLE if status_code in (502, 503) else ErrorCategory.PROVIDER_SERVER_ERROR
        # If stream already started and then server drops with 5xx, marked ambiguous
        is_ambig = stream_started
        return StructuredTransportError(
            category=cat,
            message=f"Provider server failure (HTTP {status_code}).",
            provider=provider,
            model=model,
            status_code=status_code,
            retryable=True,
            fallback_eligible=True,
            is_ambiguous=is_ambig,
        )

    return StructuredTransportError(
        category=ErrorCategory.UNKNOWN_ERROR,
        message=f"HTTP status {status_code}: {clean_body[:150]}",
        provider=provider,
        model=model,
        status_code=status_code,
        retryable=False,
        fallback_eligible=False,
    )
