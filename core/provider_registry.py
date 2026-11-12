# core/provider_registry.py
"""
HERMES 2.x — Genuine Provider Availability Registry (Phase 5).

Tracks real per-provider runtime availability states independently of static config:
  - CONFIGURED
  - AUTHENTICATED
  - HEALTHY
  - DEGRADED
  - BILLING_BLOCKED
  - MODEL_UNAVAILABLE
  - COOLDOWN

API-key presence is NEVER equated with provider health.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from config.model_config import (
    TIER1_PROVIDER,
    TIER1_MODEL,
    TIER1_BASE_URL,
    TIER2_PROVIDER,
    TIER2_MODEL,
    TIER2_BASE_URL,
    TIER3_PROVIDER,
    TIER3_MODEL,
    TIER3_BASE_URL,
    TIER4_PROVIDER,
    TIER4_MODEL,
    TIER4_BASE_URL,
    NVIDIA_API_KEY,
    GEMINI_API_KEY,
    SAMBANOVA_API_KEY,
)


class ProviderAvailabilityState(str, Enum):
    CONFIGURED = "CONFIGURED"
    AUTHENTICATED = "AUTHENTICATED"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BILLING_BLOCKED = "BILLING_BLOCKED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    COOLDOWN = "COOLDOWN"


NON_ROUTABLE_STATES = {
    ProviderAvailabilityState.BILLING_BLOCKED,
    ProviderAvailabilityState.MODEL_UNAVAILABLE,
}


@dataclass
class ProviderAvailabilityEntry:
    tier: int
    provider: str
    configured_model: str
    endpoint: str
    has_credentials: bool
    state: ProviderAvailabilityState = ProviderAvailabilityState.CONFIGURED
    served_model: Optional[str] = None
    supported_models: List[str] = field(default_factory=list)
    corrective_action: Optional[str] = None
    last_error: Optional[str] = None
    last_http_status: Optional[int] = None
    last_ttfb_ms: Optional[float] = None
    last_ttft_reasoning_ms: Optional[float] = None
    last_ttft_content_ms: Optional[float] = None
    last_ttft_usable_ms: Optional[float] = None
    last_latency_ms: Optional[float] = None
    cooldown_until: Optional[float] = None
    checked_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["routable"] = self.is_routable()
        return d

    def is_routable(self, now: Optional[float] = None) -> bool:
        if self.state in NON_ROUTABLE_STATES:
            return False
        if self.state == ProviderAvailabilityState.COOLDOWN:
            ts = now if now is not None else time.time()
            if self.cooldown_until is not None and ts < self.cooldown_until:
                return False
        return bool(self.configured_model)


class ProviderAvailabilityRegistry:
    """Authoritative runtime availability state machine for configured tiers 1–4."""

    def __init__(self) -> None:
        self._entries: Dict[int, ProviderAvailabilityEntry] = {}
        self.reset_from_config()

    def reset_from_config(self) -> None:
        self._entries = {
            1: ProviderAvailabilityEntry(
                tier=1,
                provider=TIER1_PROVIDER,
                configured_model=TIER1_MODEL,
                endpoint=TIER1_BASE_URL,
                has_credentials=bool(NVIDIA_API_KEY or os.getenv("NVIDIA_API_KEY")),
                state=ProviderAvailabilityState.CONFIGURED,
            ),
            2: ProviderAvailabilityEntry(
                tier=2,
                provider=TIER2_PROVIDER,
                configured_model=TIER2_MODEL,
                endpoint=TIER2_BASE_URL,
                has_credentials=bool(GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")),
                state=ProviderAvailabilityState.CONFIGURED,
            ),
            3: ProviderAvailabilityEntry(
                tier=3,
                provider=TIER3_PROVIDER,
                configured_model=TIER3_MODEL,
                endpoint=TIER3_BASE_URL,
                has_credentials=bool(SAMBANOVA_API_KEY or os.getenv("SAMBANOVA_API_KEY")),
                state=ProviderAvailabilityState.CONFIGURED,
            ),
            4: ProviderAvailabilityEntry(
                tier=4,
                provider=TIER4_PROVIDER,
                configured_model=TIER4_MODEL,
                endpoint=TIER4_BASE_URL,
                has_credentials=True,
                state=ProviderAvailabilityState.CONFIGURED,
            ),
        }

    def get(self, tier: int) -> Optional[ProviderAvailabilityEntry]:
        entry = self._entries.get(tier)
        if entry and entry.state == ProviderAvailabilityState.COOLDOWN:
            if entry.cooldown_until is not None and time.time() >= entry.cooldown_until:
                entry.state = ProviderAvailabilityState.DEGRADED
                entry.cooldown_until = None
        return entry

    def get_all(self) -> Dict[int, ProviderAvailabilityEntry]:
        for t in list(self._entries.keys()):
            self.get(t)
        return dict(self._entries)

    def get_routable_tiers(self) -> List[int]:
        now = time.time()
        return [
            t
            for t in sorted(self._entries.keys())
            if self._entries[t].is_routable(now=now)
        ]

    def record_outcome(
        self,
        tier: int,
        *,
        success: bool,
        error: str = "",
        status_code: Optional[int] = None,
        ttfb_ms: Optional[float] = None,
        ttft_reasoning_ms: Optional[float] = None,
        ttft_content_ms: Optional[float] = None,
        ttft_usable_ms: Optional[float] = None,
        latency_ms: Optional[float] = None,
        served_model: Optional[str] = None,
        supported_models: Optional[List[str]] = None,
        corrective_action: Optional[str] = None,
        cooldown_seconds: Optional[float] = None,
    ) -> ProviderAvailabilityEntry:
        entry = self._entries.get(tier)
        if entry is None:
            entry = ProviderAvailabilityEntry(
                tier=tier,
                provider=f"tier_{tier}",
                configured_model="",
                endpoint="",
                has_credentials=False,
            )
            self._entries[tier] = entry

        now = time.time()
        entry.checked_at = now
        if ttfb_ms is not None:
            entry.last_ttfb_ms = round(float(ttfb_ms), 2)
        if ttft_reasoning_ms is not None:
            entry.last_ttft_reasoning_ms = round(float(ttft_reasoning_ms), 2)
        if ttft_content_ms is not None:
            entry.last_ttft_content_ms = round(float(ttft_content_ms), 2)
        if ttft_usable_ms is not None:
            entry.last_ttft_usable_ms = round(float(ttft_usable_ms), 2)
        if latency_ms is not None:
            entry.last_latency_ms = round(float(latency_ms), 2)
        if served_model:
            entry.served_model = served_model
        if supported_models is not None:
            entry.supported_models = list(supported_models)
        if status_code is not None:
            entry.last_http_status = status_code

        if success:
            entry.state = ProviderAvailabilityState.HEALTHY
            entry.last_error = None
            entry.cooldown_until = None
            entry.corrective_action = corrective_action
            return entry

        err_lower = (error or "").lower()
        entry.last_error = error[:300] if error else None

        # Billing / quota permanent block (HTTP 402 or explicit billing exhaustion)
        if status_code == 402 or any(
            k in err_lower
            for k in (
                "402",
                "payment_method_required",
                "payment required",
                "balance_units",
                "billing/payment required",
                "account balance exhausted",
                "out of credits",
            )
        ):
            entry.state = ProviderAvailabilityState.BILLING_BLOCKED
            entry.last_http_status = status_code or 402
            entry.cooldown_until = None
            entry.corrective_action = corrective_action or (
                f"Account credits exhausted or payment method required for {entry.provider}."
            )
            return entry

        # Missing / invalid model or offline local Ollama model
        is_missing_model = (
            status_code == 404
            or ("model" in err_lower and "not found" in err_lower)
            or "model_not_found" in err_lower
            or "unexpected model name format" in err_lower
        )
        if is_missing_model:
            entry.state = ProviderAvailabilityState.MODEL_UNAVAILABLE
            entry.last_http_status = status_code or 404
            entry.cooldown_until = None
            if corrective_action:
                entry.corrective_action = corrective_action
            elif entry.provider == "ollama" and entry.configured_model:
                entry.corrective_action = f"Install missing local model via CLI: ollama pull {entry.configured_model}"
            else:
                entry.corrective_action = f"Verify or update model identifier '{entry.configured_model}' for {entry.provider}."
            return entry

        # Cooldown or transient degradation (timeout, 503 high demand, connection reset)
        if cooldown_seconds is not None and cooldown_seconds > 0:
            entry.state = ProviderAvailabilityState.COOLDOWN
            entry.cooldown_until = now + float(cooldown_seconds)
        else:
            entry.state = ProviderAvailabilityState.DEGRADED
        if corrective_action:
            entry.corrective_action = corrective_action
        return entry

    async def refresh_all(self, *, probe_inference: bool = True, timeout: float = 10.0) -> Dict[int, ProviderAvailabilityEntry]:
        """Run non-destructive live verification probes for all 4 tiers."""
        results = await asyncio.gather(
            self.probe_tier(1, probe_inference=probe_inference, timeout=timeout),
            self.probe_tier(2, probe_inference=probe_inference, timeout=timeout),
            self.probe_tier(3, probe_inference=probe_inference, timeout=timeout),
            self.probe_tier(4, probe_inference=probe_inference, timeout=timeout),
            return_exceptions=True,
        )
        for t, res in zip((1, 2, 3, 4), results):
            if isinstance(res, Exception):
                self.record_outcome(t, success=False, error=f"{type(res).__name__}: {res}")
        return self.get_all()

    async def probe_tier(self, tier: int, *, probe_inference: bool = True, timeout: float = 10.0) -> ProviderAvailabilityEntry:
        entry = self._entries.get(tier)
        if entry is None:
            raise ValueError(f"Unknown provider tier: {tier}")

        prov = (entry.provider or "").lower()
        t0 = time.monotonic()

        if prov == "nvidia_nim":
            key = NVIDIA_API_KEY or os.getenv("NVIDIA_API_KEY", "")
            entry.has_credentials = bool(key)
            if not key:
                return self.record_outcome(
                    tier, success=False, error="NVIDIA_API_KEY missing",
                    corrective_action="Configure NVIDIA_API_KEY in .env"
                )
            if not probe_inference:
                entry.state = ProviderAvailabilityState.CONFIGURED
                entry.checked_at = time.time()
                return entry
            from models.nvidia_client import NvidiaClient
            client = None
            try:
                client = NvidiaClient(timeout_seconds=int(max(1, round(timeout))))
                res = await client.generate(
                    model=entry.configured_model,
                    prompt="Respond with OK",
                    max_tokens=256,
                    stream=True,
                    reasoning_effort="low",
                    allow_internal_retry=False,
                    timeout_seconds=timeout,
                )
                timings = getattr(res, "raw_timing_metadata", {}) or {}
                ttfb = timings.get("ttfb_ms", getattr(res, "ttfb_ms", None))
                ttft_r = timings.get("ttft_reasoning_ms", getattr(res, "ttft_reasoning_ms", None))
                ttft_c = timings.get("ttft_content_ms", getattr(res, "ttft_content_ms", None))
                ttft_u = timings.get("ttft_usable_ms", ttft_c or getattr(res, "ttfu_ms", None))
                if res.success:
                    return self.record_outcome(
                        tier,
                        success=True,
                        ttfb_ms=ttfb,
                        ttft_reasoning_ms=ttft_r,
                        ttft_content_ms=ttft_c,
                        ttft_usable_ms=ttft_u,
                        latency_ms=res.latency_ms,
                        served_model=getattr(res, "served_model", None) or entry.configured_model,
                    )
                return self.record_outcome(
                    tier, success=False, error=res.error or "NVIDIA NIM failed",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                )
            except Exception as exc:
                return self.record_outcome(
                    tier, success=False, error=f"{type(exc).__name__}: {exc}",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                )
            finally:
                if client is not None and hasattr(client, "aclose"):
                    try:
                        await client.aclose()
                    except Exception:
                        pass

        elif prov == "gemini":
            key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
            entry.has_credentials = bool(key)
            if not key:
                return self.record_outcome(
                    tier, success=False, error="GEMINI_API_KEY missing",
                    corrective_action="Configure GEMINI_API_KEY in .env"
                )
            from models.gemini_client import GeminiClient
            client = GeminiClient(api_key=key, model=entry.configured_model, timeout_seconds=timeout, tier=tier)
            try:
                models = await client.discover_models(timeout=min(timeout, 6.0))
                if models:
                    entry.supported_models = models
                    entry.state = ProviderAvailabilityState.AUTHENTICATED
                if entry.configured_model and models and entry.configured_model not in models:
                    return self.record_outcome(
                        tier,
                        success=False,
                        status_code=404,
                        error=f"Configured model '{entry.configured_model}' not found in /v1beta/models",
                        supported_models=models,
                        corrective_action=f"Update TIER2_MODEL to a supported model (e.g. {', '.join(models[:3])}).",
                    )
                if not probe_inference:
                    entry.checked_at = time.time()
                    return entry

                res = await client.generate(
                    model=entry.configured_model,
                    prompt="Respond with OK",
                    max_tokens=32,
                    stream=False,
                    timeout_seconds=timeout,
                )
                timings = getattr(res, "raw_timing_metadata", {}) or {}
                if res.success:
                    return self.record_outcome(
                        tier,
                        success=True,
                        ttfb_ms=timings.get("ttfb_ms", getattr(res, "ttfb_ms", None)),
                        ttft_reasoning_ms=timings.get("ttft_reasoning_ms", getattr(res, "ttft_reasoning_ms", None)),
                        ttft_content_ms=timings.get("ttft_content_ms", getattr(res, "ttft_content_ms", None)),
                        ttft_usable_ms=timings.get("ttft_usable_ms", timings.get("ttft_content_ms")),
                        latency_ms=res.latency_ms,
                        served_model=getattr(res, "served_model", None) or entry.configured_model,
                        supported_models=models,
                    )
                err_txt = res.error or "Gemini generation error"
                sc = 503 if "503" in err_txt else (429 if "429" in err_txt else (404 if "404" in err_txt else None))
                suggested = next((m for m in models if "gemini-3-flash-preview" in m or "gemini-3.5-flash" in m), None)
                hint = (
                    f"Configured '{entry.configured_model}' returned error/timeout ({err_txt[:100]}). "
                    + (f"Discovered supported sibling '{suggested}' in /v1beta/models; set TIER2_MODEL or ENABLE_GEMINI_PREVIEW_FALLBACK=true if approved." if suggested else "Retry after provider demand spike subsides.")
                )
                return self.record_outcome(
                    tier,
                    success=False,
                    status_code=sc,
                    error=err_txt,
                    latency_ms=res.latency_ms or (time.monotonic() - t0) * 1000.0,
                    supported_models=models,
                    corrective_action=hint,
                )
            except Exception as exc:
                return self.record_outcome(
                    tier,
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                )
            finally:
                await client.aclose()

        elif prov == "sambanova":
            key = SAMBANOVA_API_KEY or os.getenv("SAMBANOVA_API_KEY", "")
            entry.has_credentials = bool(key)
            if not key:
                return self.record_outcome(
                    tier, success=False, error="SAMBANOVA_API_KEY missing",
                    corrective_action="Configure SAMBANOVA_API_KEY in .env"
                )
            if not probe_inference:
                entry.state = ProviderAvailabilityState.CONFIGURED
                entry.checked_at = time.time()
                return entry
            from models.common_adapter import CommonProviderAdapter
            adapter = CommonProviderAdapter(
                provider_name=entry.provider,
                model_name=entry.configured_model,
                base_url=entry.endpoint,
                api_key=key,
                tier=tier,
                timeout_seconds=timeout,
            )
            try:
                res = await adapter.generate(
                    model=entry.configured_model,
                    prompt="Respond with OK",
                    max_tokens=16,
                )
                if res.success:
                    return self.record_outcome(
                        tier, success=True, latency_ms=res.latency_ms,
                        served_model=entry.configured_model,
                    )
                err_txt = res.error or "SambaNova failure"
                sc = 402 if ("402" in err_txt or "payment" in err_txt.lower() or "balance" in err_txt.lower()) else None
                return self.record_outcome(
                    tier,
                    success=False,
                    status_code=sc,
                    error=err_txt,
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                    corrective_action=(
                        "Add a payment method / billing balance at https://cloud.sambanova.ai/plans/billing"
                        if sc == 402 else None
                    ),
                )
            except Exception as exc:
                return self.record_outcome(
                    tier, success=False, error=f"{type(exc).__name__}: {exc}",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                )
            finally:
                await adapter.close()

        elif prov == "ollama":
            base = (entry.endpoint or "http://127.0.0.1:11434").rstrip("/")
            candidates = [base]
            if "localhost" in base:
                candidates.append(base.replace("localhost", "127.0.0.1"))
            elif "127.0.0.1" in base:
                candidates.append(base.replace("127.0.0.1", "localhost"))

            installed_models: List[str] = []
            daemon_reachable = False
            last_conn_err = ""
            async with httpx.AsyncClient(timeout=min(timeout, 4.0)) as client:
                for ep in candidates:
                    try:
                        r = await client.get(f"{ep}/api/tags")
                        if r.status_code == 200:
                            daemon_reachable = True
                            payload = r.json()
                            installed_models = [
                                m.get("name", "")
                                for m in payload.get("models", [])
                                if m.get("name")
                            ]
                            break
                    except Exception as conn_exc:
                        last_conn_err = f"{type(conn_exc).__name__}: {conn_exc}"

            if not daemon_reachable:
                return self.record_outcome(
                    tier,
                    success=False,
                    status_code=503,
                    error=f"Ollama daemon unreachable at {base} ({last_conn_err or 'connection refused'})",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                    supported_models=[],
                    corrective_action=f"Start the Ollama service and install the model: ollama serve && ollama pull {entry.configured_model}",
                )

            if entry.configured_model not in installed_models:
                return self.record_outcome(
                    tier,
                    success=False,
                    status_code=404,
                    error=f"Configured model '{entry.configured_model}' is not installed locally (installed: {installed_models})",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                    supported_models=installed_models,
                    corrective_action=f"ollama pull {entry.configured_model}",
                )

            if not probe_inference:
                entry.supported_models = installed_models
                entry.state = ProviderAvailabilityState.AUTHENTICATED
                entry.checked_at = time.time()
                return entry

            from models.ollama_client import OllamaClient
            oclient = OllamaClient(base_url=base, timeout_seconds=int(timeout))
            try:
                res = await oclient.generate(
                    model=entry.configured_model,
                    prompt="Respond with OK",
                    num_predict=10,
                    timeout_seconds=timeout,
                )
                if res.success:
                    return self.record_outcome(
                        tier,
                        success=True,
                        latency_ms=res.latency_ms,
                        served_model=entry.configured_model,
                        supported_models=installed_models,
                    )
                return self.record_outcome(
                    tier,
                    success=False,
                    error=res.error or "Ollama inference error",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                    supported_models=installed_models,
                )
            except Exception as exc:
                return self.record_outcome(
                    tier,
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    latency_ms=(time.monotonic() - t0) * 1000.0,
                    supported_models=installed_models,
                )

        return entry


_GLOBAL_REGISTRY = ProviderAvailabilityRegistry()


def get_provider_registry() -> ProviderAvailabilityRegistry:
    return _GLOBAL_REGISTRY
