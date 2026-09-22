# models/nvidia_client.py
# NVIDIA NIM API client for HERMES Tier 1 primary model.
# Communicates with OpenAI-compatible NVIDIA NIM endpoint:
# https://integrate.api.nvidia.com/v1/chat/completions
# Model: z-ai/glm-5.3
# API key is loaded strictly from NVIDIA_API_KEY environment variable.
# Never log the API key.

from __future__ import annotations
import os
import time
import json
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


class NvidiaClient(ModelProvider):
    """
    Tier 1 NVIDIA NIM Provider for HERMES.
    Single gateway for all HTTP communication with the NVIDIA NIM API.
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

        self.model: str = model or TIER1_MODEL
        self.base_url: str = (base_url or "https://integrate.api.nvidia.com/v1").rstrip("/")
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
                timeout=httpx.Timeout(float(self.timeout_seconds), connect=30.0),
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
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        """
        Send a completion request to NVIDIA NIM chat completions API.
        Returns NormalizedModelResponse conforming to the HERMES provider contract.
        """
        active_model = model or getattr(self, "model", None) or TIER1_MODEL
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

        payload: Dict[str, Any] = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }

        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        url = f"{self.base_url}/chat/completions"
        start_time = time.monotonic()
        client = await self._get_client()

        try:
            try:
                response = await client.post(url, json=payload, headers=headers)
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

            if response.status_code != 200:
                err_text = f"NVIDIA NIM API returned HTTP {response.status_code}: {response.text[:300]}"
                logger.error(err_text)
                self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=False, error=err_text)
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
            content = msg_obj.get("content") or ""
            reasoning = msg_obj.get("reasoning_content") or ""

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

            usage = data.get("usage", {}) or {}
            input_tokens = usage.get("prompt_tokens") or (len(prompt) // 4)
            output_tokens = usage.get("completion_tokens") or (len(final_text) // 4)
            total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)

            # Record telemetry non-invasively
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
                )
            except Exception:
                pass

            return NormalizedModelResponse(
                text=final_text,
                model=active_model,
                provider="nvidia_nim",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                raw_response=final_text,
                success=True,
            )

        except (NvidiaTimeoutError, NvidiaConnectionError):
            raise
        except Exception as exc:
            latency = time.monotonic() - start_time
            logger.error(f"NVIDIA NIM generation exception: {exc}")
            self._record_telemetry_failure(active_model, prompt, system, start_time, timed_out=False, error=str(exc))
            return NormalizedModelResponse(
                text="",
                model=active_model,
                provider="nvidia_nim",
                latency_ms=latency * 1000.0,
                error=str(exc),
                success=False,
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
    ) -> None:
        try:
            from core.telemetry import telemetry, ModelCallTelemetry, ContextBreakdown
            ctx = ContextBreakdown(
                system_prompt_chars=len(system),
                user_prompt_chars=len(prompt),
                total_input_chars=len(system) + len(prompt),
                exact_input_tokens=input_tokens,
            )
            mc = ModelCallTelemetry(
                model=model,
                provider="nvidia_nim",
                stage="Tier 1 Generation",
                start_time_monotonic=start_time,
                end_time_monotonic=start_time + latency,
                total_latency_ms=latency * 1000.0,
                prompt_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                context=ctx,
                temperature=temperature,
                success=True,
            )
            with telemetry._global_lock:
                for req in telemetry._active_requests.values():
                    mc.request_id = req.request_id
                    mc.task_id = req.request_id
                    mc.mission_id = req.mission_id or req.request_id
                    req.model_calls.append(mc)
                    break
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
    ) -> None:
        try:
            from core.telemetry import telemetry, ModelCallTelemetry
            elapsed = time.monotonic() - start_time
            mc = ModelCallTelemetry(
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
                for req in telemetry._active_requests.values():
                    mc.request_id = req.request_id
                    req.model_calls.append(mc)
                    break
        except Exception:
            pass
