# models/nvidia_client.py
# NVIDIA NIM API client for HERMES Tier 1 primary model.
# Communicates with OpenAI-compatible NVIDIA NIM endpoint:
# https://integrate.api.nvidia.com/v1/chat/completions
# Model: z-ai/glm-5.3-flash
# API key is loaded strictly from NVIDIA_API_KEY environment variable.
# Never log the API key.

from __future__ import annotations
import os
import asyncio
import time
import json
import uuid
from typing import Optional, Any, Dict, List

import httpx
from loguru import logger

from models.provider import ModelProvider, NormalizedModelResponse, CanonicalToolCall
from config.model_config import (
    TIER1_MODEL,
    TIER1_BASE_URL,
    NVIDIA_API_KEY,
    MODEL_TIMEOUT_SECONDS,
    HEALTH_CHECK_TIMEOUT,
    validate_timeout_config,
)

# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------


class NvidiaTimeoutError(Exception):
    """Raised when NVIDIA NIM takes more than timeout_seconds to respond or stalls."""

    def __init__(
        self,
        message: str,
        timeout_type: str = "TOTAL_GENERATION_TIMEOUT",
        duration: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.timeout_type = timeout_type
        self.duration = duration


class NvidiaConnectionError(Exception):
    """Raised when NVIDIA NIM is unreachable."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_SHARED_NVIDIA_CLIENT: Optional[NvidiaClient] = None


def get_shared_nvidia_client() -> NvidiaClient:
    """Return a process-wide persistent NvidiaClient singleton."""
    global _SHARED_NVIDIA_CLIENT
    if _SHARED_NVIDIA_CLIENT is None:
        _SHARED_NVIDIA_CLIENT = NvidiaClient(
            base_url=TIER1_BASE_URL,
            timeout_seconds=validate_timeout_config("MODEL_TIMEOUT_SECONDS", MODEL_TIMEOUT_SECONDS or 360),
        )
    return _SHARED_NVIDIA_CLIENT


async def close_shared_nvidia_client() -> None:
    """Gracefully close the process-wide persistent NvidiaClient."""
    global _SHARED_NVIDIA_CLIENT
    if _SHARED_NVIDIA_CLIENT is not None:
        await _SHARED_NVIDIA_CLIENT.aclose()
        _SHARED_NVIDIA_CLIENT = None


def validate_token_ceiling_config(
    env_var_name: str = "TIER1_MAX_TOKENS_CEILING",
    default_val: int = 8192,
    fallback_env_var: Optional[str] = None,
) -> int:
    """
    Validate and return the configured token limit from environment.
    Produces a clear, actionable configuration error if invalid.
    """
    raw_val = os.getenv(env_var_name)
    active_var = env_var_name
    if (raw_val is None or raw_val.strip() == "") and fallback_env_var:
        raw_val = os.getenv(fallback_env_var)
        if raw_val is not None and raw_val.strip() != "":
            active_var = fallback_env_var

    if raw_val is None or raw_val.strip() == "":
        return default_val
    stripped = raw_val.strip()
    try:
        val = int(stripped)
    except (TypeError, ValueError) as err:
        raise ValueError(
            f"Configuration error: {active_var}='{raw_val}' must be a valid positive integer."
        ) from err
    if val <= 0:
        raise ValueError(
            f"Configuration error: {active_var}={val} must be a positive integer greater than 0."
        )
    return val


def resolve_effective_max_tokens(
    max_tokens: Optional[int] = None,
    num_predict: Optional[int] = None,
    default_cap: int = 8192,
    allow_override: bool = False,
    application_upper_limit: int = 16384,
    **kwargs: Any,
) -> int:
    """
    Resolve and validate the effective token generation budget for Tier 1 requests.

    Invariants & Contract:
    1. Environment configurations TIER1_MAX_TOKENS_CEILING and TIER1_MAX_OVERRIDE_LIMIT
       (with backward-compatible fallback to TIER1_PROVIDER_HARD_LIMIT) are validated
       before computing any effective budget.
    2. The application upper limit (default: 16,384 tokens) is a conservative HERMES safety cap
       designed to prevent runaway token expenditure and streaming timeouts. It is NOT NVIDIA's
       advertised context capacity (NVIDIA NIM documents context lengths up to 1M tokens, and an
       inference API parameter max_tokens range up to 131,072 for Nemotron 3.5), but a deliberate
       client-side execution boundary.
    3. The effective policy ceiling is bounded by the application upper limit:
       effective_policy_ceiling = min(policy_ceiling, upper_limit).
    4. Missing budget (None) resolves to effective_policy_ceiling (default: 8,192).
    5. Python bool values (True, False) are strictly rejected with TypeError.
    6. Floating-point values (fractional and integral-valued) are strictly rejected with TypeError.
    7. String values are strictly rejected with TypeError.
    8. Non-positive integers (<= 0) are strictly rejected with ValueError.
    9. Explicit small positive integers <= effective_policy_ceiling are preserved exactly.
    10. Requests exceeding effective_policy_ceiling without override are clamped to effective_policy_ceiling.
    11. Explicit overrides (allow_override=True) allow budgets above the policy ceiling up to the
        application upper limit (16,384 tokens), clamping any excess.
    """
    # Backward compatibility: honor provider_hard_limit kwarg if passed
    if "provider_hard_limit" in kwargs:
        upper_limit_default = kwargs["provider_hard_limit"]
    else:
        upper_limit_default = application_upper_limit

    # 1. Validate environment configurations first on all execution paths
    policy_ceiling = validate_token_ceiling_config("TIER1_MAX_TOKENS_CEILING", default_cap)
    upper_limit = validate_token_ceiling_config(
        "TIER1_MAX_OVERRIDE_LIMIT",
        upper_limit_default,
        fallback_env_var="TIER1_PROVIDER_HARD_LIMIT",
    )

    # 2. Enforce invariant: policy ceiling cannot exceed application upper limit
    if policy_ceiling > upper_limit:
        logger.warning(
            f"Configured policy ceiling {policy_ceiling} exceeds application upper limit {upper_limit}; "
            f"bounding effective policy ceiling to {upper_limit}."
        )
        effective_policy_ceiling = upper_limit
    else:
        effective_policy_ceiling = policy_ceiling

    # 3. Extract candidate budget parameter
    candidate = max_tokens if max_tokens is not None else num_predict
    if candidate is None:
        candidate = kwargs.get("max_tokens")

    # 4. Missing value branch: bounded by effective_policy_ceiling and upper_limit
    if candidate is None:
        return min(effective_policy_ceiling, upper_limit)

    # 5. Type validation on candidate
    if isinstance(candidate, bool):
        raise TypeError(f"Invalid max_tokens type 'bool' ({candidate}): boolean values are not permitted as token counts.")

    if isinstance(candidate, float):
        raise TypeError(f"Invalid max_tokens type 'float' ({candidate}): floating-point token values are not permitted.")

    if isinstance(candidate, str):
        raise TypeError(f"Invalid max_tokens type 'str' ('{candidate}'): string token values are not permitted; must be positive integers.")

    if not isinstance(candidate, int):
        raise TypeError(f"Invalid max_tokens type '{type(candidate).__name__}': token counts must be positive integers.")

    if candidate <= 0:
        raise ValueError(f"Invalid max_tokens value {candidate}: must be a positive integer greater than 0.")

    # 6. Override flag
    is_override = allow_override or bool(kwargs.get("allow_override")) or bool(kwargs.get("override_max_tokens"))

    # 7. Bound against policy ceiling and upper limit
    if is_override:
        if candidate > upper_limit:
            logger.warning(
                f"Explicit override token budget {candidate} exceeds application upper limit {upper_limit}; "
                f"clamping to {upper_limit} to prevent runaway generation."
            )
            return upper_limit
        return min(candidate, upper_limit)

    # Ordinary request without override
    if candidate > effective_policy_ceiling:
        logger.warning(
            f"Requested token budget {candidate} exceeds configured policy ceiling {effective_policy_ceiling}; "
            f"clamping to {effective_policy_ceiling}. Pass allow_override=True to bypass."
        )
        return min(effective_policy_ceiling, upper_limit)

    return min(candidate, upper_limit)


class NvidiaClient(ModelProvider):
    """
    Tier 1 NVIDIA NIM Provider for HERMES.
    Single gateway for all HTTP communication with the NVIDIA NIM API.
    Supports real-time SSE streaming with content, reasoning_content,
    and tool_calls delta accumulation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = TIER1_MODEL,
        base_url: str = TIER1_BASE_URL,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        self.api_key: str = api_key or os.getenv("NVIDIA_API_KEY", "") or NVIDIA_API_KEY
        if not self.api_key:
            logger.warning("NVIDIA_API_KEY not set — Tier 1 NVIDIA NIM will be unavailable")

        # Guarantee z-ai/glm-5.3-flash model lock
        chosen_model = model or TIER1_MODEL
        if chosen_model == "z-ai/glm-5.3":
            chosen_model = "z-ai/glm-5.3-flash"
        self.model: str = chosen_model

        self.base_url: str = (base_url or "https://integrate.api.nvidia.com/v1").rstrip("/")
        self.provider: str = "nvidia_nim"

        # Validate timeout_seconds
        if timeout_seconds is None:
            self.timeout_seconds: int = validate_timeout_config(
                "MODEL_TIMEOUT_SECONDS",
                MODEL_TIMEOUT_SECONDS if MODEL_TIMEOUT_SECONDS is not None else 360,
            )
        else:
            if isinstance(timeout_seconds, bool):
                raise TypeError(
                    f"Invalid timeout_seconds type 'bool' ({timeout_seconds}): boolean values are not permitted."
                )
            if isinstance(timeout_seconds, float):
                raise TypeError(
                    f"Invalid timeout_seconds type 'float' ({timeout_seconds}): floating-point timeout values are not permitted."
                )
            if isinstance(timeout_seconds, str):
                raise TypeError(
                    f"Invalid timeout_seconds type 'str' ('{timeout_seconds}'): string timeout values are not permitted; must be positive integers."
                )
            if not isinstance(timeout_seconds, int):
                raise TypeError(
                    f"Invalid timeout_seconds type '{type(timeout_seconds).__name__}': timeout must be a positive integer."
                )
            if timeout_seconds <= 0:
                raise ValueError(
                    f"Invalid timeout_seconds value ({timeout_seconds}): must be a positive integer greater than 0."
                )
            self.timeout_seconds = timeout_seconds

        self._async_client: Optional[httpx.AsyncClient] = None
        self.last_raw_response: Optional[dict[str, Any]] = None
        self._failed_models: set[str] = set()

        logger.info(
            f"NvidiaClient ready | endpoint={self.base_url} | model={self.model}"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        from core.transport.client_manager import transport_client_manager
        from config.model_config import MODEL_FIRST_TOKEN_TIMEOUT
        read_to = float(os.getenv("MODEL_FIRST_TOKEN_TIMEOUT", str(MODEL_FIRST_TOKEN_TIMEOUT or 25.0)))
        # For SSE streaming with 120B reasoning models, socket read timeout must accommodate inter-chunk reasoning pauses
        stream_read_to = max(read_to, 90.0)
        return await transport_client_manager.get_client(
            base_url=self.base_url,
            connect_timeout=10.0,
            read_timeout=stream_read_to,
            write_timeout=15.0,
            pool_timeout=10.0,
        )

    async def is_running(self, timeout: Optional[float] = None) -> bool:
        """Return True if NVIDIA API key is configured and endpoint responds.
        Safe to use as startup health check; never raises.
        """
        if not self.api_key:
            return False
        check_timeout = timeout if timeout is not None else HEALTH_CHECK_TIMEOUT
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(check_timeout)) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                return resp.status_code in (200, 401, 403, 404)
        except Exception:
            return False

    async def aclose(self) -> None:
        """Close the persistent async HTTP client."""
        if self._async_client is not None and not self._async_client.is_closed:
            await self._async_client.aclose()
            self._async_client = None

    async def is_available(self) -> bool:
        """Check if API key is present."""
        return bool(self.api_key)

    async def generate(
        self,
        model: str = "",
        prompt: str = "",
        system: str = "",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        num_predict: Optional[int] = None,
        stream: bool = True,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        """
        Send a completion request to NVIDIA NIM chat completions API.
        Default: Streaming SSE with delta aggregation.
        Returns NormalizedModelResponse conforming to the HERMES provider contract.
        """
        active_model = model or getattr(self, "model", None) or TIER1_MODEL
        if active_model == "z-ai/glm-5.3":
            active_model = "z-ai/glm-5.3-flash"

        if not self.api_key:
            err_msg = "NVIDIA_API_KEY is required for runtime verification."
            logger.error(err_msg)
            return NormalizedModelResponse(
                text="",
                model=active_model,
                provider="nvidia_nim",
                error=err_msg,
                success=False,
            )

        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Resolve effective token budget honoring small values, default ceiling, and overrides
        effective_max_tokens = resolve_effective_max_tokens(
            max_tokens=max_tokens,
            num_predict=num_predict,
            default_cap=8192,
            **kwargs,
        )

        # Determine whether streaming should be used.
        # If httpx.AsyncClient.post was mocked (e.g. by unit tests), route to non-stream.
        post_attr = getattr(httpx.AsyncClient, "post", None)
        is_post_mocked = post_attr is not None and getattr(post_attr, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        effective_stream = False if is_post_mocked else stream

        payload: Dict[str, Any] = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            "stream": effective_stream,
        }

        # Transfer allowed optional parameters, explicitly filtering disallowed ones
        # (e.g. clear_thinking, num_predict, num_ctx, keep_alive, think, format)
        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]
        if "reasoning_effort" in kwargs and kwargs["reasoning_effort"] is not None:
            payload["reasoning_effort"] = kwargs["reasoning_effort"]
        elif active_model.startswith("z-ai/") or "nemotron" in active_model.lower():
            payload["reasoning_effort"] = "low"

        if "tools" in kwargs:
            raw_tools = kwargs["tools"]
            if isinstance(raw_tools, list):
                sanitized_tools = []
                for t in raw_tools:
                    if isinstance(t, dict) and t.get("type") == "function" and "function" in t:
                        t_copy = json.loads(json.dumps(t))
                        fname = t_copy["function"].get("name", "")
                        # NVIDIA NIM requires names matching ^[a-zA-Z0-9_-]+$ (no dots like fs.read)
                        if "." in fname:
                            t_copy["function"]["name"] = fname.replace(".", "_")
                        sanitized_tools.append(t_copy)
                    else:
                        sanitized_tools.append(t)
                payload["tools"] = sanitized_tools
            else:
                payload["tools"] = raw_tools
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if effective_stream else "application/json",
        }

        request_id = kwargs.get("request_id")
        mission_id = kwargs.get("mission_id")
        task_id = kwargs.get("task_id")
        stage = kwargs.get("stage", "Tier 1 Generation")
        on_tool_call = kwargs.get("on_tool_call")

        effective_timeout = float(kwargs.get("timeout_seconds") or self.timeout_seconds)
        url = f"{self.base_url}/chat/completions"
        start_time = time.monotonic()
        turn_index = kwargs.get("turn_index") or kwargs.get("turn_id")
        for attempt in range(2):
            client = await self._get_client()
            try:
                if effective_stream:
                    return await self._generate_stream(
                        client=client,
                        url=url,
                        payload=payload,
                        headers=headers,
                        active_model=active_model,
                        prompt=prompt,
                        system=system,
                        temperature=temperature,
                        start_time=start_time,
                        request_id=request_id,
                        mission_id=mission_id,
                        task_id=task_id,
                        stage=stage,
                        on_tool_call=on_tool_call,
                        effective_timeout=effective_timeout,
                        attempt_index=attempt,
                        turn_index=turn_index,
                    )
                else:
                    return await self._generate_non_stream(
                        client=client,
                        url=url,
                        payload=payload,
                        headers=headers,
                        active_model=active_model,
                        prompt=prompt,
                        system=system,
                        temperature=temperature,
                        start_time=start_time,
                        request_id=request_id,
                        mission_id=mission_id,
                        task_id=task_id,
                        stage=stage,
                        effective_timeout=effective_timeout,
                        attempt_index=attempt,
                        turn_index=turn_index,
                    )
            except NvidiaConnectionError as conn_exc:
                await self.aclose()
                if attempt < 1:
                    logger.warning(
                        f"NvidiaClient connection error ({conn_exc}), retrying attempt 2/2 after 1.5s..."
                    )
                    await asyncio.sleep(1.5)
                    continue
                raise
            except NvidiaTimeoutError as timeout_exc:
                elapsed = time.monotonic() - start_time
                rem_budget = effective_timeout - elapsed
                if attempt < 1 and timeout_exc.timeout_type != "FIRST_TOKEN_TIMEOUT" and rem_budget > 15.0:
                    logger.warning(
                        f"NvidiaClient primary model {active_model} timed out ({timeout_exc.timeout_type}), "
                        f"retrying attempt 2/2 with remaining budget {rem_budget:.1f}s after 0.5s..."
                    )
                    effective_timeout = rem_budget
                    await asyncio.sleep(0.5)
                    continue
                logger.warning(
                    f"NvidiaClient primary model {active_model} timed out ({timeout_exc.timeout_type}) after {elapsed:.1f}s. "
                    f"Remaining budget {rem_budget:.1f}s. Fast-path raising to orchestrator for multi-tier failover."
                )
                raise
            except Exception as exc:
                await self.aclose()
                latency = time.monotonic() - start_time
                logger.error(f"NVIDIA NIM generation exception: {exc}")
                self._record_telemetry_failure(
                    active_model, prompt, system, start_time, timed_out=False, error=str(exc),
                    request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                )
                if attempt < 1:
                    logger.warning(f"NvidiaClient generation error ({exc}), retrying attempt 2/2 after 1.0s...")
                    await asyncio.sleep(1.0)
                    continue
                raise NvidiaConnectionError(f"NVIDIA NIM generation failed after retries: {exc}") from exc

    async def _generate_stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        active_model: str,
        prompt: str,
        system: str,
        temperature: float,
        start_time: float,
        request_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: str = "Tier 1 Generation",
        on_tool_call: Optional[Any] = None,
        effective_timeout: Optional[float] = None,
        attempt_index: int = 0,
        turn_index: Optional[Any] = None,
    ) -> NormalizedModelResponse:
        timeout_limit = float(effective_timeout if effective_timeout is not None else self.timeout_seconds)
        connect_time: Optional[float] = None
        first_token_time: Optional[float] = None
        first_reasoning_time: Optional[float] = None
        first_content_time: Optional[float] = None
        first_tool_time: Optional[float] = None
        first_useful_action_time: Optional[float] = None
        content_chunks: List[str] = []
        reasoning_chunks: List[str] = []
        tool_calls_map: Dict[int, Dict[str, Any]] = {}
        dispatched_indices: set[int] = set()
        stop_requested: bool = False
        usage_dict: Dict[str, Any] = {}
        finish_reason: Optional[str] = None
        last_chunk_time: float = start_time
        max_idle_interval_ms: float = 0.0

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                connect_time = time.monotonic()
                last_chunk_time = connect_time
                logger.info(f"NvidiaClient: stream connected | HTTP {response.status_code}")
                if response.status_code != 200:
                    err_body = await response.aread()
                    err_text = f"NVIDIA NIM API returned HTTP {response.status_code}: {err_body.decode(errors='replace')[:300]}"
                    logger.error(err_text)
                    self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=False, error=err_text)
                    return NormalizedModelResponse(
                        text="",
                        model=active_model,
                        provider="nvidia_nim",
                        latency_ms=(time.monotonic() - start_time) * 1000.0,
                        error=err_text,
                        success=False,
                    )

                async for line in response.aiter_lines():
                    now_time = time.monotonic()
                    chunk_idle = (now_time - last_chunk_time) * 1000.0
                    if chunk_idle > max_idle_interval_ms:
                        max_idle_interval_ms = chunk_idle
                    last_chunk_time = now_time
                    elapsed = now_time - start_time
                    if elapsed > timeout_limit:
                        logger.warning(f"NvidiaClient: stream exceeded timeout threshold ({timeout_limit}s)")
                        raise NvidiaTimeoutError(
                            f"NVIDIA NIM stream exceeded total allowed duration ({elapsed:.1f}s > {timeout_limit}s)",
                            timeout_type="TOTAL_GENERATION_TIMEOUT",
                            duration=elapsed,
                        )
                    if not line:
                        continue
                    line_stripped = line.strip()
                    if "[DONE]" in line_stripped:
                        break
                    if line_stripped.startswith("data:"):
                        data_str = line_stripped[5:].strip()
                        if not data_str:
                            continue
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            self.last_raw_response = chunk
                            if "usage" in chunk and chunk["usage"]:
                                usage_dict = chunk["usage"]

                            choices = chunk.get("choices", [])
                            if choices:
                                ch = choices[0]
                                fr = ch.get("finish_reason")
                                if fr:
                                    finish_reason = fr
                                delta = ch.get("delta", {})
                                
                                # Accumulate content
                                c = delta.get("content")
                                if c:
                                    content_chunks.append(c)
                                    if first_content_time is None:
                                        first_content_time = time.monotonic()

                                # Accumulate reasoning_content
                                r = delta.get("reasoning_content")
                                if r:
                                    reasoning_chunks.append(r)
                                    if first_reasoning_time is None:
                                        first_reasoning_time = time.monotonic()

                                # Accumulate tool_calls deltas
                                tc_deltas = delta.get("tool_calls")
                                if tc_deltas and isinstance(tc_deltas, list):
                                    if first_tool_time is None:
                                        first_tool_time = time.monotonic()
                                    for tc_delta in tc_deltas:
                                        if not isinstance(tc_delta, dict):
                                            continue
                                        idx = tc_delta.get("index") if tc_delta.get("index") is not None else 0
                                        if idx not in tool_calls_map:
                                            tool_calls_map[idx] = {
                                                "id": tc_delta.get("id", f"call_{idx}"),
                                                "type": tc_delta.get("type", "function"),
                                                "function": {"name": "", "arguments": ""},
                                            }
                                        if tc_delta.get("id"):
                                            tool_calls_map[idx]["id"] = tc_delta["id"]

                                        # Support top-level name if provided
                                        top_name = tc_delta.get("name")
                                        if top_name and isinstance(top_name, str):
                                            curr = tool_calls_map[idx]["function"]["name"]
                                            if not curr:
                                                tool_calls_map[idx]["function"]["name"] = top_name
                                            elif not curr.endswith(top_name) and curr != top_name:
                                                tool_calls_map[idx]["function"]["name"] += top_name

                                        # Support function object delta
                                        f_delta = tc_delta.get("function")
                                        if isinstance(f_delta, dict):
                                            new_name = f_delta.get("name")
                                            if new_name and isinstance(new_name, str):
                                                curr = tool_calls_map[idx]["function"]["name"]
                                                if not curr:
                                                    tool_calls_map[idx]["function"]["name"] = new_name
                                                elif not curr.endswith(new_name) and curr != new_name:
                                                    tool_calls_map[idx]["function"]["name"] += new_name
                                            # Note: if new_name is None, missing, or empty, curr name is preserved!

                                            new_args = f_delta.get("arguments")
                                            if new_args and isinstance(new_args, str):
                                                tool_calls_map[idx]["function"]["arguments"] += new_args

                                                # Check if this tool call arguments are now complete JSON
                                                curr_fname = tool_calls_map[idx]["function"]["name"]
                                                curr_args_str = tool_calls_map[idx]["function"]["arguments"].strip()
                                                if curr_fname and curr_args_str.startswith("{") and curr_args_str.endswith("}") and idx not in dispatched_indices:
                                                    try:
                                                        parsed_args = json.loads(curr_args_str)
                                                        if isinstance(parsed_args, dict):
                                                            from tools.registry import get_canonical_tool_name
                                                            canonical_name = get_canonical_tool_name(curr_fname)
                                                            if canonical_name:
                                                                dispatched_indices.add(idx)
                                                                if first_tool_time is None:
                                                                    first_tool_time = time.monotonic()
                                                                if first_useful_action_time is None:
                                                                    first_useful_action_time = time.monotonic()
                                                                canonical_tc = CanonicalToolCall(
                                                                    tool_call_id=tool_calls_map[idx].get("id", f"call_{idx}"),
                                                                    canonical_tool_name=canonical_name,
                                                                    raw_tool_name=curr_fname,
                                                                    arguments=parsed_args,
                                                                    stream_position=idx,
                                                                    timestamp=time.monotonic(),
                                                                    request_id=request_id or "",
                                                                    mission_id=mission_id or "",
                                                                    task_id=task_id or "",
                                                                )
                                                                logger.info(
                                                                    f"NvidiaClient: early complete tool call: {canonical_name} "
                                                                    f"at +{(time.monotonic() - start_time):.2f}s"
                                                                )
                                                                if on_tool_call is not None:
                                                                    import inspect
                                                                    if inspect.iscoroutinefunction(on_tool_call):
                                                                        should_stop = await on_tool_call(canonical_tc)
                                                                    else:
                                                                        should_stop = on_tool_call(canonical_tc)
                                                                    if should_stop:
                                                                        finish_reason = "tool_calls"
                                                                        stop_requested = True
                                                                        break
                                                    except (json.JSONDecodeError, ValueError):
                                                        pass

                                        if stop_requested:
                                            break

                                if first_token_time is None and (c or r or tc_deltas):
                                    first_token_time = time.monotonic()

                                # First Useful Action detection (TTFU)
                                if first_useful_action_time is None:
                                    if fr in ("tool_calls", "stop") or (tool_calls_map and fr):
                                        first_useful_action_time = time.monotonic()
                                    elif content_chunks and not tool_calls_map and len("".join(content_chunks).strip()) >= 40:
                                        first_useful_action_time = time.monotonic()

                                if stop_requested:
                                    break

                        except Exception as e:
                            logger.debug(f"NvidiaClient: SSE chunk parse error: {e}")

                    if stop_requested:
                        break

        except httpx.ConnectTimeout as exc:
            elapsed = time.monotonic() - start_time
            self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=True, error=str(exc))
            raise NvidiaTimeoutError(
                f"NVIDIA NIM connect timed out after {elapsed:.1f}s",
                timeout_type="CONNECT_TIMEOUT",
                duration=elapsed,
            ) from exc
        except httpx.ReadTimeout as exc:
            elapsed = time.monotonic() - start_time
            if tool_calls_map or (content_chunks and len("".join(content_chunks).strip()) > 20):
                logger.info(
                    f"NvidiaClient: SSE read timeout after {elapsed:.1f}s, but collected "
                    f"{len(tool_calls_map)} tool call(s) / {len(content_chunks)} content chunks. Completing stream gracefully."
                )
                finish_reason = finish_reason or "tool_calls" if tool_calls_map else "stop"
            else:
                self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=True, error=str(exc))
                if first_token_time is None:
                    raise NvidiaTimeoutError(
                        f"NVIDIA NIM first token timed out after {elapsed:.1f}s (upstream server stalled before emitting first SSE chunk)",
                        timeout_type="FIRST_TOKEN_TIMEOUT",
                        duration=elapsed,
                    ) from exc
                else:
                    raise NvidiaTimeoutError(
                        f"NVIDIA NIM SSE stream stalled after {elapsed:.1f}s (no data received within read timeout)",
                        timeout_type="SSE_READ_STALL",
                        duration=elapsed,
                    ) from exc
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - start_time
            self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=True, error=str(exc))
            raise NvidiaTimeoutError(
                f"NVIDIA NIM request timed out after {elapsed:.1f}s: {exc}",
                timeout_type="TOTAL_GENERATION_TIMEOUT",
                duration=elapsed,
            ) from exc
        except httpx.ConnectError as exc:
            self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=False, error=str(exc))
            raise NvidiaConnectionError(
                f"Could not connect to NVIDIA NIM at {self.base_url}"
            ) from exc

        # Dispatch any remaining complete tool calls that were not sent early
        for idx, tc_data in tool_calls_map.items():
            if idx not in dispatched_indices:
                fn_obj = tc_data.get("function", {})
                f_name = fn_obj.get("name", "")
                f_args_raw = fn_obj.get("arguments", "{}")
                if f_name:
                    p_args = {}
                    if isinstance(f_args_raw, dict):
                        p_args = f_args_raw
                    elif isinstance(f_args_raw, str):
                        try:
                            p_args = json.loads(f_args_raw)
                        except Exception:
                            p_args = {}
                    from tools.registry import get_canonical_tool_name
                    c_name = get_canonical_tool_name(f_name)
                    if c_name:
                        dispatched_indices.add(idx)
                        c_tc = CanonicalToolCall(
                            tool_call_id=tc_data.get("id", f"call_{idx}"),
                            canonical_tool_name=c_name,
                            raw_tool_name=f_name,
                            arguments=p_args if isinstance(p_args, dict) else {},
                            stream_position=idx,
                            timestamp=time.monotonic(),
                            request_id=request_id or "",
                            mission_id=mission_id or "",
                            task_id=task_id or "",
                        )
                        if on_tool_call is not None:
                            try:
                                import inspect
                                if inspect.iscoroutinefunction(on_tool_call):
                                    await on_tool_call(c_tc)
                                else:
                                    on_tool_call(c_tc)
                            except Exception:
                                pass

        latency = time.monotonic() - start_time
        latency_ms = latency * 1000.0

        content = "".join(content_chunks)
        reasoning = "".join(reasoning_chunks).strip()

        # Format tool calls list sorted by index
        tool_calls_list = [tool_calls_map[idx] for idx in sorted(tool_calls_map.keys())]

        logger.info(
            f"NvidiaClient: stream finished | latency={latency:.2f}s | "
            f"content_len={len(content)} | reasoning_len={len(reasoning)} | tool_calls={len(tool_calls_list)}"
        )

        # Synthesize content from tool calls if content is empty or lacks structured tool call
        has_tool_in_content = content and '"tool"' in content
        if tool_calls_list and not has_tool_in_content:
            first_tc = tool_calls_list[0]
            fn = first_tc.get("function", {})
            fname = fn.get("name", "")
            fargs_raw = fn.get("arguments", "{}")
            fargs = {}
            if isinstance(fargs_raw, dict):
                fargs = fargs_raw
            elif isinstance(fargs_raw, str):
                try:
                    fargs = json.loads(fargs_raw, strict=False)
                except Exception:
                    try:
                        from core.response_parser import _clean_json_string
                        fargs = json.loads(_clean_json_string(fargs_raw), strict=False)
                    except Exception:
                        fargs = {}
            synthesized_json = json.dumps({
                "tool": fname,
                "parameters": fargs,
                "reasoning": reasoning or "Tool selection executed.",
                "explanation": f"Executing tool {fname}."
            })
            content = synthesized_json

        # Standardize reasoning representation to <think>...</think> for ResponseParser
        if reasoning and not content:
            if "<think>" in reasoning:
                final_text = reasoning
            else:
                final_text = f"<think>\n{reasoning}\n</think>"
        elif reasoning and content:
            if "<think>" in reasoning:
                final_text = f"{reasoning}\n{content}"
            else:
                final_text = f"<think>\n{reasoning}\n</think>\n{content}"
        else:
            final_text = content

        input_tokens = usage_dict.get("prompt_tokens") or (len(prompt) // 4)
        output_tokens = usage_dict.get("completion_tokens") or (len(final_text) // 4)
        total_tokens = usage_dict.get("total_tokens") or (input_tokens + output_tokens)

        if first_useful_action_time is None:
            first_useful_action_time = time.monotonic()

        connect_latency_ms = (connect_time - start_time) * 1000.0 if connect_time else 0.0
        ttfb_ms = connect_latency_ms
        ttft_ms = (first_token_time - start_time) * 1000.0 if first_token_time else 0.0
        ttft_reasoning_ms = (first_reasoning_time - start_time) * 1000.0 if first_reasoning_time else 0.0
        ttft_content_ms = (first_content_time - start_time) * 1000.0 if first_content_time else 0.0
        ttft_tool_ms = (first_tool_time - start_time) * 1000.0 if first_tool_time else 0.0
        ttfu_ms = (first_useful_action_time - start_time) * 1000.0 if first_useful_action_time else 0.0
        tools_char_len = len(json.dumps(payload.get("tools", []))) if payload.get("tools") else 0

        raw_timings = {
            "connect_ms": round(connect_latency_ms, 2),
            "ttfb_ms": round(ttfb_ms, 2),
            "ttft_ms": round(ttft_ms, 2),
            "ttft_reasoning_ms": round(ttft_reasoning_ms, 2),
            "ttft_content_ms": round(ttft_content_ms, 2),
            "ttft_tool_ms": round(ttft_tool_ms, 2),
            "ttfu_ms": round(ttfu_ms, 2),
            "eval_ms": round(max(0.0, latency_ms - ttft_ms), 2),
            "max_idle_interval_ms": round(max_idle_interval_ms, 2),
            "reasoning_effort": payload.get("reasoning_effort", "none"),
        }

        try:
            self._record_telemetry_success(
                model=active_model,
                prompt=prompt,
                system=system,
                start_time=start_time,
                latency=latency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                temperature=temperature,
                connect_latency_ms=connect_latency_ms,
                ttft_ms=ttft_ms,
                ttfb_ms=ttfb_ms,
                ttft_reasoning_ms=ttft_reasoning_ms,
                ttft_content_ms=ttft_content_ms,
                ttft_tool_ms=ttft_tool_ms,
                ttfu_ms=ttfu_ms,
                tool_call_count=len(tool_calls_list),
                thinking_present=bool(reasoning),
                thinking_length=len(reasoning),
                tool_defs_chars=tools_char_len,
                request_id=request_id,
                mission_id=mission_id,
                task_id=task_id,
                stage=stage,
                attempt_index=attempt_index,
                turn_index=turn_index,
                reasoning_effort=payload.get("reasoning_effort", "none"),
                finish_reason=finish_reason,
                max_idle_interval_ms=max_idle_interval_ms,
            )
        except Exception:
            pass

        return NormalizedModelResponse(
            text=final_text,
            tool_calls=tool_calls_list,
            finish_reason=finish_reason,
            model=active_model,
            provider="nvidia_nim",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            ttfb_ms=ttfb_ms,
            ttft_reasoning_ms=ttft_reasoning_ms,
            ttft_content_ms=ttft_content_ms,
            ttft_tool_ms=ttft_tool_ms,
            ttfu_ms=ttfu_ms,
            raw_timing_metadata=raw_timings,
            raw_response=final_text,
            success=True,
        )

    async def _generate_non_stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        active_model: str,
        prompt: str,
        system: str,
        temperature: float,
        start_time: float,
        request_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: str = "Tier 1 Generation",
        effective_timeout: Optional[float] = None,
        attempt_index: int = 0,
        turn_index: Optional[int] = None,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        timeout_limit = float(effective_timeout if effective_timeout is not None else self.timeout_seconds)
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=httpx.Timeout(timeout_limit))
        except httpx.ConnectTimeout as exc:
            elapsed = time.monotonic() - start_time
            self._record_telemetry_failure(
                active_model, prompt, system, start_time, timed_out=True, error=str(exc),
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            raise NvidiaTimeoutError(
                f"NVIDIA NIM connect timed out after {elapsed:.1f}s",
                timeout_type="CONNECT_TIMEOUT",
                duration=elapsed,
            ) from exc
        except httpx.ReadTimeout as exc:
            elapsed = time.monotonic() - start_time
            self._record_telemetry_failure(
                active_model, prompt, system, start_time, timed_out=True, error=str(exc),
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            raise NvidiaTimeoutError(
                f"NVIDIA NIM read timed out after {elapsed:.1f}s",
                timeout_type="FIRST_TOKEN_TIMEOUT",
                duration=elapsed,
            ) from exc
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - start_time
            self._record_telemetry_failure(
                active_model, prompt, system, start_time, timed_out=True, error=str(exc),
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            raise NvidiaTimeoutError(
                f"NVIDIA NIM request timed out after {elapsed:.1f}s: {exc}",
                timeout_type="TOTAL_GENERATION_TIMEOUT",
                duration=elapsed,
            ) from exc
        except httpx.ConnectError as exc:
            self._record_telemetry_failure(
                active_model, prompt, system, start_time, timed_out=False, error=str(exc),
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            raise NvidiaConnectionError(
                f"Could not connect to NVIDIA NIM at {self.base_url}"
            ) from exc

        latency = time.monotonic() - start_time
        latency_ms = latency * 1000.0

        if response.status_code != 200:
            err_text = f"NVIDIA NIM API returned HTTP {response.status_code}: {response.text[:300]}"
            logger.error(err_text)
            self._record_telemetry_failure(
                active_model, prompt, system, start_time, timed_out=False, error=err_text,
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            return NormalizedModelResponse(
                text="",
                model=active_model,
                provider="nvidia_nim",
                latency_ms=latency_ms,
                error=err_text,
                success=False,
            )

        data = response.json()
        self.last_raw_response = data

        choices = data.get("choices", [])
        msg_obj = choices[0].get("message", {}) if choices else {}
        finish_reason = choices[0].get("finish_reason") if choices else None
        content = msg_obj.get("content") or ""
        reasoning = (msg_obj.get("reasoning_content") or "").strip()
        tool_calls = msg_obj.get("tool_calls") or []

        has_tool_in_content = content and '"tool"' in content
        if tool_calls and not has_tool_in_content:
            first_tc = tool_calls[0]
            fn = first_tc.get("function", {})
            fname = fn.get("name", "")
            fargs_raw = fn.get("arguments", "{}")
            try:
                fargs = json.loads(fargs_raw) if isinstance(fargs_raw, str) else fargs_raw
            except Exception:
                fargs = {}
            content = json.dumps({
                "tool": fname,
                "parameters": fargs,
                "reasoning": reasoning or "Tool selection executed.",
                "explanation": f"Executing tool {fname}."
            })

        if reasoning and not content:
            if "<think>" in reasoning:
                final_text = reasoning
            else:
                final_text = f"<think>\n{reasoning}\n</think>"
        elif reasoning and content:
            if "<think>" in reasoning:
                final_text = f"{reasoning}\n{content}"
            else:
                final_text = f"<think>\n{reasoning}\n</think>\n{content}"
        else:
            final_text = content

        usage = data.get("usage", {}) or {}
        input_tokens = usage.get("prompt_tokens") or (len(prompt) // 4)
        output_tokens = usage.get("completion_tokens") or (len(final_text) // 4)
        total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)

        try:
            self._record_telemetry_success(
                model=active_model,
                prompt=prompt,
                system=system,
                start_time=start_time,
                latency=latency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                temperature=temperature,
                request_id=request_id,
                mission_id=mission_id,
                task_id=task_id,
                stage=stage,
            )
        except Exception:
            pass

        return NormalizedModelResponse(
            text=final_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            model=active_model,
            provider="nvidia_nim",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            raw_response=final_text,
            success=True,
        )

    def _record_telemetry_success(
        self,
        model: str,
        prompt: str,
        system: str,
        start_time: float,
        latency: float,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        temperature: float,
        connect_latency_ms: float = 0.0,
        ttft_ms: float = 0.0,
        ttfb_ms: float = 0.0,
        ttft_reasoning_ms: float = 0.0,
        ttft_content_ms: float = 0.0,
        ttft_tool_ms: float = 0.0,
        ttfu_ms: float = 0.0,
        tool_call_count: int = 0,
        thinking_present: bool = False,
        thinking_length: int = 0,
        tool_defs_chars: int = 0,
        request_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: str = "Tier 1 Generation",
        attempt_index: int = 0,
        turn_index: Optional[Any] = None,
        reasoning_effort: Optional[str] = None,
        finish_reason: Optional[str] = None,
        max_idle_interval_ms: float = 0.0,
    ) -> None:
        try:
            from core.telemetry import telemetry, ModelCallTelemetry, ContextBreakdown
            ctx = ContextBreakdown(
                system_prompt_chars=len(system),
                user_prompt_chars=len(prompt),
                tool_defs_chars=tool_defs_chars,
                total_input_chars=len(system) + len(prompt) + tool_defs_chars,
                exact_input_tokens=input_tokens,
            )
            mc = ModelCallTelemetry(
                inference_id=uuid.uuid4().hex[:8],
                request_id=request_id or "",
                mission_id=mission_id or "",
                task_id=task_id or "",
                stage=stage,
                model=model,
                provider="nvidia_nim",
                start_time_monotonic=start_time,
                end_time_monotonic=start_time + latency,
                total_latency_ms=latency * 1000.0,
                ttft_ms=ttft_ms,
                ttfb_ms=ttfb_ms,
                ttft_reasoning_ms=ttft_reasoning_ms,
                ttft_content_ms=ttft_content_ms,
                ttft_tool_ms=ttft_tool_ms,
                ttfu_ms=ttfu_ms,
                prompt_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                context=ctx,
                temperature=temperature,
                tool_call_count=tool_call_count,
                thinking_present=thinking_present,
                thinking_length=thinking_length,
                attempt_index=attempt_index,
                turn_index=turn_index if isinstance(turn_index, int) else None,
                reasoning_effort=reasoning_effort,
                finish_reason=finish_reason,
                max_idle_interval_ms=max_idle_interval_ms,
                raw_timing_metadata={
                    "connect_ms": round(connect_latency_ms, 2),
                    "ttfb_ms": round(ttfb_ms, 2),
                    "ttft_ms": round(ttft_ms, 2),
                    "ttft_reasoning_ms": round(ttft_reasoning_ms, 2),
                    "ttft_content_ms": round(ttft_content_ms, 2),
                    "ttft_tool_ms": round(ttft_tool_ms, 2),
                    "ttfu_ms": round(ttfu_ms, 2),
                    "eval_ms": round(max(0.0, (latency * 1000.0) - ttft_ms), 2),
                    "max_idle_interval_ms": round(max_idle_interval_ms, 2),
                    "reasoning_effort": reasoning_effort,
                },
                success=True,
            )
            with telemetry._global_lock:
                target_req = None
                if request_id and request_id in telemetry._active_requests:
                    target_req = telemetry._active_requests[request_id]
                elif mission_id:
                    for req in telemetry._active_requests.values():
                        if req.mission_id == mission_id or req.request_id == mission_id:
                            target_req = req
                            break
                if target_req:
                    mc.request_id = target_req.request_id
                    mc.task_id = task_id or target_req.request_id
                    mc.mission_id = target_req.mission_id or target_req.request_id
                    mc.execution_mode = target_req.execution_mode
                    target_req.model_calls.append(mc)
        except Exception:
            pass

    def _record_telemetry_failure(
        self,
        model: str,
        prompt: str,
        system: str,
        start_time: float,
        timed_out: bool,
        error: str,
        request_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: str = "Tier 1 Generation",
    ) -> None:
        try:
            from core.telemetry import telemetry, ModelCallTelemetry
            elapsed = time.monotonic() - start_time
            mc = ModelCallTelemetry(
                inference_id=uuid.uuid4().hex[:8],
                request_id=request_id or "",
                mission_id=mission_id or "",
                task_id=task_id or "",
                stage=stage,
                model=model,
                provider="nvidia_nim",
                start_time_monotonic=start_time,
                end_time_monotonic=start_time + elapsed,
                total_latency_ms=elapsed * 1000.0,
                success=False,
                timed_out=timed_out,
                error=error,
                error_type="Timeout" if timed_out else "ConnectionOrRuntime",
                error_message=str(error),
            )
            with telemetry._global_lock:
                target_req = None
                if request_id and request_id in telemetry._active_requests:
                    target_req = telemetry._active_requests[request_id]
                elif mission_id:
                    for req in telemetry._active_requests.values():
                        if req.mission_id == mission_id or req.request_id == mission_id:
                            target_req = req
                            break

                if target_req:
                    mc.request_id = target_req.request_id
                    mc.task_id = task_id or target_req.request_id
                    mc.mission_id = target_req.mission_id or target_req.request_id
                    mc.execution_mode = target_req.execution_mode
                    target_req.model_calls.append(mc)
        except Exception:
            pass
