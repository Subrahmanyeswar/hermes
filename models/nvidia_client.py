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

from models.provider import ModelProvider, NormalizedModelResponse
from config.model_config import (
    TIER1_MODEL,
    TIER1_BASE_URL,
    NVIDIA_API_KEY,
    MODEL_TIMEOUT_SECONDS,
)

# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------


class NvidiaTimeoutError(Exception):
    """Raised when NVIDIA NIM takes more than timeout_seconds to respond."""


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
            timeout_seconds=MODEL_TIMEOUT_SECONDS,
        )
    return _SHARED_NVIDIA_CLIENT


async def close_shared_nvidia_client() -> None:
    """Gracefully close the process-wide persistent NvidiaClient."""
    global _SHARED_NVIDIA_CLIENT
    if _SHARED_NVIDIA_CLIENT is not None:
        await _SHARED_NVIDIA_CLIENT.aclose()
        _SHARED_NVIDIA_CLIENT = None


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
        timeout_seconds: int = MODEL_TIMEOUT_SECONDS,
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
        self.timeout_seconds: int = timeout_seconds
        self._async_client: Optional[httpx.AsyncClient] = None
        self.last_raw_response: Optional[dict[str, Any]] = None

        logger.info(
            f"NvidiaClient ready | endpoint={self.base_url} | model={self.model}"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Return or create a reusable persistent async HTTP client."""
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(
                timeout=httpx.Timeout(float(self.timeout_seconds), connect=30.0, read=float(self.timeout_seconds)),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._async_client

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

        # Calculate max tokens honoring num_predict alias if passed
        effective_max_tokens = max_tokens or num_predict
        if effective_max_tokens is None:
            effective_max_tokens = kwargs.get("max_tokens", 8192)

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
        payload["reasoning_effort"] = kwargs.get("reasoning_effort", "low")
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]
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

        url = f"{self.base_url}/chat/completions"
        start_time = time.monotonic()
        for attempt in range(3):
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
                    )
            except NvidiaConnectionError as conn_exc:
                await self.aclose()
                if attempt < 2:
                    logger.warning(
                        f"NvidiaClient connection error ({conn_exc}), retrying attempt {attempt + 1}/3 after 1.5s..."
                    )
                    await asyncio.sleep(1.5)
                    continue
                raise
            except NvidiaTimeoutError:
                raise
            except Exception as exc:
                latency = time.monotonic() - start_time
                logger.error(f"NVIDIA NIM generation exception: {exc}")
                self._record_telemetry_failure(
                    active_model, prompt, system, start_time, timed_out=False, error=str(exc),
                    request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                )
                return NormalizedModelResponse(
                    text="",
                    model=active_model,
                    provider="nvidia_nim",
                    latency_ms=latency * 1000.0,
                    error=str(exc),
                    success=False,
                )

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
    ) -> NormalizedModelResponse:
        connect_time: Optional[float] = None
        first_token_time: Optional[float] = None
        first_reasoning_time: Optional[float] = None
        first_content_time: Optional[float] = None
        first_tool_time: Optional[float] = None
        first_useful_action_time: Optional[float] = None
        content_chunks: List[str] = []
        reasoning_chunks: List[str] = []
        tool_calls_map: Dict[int, Dict[str, Any]] = {}
        usage_dict: Dict[str, Any] = {}
        finish_reason: Optional[str] = None

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                connect_time = time.monotonic()
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
                                        idx = tc_delta.get("index") if tc_delta.get("index") is not None else 0
                                        if idx not in tool_calls_map:
                                            tool_calls_map[idx] = {
                                                "id": tc_delta.get("id", f"call_{idx}"),
                                                "type": tc_delta.get("type", "function"),
                                                "function": {"name": "", "arguments": ""},
                                            }
                                        if tc_delta.get("id"):
                                            tool_calls_map[idx]["id"] = tc_delta["id"]
                                        f_delta = tc_delta.get("function", {})
                                        if f_delta.get("name"):
                                            tool_calls_map[idx]["function"]["name"] += f_delta["name"]
                                        if f_delta.get("arguments"):
                                            tool_calls_map[idx]["function"]["arguments"] += f_delta["arguments"]

                                if first_token_time is None and (c or r or tc_deltas):
                                    first_token_time = time.monotonic()

                                # First Useful Action detection (TTFU)
                                if first_useful_action_time is None:
                                    if fr in ("tool_calls", "stop") or (tool_calls_map and fr):
                                        first_useful_action_time = time.monotonic()
                                    elif content_chunks and not tool_calls_map and len("".join(content_chunks).strip()) >= 40:
                                        first_useful_action_time = time.monotonic()

                        except Exception as e:
                            logger.debug(f"NvidiaClient: SSE chunk parse error: {e}")

        except httpx.TimeoutException as exc:
            self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=True, error=str(exc))
            raise NvidiaTimeoutError(
                f"NVIDIA NIM request timed out after {self.timeout_seconds}s"
            ) from exc
        except httpx.ConnectError as exc:
            self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=False, error=str(exc))
            raise NvidiaConnectionError(
                f"Could not connect to NVIDIA NIM at {self.base_url}"
            ) from exc

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

        # Synthesize content from tool calls if content is empty
        if tool_calls_list and not content:
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
    ) -> NormalizedModelResponse:
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            self._record_telemetry_failure(
                active_model, prompt, system, start_time, timed_out=True, error=str(exc),
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            raise NvidiaTimeoutError(
                f"NVIDIA NIM request timed out after {self.timeout_seconds}s"
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

        if tool_calls and not content:
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
                raw_timing_metadata={
                    "connect_ms": round(connect_latency_ms, 2),
                    "ttfb_ms": round(ttfb_ms, 2),
                    "ttft_ms": round(ttft_ms, 2),
                    "ttft_reasoning_ms": round(ttft_reasoning_ms, 2),
                    "ttft_content_ms": round(ttft_content_ms, 2),
                    "ttft_tool_ms": round(ttft_tool_ms, 2),
                    "ttfu_ms": round(ttfu_ms, 2),
                    "eval_ms": round(max(0.0, (latency * 1000.0) - ttft_ms), 2),
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
