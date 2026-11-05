# models/gemini_client.py
"""
HERMES Gemini API Client — Tier 1 Provider
Uses Google's native Gemini REST API (not OpenAI-compatible).
Model: gemini-2.5-flash
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Union

import httpx
from loguru import logger

from models.provider import ModelProvider, NormalizedModelResponse


class GeminiClient(ModelProvider):
    """
    Gemini API client for HERMES Tier 1.
    Uses Google's native generateContent REST endpoint.
    NOT OpenAI-compatible — uses Gemini-specific message and tool formats.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        tier: int = 2,
    ) -> None:
        from config.model_config import GEMINI_API_KEY
        self.api_key = api_key or GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("TIER2_MODEL", os.getenv("TIER1_MODEL", "gemini-3.8-flash"))
        from config.model_config import HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS)
        self.tier = tier
        self.provider = "gemini"
        self.base_url = self.BASE_URL
        self._client: Optional[httpx.AsyncClient] = None
        # Semaphore: Gemini free tier is ~15 RPM, allow 2 concurrent
        self._semaphore = asyncio.Semaphore(2)
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured — Tier 1 Gemini will be unavailable")
        else:
            logger.info(f"GeminiClient ready | model={self.model}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def is_available(self, timeout: float = 5.0) -> bool:
        if not self.api_key:
            return False
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.BASE_URL}/models",
                params={"key": self.api_key},
                timeout=timeout,
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def is_running(self, timeout: Optional[float] = None) -> bool:
        return await self.is_available(timeout=timeout or 5.0)

    def _convert_tools_to_gemini(self, tools: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Convert OpenAI-style tool definitions to Gemini functionDeclarations."""
        if not tools:
            return None
        function_declarations = []
        for t in tools:
            if isinstance(t, dict) and t.get("type") == "function" and "function" in t:
                fn = t["function"]
                decl: Dict[str, Any] = {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                }
                params = fn.get("parameters")
                if params:
                    decl["parameters"] = params
                function_declarations.append(decl)
        if not function_declarations:
            return None
        return [{"functionDeclarations": function_declarations}]

    def _convert_messages_to_contents(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """Convert OpenAI messages to Gemini contents + systemInstruction."""
        system_text: Optional[str] = None
        contents: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_text = content if isinstance(content, str) else str(content)
                continue

            if role == "assistant":
                gemini_role = "model"
                parts = []
                if isinstance(content, str) and content:
                    parts.append({"text": content})
                # Handle tool calls in assistant message
                tool_calls = msg.get("tool_calls") or []
                for tc in tool_calls:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    fname = fn.get("name", tc.get("name", "")) if isinstance(tc, dict) else ""
                    fargs = fn.get("arguments", tc.get("arguments", "{}")) if isinstance(tc, dict) else "{}"
                    if isinstance(fargs, str):
                        try:
                            fargs = json.loads(fargs)
                        except Exception:
                            fargs = {}
                    parts.append({"functionCall": {"name": fname, "args": fargs}})
                if parts:
                    contents.append({"role": gemini_role, "parts": parts})
                continue

            if role == "tool":
                # Tool result — map to functionResponse
                tool_call_id = msg.get("tool_call_id", "")
                tool_name = msg.get("name", "") or msg.get("tool_name", "")
                result_content = content if isinstance(content, str) else str(content)
                try:
                    result_obj = json.loads(result_content) if isinstance(result_content, str) else result_content
                except Exception:
                    result_obj = {"result": result_content}
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": tool_name or "tool",
                            "response": {"result": result_obj},
                        }
                    }]
                })
                continue

            # user role
            if isinstance(content, str):
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append({"text": part.get("text", "")})
                if parts:
                    contents.append({"role": "user", "parts": parts})

        return system_text, contents

    def _parse_gemini_response(
        self, data: Dict[str, Any], model: str
    ) -> NormalizedModelResponse:
        """Parse Gemini generateContent response into NormalizedModelResponse."""
        candidates = data.get("candidates") or []
        usage = data.get("usageMetadata") or {}
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)

        if not candidates:
            return NormalizedModelResponse(
                text="",
                model=model,
                provider="gemini",
                error="No candidates in Gemini response",
                success=False,
            )

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason", "STOP")
        content_obj = candidate.get("content") or {}
        parts = content_obj.get("parts") or []

        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []

        for part in parts:
            if "text" in part and part["text"]:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                fname = fc.get("name", "")
                fargs = fc.get("args", {})
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "name": fname,
                    "arguments": fargs if isinstance(fargs, dict) else {},
                })
            elif "thought" in part:
                # Thinking content — skip for now
                pass

        full_text = "".join(text_parts)
        return NormalizedModelResponse(
            text=full_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            model=model,
            provider="gemini",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            success=True,
        )

    async def generate(
        self,
        model: str = "",
        prompt: str = "",
        system: str = "",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        active_model = model or self.model
        req_id = kwargs.get("request_id") or f"req_{uuid.uuid4().hex[:8]}"
        timeout_val = float(kwargs.get("timeout_seconds") or self.timeout_seconds)
        reasoning_effort = kwargs.get("reasoning_effort", "low")

        if not self.api_key:
            return NormalizedModelResponse(
                text="",
                model=active_model,
                provider="gemini",
                error="GEMINI_API_KEY not configured",
                success=False,
            )

        # Build messages list
        if messages:
            all_messages = messages
        else:
            all_messages = []
            if system:
                all_messages.append({"role": "system", "content": system})
            if prompt:
                all_messages.append({"role": "user", "content": prompt})

        system_text, contents = self._convert_messages_to_contents(all_messages)

        # Gemini requires at least one content entry
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

        # Build thinking config based on reasoning_effort
        # Valid thinking levels for Gemini 3.8 Flash: LOW, MEDIUM, HIGH
        effort_str = str(reasoning_effort).lower() if reasoning_effort else "low"
        if effort_str in ("none", "off", "minimal"):
            level = "LOW"
        elif effort_str in ("medium", "med"):
            level = "MEDIUM"
        elif effort_str in ("high", "max"):
            level = "HIGH"
        else:
            level = "LOW"

        generation_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens or 8192,
        }
        # Do NOT send unsupported parameters like candidate_count, frequency_penalty, presence_penalty
        if "3.8" in active_model or "3-" in active_model or "3." in active_model:
            generation_config["thinkingConfig"] = {"thinkingLevel": level}
        elif "flash" in active_model or "pro" in active_model:
            thinking_budget = 512 if level == "LOW" else (2048 if level == "MEDIUM" else 8192)
            generation_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }

        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        gemini_tools = self._convert_tools_to_gemini(tools or [])
        if gemini_tools:
            payload["tools"] = gemini_tools
            # Tool config — auto means model decides
            if tool_choice == "required":
                payload["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
            elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                fn_name = tool_choice.get("function", {}).get("name", "")
                if fn_name:
                    payload["toolConfig"] = {
                        "functionCallingConfig": {
                            "mode": "ANY",
                            "allowedFunctionNames": [fn_name],
                        }
                    }
            else:
                payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        url = f"{self.BASE_URL}/models/{active_model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        t0 = time.monotonic()
        async with self._semaphore:
            client = await self._get_client()
            try:
                resp = await client.post(
                    url,
                    headers=headers,
                    params={"key": self.api_key} if self.api_key else {},
                    json=payload,
                    timeout=timeout_val,
                )
                latency_ms = (time.monotonic() - t0) * 1000

                if resp.status_code in (429, 503):
                    elapsed = time.monotonic() - t0
                    rem = timeout_val - elapsed
                    if rem > 3.0:
                        retry_after = resp.headers.get("retry-after")
                        wait_sec = min(float(retry_after), 3.0) if retry_after else 1.5
                        if wait_sec < rem:
                            logger.info(f"[GEMINI] HTTP {resp.status_code} transient rate-limit/overload — backing off {wait_sec:.1f}s and retrying...")
                            await asyncio.sleep(wait_sec)
                            try:
                                rem_to = max(1.0, timeout_val - (time.monotonic() - t0))
                                resp = await client.post(
                                    url,
                                    headers=headers,
                                    params={"key": self.api_key} if self.api_key else {},
                                    json=payload,
                                    timeout=rem_to,
                                )
                            except Exception:
                                pass

                if resp.status_code != 200:
                    err_body = resp.text[:500]
                    # If gemini-3.8-flash hit free-tier quota (limit 20 RPD) or high demand (503), fall back to gemini-3-flash-preview
                    if active_model == "gemini-3.8-flash" and ("limit" in err_body.lower() or "quota" in err_body.lower() or resp.status_code in (429, 503)):
                        logger.info(f"[GEMINI FALLBACK] gemini-3.8-flash reached quota or demand spike. Seamlessly executing via gemini-3-flash-preview...")
                        fb_url = f"{self.BASE_URL}/models/gemini-3-flash-preview:generateContent"
                        rem_to = max(2.0, timeout_val - (time.monotonic() - t0))
                        try:
                            fb_resp = await client.post(
                                fb_url,
                                headers=headers,
                                params={"key": self.api_key} if self.api_key else {},
                                json=payload,
                                timeout=rem_to,
                            )
                            if fb_resp.status_code == 200:
                                data = fb_resp.json()
                                result = self._parse_gemini_response(data, "gemini-3-flash-preview")
                                result.latency_ms = (time.monotonic() - t0) * 1000
                                return result
                        except Exception as fb_err:
                            logger.warning(f"[GEMINI FALLBACK ERROR] {fb_err}")

                    logger.warning(f"[GEMINI ERROR] HTTP {resp.status_code}: {err_body}")
                    return NormalizedModelResponse(
                        text="",
                        model=active_model,
                        provider="gemini",
                        error=f"HTTP {resp.status_code}: {err_body}",
                        success=False,
                        latency_ms=latency_ms,
                    )

                data = resp.json()
                result = self._parse_gemini_response(data, active_model)
                result.latency_ms = latency_ms
                logger.info(
                    f"[GEMINI] model={active_model} | latency={latency_ms:.0f}ms | "
                    f"tokens_in={result.input_tokens} out={result.output_tokens} | "
                    f"tools={len(result.tool_calls or [])}"
                )
                return result

            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                logger.warning(f"[GEMINI TIMEOUT] {exc} after {latency_ms:.0f}ms")
                return NormalizedModelResponse(
                    text="",
                    model=active_model,
                    provider="gemini",
                    error=f"Request timed out after {latency_ms/1000:.1f}s",
                    success=False,
                    latency_ms=latency_ms,
                )
            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                logger.error(f"[GEMINI EXCEPTION] {exc}")
                return NormalizedModelResponse(
                    text="",
                    model=active_model,
                    provider="gemini",
                    error=str(exc),
                    success=False,
                    latency_ms=latency_ms,
                )

    async def run_diagnostics(self) -> Dict[str, Any]:
        """Run health check and return diagnostics dict."""
        t0 = time.monotonic()
        has_key = bool(self.api_key)
        masked = f"{self.api_key[:8]}...{self.api_key[-4:]}" if has_key and len(self.api_key) > 12 else ("SET" if has_key else "MISSING")
        result: Dict[str, Any] = {
            "tier": self.tier,
            "provider": "gemini",
            "model": self.model,
            "configured": has_key,
            "masked_key": masked,
            "base_url": self.BASE_URL,
            "healthy": False,
            "latency_ms": 0.0,
            "tool_call_supported": False,
            "status": "UNCONFIGURED" if not has_key else "UNKNOWN",
            "last_error": None,
        }
        if not has_key:
            result["status"] = "MISSING_KEY"
            result["last_error"] = "GEMINI_API_KEY not set"
            return result

        resp = await self.generate(prompt="ping", max_tokens=5, stream=False, timeout_seconds=10.0)
        result["latency_ms"] = round((time.monotonic() - t0) * 1000, 2)
        if resp.success:
            result["healthy"] = True
            result["status"] = "HEALTHY"
            # Test tool calling
            test_tool = [{
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "Test tool",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
                }
            }]
            tool_resp = await self.generate(
                prompt="Call test_tool with q='hello'",
                tools=test_tool,
                max_tokens=64,
                stream=False,
                timeout_seconds=15.0,
            )
            result["tool_call_supported"] = bool(tool_resp.success and tool_resp.tool_calls)
        else:
            result["healthy"] = False
            result["status"] = "UNAVAILABLE"
            result["last_error"] = resp.error
        return result
