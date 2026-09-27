# core/network/adapters.py
"""
Provider adapters for HERMES 2.x
Encapsulates protocol mechanics for NVIDIA NIM, Ollama, and test mocks.
Translates provider-specific wire responses and exceptions into canonical HERMES types.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx
from loguru import logger

from models.provider import NormalizedModelResponse
from core.network.models import (
    FailureClassification,
    ProviderCapabilities,
    ProviderType,
    StreamDelta,
)


def classify_httpx_exception(exc: Exception) -> FailureClassification:
    """Classify httpx and network exceptions into deterministic FailureClassification."""
    if isinstance(exc, httpx.ConnectTimeout):
        return FailureClassification.CONNECT_TIMEOUT
    if isinstance(exc, httpx.ReadTimeout):
        return FailureClassification.READ_TIMEOUT
    if isinstance(exc, httpx.WriteTimeout) or isinstance(exc, httpx.PoolTimeout):
        return FailureClassification.CONNECT_TIMEOUT
    if isinstance(exc, httpx.ConnectError):
        msg = str(exc).lower()
        if "connection refused" in msg:
            return FailureClassification.CONNECTION_REFUSED
        if "name resolution" in msg or "dns" in msg or "getaddrinfo" in msg:
            return FailureClassification.DNS_ERROR
        if "tls" in msg or "ssl" in msg or "cert" in msg:
            return FailureClassification.TLS_ERROR
        return FailureClassification.CONNECTION_RESET
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 401 or status == 403:
            return FailureClassification.AUTH_FAILURE
        if status == 404:
            return FailureClassification.MODEL_NOT_FOUND
        if status == 429:
            return FailureClassification.HTTP_429
        if 500 <= status < 600:
            return FailureClassification.HTTP_5XX
        if 400 <= status < 500:
            return FailureClassification.INVALID_REQUEST
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return FailureClassification.MALFORMED_RESPONSE
    if isinstance(exc, asyncio.CancelledError):
        return FailureClassification.CANCELLED
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        msg = str(exc).lower()
        if "stall" in msg or "idle" in msg or "first_delta" in msg:
            return FailureClassification.STREAM_STALL
        if "connect" in msg:
            return FailureClassification.CONNECT_TIMEOUT
        return FailureClassification.DEADLINE_EXCEEDED

    return FailureClassification.UNKNOWN_NETWORK_ERROR


class BaseProviderAdapter:
    """Base interface for all HERMES model provider adapters."""

    def __init__(self, provider_name: str, capabilities: ProviderCapabilities) -> None:
        self.provider_name = provider_name
        self.capabilities = capabilities

    async def open_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamDelta]:
        """Yield StreamDelta items incrementally as tokens arrive."""
        raise NotImplementedError

    async def execute_non_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        """Execute non-streaming completion."""
        raise NotImplementedError

    async def check_health(self, timeout: float = 2.0) -> bool:
        """Probe provider liveness/readiness endpoint."""
        return True

    async def aclose(self) -> None:
        """Cleanly close any connection pools."""
        pass


class NvidiaAdapter(BaseProviderAdapter):
    """Adapter for NVIDIA NIM OpenAI-compatible SSE endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        timeout: float = 45.0,
    ) -> None:
        super().__init__(
            provider_name=ProviderType.NVIDIA_NIM.value,
            capabilities=ProviderCapabilities(
                provider_name=ProviderType.NVIDIA_NIM.value,
                streaming=True,
                non_streaming_fallback=True,
                server_health_check=True,
                cancellation_supported=False,
                resumable_stream=False,
                tool_call_streaming=True,
                keep_alive_param=False,
                requires_api_key=True,
            ),
        )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=10.0, read=timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def open_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 45.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamDelta]:
        client = await self._get_client(timeout)
        url = f"{self.base_url}/chat/completions"

        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
            "stream": True,
        }
        if "tools" in kwargs and kwargs["tools"]:
            payload["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        try:
            req = client.build_request("POST", url, json=payload, headers=headers, timeout=timeout)
            resp = await client.send(req, stream=True)
            if resp.status_code >= 400:
                body_bytes = await resp.aread()
                resp.raise_for_status()

            async for line in resp.aiter_lines():
                if not line:
                    continue
                line_str = line.strip()
                if not line_str.startswith("data:"):
                    continue
                data_str = line_str[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                delta_item = StreamDelta(raw_chunk=data)
                choices = data.get("choices", [])
                if choices:
                    c = choices[0]
                    delta_dict = c.get("delta", {})
                    delta_item.content = delta_dict.get("content", "") or ""
                    delta_item.reasoning_content = (
                        delta_dict.get("reasoning_content") or delta_dict.get("reasoning") or ""
                    )
                    delta_item.tool_calls = delta_dict.get("tool_calls", []) or []
                    delta_item.finish_reason = c.get("finish_reason")

                yield delta_item
        finally:
            pass

    async def execute_non_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 45.0,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        client = await self._get_client(timeout)
        url = f"{self.base_url}/chat/completions"

        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
            "stream": False,
        }
        if "tools" in kwargs and kwargs["tools"]:
            payload["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices", [])
        content = ""
        tool_calls: List[Dict[str, Any]] = []
        finish_reason = None
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls", []) or []
            finish_reason = choices[0].get("finish_reason")

        usage = data.get("usage", {})
        return NormalizedModelResponse(
            text=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            model=model,
            provider=self.provider_name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            success=True,
        )

    async def check_health(self, timeout: float = 2.0) -> bool:
        """Lightweight readiness/models check."""
        try:
            client = await self._get_client(timeout)
            url = f"{self.base_url}/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            resp = await client.get(url, headers=headers, timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class OllamaAdapter(BaseProviderAdapter):
    """Adapter for local Ollama server endpoint."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 45.0,
    ) -> None:
        super().__init__(
            provider_name=ProviderType.OLLAMA.value,
            capabilities=ProviderCapabilities(
                provider_name=ProviderType.OLLAMA.value,
                streaming=True,
                non_streaming_fallback=True,
                server_health_check=True,
                cancellation_supported=True,
                resumable_stream=False,
                tool_call_streaming=False,
                keep_alive_param=True,
                requires_api_key=False,
            ),
        )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5.0, read=timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def open_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 45.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamDelta]:
        client = await self._get_client(timeout)
        url = f"{self.base_url}/api/generate"

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "keep_alive": 0,  # release VRAM immediately
            "options": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        req = client.build_request("POST", url, json=payload, timeout=timeout)
        resp = await client.send(req, stream=True)
        if resp.status_code >= 400:
            await resp.aread()
            resp.raise_for_status()

        async for line in resp.aiter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            delta_item = StreamDelta(
                content=data.get("response", ""),
                reasoning_content=data.get("thinking", ""),
                raw_chunk=data,
                finish_reason="stop" if data.get("done") else None,
            )
            yield delta_item
            if data.get("done"):
                break

    async def execute_non_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 45.0,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        client = await self._get_client(timeout)
        url = f"{self.base_url}/api/generate"

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "keep_alive": 0,
            "options": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        resp = await client.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        text = data.get("response", "")
        thinking = data.get("thinking", "")
        if thinking and text:
            full_text = f"<think>\n{thinking}\n</think>\n{text}"
        elif thinking:
            full_text = f"<think>\n{thinking}\n</think>"
        else:
            full_text = text

        return NormalizedModelResponse(
            text=full_text,
            finish_reason="stop" if data.get("done") else None,
            model=model,
            provider=self.provider_name,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            success=True,
        )

    async def check_health(self, timeout: float = 2.0) -> bool:
        try:
            client = await self._get_client(timeout)
            url = f"{self.base_url}/api/version"
            resp = await client.get(url, timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class FakeProviderAdapter(BaseProviderAdapter):
    """
    Test and simulation adapter supporting granular fault injection,
    delays, mid-stream stalls, malformed chunks, and error responses.
    """

    def __init__(
        self,
        provider_name: str = "fake_provider",
        capabilities: Optional[ProviderCapabilities] = None,
    ) -> None:
        super().__init__(
            provider_name=provider_name,
            capabilities=capabilities or ProviderCapabilities(provider_name=provider_name),
        )
        self.connect_delay: float = 0.0
        self.first_delta_delay: float = 0.0
        self.inter_delta_delay: float = 0.0
        self.stall_after_deltas: Optional[int] = None
        self.stall_duration: float = 60.0
        self.disconnect_after_deltas: Optional[int] = None
        self.status_code_error: Optional[int] = None
        self.exception_to_raise: Optional[Exception] = None
        self.persistent_exception: bool = False
        self.deltas_to_yield: List[StreamDelta] = []
        self.non_stream_response: Optional[NormalizedModelResponse] = None
        self.call_count: int = 0
        self.closed: bool = False

    async def open_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamDelta]:
        self.call_count += 1

        if self.connect_delay > 0:
            await asyncio.sleep(self.connect_delay)

        if self.exception_to_raise is not None:
            exc = self.exception_to_raise
            if not self.persistent_exception:
                self.exception_to_raise = None  # Consume single-shot if not persistent
            raise exc

        if self.status_code_error is not None:
            code = self.status_code_error
            self.status_code_error = None
            req = httpx.Request("POST", "http://fake/api")
            resp = httpx.Response(code, request=req)
            raise httpx.HTTPStatusError(f"HTTP {code}", request=req, response=resp)

        if self.first_delta_delay > 0:
            await asyncio.sleep(self.first_delta_delay)

        deltas = self.deltas_to_yield or [
            StreamDelta(content="Hello "),
            StreamDelta(content="world!"),
        ]

        for i, delta in enumerate(deltas):
            if self.disconnect_after_deltas is not None and i >= self.disconnect_after_deltas:
                raise httpx.ConnectError("Connection reset by peer")

            if self.stall_after_deltas is not None and i >= self.stall_after_deltas:
                # Mid-stream freeze
                await asyncio.sleep(self.stall_duration)

            if i > 0 and self.inter_delta_delay > 0:
                await asyncio.sleep(self.inter_delta_delay)

            yield delta

    async def execute_non_stream(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        self.call_count += 1
        if self.connect_delay > 0:
            await asyncio.sleep(self.connect_delay)

        if self.exception_to_raise is not None:
            exc = self.exception_to_raise
            if not self.persistent_exception:
                self.exception_to_raise = None
            raise exc

        if self.status_code_error is not None:
            code = self.status_code_error
            self.status_code_error = None
            req = httpx.Request("POST", "http://fake/api")
            resp = httpx.Response(code, request=req)
            raise httpx.HTTPStatusError(f"HTTP {code}", request=req, response=resp)

        if self.non_stream_response is not None:
            return self.non_stream_response

        return NormalizedModelResponse(
            text="Fake non-streaming response",
            model=model,
            provider=self.provider_name,
            success=True,
        )

    async def check_health(self, timeout: float = 2.0) -> bool:
        return self.exception_to_raise is None and self.status_code_error is None

    async def aclose(self) -> None:
        self.closed = True
