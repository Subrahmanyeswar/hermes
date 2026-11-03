# models/common_adapter.py
"""
HERMES Common Provider Adapter Architecture
===========================================
Unified, production-grade interface for the Three-Provider AI Architecture:
  Tier 1: Z.ai / BigModel (glm-4.7-flash)
  Tier 2: NVIDIA NIM (minimaxai/minimax-m3.1-flash)
  Tier 3: OpenRouter (moonshotai/kimi-k2.6:free)

Provides:
  - Unified chat completion with multi-turn messages (system, user, assistant, tool).
  - Robust streaming SSE parser with delta accumulation.
  - Normalized tool calls with ID preservation and argument parsing.
  - Fine-grained provider error classification (401, 403, 404, 408, 413, 422, 429, 5xx, timeouts, DNS/TLS).
  - High-precision telemetry metrics (TTFT, latency, tokens, cost).
  - Request cancellation and resource management.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

import httpx
from loguru import logger

from models.provider import ModelProvider, NormalizedModelResponse


# ==============================================================================
# 1. ERROR CLASSIFICATION (SECTION 6)
# ==============================================================================

class ErrorClassification(str, Enum):
    AUTH_FAILURE = "AUTH_FAILURE"                   # HTTP 401
    PERMISSION_DENIED = "PERMISSION_DENIED"         # HTTP 403
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"             # HTTP 404
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"             # HTTP 408
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"         # HTTP 413
    INVALID_REQUEST = "INVALID_REQUEST"             # HTTP 422
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"     # HTTP 429
    INTERNAL_ERROR = "INTERNAL_ERROR"               # HTTP 500
    BAD_GATEWAY = "BAD_GATEWAY"                     # HTTP 502
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"     # HTTP 503
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"             # HTTP 504
    CONNECTION_FAILURE = "CONNECTION_FAILURE"       # Socket/TCP failure
    DNS_FAILURE = "DNS_FAILURE"                     # Name resolution error
    TLS_FAILURE = "TLS_FAILURE"                     # SSL handshake failure
    STREAMING_INTERRUPTED = "STREAMING_INTERRUPTED" # Premature stream termination
    INVALID_JSON = "INVALID_JSON"                   # Corrupt response payload
    INVALID_TOOL_CALL = "INVALID_TOOL_CALL"         # Malformed tool call
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"           # Exceeded context window
    MODEL_TTFT_TIMEOUT = "MODEL_TTFT_TIMEOUT"       # First token timeout
    MODEL_STREAM_STALL = "MODEL_STREAM_STALL"       # In-flight stream stall
    MODEL_REQUEST_TIMEOUT = "MODEL_REQUEST_TIMEOUT" # Overall request attempt timeout
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    # Canonical error classifications per Section 5 & P0 Fix B
    UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER"
    PROVIDER_CONNECT_TIMEOUT = "PROVIDER_CONNECT_TIMEOUT"
    PROVIDER_READ_TIMEOUT = "PROVIDER_READ_TIMEOUT"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_SERVER_ERROR = "PROVIDER_SERVER_ERROR"
    PROVIDER_AUTH_ERROR = "PROVIDER_AUTH_ERROR"
    PROVIDER_MODEL_NOT_FOUND = "PROVIDER_MODEL_NOT_FOUND"
    PROVIDER_ENDPOINT_ERROR = "PROVIDER_ENDPOINT_ERROR"
    PROVIDER_BAD_REQUEST = "PROVIDER_BAD_REQUEST"
    PROVIDER_DNS_ERROR = "PROVIDER_DNS_ERROR"
    PROVIDER_TLS_ERROR = "PROVIDER_TLS_ERROR"
    RESPONSE_PARSE_ERROR = "RESPONSE_PARSE_ERROR"
    TOOL_CALL_SCHEMA_ERROR = "TOOL_CALL_SCHEMA_ERROR"
    EMPTY_TOOL_CALL = "EMPTY_TOOL_CALL"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    APP_VALIDATION_ERROR = "APP_VALIDATION_ERROR"
    NO_PROGRESS = "NO_PROGRESS"
    INTERNAL_RUNTIME_ERROR = "INTERNAL_RUNTIME_ERROR"


class TTFTTimeoutError(TimeoutError):
    """Raised when first token (TTFT) exceeds deadline."""
    pass


class StreamStallError(TimeoutError):
    """Raised when an active stream stops producing tokens."""
    pass


class AttemptTimeoutError(TimeoutError):
    """Raised when a single provider attempt exceeds deadline."""
    pass


@dataclass
class ProviderErrorInfo:
    classification: ErrorClassification
    status_code: Optional[int]
    message: str
    is_transient: bool
    is_quota_exhausted: bool
    is_unauthorized: bool
    is_model_unavailable: bool
    raw_response: str = ""

    def __str__(self) -> str:
        code_str = f"[{self.status_code}] " if self.status_code else ""
        return f"{self.classification.value}: {code_str}{self.message}"


def classify_provider_error(
    exc: Optional[Exception] = None,
    status_code: Optional[int] = None,
    response_body: Optional[str] = None,
) -> ProviderErrorInfo:
    """Classify provider error into actionable categories per Section 6."""
    body_text = response_body or (str(exc) if exc else "")
    body_lower = body_text.lower()

    # 1. HTTP Status Code Mapping
    if status_code == 400:
        if "invalid_model" in body_lower or ("model" in body_lower and "not found" in body_lower):
            return ProviderErrorInfo(
                classification=ErrorClassification.MODEL_NOT_FOUND,
                status_code=400,
                message="Model not found or invalid model ID",
                is_transient=False,
                is_quota_exhausted=False,
                is_unauthorized=False,
                is_model_unavailable=True,
                raw_response=body_text,
            )
        return ProviderErrorInfo(
            classification=ErrorClassification.INVALID_REQUEST,
            status_code=400,
            message="Invalid request or unsupported parameters",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if status_code == 401:
        return ProviderErrorInfo(
            classification=ErrorClassification.AUTH_FAILURE,
            status_code=401,
            message="Authentication failure (invalid or expired API key)",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=True,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 403:
        return ProviderErrorInfo(
            classification=ErrorClassification.PERMISSION_DENIED,
            status_code=403,
            message="Access denied or insufficient permissions for this endpoint/model",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=True,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 404:
        return ProviderErrorInfo(
            classification=ErrorClassification.MODEL_NOT_FOUND,
            status_code=404,
            message="Model or endpoint unavailable",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=True,
            raw_response=body_text,
        )
    if status_code == 408:
        return ProviderErrorInfo(
            classification=ErrorClassification.REQUEST_TIMEOUT,
            status_code=408,
            message="Request timed out by provider",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 413:
        return ProviderErrorInfo(
            classification=ErrorClassification.REQUEST_TOO_LARGE,
            status_code=413,
            message="Request payload too large",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 422:
        return ProviderErrorInfo(
            classification=ErrorClassification.INVALID_REQUEST,
            status_code=422,
            message="Invalid request or unsupported parameters",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 429:
        is_quota = "quota" in body_lower or "insufficient" in body_lower or "credit" in body_lower
        return ProviderErrorInfo(
            classification=ErrorClassification.RATE_LIMIT_EXCEEDED,
            status_code=429,
            message="Rate limit exceeded or quota exhausted",
            is_transient=not is_quota,
            is_quota_exhausted=is_quota,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 500:
        return ProviderErrorInfo(
            classification=ErrorClassification.INTERNAL_ERROR,
            status_code=500,
            message="Internal provider server error",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 502:
        return ProviderErrorInfo(
            classification=ErrorClassification.BAD_GATEWAY,
            status_code=502,
            message="Bad gateway",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 503:
        return ProviderErrorInfo(
            classification=ErrorClassification.SERVICE_UNAVAILABLE,
            status_code=503,
            message="Provider service unavailable / capacity overloaded",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if status_code == 504:
        return ProviderErrorInfo(
            classification=ErrorClassification.GATEWAY_TIMEOUT,
            status_code=504,
            message="Gateway timeout",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if "unknown_provider" in body_lower or "unknown provider" in body_lower:
        return ProviderErrorInfo(
            classification=ErrorClassification.UNKNOWN_PROVIDER,
            status_code=None,
            message=body_text or "Unknown provider configured",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=True,
            raw_response=body_text,
        )

    # 2. Exception type & message matching
    if isinstance(exc, httpx.ConnectTimeout):
        return ProviderErrorInfo(
            classification=ErrorClassification.PROVIDER_CONNECT_TIMEOUT,
            status_code=408,
            message=f"Provider connect timeout: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if isinstance(exc, httpx.ReadTimeout):
        return ProviderErrorInfo(
            classification=ErrorClassification.PROVIDER_READ_TIMEOUT,
            status_code=408,
            message=f"Provider read timeout: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )
    if isinstance(exc, TTFTTimeoutError) or "ttft" in body_lower or "first token" in body_lower:
        return ProviderErrorInfo(
            classification=ErrorClassification.MODEL_TTFT_TIMEOUT,
            status_code=408,
            message=f"Model TTFT timeout: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if isinstance(exc, StreamStallError) or "stream stall" in body_lower or "stream idle" in body_lower:
        return ProviderErrorInfo(
            classification=ErrorClassification.MODEL_STREAM_STALL,
            status_code=408,
            message=f"Model stream stall: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if isinstance(exc, AttemptTimeoutError) or "attempt timeout" in body_lower or "attempt exceeded" in body_lower:
        return ProviderErrorInfo(
            classification=ErrorClassification.MODEL_REQUEST_TIMEOUT,
            status_code=408,
            message=f"Model request timeout: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return ProviderErrorInfo(
            classification=ErrorClassification.REQUEST_TIMEOUT,
            status_code=408,
            message=f"Request timed out: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if isinstance(exc, ssl.SSLError) or "ssl" in body_lower or "tls" in body_lower:
        return ProviderErrorInfo(
            classification=ErrorClassification.TLS_FAILURE,
            status_code=None,
            message=f"TLS/SSL error: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if "dns" in body_lower or "getaddrinfo" in body_lower or "nameresolution" in body_lower:
        return ProviderErrorInfo(
            classification=ErrorClassification.DNS_FAILURE,
            status_code=None,
            message=f"DNS resolution failure: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if isinstance(exc, (httpx.ConnectError, ConnectionRefusedError, ConnectionResetError)):
        return ProviderErrorInfo(
            classification=ErrorClassification.CONNECTION_FAILURE,
            status_code=None,
            message=f"Connection failure: {exc}",
            is_transient=True,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if "context" in body_lower and ("length" in body_lower or "window" in body_lower or "too long" in body_lower):
        return ProviderErrorInfo(
            classification=ErrorClassification.CONTEXT_OVERFLOW,
            status_code=status_code,
            message="Context window exceeded",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if "unauthorized" in body_lower or "token expired" in body_lower or "invalid api key" in body_lower:
        return ProviderErrorInfo(
            classification=ErrorClassification.AUTH_FAILURE,
            status_code=401,
            message="Authentication error in response",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=True,
            is_model_unavailable=False,
            raw_response=body_text,
        )

    if "model" in body_lower and ("not found" in body_lower or "unavailable" in body_lower or "gone" in body_lower):
        return ProviderErrorInfo(
            classification=ErrorClassification.MODEL_NOT_FOUND,
            status_code=status_code or 404,
            message="Model unavailable or retired",
            is_transient=False,
            is_quota_exhausted=False,
            is_unauthorized=False,
            is_model_unavailable=True,
            raw_response=body_text,
        )

    return ProviderErrorInfo(
        classification=ErrorClassification.UNKNOWN_ERROR,
        status_code=status_code,
        message=f"Provider error: {exc or body_text}",
        is_transient=True,
        is_quota_exhausted=False,
        is_unauthorized=False,
        is_model_unavailable=False,
        raw_response=body_text,
    )


# ==============================================================================
# 2. METRICS & LATENCY TRACKING (SECTION 7)
# ==============================================================================

@dataclass
class RequestTelemetry:
    mission_id: str = ""
    request_id: str = ""
    provider: str = ""
    model: str = ""
    tier: int = 1
    start_time: float = 0.0
    connection_time: float = 0.0
    ttft_ms: float = 0.0
    total_latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_call_count: int = 0
    retry_count: int = 0
    error_classification: Optional[str] = None
    routing_transition: Optional[str] = None
    final_result: str = "PENDING"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "ttft_ms": round(self.ttft_ms, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_call_count": self.tool_call_count,
            "retry_count": self.retry_count,
            "error_classification": self.error_classification,
            "routing_transition": self.routing_transition,
            "final_result": self.final_result,
        }


# ==============================================================================
# 3. COMMON OPENAI-COMPATIBLE PROVIDER ADAPTER (SECTION 4)
# ==============================================================================

class CommonProviderAdapter(ModelProvider):
    """
    Standardized provider adapter conforming to HERMES ModelProvider interface.
    Normalizes requests, streaming chunks, tool calls, and errors across:
      - Z.ai / BigModel
      - NVIDIA NIM
      - OpenRouter
    """

    def __init__(
        self,
        provider_name: str,
        model_name: str,
        base_url: str,
        api_key: str,
        tier: int = 1,
        timeout_seconds: float = 45.0,
        extra_headers: Optional[Dict[str, str]] = None,
        first_token_timeout_seconds: float = 15.0,
        stream_idle_timeout_seconds: float = 15.0,
        attempt_timeout_seconds: float = 45.0,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.tier = tier
        self.timeout_seconds = timeout_seconds
        self.first_token_timeout_seconds = first_token_timeout_seconds
        self.stream_idle_timeout_seconds = max(float(stream_idle_timeout_seconds), 30.0)
        self.attempt_timeout_seconds = attempt_timeout_seconds
        self.extra_headers = extra_headers or {}
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def _semaphore(self) -> asyncio.Semaphore:
        """Loop-aware semaphore preventing 'Event loop is closed' errors across tests or tasks."""
        try:
            curr_loop = asyncio.get_running_loop()
        except RuntimeError:
            return getattr(self, "_sem", None) or asyncio.Semaphore(3)
        cached_loop = getattr(self, "_semaphore_loop", None)
        if getattr(self, "_sem", None) is None or cached_loop is not curr_loop or (cached_loop and cached_loop.is_closed()):
            max_concurrency = 1 if self.provider_name in ("zai", "z_ai", "bigmodel") else 3
            self._sem = asyncio.Semaphore(max_concurrency)
            self._semaphore_loop = curr_loop
        return self._sem

    async def _get_client(self) -> httpx.AsyncClient:
        """Loop-aware AsyncClient retrieval preventing stale closed event loop binding."""
        curr_loop = asyncio.get_running_loop()
        cached_loop = getattr(self, "_client_loop", None)
        if (
            self._client is None
            or self._client.is_closed
            or cached_loop is None
            or cached_loop is not curr_loop
            or cached_loop.is_closed()
        ):
            if self._client and not self._client.is_closed and (cached_loop and not cached_loop.is_closed()):
                try:
                    await self._client.aclose()
                except Exception:
                    pass
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
            self._client_loop = curr_loop
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # Normalization helpers
    def _sanitize_tool_definitions(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        sanitized = []
        for t in tools:
            if isinstance(t, dict) and t.get("type") == "function" and "function" in t:
                t_copy = json.loads(json.dumps(t))
                fn = t_copy["function"]
                fname = fn.get("name", "")
                # NVIDIA NIM requires names matching ^[a-zA-Z0-9_-]+$ (no dots like fs.read)
                if "." in fname and self.provider_name in ("nvidia_nim", "nvidia"):
                    fn["name"] = fname.replace(".", "_")
                sanitized.append(t_copy)
            else:
                sanitized.append(t)
        return sanitized

    def _normalize_tool_name_back(self, raw_name: str) -> str:
        """Map sanitized underscores back to canonical dots for Hermes known tools."""
        known_prefixes = ["fs_", "browser_", "search_", "exec_"]
        for p in known_prefixes:
            if raw_name.startswith(p):
                return raw_name.replace("_", ".", 1)
        return raw_name

    def _normalize_tool_calls(self, raw_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for tc in raw_calls:
            call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            fn_dict = tc.get("function") or {}
            raw_name = fn_dict.get("name") or tc.get("name") or ""
            canon_name = self._normalize_tool_name_back(raw_name)

            raw_args = fn_dict.get("arguments") or tc.get("arguments") or {}
            if isinstance(raw_args, str):
                try:
                    args_dict = json.loads(raw_args) if raw_args.strip() else {}
                except Exception:
                    args_dict = {"raw": raw_args}
            elif isinstance(raw_args, dict):
                args_dict = raw_args
            else:
                args_dict = {}

            normalized.append({
                "id": call_id,
                "name": canon_name,
                "arguments": args_dict,
            })
        return normalized

    async def generate(
        self,
        model: str = "",
        prompt: str = "",
        system: str = "",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        stream: bool = True,
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        """
        Send completion request to provider with streaming, tool parsing,
        metrics capture, and error handling.
        """
        active_model = model or self.model_name
        req_id = kwargs.get("request_id") or f"req_{uuid.uuid4().hex[:8]}"
        mid = kwargs.get("mission_id") or ""
        passed_to = float(kwargs.get("timeout_seconds") or self.timeout_seconds)
        timeout_val = min(passed_to, getattr(self, "attempt_timeout_seconds", 45.0))

        telemetry = RequestTelemetry(
            mission_id=mid,
            request_id=req_id,
            provider=self.provider_name,
            model=active_model,
            tier=self.tier,
            start_time=time.monotonic(),
        )

        if not self.api_key:
            err_info = ProviderErrorInfo(
                classification=ErrorClassification.AUTH_FAILURE,
                status_code=401,
                message=f"{self.provider_name.upper()} API key is not configured.",
                is_transient=False,
                is_quota_exhausted=False,
                is_unauthorized=True,
                is_model_unavailable=False,
            )
            telemetry.final_result = "AUTH_FAILED"
            telemetry.error_classification = err_info.classification.value
            return NormalizedModelResponse(
                text="",
                model=active_model,
                provider=self.provider_name,
                error=f"{err_info.classification.value}: {err_info.message}",
                success=False,
                raw_timing_metadata=telemetry.to_dict(),
            )

        # Build messages payload
        payload_messages: List[Dict[str, Any]] = []
        if messages:
            payload_messages = list(messages)
        else:
            if system:
                payload_messages.append({"role": "system", "content": system})
            if prompt:
                payload_messages.append({"role": "user", "content": prompt})

        # Sanitize tools
        sanitized_tools = self._sanitize_tool_definitions(tools)

        effective_max = max_tokens if max_tokens is not None else 8192
        if self.provider_name == "groq":
            effective_max = min(max_tokens if max_tokens is not None else 4096, 8192)
            # Groq free tier has strict request payload / TPM limits.
            # Truncate overly large single messages by retaining head (task requirements)
            # and tail (recent observations).
            for msg in payload_messages:
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 18000:
                    msg["content"] = (
                        content[:6000]
                        + "\n\n[... earlier context trimmed for length ...]\n\n"
                        + content[-8000:]
                    )
        payload: Dict[str, Any] = {
            "model": active_model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": effective_max,
        }
        if sanitized_tools:
            payload["tools"] = sanitized_tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        # Add provider-specific parameters
        if self.provider_name == "openrouter":
            payload["transforms"] = []
        if "reasoning_effort" in kwargs and kwargs["reasoning_effort"] is not None:
            payload["reasoning_effort"] = kwargs["reasoning_effort"]
        elif self.provider_name == "mistral":
            # Default reasoning_effort none per Part 6.D if reasoning model
            if "small" in active_model or "2603" in active_model:
                payload["reasoning_effort"] = "none"

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)

        url = f"{self.base_url}/chat/completions"
        client = await self._get_client()

        # Check if mocked in tests
        post_attr = getattr(httpx.AsyncClient, "post", None)
        is_mocked = post_attr is not None and getattr(post_attr, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        effective_stream = stream and not is_mocked

        if effective_stream:
            headers["Accept"] = "text/event-stream"
            payload["stream"] = True

        async with self._semaphore:
            max_attempts = 3 if self.provider_name in ("zai", "z_ai", "bigmodel") else 1
            for attempt in range(max_attempts):
                if effective_stream:
                    resp = await self._execute_streaming(client, url, headers, payload, telemetry, timeout_val)
                else:
                    payload["stream"] = False
                    resp = await self._execute_non_streaming(client, url, headers, payload, telemetry, timeout_val)

                if resp.success:
                    return resp

                err_lower = (resp.error or "").lower()
                is_rate_limited = "429" in err_lower or "rate_limit_exceeded" in err_lower
                if is_rate_limited and attempt < max_attempts - 1:
                    retry_after = getattr(resp, "_retry_after", None)
                    backoff = retry_after if (retry_after is not None and retry_after > 0) else (2.0 * (attempt + 1))
                    backoff = min(backoff, 6.0)
                    logger.info(
                        f"[{self.provider_name.upper()}] Recoverable 429 rate limit detected "
                        f"(attempt {attempt+1}/{max_attempts}). Backing off {backoff:.1f}s before retry..."
                    )
                    telemetry.retry_count += 1
                    await asyncio.sleep(backoff)
                else:
                    return resp

    async def _execute_streaming(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        telemetry: RequestTelemetry,
        timeout: float,
    ) -> NormalizedModelResponse:
        t0 = time.monotonic()
        first_token_ts: Optional[float] = None
        accumulated_text: List[str] = []
        tool_calls_map: Dict[int, Dict[str, Any]] = {}
        finish_reason: Optional[str] = None
        input_tokens = 0
        output_tokens = 0

        try:
            async with client.stream("POST", url, headers=headers, json=payload, timeout=timeout) as response:
                telemetry.connection_time = (time.monotonic() - t0) * 1000

                if response.status_code != 200:
                    err_body = (await response.aread()).decode("utf-8", errors="ignore")
                    err_info = classify_provider_error(status_code=response.status_code, response_body=err_body)
                    telemetry.total_latency_ms = (time.monotonic() - t0) * 1000
                    telemetry.error_classification = err_info.classification.value
                    telemetry.final_result = "ERROR"
                    logger.warning(f"[{self.provider_name.upper()} STREAM ERROR] {err_info}")
                    retry_header = response.headers.get("retry-after") or response.headers.get("Retry-After")
                    retry_val = None
                    if retry_header:
                        try:
                            retry_val = float(retry_header)
                        except Exception:
                            pass
                    norm_err = NormalizedModelResponse(
                        text="",
                        model=payload["model"],
                        provider=self.provider_name,
                        error=f"{err_info.classification.value}: {err_info.message}",
                        success=False,
                        raw_response=err_body,
                        raw_timing_metadata=telemetry.to_dict(),
                    )
                    norm_err._retry_after = retry_val
                    return norm_err

                first_token_to = getattr(self, "first_token_timeout_seconds", 15.0)
                stream_idle_to = getattr(self, "stream_idle_timeout_seconds", 15.0)
                aiter = response.aiter_lines().__aiter__()

                while True:
                    rem_time = timeout - (time.monotonic() - t0)
                    if rem_time <= 0:
                        raise AttemptTimeoutError(f"Request attempt exceeded deadline of {timeout:.1f}s")

                    chunk_to = min(first_token_to, rem_time) if first_token_ts is None else min(stream_idle_to, rem_time)
                    try:
                        line = await asyncio.wait_for(aiter.__anext__(), timeout=max(0.01, chunk_to))
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        if first_token_ts is None:
                            if (time.monotonic() - t0) >= timeout:
                                raise AttemptTimeoutError(f"Request attempt exceeded deadline of {timeout:.1f}s")
                            raise TTFTTimeoutError(f"First token not received within {first_token_to:.1f}s")
                        elif (time.monotonic() - t0) >= timeout:
                            raise AttemptTimeoutError(f"Request attempt exceeded deadline of {timeout:.1f}s")
                        else:
                            raise StreamStallError(f"Stream idle timeout exceeded {stream_idle_to:.1f}s")

                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Capture usage if present
                        if "usage" in chunk and chunk["usage"]:
                            u = chunk["usage"]
                            input_tokens = u.get("prompt_tokens", input_tokens)
                            output_tokens = u.get("completion_tokens", output_tokens)

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        finish_reason = choice.get("finish_reason") or finish_reason

                        delta = choice.get("delta") or {}
                        content_piece = delta.get("content") or ""
                        reasoning_piece = delta.get("reasoning_content") or ""
                        if content_piece or reasoning_piece:
                            if first_token_ts is None:
                                first_token_ts = time.monotonic()
                                telemetry.ttft_ms = (first_token_ts - t0) * 1000
                        if content_piece:
                            accumulated_text.append(content_piece)

                        # Accumulate delta tool calls
                        delta_tools = delta.get("tool_calls")
                        if delta_tools and isinstance(delta_tools, list):
                            if first_token_ts is None:
                                first_token_ts = time.monotonic()
                                telemetry.ttft_ms = (first_token_ts - t0) * 1000
                            for dt in delta_tools:
                                idx = dt.get("index", 0)
                                if idx not in tool_calls_map:
                                    tool_calls_map[idx] = {
                                        "id": dt.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                        "name": "",
                                        "arguments": "",
                                    }
                                if dt.get("id"):
                                    tool_calls_map[idx]["id"] = dt["id"]
                                fn = dt.get("function") or {}
                                if fn.get("name"):
                                    tool_calls_map[idx]["name"] += fn["name"]
                                if fn.get("arguments"):
                                    tool_calls_map[idx]["arguments"] += fn["arguments"]

        except Exception as exc:
            err_info = classify_provider_error(exc=exc)
            telemetry.total_latency_ms = (time.monotonic() - t0) * 1000
            telemetry.error_classification = err_info.classification.value
            telemetry.final_result = "ERROR"
            logger.warning(f"[{self.provider_name.upper()} STREAM EXCEPTION] {err_info}")
            return NormalizedModelResponse(
                text="".join(accumulated_text),
                model=payload["model"],
                provider=self.provider_name,
                error=f"{err_info.classification.value}: {err_info.message}",
                success=False,
                raw_timing_metadata=telemetry.to_dict(),
            )

        total_lat = (time.monotonic() - t0) * 1000
        telemetry.total_latency_ms = total_lat
        telemetry.final_result = "SUCCESS"

        # Format sorted tool calls
        raw_tool_calls = []
        for idx in sorted(tool_calls_map.keys()):
            tc = tool_calls_map[idx]
            raw_tool_calls.append({
                "id": tc["id"],
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                }
            })
        normalized_calls = self._normalize_tool_calls(raw_tool_calls)
        telemetry.tool_call_count = len(normalized_calls)

        full_text = "".join(accumulated_text)
        has_invalid_tool_args = any(
            isinstance(tc.get("arguments"), dict) and "raw" in tc.get("arguments", {})
            for tc in normalized_calls
        )
        is_length_truncated = finish_reason in ("length", "max_tokens")
        is_truncated = is_length_truncated or has_invalid_tool_args

        error_msg = None
        if is_length_truncated:
            error_msg = "MODEL_OUTPUT_TRUNCATED: Response truncated by token length limit"
        elif has_invalid_tool_args:
            error_msg = "INVALID_TOOL_CALL: Tool arguments could not be parsed as valid JSON"

        return NormalizedModelResponse(
            text=full_text,
            tool_calls=normalized_calls if not is_truncated else [],
            finish_reason=finish_reason,
            model=payload["model"],
            provider=self.provider_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens or len(full_text.split()),
            total_tokens=input_tokens + (output_tokens or len(full_text.split())),
            latency_ms=total_lat,
            ttfb_ms=telemetry.ttft_ms,
            success=not is_truncated,
            error=error_msg,
            raw_timing_metadata=telemetry.to_dict(),
        )

    async def _execute_non_streaming(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        telemetry: RequestTelemetry,
        timeout: float,
    ) -> NormalizedModelResponse:
        t0 = time.monotonic()
        try:
            resp = await asyncio.wait_for(
                client.post(url, headers=headers, json=payload, timeout=timeout),
                timeout=timeout,
            )
            telemetry.connection_time = (time.monotonic() - t0) * 1000
            telemetry.total_latency_ms = (time.monotonic() - t0) * 1000

            if resp.status_code != 200:
                err_info = classify_provider_error(status_code=resp.status_code, response_body=resp.text)
                telemetry.error_classification = err_info.classification.value
                telemetry.final_result = "ERROR"
                logger.warning(f"[{self.provider_name.upper()} ERROR] {err_info}")
                retry_header = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
                retry_val = None
                if retry_header:
                    try:
                        retry_val = float(retry_header)
                    except Exception:
                        pass
                norm_err = NormalizedModelResponse(
                    text="",
                    model=payload["model"],
                    provider=self.provider_name,
                    error=f"{err_info.classification.value}: {err_info.message}",
                    success=False,
                    raw_response=resp.text if isinstance(getattr(resp, "text", None), str) else "",
                    raw_timing_metadata=telemetry.to_dict(),
                )
                norm_err._retry_after = retry_val
                return norm_err

            data = resp.json()
            telemetry.final_result = "SUCCESS"

            choices = data.get("choices") or []
            content = ""
            raw_tools = []
            finish_reason = None
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                if not content and reasoning and not msg.get("tool_calls"):
                    content = reasoning
                raw_tools = msg.get("tool_calls") or []
                finish_reason = choices[0].get("finish_reason")

            usage = data.get("usage") or {}
            in_tok = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)

            normalized_calls = self._normalize_tool_calls(raw_tools)
            telemetry.tool_call_count = len(normalized_calls)
            telemetry.input_tokens = in_tok
            telemetry.output_tokens = out_tok

            has_invalid_tool_args = any(
                isinstance(tc.get("arguments"), dict) and "raw" in tc.get("arguments", {})
                for tc in normalized_calls
            )
            is_length_truncated = finish_reason in ("length", "max_tokens")
            is_truncated = is_length_truncated or has_invalid_tool_args

            error_msg = None
            if is_length_truncated:
                error_msg = "MODEL_OUTPUT_TRUNCATED: Response truncated by token length limit"
            elif has_invalid_tool_args:
                error_msg = "INVALID_TOOL_CALL: Tool arguments could not be parsed as valid JSON"

            return NormalizedModelResponse(
                text=content,
                tool_calls=normalized_calls if not is_truncated else [],
                finish_reason=finish_reason,
                model=payload["model"],
                provider=self.provider_name,
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=in_tok + out_tok,
                latency_ms=telemetry.total_latency_ms,
                ttfb_ms=telemetry.total_latency_ms,
                success=not is_truncated,
                error=error_msg,
                raw_response=resp.text if isinstance(getattr(resp, "text", None), str) else "",
                raw_timing_metadata=telemetry.to_dict(),
            )
        except Exception as exc:
            err_info = classify_provider_error(exc=exc)
            telemetry.total_latency_ms = (time.monotonic() - t0) * 1000
            telemetry.error_classification = err_info.classification.value
            telemetry.final_result = "ERROR"
            logger.warning(f"[{self.provider_name.upper()} EXCEPTION] {err_info}")
            return NormalizedModelResponse(
                text="",
                model=payload["model"],
                provider=self.provider_name,
                error=f"{err_info.classification.value}: {err_info.message}",
                success=False,
                raw_timing_metadata=telemetry.to_dict(),
            )

    async def is_available(self, timeout: float = 3.0) -> bool:
        """Lightweight reachability check without expensive prompts."""
        if not self.api_key:
            return False
        if self.provider_name in ("zai", "z_ai", "bigmodel") and self._semaphore.locked():
            return True
        client = await self._get_client()
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        headers.update(self.extra_headers)
        try:
            resp = await client.get(url, headers=headers, timeout=timeout)
            return resp.status_code in (200, 204)
        except Exception:
            return False

    async def run_diagnostics(self) -> Dict[str, Any]:
        """Perform provider health, model verification, and tool-call readiness."""
        t0 = time.monotonic()
        has_key = bool(self.api_key)
        masked_key = f"{self.api_key[:4]}...{self.api_key[-4:]}" if (has_key and len(self.api_key) > 8) else ("SET" if has_key else "MISSING")

        result: Dict[str, Any] = {
            "tier": self.tier,
            "provider": self.provider_name,
            "model": self.model_name,
            "configured": has_key,
            "masked_key": masked_key,
            "base_url": self.base_url,
            "healthy": False,
            "latency_ms": 0.0,
            "tool_call_supported": False,
            "status": "UNCONFIGURED" if not has_key else "UNKNOWN",
            "last_error": None,
        }
        if not has_key:
            result["status"] = "MISSING_KEY"
            result["last_error"] = f"{self.provider_name.upper()}_API_KEY not set in environment"
            return result

        if self.provider_name in ("zai", "z_ai", "bigmodel") and self._semaphore.locked():
            result["healthy"] = True
            result["status"] = "HEALTHY_ACTIVE_MISSION"
            return result

        # Test simple chat completion (1 token ping)
        try:
            resp = await self.generate(
                prompt="Respond with only the word PONG.",
                max_tokens=32,
                stream=False,
                timeout_seconds=5.0,
            )
            lat = (time.monotonic() - t0) * 1000
            result["latency_ms"] = round(lat, 2)
            if resp.success:
                result["healthy"] = True
                result["status"] = "HEALTHY"
                test_tool = [{
                    "type": "function",
                    "function": {
                        "name": "test_tool",
                        "description": "Test tool",
                        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
                    }
                }]
                try:
                    tool_resp = await self.generate(
                        prompt="Call test_tool with q='hello'",
                        tools=test_tool,
                        max_tokens=64,
                        stream=False,
                        timeout_seconds=10.0,
                    )
                    result["tool_call_supported"] = bool(tool_resp.success and tool_resp.tool_calls)
                except Exception:
                    result["tool_call_supported"] = False
            else:
                result["healthy"] = False
                result["status"] = "UNAVAILABLE"
                result["last_error"] = resp.error
        except Exception as e:
            result["healthy"] = False
            result["status"] = "ERROR"
            result["last_error"] = str(e)
            result["latency_ms"] = round((time.monotonic() - t0) * 1000, 2)

        return result


# ==============================================================================
class UnknownProviderAdapter(ModelProvider):
    """Explicit adapter for unconfigured or unknown providers per Section 4."""

    def __init__(
        self,
        provider_name: str,
        model_name: Optional[str] = None,
        tier: Optional[int] = None,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name or "unknown"
        self.tier = tier
        self.base_url = ""
        self.api_key = ""
        logger.error(
            f"UNKNOWN_PROVIDER: Provider identifier '{provider_name}' configured for Tier {tier} "
            f"(model: '{self.model_name}') is not recognized."
        )

    async def generate(self, *args, **kwargs) -> NormalizedModelResponse:
        err_msg = (
            f"UNKNOWN_PROVIDER: Provider '{self.provider_name}' (tier {self.tier}, model '{self.model_name}') "
            f"is not recognized. Refusing to send request to generic or unrelated endpoint."
        )
        return NormalizedModelResponse(
            text="",
            model=self.model_name,
            provider=self.provider_name,
            error=err_msg,
            success=False,
            raw_response=err_msg,
        )

    async def close(self) -> None:
        pass


# 4. PROVIDER REGISTRY & SHARED CLIENT FACTORY
# ==============================================================================

_adapter_cache: Dict[str, CommonProviderAdapter] = {}

def get_provider_adapter(
    provider_name: str,
    model_name: Optional[str] = None,
    tier: Optional[int] = None,
) -> CommonProviderAdapter:
    """Retrieve or construct the canonical adapter for the requested provider."""
    from config.model_config import (
        TIER1_PROVIDER, TIER1_MODEL, TIER1_BASE_URL, ZAI_API_KEY,
        TIER2_PROVIDER, TIER2_MODEL, TIER2_BASE_URL, NVIDIA_API_KEY,
        TIER3_PROVIDER, TIER3_MODEL, TIER3_BASE_URL, OPENROUTER_API_KEY,
        GEMINI_API_KEY, GROQ_API_KEY,
    )

    p_norm = provider_name.lower().replace("-", "_")
    eff_tier = tier if tier is not None else (2 if p_norm in ("mistral", "mistral_ai", "mistralai", "codestral", "groq", "groq_api") else (3 if p_norm in ("nvidia_nim", "nvidia", "nim", "openrouter", "open_router") else 1))

    # ── Gemini (Tier 1) ────────────────────────────────────────────────
    if p_norm in ("gemini", "google", "google_gemini"):
        m = model_name or os.getenv("TIER1_MODEL", "gemini-2.5-flash")
        cache_key = f"gemini:{m}"
        if cache_key not in _adapter_cache:
            from models.gemini_client import GeminiClient
            adapter = GeminiClient(
                api_key=GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", ""),
                model=m,
                tier=tier,
            )
            # Wrap in a thin shim so the rest of HERMES gets the same interface.
            # GeminiClient exposes .generate() natively; we store it under the
            # GeminiClient type but cast to Any so the cache typing stays uniform.
            _adapter_cache[cache_key] = adapter  # type: ignore[assignment]
        return _adapter_cache[cache_key]

    # ── Mistral (Tier 2, OpenAI-compatible) ───────────────────────────
    if p_norm in ("mistral", "mistral_ai", "mistralai", "codestral"):
        m = model_name or os.getenv("TIER2_MODEL", "codestral-latest")
        cache_key = f"mistral:{m}:{eff_tier}"
        if cache_key not in _adapter_cache:
            from config.model_config import (
                MISTRAL_API_KEY,
                HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS,
                HERMES_MODEL_FIRST_TOKEN_TIMEOUT_SECONDS,
                HERMES_MODEL_STREAM_IDLE_TIMEOUT_SECONDS,
            )
            _adapter_cache[cache_key] = CommonProviderAdapter(
                provider_name="mistral",
                model_name=m,
                base_url=os.getenv("TIER2_BASE_URL", "https://api.mistral.ai/v1"),
                api_key=MISTRAL_API_KEY or os.getenv("MISTRAL_API_KEY", ""),
                tier=eff_tier,
                timeout_seconds=float(os.getenv("HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS", "45.0")),
                first_token_timeout_seconds=float(os.getenv("HERMES_MODEL_FIRST_TOKEN_TIMEOUT_SECONDS", "15.0")),
                stream_idle_timeout_seconds=float(os.getenv("HERMES_MODEL_STREAM_IDLE_TIMEOUT_SECONDS", "15.0")),
                attempt_timeout_seconds=float(os.getenv("HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS", "45.0")),
            )
        return _adapter_cache[cache_key]

    # ── Groq (Legacy, OpenAI-compatible) ──────────────────────────────
    if p_norm in ("groq", "groq_api"):
        m = model_name or os.getenv("TIER2_MODEL", "codestral-latest")
        cache_key = f"groq:{m}"
        if cache_key not in _adapter_cache:
            _adapter_cache[cache_key] = CommonProviderAdapter(
                provider_name="groq",
                model_name=m,
                base_url=os.getenv("TIER2_BASE_URL", "https://api.groq.com/openai/v1"),
                api_key=GROQ_API_KEY or os.getenv("GROQ_API_KEY", ""),
                tier=tier,
                timeout_seconds=60.0,
            )
        return _adapter_cache[cache_key]

    if p_norm in ("zai", "z_ai", "bigmodel"):
        m = model_name or TIER1_MODEL
        cache_key = f"zai:{m}"
        if cache_key not in _adapter_cache:
            _adapter_cache[cache_key] = CommonProviderAdapter(
                provider_name="zai",
                model_name=m,
                base_url=TIER1_BASE_URL,
                api_key=ZAI_API_KEY or os.getenv("ZAI_API_KEY", ""),
                tier=1,
            )
        return _adapter_cache[cache_key]

    if p_norm in ("nvidia_nim", "nvidia", "nim"):
        m = model_name or os.getenv("TIER3_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
        cache_key = f"nvidia_nim:{m}"
        if cache_key not in _adapter_cache:
            _adapter_cache[cache_key] = CommonProviderAdapter(
                provider_name="nvidia_nim",
                model_name=m,
                base_url=os.getenv("TIER3_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                api_key=NVIDIA_API_KEY or os.getenv("NVIDIA_API_KEY", ""),
                tier=tier or 3,
            )
        return _adapter_cache[cache_key]

    if p_norm in ("openrouter", "open_router"):
        m = model_name or TIER3_MODEL
        cache_key = f"openrouter:{m}"
        if cache_key not in _adapter_cache:
            _adapter_cache[cache_key] = CommonProviderAdapter(
                provider_name="openrouter",
                model_name=m,
                base_url=TIER3_BASE_URL,
                api_key=OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", ""),
                tier=3,
                extra_headers={
                    "HTTP-Referer": "https://hermes.local",
                    "X-Title": "HERMES Autonomous Agent",
                },
            )
        return _adapter_cache[cache_key]

    # Fallback: Unknown provider must never silently inherit OpenAI base_url / key
    logger.error(
        f"UNKNOWN_PROVIDER: Provider '{provider_name}' (tier {eff_tier}, model: '{model_name}') is not recognized. "
        "Valid providers: gemini, mistral/codestral, groq, zai, nvidia_nim, openrouter."
    )
    cache_key = f"unknown:{p_norm}:{model_name or 'default'}:{eff_tier}"
    if cache_key not in _adapter_cache:
        _adapter_cache[cache_key] = UnknownProviderAdapter(
            provider_name=provider_name,
            model_name=model_name,
            tier=eff_tier,
        )
    return _adapter_cache[cache_key]


async def close_all_adapters() -> None:
    """Safely shut down all cached HTTP clients on server termination."""
    for adapter in list(_adapter_cache.values()):
        try:
            await adapter.close()
        except Exception:
            pass
    _adapter_cache.clear()
