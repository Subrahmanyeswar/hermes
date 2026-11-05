# models/ollama_client.py
# Ollama API client for HERMES.
# All calls use keep_alive=0 to release VRAM immediately after generation.
# This is the ONLY file that makes HTTP calls to Ollama.

from __future__ import annotations

import os
import shutil
import time
import re
import uuid
import asyncio
from typing import Any, Optional, Union

import httpx
from loguru import logger

from models.provider import ModelProvider, NormalizedModelResponse
from config.model_config import MODEL_KEEP_ALIVE, MODEL_TIMEOUT_SECONDS, HEALTH_CHECK_TIMEOUT

# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------


class OllamaTimeoutError(Exception):
    """Raised when Ollama takes more than timeout_seconds to respond."""


class OllamaConnectionError(Exception):
    """Raised when Ollama is not running or is otherwise unreachable."""


def normalize_ollama_payload(data: Any) -> str:
    """
    Faithfully normalize Ollama API response payload into canonical model response text.
    Handles standard models, reasoning models (e.g. DeepSeek-R1), and mixed payloads.
    Preserves <think> semantic structure for reasoning content without duplication.
    """
    if not isinstance(data, dict):
        return ""

    resp = data.get("response")
    resp_text = str(resp).strip() if resp is not None and isinstance(resp, str) else ""

    thinking = data.get("thinking")
    thinking_text = str(thinking).strip() if thinking is not None and isinstance(thinking, str) else ""

    if thinking_text and resp_text:
        clean_think = re.sub(r'</?think>', '', thinking_text).strip()
        return f"<think>\n{clean_think}\n</think>\n{resp_text}"
    elif thinking_text and not resp_text:
        clean_think = re.sub(r'</?think>', '', thinking_text).strip()
        return f"<think>\n{clean_think}\n</think>"
    elif resp_text:
        return str(data.get("response", ""))
    else:
        return ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_SHARED_OLLAMA_CLIENT: Optional[OllamaClient] = None
_SHARED_TIER2_SEMAPHORE: Optional[asyncio.Semaphore] = None
_OLLAMA_STARTUP_LOCK: Optional[asyncio.Lock] = None
_OWNED_OLLAMA_PROCESS: Optional[Any] = None
_LAST_RECOVERY_ATTEMPT: float = 0.0


def get_tier2_semaphore() -> asyncio.Semaphore:
    """Return process-wide single-request semaphore (concurrency=1) for Tier 2."""
    global _SHARED_TIER2_SEMAPHORE
    if _SHARED_TIER2_SEMAPHORE is None:
        _SHARED_TIER2_SEMAPHORE = asyncio.Semaphore(1)
    return _SHARED_TIER2_SEMAPHORE


def reset_tier2_semaphore(concurrency: int = 1) -> asyncio.Semaphore:
    """Reset the process-wide Tier 2 semaphore (for tests or isolation)."""
    global _SHARED_TIER2_SEMAPHORE
    _SHARED_TIER2_SEMAPHORE = asyncio.Semaphore(concurrency)
    return _SHARED_TIER2_SEMAPHORE


def _get_startup_lock() -> asyncio.Lock:
    global _OLLAMA_STARTUP_LOCK
    if _OLLAMA_STARTUP_LOCK is None:
        _OLLAMA_STARTUP_LOCK = asyncio.Lock()
    return _OLLAMA_STARTUP_LOCK


def get_shared_ollama_client() -> OllamaClient:
    """Return a process-wide persistent OllamaClient singleton."""
    global _SHARED_OLLAMA_CLIENT
    if _SHARED_OLLAMA_CLIENT is None:
        _SHARED_OLLAMA_CLIENT = OllamaClient(
            timeout_seconds=MODEL_TIMEOUT_SECONDS,
        )
    return _SHARED_OLLAMA_CLIENT


async def close_shared_ollama_client() -> None:
    """Gracefully close the process-wide persistent OllamaClient."""
    global _SHARED_OLLAMA_CLIENT
    if _SHARED_OLLAMA_CLIENT is not None:
        await _SHARED_OLLAMA_CLIENT.aclose()
        _SHARED_OLLAMA_CLIENT = None


class OllamaClient(ModelProvider):
    """Single gateway for all HTTP communication with the Ollama API server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = MODEL_TIMEOUT_SECONDS,
        num_ctx: int = 4096,
        semaphore: Optional[asyncio.Semaphore] = None,
    ) -> None:
        """Store connection configuration; initialize persistent connection pool."""
        self.base_url: str = base_url.rstrip("/")
        self.timeout_seconds: int = timeout_seconds
        self.num_ctx: int = num_ctx
        self.last_raw_response: Optional[dict[str, Any]] = None
        self._async_client: Optional[httpx.AsyncClient] = None
        self._last_loaded_model: Optional[str] = None
        self._semaphore: Optional[asyncio.Semaphore] = semaphore

    @classmethod
    async def is_available(cls, base_url: str = "http://127.0.0.1:11434", timeout: float = 1.0) -> bool:
        """
        Check if the local Ollama daemon is currently running and reachable.
        Does not hang or spawn processes during passive availability checks.
        Returns False immediately if daemon is not responding.
        """
        import httpx
        try:
            target_url = getattr(cls, "base_url", base_url) if not isinstance(cls, type) else base_url
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{target_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    @classmethod
    def is_available_sync(cls, base_url: str = "http://127.0.0.1:11434", timeout: float = 1.0) -> bool:
        """Synchronous connectivity check for Ollama endpoint."""
        import urllib.request
        try:
            target_url = getattr(cls, "base_url", base_url) if not isinstance(cls, type) else base_url
            req = urllib.request.Request(f"{target_url}/api/tags")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_semaphore(self) -> asyncio.Semaphore:
        """Return the single-request concurrency semaphore for Tier 2."""
        if self._semaphore is not None:
            return self._semaphore
        return get_tier2_semaphore()

    async def _get_client(self) -> httpx.AsyncClient:
        """Return or create a reusable persistent async HTTP client with connection pooling."""
        from core.transport.client_manager import transport_client_manager
        return await transport_client_manager.get_client(
            base_url=self.base_url,
            connect_timeout=3.0,
            read_timeout=float(self.timeout_seconds),
            write_timeout=15.0,
            pool_timeout=10.0,
        )

    async def _ensure_local_server_running(self) -> bool:
        """
        Attempt to spawn or recover local ollama serve safely and idempotently.
        Guarantees concurrency isolation, listener ownership checks, and bounded startup.
        """
        global _OWNED_OLLAMA_PROCESS, _LAST_RECOVERY_ATTEMPT
        import shutil, subprocess

        lock = _get_startup_lock()
        async with lock:
            # 1. Check service readiness first
            try:
                c = await self._get_client()
                r = await c.get(f"{self.base_url}/api/tags", timeout=1.0)
                if r.status_code == 200:
                    return True
            except Exception:
                pass

            # 2. Check if binary is available
            ollama_bin = shutil.which("ollama") or r"C:\Users\SUBBU\AppData\Local\Programs\Ollama\ollama.exe"
            if not os.path.exists(ollama_bin):
                return False

            # 3. Check debounce cooldown (min 5s between recovery attempts)
            now = time.monotonic()
            if now - _LAST_RECOVERY_ATTEMPT < 5.0:
                for _ in range(6):
                    await asyncio.sleep(0.5)
                    try:
                        c = await self._get_client()
                        r = await c.get(f"{self.base_url}/api/tags", timeout=1.0)
                        if r.status_code == 200:
                            return True
                    except Exception:
                        pass
                return False

            _LAST_RECOVERY_ATTEMPT = now
            t0 = time.monotonic()

            # 4. If we own an existing child process that is unresponsive, safely terminate our owned process
            if _OWNED_OLLAMA_PROCESS is not None:
                try:
                    if _OWNED_OLLAMA_PROCESS.poll() is None:
                        logger.warning("OllamaClient: Terminating hung owned Ollama child process...")
                        _OWNED_OLLAMA_PROCESS.terminate()
                        _OWNED_OLLAMA_PROCESS.wait(timeout=2.0)
                except Exception as e:
                    logger.debug(f"OllamaClient: Owned process termination error: {e}")
                _OWNED_OLLAMA_PROCESS = None

            # 5. Launch single managed background instance
            try:
                logger.info(f"OllamaClient: Launching local Ollama server via {ollama_bin}...")
                _OWNED_OLLAMA_PROCESS = subprocess.Popen(
                    [ollama_bin, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                for _ in range(12):
                    await asyncio.sleep(0.5)
                    try:
                        c = await self._get_client()
                        r = await c.get(f"{self.base_url}/api/tags", timeout=1.0)
                        if r.status_code == 200:
                            dur = time.monotonic() - t0
                            logger.info(f"OllamaClient: Local Ollama server successfully started in {dur:.2f}s.")
                            return True
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"OllamaClient: Failed to start Ollama server: {e}")
            return False

    async def aclose(self) -> None:
        """Close the persistent async HTTP client."""
        if self._async_client is not None and not self._async_client.is_closed:
            await self._async_client.aclose()
            self._async_client = None

    async def preload_model(self, model: str, keep_alive: Union[int, str] = MODEL_KEEP_ALIVE) -> bool:
        """Preload a model into VRAM without user prompt latency. Returns True on success."""
        url = f"{self.base_url}/api/generate"
        client = await self._get_client()
        try:
            resp = await client.post(
                url,
                json={"model": model, "keep_alive": keep_alive, "prompt": "", "stream": False},
                timeout=httpx.Timeout(self.timeout_seconds),
            )
            if resp.status_code == 200:
                self._last_loaded_model = model
                logger.info(f"OllamaClient: preloaded model '{model}' into VRAM (keep_alive={keep_alive})")
                return True
        except Exception as e:
            logger.warning(f"OllamaClient: failed to preload model '{model}': {e}")
        return False

    async def unload_model(self, model: str) -> bool:
        """Explicitly evict a model from VRAM by sending keep_alive=0."""
        url = f"{self.base_url}/api/generate"
        client = await self._get_client()
        try:
            resp = await client.post(
                url,
                json={"model": model, "keep_alive": 0, "prompt": "", "stream": False},
                timeout=httpx.Timeout(30.0),
            )
            if self._last_loaded_model == model:
                self._last_loaded_model = None
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"OllamaClient: failed to unload model '{model}': {e}")
            return False

    async def unload_all(self) -> bool:
        """Unload any active models from VRAM."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/api/ps", timeout=httpx.Timeout(5.0))
            if resp.status_code == 200:
                data = resp.json()
                for m in data.get("models", []):
                    name = m.get("name", "")
                    if name:
                        await self.unload_model(name)
            self._last_loaded_model = None
            return True
        except Exception as e:
            logger.warning(f"OllamaClient: unload_all encountered error: {e}")
            return False

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        keep_alive: Union[int, str] = 0,
        temperature: float = 0.1,
        num_ctx: int = 4096,
        num_predict: Optional[int] = None,
        is_foreground: bool = True,
        think: Optional[bool] = None,
        format: Optional[Union[str, dict]] = None,
        **kwargs: Any
    ) -> NormalizedModelResponse:
        """
        Send a generation request to Ollama and return a NormalizedModelResponse.
        """
        from core.model_residency_manager import model_residency_manager
        if keep_alive == MODEL_KEEP_ALIVE:
            keep_alive = await model_residency_manager.acquire_model(model, is_foreground=is_foreground)

        url: str = f"{self.base_url}/api/generate"
        options = {
            "num_ctx": num_ctx if num_ctx else self.num_ctx,
            "temperature": temperature,
        }
        if num_predict is not None:
            options["num_predict"] = num_predict
        for k, v in kwargs.items():
            if k in ("num_predict", "top_p", "top_k", "stop"):
                options[k] = v

        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "keep_alive": keep_alive,
            "stream": False,
            "options": options,
        }
        if think is not None:
            if isinstance(think, (int, float)) and not isinstance(think, bool):
                logger.warning("OllamaClient: Ignoring unsupported numeric think={}; must be boolean or valid string.", think)
            else:
                body["think"] = think
        elif "think" in kwargs:
            raw_think = kwargs["think"]
            if isinstance(raw_think, (int, float)) and not isinstance(raw_think, bool):
                logger.warning("OllamaClient: Ignoring unsupported numeric think={}; must be boolean or valid string.", raw_think)
            else:
                body["think"] = raw_think

        if format is not None:
            body["format"] = format
        elif "format" in kwargs:
            body["format"] = kwargs["format"]

        logger.debug(
            "OllamaClient.generate | model={} | prompt_len={} chars | keep_alive={}",
            model,
            len(prompt),
            keep_alive,
        )

        request_id = kwargs.get("request_id")
        mission_id = kwargs.get("mission_id")
        task_id = kwargs.get("task_id")
        stage = kwargs.get("stage", "Tier 2 Verification")

        to_seconds = float(kwargs.get("timeout_seconds") or self.timeout_seconds)
        start_monotonic = time.monotonic()
        deadline = start_monotonic + to_seconds

        sem = self.get_semaphore()
        acquired = False
        remaining_to_acquire = deadline - time.monotonic()
        if remaining_to_acquire <= 0:
            self._record_telemetry_failure(
                model, prompt, system, keep_alive, temperature, num_ctx, start_monotonic,
                timed_out=True, error=f"Ollama request timed out after {to_seconds}s waiting for execution slot",
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            raise OllamaTimeoutError(
                f"Ollama request timed out after {to_seconds}s waiting for execution slot"
            )

        try:
            await asyncio.wait_for(sem.acquire(), timeout=remaining_to_acquire)
            acquired = True
        except (asyncio.TimeoutError, TimeoutError) as exc:
            self._record_telemetry_failure(
                model, prompt, system, keep_alive, temperature, num_ctx, start_monotonic,
                timed_out=True, error=f"Ollama request timed out after {to_seconds}s waiting for execution slot",
                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
            )
            raise OllamaTimeoutError(
                f"Ollama request timed out after {to_seconds}s waiting for execution slot"
            ) from exc

        start: float = time.perf_counter()
        try:
            remaining_inference_seconds = deadline - time.monotonic()
            if remaining_inference_seconds <= 0:
                self._record_telemetry_failure(
                    model, prompt, system, keep_alive, temperature, num_ctx, start_monotonic,
                    timed_out=True, error=f"Ollama request timed out: exceeded its {to_seconds}s total deadline",
                    request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                )
                raise OllamaTimeoutError(
                    f"Ollama request timed out: exceeded its {to_seconds}s total deadline"
                )

            client = await self._get_client()

            timeout_scope = asyncio.timeout(remaining_inference_seconds)
            try:
                async with timeout_scope:
                    try:
                        response: httpx.Response = await client.post(
                            url, json=body, timeout=httpx.Timeout(remaining_inference_seconds)
                        )
                    except httpx.ConnectError as exc:
                        if "127.0.0.1" in self.base_url or "localhost" in self.base_url:
                            if await self._ensure_local_server_running():
                                retry_remaining = deadline - time.monotonic()
                                if retry_remaining > 0:
                                    try:
                                        response = await client.post(
                                            url, json=body, timeout=httpx.Timeout(retry_remaining)
                                        )
                                        exc = None
                                    except Exception as retry_exc:
                                        exc = retry_exc
                        if exc is not None:
                            self._record_telemetry_failure(
                                model, prompt, system, keep_alive, temperature, num_ctx, start, timed_out=False, error=str(exc),
                                request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                            )
                            raise OllamaConnectionError(
                                f"Could not connect to Ollama at {self.base_url}. "
                                "Is the Ollama server running?"
                            ) from exc

                    elapsed: float = time.perf_counter() - start
                    data: dict[str, Any] = response.json()
                    self.last_raw_response = data
            except TimeoutError as exc:
                if timeout_scope.expired():
                    self._record_telemetry_failure(
                        model, prompt, system, keep_alive, temperature, num_ctx, start_monotonic, timed_out=True,
                        error=f"Ollama request timed out: exceeded its {to_seconds}s total deadline",
                        request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                    )
                    raise OllamaTimeoutError(
                        f"Ollama request timed out: exceeded its {to_seconds}s total deadline"
                    ) from exc
                raise
            except httpx.TimeoutException as exc:
                self._record_telemetry_failure(
                    model, prompt, system, keep_alive, temperature, num_ctx, start_monotonic, timed_out=True,
                    error="Ollama HTTP operation timed out",
                    request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                )
                raise OllamaTimeoutError(
                    f"Ollama request timed out after {to_seconds}s"
                ) from exc

            if "error" in data:
                self._record_telemetry_failure(
                    model, prompt, system, keep_alive, temperature, num_ctx, start, timed_out=False, error=data["error"],
                    request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                )
                raise RuntimeError(data["error"])

            result: str = normalize_ollama_payload(data)
            prompt_tokens = data.get("prompt_eval_count", 0) or 0
            eval_tokens = data.get("eval_count", 0) or 0
            load_dur_ms = (data.get("load_duration", 0) or 0) / 1_000_000.0

            prev_model = self._last_loaded_model
            # Classify lifecycle state
            if load_dur_ms < 500.0 and self._last_loaded_model == model:
                lifecycle_state = "WARM"
            elif self._last_loaded_model and self._last_loaded_model != model and load_dur_ms >= 500.0:
                lifecycle_state = "SWITCH_RELOAD"
            else:
                lifecycle_state = "COLD"

            # If model switch occurred, record model switch telemetry
            if prev_model and prev_model != model:
                try:
                    from core.telemetry import telemetry, ModelSwitchTelemetry
                    sw = ModelSwitchTelemetry(
                        from_model=prev_model,
                        to_model=model,
                        switch_start=start,
                        switch_end=start + (load_dur_ms / 1000.0),
                        switch_duration_ms=load_dur_ms,
                        previous_residency_state="RESIDENT",
                        new_residency_state="RESIDENT",
                        load_duration_ms=load_dur_ms,
                    )
                    telemetry.record_model_switch(sw)
                except Exception:
                    pass

            self._last_loaded_model = model

            # Record telemetry metrics non-invasively
            try:
                self._record_telemetry_success(
                    model, prompt, system, keep_alive, temperature, num_ctx, start, elapsed, data, lifecycle_state,
                    prev_model=prev_model, request_id=request_id, mission_id=mission_id, task_id=task_id, stage=stage
                )
            except Exception:
                pass

            logger.debug(
                "OllamaClient.generate | model={} | state={} | load_dur={:.1f}ms | elapsed={:.3f}s",
                model,
                lifecycle_state,
                load_dur_ms,
                elapsed,
            )

            return NormalizedModelResponse(
                text=result,
                model=model,
                provider="ollama",
                input_tokens=prompt_tokens,
                output_tokens=eval_tokens,
                total_tokens=prompt_tokens + eval_tokens,
                latency_ms=elapsed * 1000.0,
                raw_response=result,
                lifecycle_state=lifecycle_state,
                success=True
            )
        finally:
            if acquired:
                sem.release()
            model_residency_manager.release_model(model, is_foreground=is_foreground)

    def _record_telemetry_success(
        self,
        model: str,
        prompt: str,
        system: str,
        keep_alive: Any,
        temperature: float,
        num_ctx: int,
        start_perf: float,
        elapsed_sec: float,
        data: dict,
        lifecycle_state: str = "UNKNOWN",
        prev_model: Optional[str] = None,
        request_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: str = "Tier 2 Verification",
    ):
        from core.telemetry import telemetry, ModelCallTelemetry, ContextBreakdown, sample_system_resources
        
        # Ollama reports durations in nanoseconds (1e-9 s -> 1e-6 ms)
        total_dur_ms = (data.get("total_duration", 0) or 0) / 1_000_000.0
        load_dur_ms = (data.get("load_duration", 0) or 0) / 1_000_000.0
        prompt_eval_dur_ms = (data.get("prompt_eval_duration", 0) or 0) / 1_000_000.0
        eval_dur_ms = (data.get("eval_duration", 0) or 0) / 1_000_000.0
        prompt_tokens = data.get("prompt_eval_count", 0) or 0
        output_tokens = data.get("eval_count", 0) or 0
        total_tokens = prompt_tokens + output_tokens

        thinking = data.get("thinking")
        thinking_text = str(thinking).strip() if thinking is not None and isinstance(thinking, str) else ""
        resp = data.get("response")
        resp_text = str(resp).strip() if resp is not None and isinstance(resp, str) else ""
        
        tok_per_sec = 0.0
        if eval_dur_ms > 0:
            tok_per_sec = (output_tokens / (eval_dur_ms / 1000.0))
        elif elapsed_sec > 0 and output_tokens > 0:
            tok_per_sec = output_tokens / elapsed_sec
            
        sys_info = sample_system_resources()
        
        # Context breakdown estimation
        ctx = ContextBreakdown(
            system_prompt_chars=len(system),
            user_prompt_chars=len(prompt),
            total_input_chars=len(system) + len(prompt),
            estimated_input_tokens=(len(system) + len(prompt)) // 4,
            exact_input_tokens=prompt_tokens if prompt_tokens > 0 else None,
        )

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        mc = ModelCallTelemetry(
            inference_id=uuid.uuid4().hex[:8],
            request_id=request_id or "",
            mission_id=mission_id or "",
            task_id=task_id or "",
            stage=stage,
            model=model,
            provider="ollama",
            start_time_monotonic=start_perf,
            end_time_monotonic=start_perf + elapsed_sec,
            start_timestamp=now_iso,
            end_timestamp=now_iso,
            first_token_timestamp=None,
            total_latency_ms=elapsed_sec * 1000.0,
            total_duration=total_dur_ms,
            load_duration_ms=load_dur_ms,
            load_duration=load_dur_ms,
            prompt_eval_duration_ms=prompt_eval_dur_ms,
            prompt_eval_duration=prompt_eval_dur_ms,
            eval_duration_ms=eval_dur_ms,
            eval_duration=eval_dur_ms,
            ttft_ms=load_dur_ms + prompt_eval_dur_ms,
            prompt_eval_count=data.get("prompt_eval_count"),
            eval_count=data.get("eval_count"),
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            tokens_per_second=round(tok_per_sec, 2),
            think_enabled=False,
            thinking_present=bool(thinking_text),
            thinking_available=False,
            thinking_length=len(thinking_text),
            final_response_length=len(resp_text),
            thinking_tokens=None,
            tool_call_count=1 if ('"tool"' in resp_text or '"action"' in resp_text) else 0,
            context=ctx,
            temperature=temperature,
            num_ctx=num_ctx,
            keep_alive=keep_alive,
            lifecycle_state=lifecycle_state,
            warm_cold_state=lifecycle_state,
            model_switch_state="SWITCH_RELOAD" if prev_model and prev_model != model else "SAME",
            previous_model=prev_model,
            requested_model=model,
            success=True,
            gpu_vram_used_mb=sys_info.get("gpu_vram_used_mb", 0.0),
            gpu_util_percent=sys_info.get("gpu_util_percent", 0.0),
            raw_timing_metadata={k: data[k] for k in ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration") if k in data},
        )
        
        # Attach to exact matching active request if any
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

    def _record_telemetry_failure(
        self,
        model: str,
        prompt: str,
        system: str,
        keep_alive: Any,
        temperature: float,
        num_ctx: int,
        start_perf: float,
        timed_out: bool,
        error: str,
        request_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: str = "Tier 2 Verification",
    ):
        from core.telemetry import telemetry, ModelCallTelemetry
        elapsed_sec = time.perf_counter() - start_perf
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mc = ModelCallTelemetry(
            inference_id=uuid.uuid4().hex[:8],
            request_id=request_id or "",
            mission_id=mission_id or "",
            task_id=task_id or "",
            stage=stage,
            model=model,
            provider="ollama",
            start_time_monotonic=start_perf,
            end_time_monotonic=time.perf_counter(),
            start_timestamp=now_iso,
            end_timestamp=now_iso,
            total_latency_ms=elapsed_sec * 1000.0,
            temperature=temperature,
            num_ctx=num_ctx,
            keep_alive=keep_alive,
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

    async def is_running(self, timeout: Optional[float] = None) -> bool:
        """Return True if Ollama responds with HTTP 200, False for any error.

        Never raises; safe to use as a startup health check.
        Uses fast HEALTH_CHECK_TIMEOUT (default 2.5s) instead of model execution timeout.
        """
        url: str = f"{self.base_url}/api/tags"
        check_timeout = timeout if timeout is not None else HEALTH_CHECK_TIMEOUT
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(check_timeout)
            ) as client:
                response: httpx.Response = await client.get(url)
            return response.status_code == 200
        except Exception:  # noqa: BLE001 — intentionally broad: method must never raise
            return False

    async def list_models(self, timeout: Optional[float] = None) -> list[str]:
        """Return a list of locally available Ollama model name strings.

        Returns an empty list on any error; never raises.
        Uses fast HEALTH_CHECK_TIMEOUT (default 2.5s) instead of model execution timeout.
        """
        url: str = f"{self.base_url}/api/tags"
        check_timeout = timeout if timeout is not None else HEALTH_CHECK_TIMEOUT
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(check_timeout)
            ) as client:
                response: httpx.Response = await client.get(url)
            data: dict[str, Any] = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:  # noqa: BLE001 — intentionally broad: method must never raise
            return []

    def get_cost_summary(self) -> dict[str, Any]:
        """Return summary of spending and caps (Ollama incurs no external API charges)."""
        return {
            "total_spent": 0.0,
            "cap": 25.0,
            "remaining": 25.0,
            "alert_threshold": 15.0,
        }

    async def arbitrate(
        self,
        task: str = "",
        tier1_output: str = "",
        tier2_issues: Optional[list[str]] = None,
        tool_result: str = "",
        escalation_reason: str = "",
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Arbitrate between Tier 1 proposal and Tier 2 concerns using Tier 3 model.
        Returns Tier3Response for full drop-in compatibility.
        """
        from config.model_config import TIER3_MODEL
        from models.openrouter_client import Tier3Response

        if not task and "task_description" in kwargs:
            task = str(kwargs["task_description"])
        if tier2_issues is None:
            tier2_issues = []
        if "tier1_tool_call" in kwargs and not tier1_output:
            tier1_output = str(kwargs["tier1_tool_call"])

        target_model = model or TIER3_MODEL

        system_prompt = (
            "You are an expert code reviewer arbitrating between two AI agents in HERMES. "
            "Agent 1 proposed a tool call. Agent 2 raised verification concerns. "
            "Your job is to make the authoritative final decision. "
            "Respond with your decision in 2-3 sentences. "
            "Be direct and specific about what action should proceed or be modified."
        )

        user_prompt = (
            f"TASK: {task}\n\n"
            f"AGENT 1 OUTPUT:\n{tier1_output[:600]}\n\n"
            f"AGENT 2 CONCERNS:\n" +
            "\n".join(f"- {issue}" for issue in tier2_issues) + "\n\n"
            f"TOOL RESULT:\n{tool_result[:400]}\n\n"
            f"ESCALATION REASON: {escalation_reason}\n\n"
            f"What is your final decision? Should the action proceed, be modified, or be rejected?"
        )

        start_time = time.monotonic()
        res = await self.generate(
            model=target_model,
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.0,
            num_predict=512,
            request_id=kwargs.get("request_id"),
            mission_id=kwargs.get("mission_id"),
            task_id=kwargs.get("task_id"),
            stage=kwargs.get("stage", "Tier 3 Arbitration"),
        )
        latency = time.monotonic() - start_time

        if not res.success:
            logger.warning(f"Ollama arbitration failed, falling back to T1 output: {res.error}")
            return Tier3Response(
                content=tier1_output,
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
                cost_usd=0.0,
                model=target_model,
                latency_seconds=latency,
                success=False,
                error=res.error,
            )

        return Tier3Response(
            content=res.text,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            cost_usd=0.0,
            model=target_model,
            latency_seconds=latency,
            success=True,
        )
