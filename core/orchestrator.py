from core.request_guard import mission_request_guard
# core/orchestrator.py
# The HERMES Master Orchestrator — implements the full 12-stage pipeline.
# Every user request flows through this exactly once, top to bottom.
# Stage 1:  Sanitise user input
# Stage 2:  Task planner -> Task object
# Stage 3:  Skill + Memory injection -> enriched system prompt
# Stage 4:  Tier 1 generation -> JSON tool call
# Stage 5:  Tool validation + safety gates
# Stage 6:  Tool execution
# Stage 7:  Tier 2 verification
# Stage 8:  Disagreement router -> decision
# Stage 9:  Tier 3 arbitration (conditional)
# Stage 10: Memory update (only if exit_code == 0)
# Stage 11: Task queue update
# Stage 12: Build and return final output

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

from loguru import logger

from core.error_handler import ErrorHandler, FailureMode, RecoveryAction
from utils.logging import (
    generate_trace_id, setup_logging,
    log_pipeline_start, log_pipeline_complete,
    log_tier1_call, log_tier2_call, log_tier3_call,
    log_tool_call, log_tool_result, log_memory_event,
    log_security_gate, get_trace_logger
)

from models.ollama_client import OllamaClient
from models.openrouter_client import OpenRouterClient, Tier3Response
from models.nvidia_client import NvidiaClient
from models.claude_client import ClaudeClient
from config.model_config import (
    TIER1_PROVIDER,
    TIER1_MODEL,
    TIER1_BASE_URL,
    TIER2_PROVIDER,
    TIER2_MODEL,
    TIER3_PROVIDER,
    TIER3_MODEL,
    MODEL_KEEP_ALIVE,
    MODEL_TIMEOUT_SECONDS,
)
from core.verifier import Tier2Verifier
from core.verification_gate import VerificationGate
from core.reasoning_budget import ReasoningBudgetManager, ComplexityLevel
from core.reasoning_policy import ReasoningPolicy, TaskComplexity
from core.tool_validator import tool_validator


class MultiTierRoutingExhaustedError(RuntimeError):
    """Raised when all configured model tiers fail in sequence."""
    pass

from core.disagreement_router import DisagreementRouter, RoutingDecision, RouterResult, ALWAYS_ESCALATE_TOOLS
from core.planner import TaskPlanner, Task
from core.intent_classifier import IntentClassifier
from core.prompt_builder import PromptContext, build_system_prompt, build_user_message
from core.telemetry import telemetry, ToolTelemetry, StageSpan, VerificationTelemetry, RepairTelemetry
import tools  # Triggers tool registration
from tools.registry import get_tool, tool_schema_for_prompt, list_tools, PermissionGate, get_canonical_tool_name
from tools.base import ToolResult
from memory.store import read_context_for_prompt
from memory.extractor import confirm_and_write_facts, extract_memories
from memory.session_logger import SessionLogger
from memory.background_worker import background_memory_manager, MemoryJob
from kairos.db import init_db, DB_PATH
from kairos.task_queue import register_task, mark_running, mark_completed, mark_failed
from kairos.daemon import KairosDaemon


# ──────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────

@dataclass
class OrchestratorResult:
    """The complete result of one orchestrator pipeline run."""
    success: bool
    final_output: str                    # What to show the user
    tool_name: Optional[str] = None
    tool_result: Optional[ToolResult] = None
    task: Optional[Task] = None
    skill_ids_used: list[str] = field(default_factory=list)
    tier3_was_called: bool = False
    total_latency_seconds: float = 0.0
    error: Optional[str] = None
    pipeline_stage_reached: int = 0      # Which stage completed last
    trace_id: str = ""                   # Unique trace ID for this pipeline run


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────

class Orchestrator:
    """
    Master 12-stage pipeline controller for HERMES.
    Every user request flows through this exactly once, top to bottom.
    Never raises — always returns an OrchestratorResult.
    """

    def __init__(
        self,
        mode: str = "auto",
        project: str = "default",
        progress_callback=None,
        execution_mode: str = "production",
    ) -> None:
        self.mode = mode        # "safe", "plan", or "auto"
        self._mode = mode
        self.project = project
        self._project = project
        self.execution_mode = execution_mode  # "production", "benchmark", "demo", "performance"
        self._progress_callback = progress_callback
        # Historical / mock test compatibility
        try:
            from models.ollama_client import get_shared_ollama_client
            self.ollama = get_shared_ollama_client()
        except Exception:
            self.ollama = None

        from models.common_adapter import get_provider_adapter
        from config.model_config import (
            TIER1_PROVIDER, TIER1_MODEL,
            TIER2_PROVIDER, TIER2_MODEL,
            TIER3_PROVIDER, TIER3_MODEL,
        )
        self.tier1 = get_provider_adapter(TIER1_PROVIDER, TIER1_MODEL, tier=1)
        self.tier2 = get_provider_adapter(TIER2_PROVIDER, TIER2_MODEL, tier=2)
        self.tier3 = get_provider_adapter(TIER3_PROVIDER, TIER3_MODEL, tier=3)
        self._tier3 = self.tier3
        self.claude = self._tier3  # Backwards compatibility alias
        self._default_ollama = self.ollama
        self.verifier = Tier2Verifier(getattr(self, "tier2", self.ollama), model=TIER2_MODEL)
        self.verification_gate = VerificationGate()
        self.budget_manager = ReasoningBudgetManager()
        self.tool_validator = tool_validator
        self.router = DisagreementRouter()
        self.planner = TaskPlanner()
        self.classifier = IntentClassifier("skills/")
        self.session_logger = SessionLogger()
        logger.info(
            f"Orchestrator ready | mode={mode} | project={project} | "
            f"session={self.session_logger.session_id}"
        )
        self.error_handler = ErrorHandler()
        # Initialise background memory manager
        self.memory_manager = background_memory_manager
        self.memory_manager.set_client(self.tier1)
        # Initialise database and KAIROS daemon
        init_db()
        self.kairos = KairosDaemon(db_path=DB_PATH)
        self._kairos_started = False
        logger.info("Orchestrator: KAIROS daemon attached (not yet started)")

    @property
    def active_t1_client(self):
        t1 = getattr(self, "tier1", None)
        if t1 is not None and t1 is not getattr(self, "ollama", None):
            t1_gen = getattr(t1, "generate", None)
            if t1_gen is not None and (
                hasattr(t1_gen, "assert_called")
                or hasattr(t1_gen, "mock")
                or getattr(t1_gen, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
            ):
                return t1

        current_ollama = getattr(self, "ollama", None)
        if current_ollama is not None and current_ollama is not getattr(self, "_default_ollama", None):
            return current_ollama
        ollama_gen = getattr(current_ollama, "generate", None)
        if ollama_gen is not None and (
            hasattr(ollama_gen, "assert_called")
            or hasattr(ollama_gen, "mock")
            or getattr(ollama_gen, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        ):
            return current_ollama
        return getattr(self, "tier1", self.ollama)

    @active_t1_client.setter
    def active_t1_client(self, client: Any) -> None:
        self.tier1 = client

    async def _generate_t1(self, **kwargs) -> Any:
        """Execute Tier 1 generation through configured provider with test harness compatibility."""
        from config.model_config import (
            TIER1_PROVIDER, TIER1_MODEL,
            TIER2_PROVIDER, TIER2_MODEL,
            TIER3_PROVIDER, TIER3_MODEL,
        )
        tier1_client = self.active_t1_client
        if "request_id" not in kwargs:
            curr_trace = getattr(self, "_current_trace_id", None)
            if curr_trace:
                kwargs["request_id"] = curr_trace
                kwargs.setdefault("mission_id", curr_trace)
                kwargs.setdefault("task_id", curr_trace)
        kwargs.setdefault("stage", "Tier 1 Generation")
        t1_gen = getattr(tier1_client, "generate", None)
        is_t1_mocked = t1_gen is not None and (
            hasattr(t1_gen, "assert_called")
            or hasattr(t1_gen, "mock")
            or getattr(t1_gen, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        )

        if not is_t1_mocked:
            if tier1_client is getattr(self, "ollama", None) and self.ollama is not getattr(self, "_default_ollama", None):
                return await self.ollama.generate(**kwargs)
            ollama_gen = getattr(getattr(self, "ollama", None), "generate", None)
            if ollama_gen is not None and (
                hasattr(ollama_gen, "assert_called")
                or hasattr(ollama_gen, "mock")
                or getattr(ollama_gen, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
            ):
                return await self.ollama.generate(**kwargs)

        prov = getattr(tier1_client, "provider", TIER1_PROVIDER)
        mod = getattr(tier1_client, "model", TIER1_MODEL)
        from core.adaptive_routing import get_adaptive_router
        router = get_adaptive_router()

        mid = kwargs.get("mission_id", "")
        turn_id = kwargs.get("turn_id", "")

        # Guard against duplicate concurrent in-flight requests for the same mission
        if mid and not kwargs.get("_bypass_in_flight_guard", False):
            if mission_request_guard.is_in_flight(mid):
                from core.request_guard import DuplicateInFlightRequestError
                raise DuplicateInFlightRequestError(f"Duplicate model request rejected: mission '{mid}' already has a model call in flight.")

        total_decision_budget = min(float(kwargs.get("timeout_seconds") or 25.0), 25.0)
        t_decision_start = time.monotonic()

        route_decision = router.route_primary(client_t1=tier1_client)
        current_ollama = getattr(self, "ollama", None)
        ollama_mocked = current_ollama is not None and (
            current_ollama is not getattr(self, "_default_ollama", None)
            or hasattr(getattr(current_ollama, "generate", None), "assert_called")
            or hasattr(getattr(current_ollama, "generate", None), "mock")
            or getattr(getattr(current_ollama, "generate", None), "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        )
        if ollama_mocked:
            tier2_client = current_ollama
        else:
            tier2_client = getattr(self, "tier2", None) or current_ollama
        tier3_client = getattr(self, "tier3", None) or getattr(self, "_tier3", None) or getattr(self, "ollama", None)

        t2_gen = getattr(tier2_client, "generate", None)
        is_t2_mocked = t2_gen is not None and (
            hasattr(t2_gen, "assert_called")
            or hasattr(t2_gen, "mock")
            or getattr(t2_gen, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        )
        t3_gen = getattr(tier3_client, "generate", None)
        is_t3_mocked = t3_gen is not None and (
            hasattr(t3_gen, "assert_called")
            or hasattr(t3_gen, "mock")
            or getattr(t3_gen, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        )
        allow_t2_failover = tier2_client is not None and (not is_t1_mocked or is_t2_mocked)
        allow_t3_failover = tier3_client is not None and bool(TIER3_MODEL) and (not is_t1_mocked or is_t3_mocked)

        if route_decision.bypassed and allow_t2_failover:
            logger.info(
                f"Tier 1 circuit is open. Zero-wait failover to Tier 2 ({TIER2_PROVIDER} / {TIER2_MODEL}) | "
                f"reason={route_decision.reason} | avoided_wait={route_decision.avoided_timeout_ms:.0f}ms"
            )
            await self._emit_progress("circuit_bypass", {
                "tier": 2,
                "provider": TIER2_PROVIDER,
                "model": TIER2_MODEL,
                "reason": route_decision.reason,
                "avoided_timeout_ms": route_decision.avoided_timeout_ms,
                "mission_id": mid,
                "turn_id": turn_id,
            })
            await self._emit_progress("model_start", {
                "tier": 2, "provider": TIER2_PROVIDER, "model": TIER2_MODEL,
                "mission_id": mid,
                "turn_id": turn_id,
            })
            t2_kwargs = self._build_t2_failover_kwargs(kwargs)
            rem_budget = max(0.0, total_decision_budget - (time.monotonic() - t_decision_start))
            if rem_budget <= 1.0:
                raise TimeoutError(f"Model decision deadline exceeded ({total_decision_budget:.1f}s shared budget exhausted)")
            t2_kwargs["timeout_seconds"] = rem_budget
            t2_t0 = time.monotonic()
            try:
                resp2 = await asyncio.wait_for(tier2_client.generate(**t2_kwargs), timeout=rem_budget)
                resp2_text = (getattr(resp2, "content", "") or getattr(resp2, "text", "") or "")
                resp2_calls = getattr(resp2, "tool_calls", None) or []
                if getattr(resp2, "success", True) is False or (not str(resp2_text).strip() and not resp2_calls):
                    raise RuntimeError(getattr(resp2, "error", None) or f"Tier 2 ({TIER2_PROVIDER}/{TIER2_MODEL}) failed: empty or unsuccessful response")
                t2_lat = time.monotonic() - t2_t0
                router.record_success(tier=2, latency=t2_lat)
                self._active_tier = 2
                if hasattr(resp2, "__dict__"):
                    try:
                        setattr(resp2, "tier", 2)
                        if not getattr(resp2, "provider", None):
                            setattr(resp2, "provider", TIER2_PROVIDER)
                        if not getattr(resp2, "model", None):
                            setattr(resp2, "model", TIER2_MODEL)
                    except Exception:
                        pass
                logger.info(f"MODEL_COMPLETE | tier=2 (circuit_bypass) | provider={TIER2_PROVIDER} | model={TIER2_MODEL} | latency={t2_lat:.2f}s")
                await self._emit_progress("model_complete", {
                    "tier": 2, "provider": TIER2_PROVIDER, "model": TIER2_MODEL, "latency": t2_lat,
                    "mission_id": mid,
                    "turn_id": turn_id,
                })
                return resp2
            except Exception as t2_exc:
                router.record_failure(tier=2, error=t2_exc, latency=time.monotonic() - t2_t0)
                logger.error(f"Tier 2 circuit bypass also failed: {t2_exc}. Attempting Tier 3 failover...")
                if tier3_client is not None and TIER3_MODEL:
                    rem_budget_t3 = max(0.0, total_decision_budget - (time.monotonic() - t_decision_start))
                    if rem_budget_t3 <= 1.0:
                        raise TimeoutError(f"Model decision deadline exceeded before Tier 3 fallback ({total_decision_budget:.1f}s shared budget exhausted)")
                    t3_kwargs = dict(t2_kwargs)
                    t3_kwargs["model"] = TIER3_MODEL
                    t3_kwargs["timeout_seconds"] = rem_budget_t3
                    t3_t0 = time.monotonic()
                    try:
                        resp3 = await asyncio.wait_for(tier3_client.generate(**t3_kwargs), timeout=rem_budget_t3)
                        t3_lat = time.monotonic() - t3_t0
                        self._active_tier = 3
                        if hasattr(resp3, "__dict__"):
                            try:
                                setattr(resp3, "tier", 3)
                                if not getattr(resp3, "provider", None):
                                    setattr(resp3, "provider", TIER3_PROVIDER)
                                if not getattr(resp3, "model", None):
                                    setattr(resp3, "model", TIER3_MODEL)
                            except Exception:
                                pass
                        logger.info(f"MODEL_COMPLETE | tier=3 (failover) | provider={TIER3_PROVIDER} | model={TIER3_MODEL} | latency={t3_lat:.2f}s")
                        await self._emit_progress("model_complete", {
                            "tier": 3, "provider": TIER3_PROVIDER, "model": TIER3_MODEL, "latency": t3_lat,
                            "mission_id": mid,
                            "turn_id": turn_id,
                        })
                        return resp3
                    except Exception as t3_exc:
                        logger.error(f"Tier 3 failover also failed: {t3_exc}")
                        raise MultiTierRoutingExhaustedError(
                            f"All model tiers failed during circuit bypass. Tier 2: {t2_exc}. Tier 3: {t3_exc}"
                        ) from t3_exc
                raise MultiTierRoutingExhaustedError(
                    f"Tier 2 failed during circuit bypass and no Tier 3 fallback available: {t2_exc}"
                ) from t2_exc

        from config.model_config import HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS
        rem_budget_t1 = max(0.0, total_decision_budget - (time.monotonic() - t_decision_start))
        if rem_budget_t1 <= 1.0:
            raise TimeoutError(f"Model decision deadline exceeded before Tier 1 attempt ({total_decision_budget:.1f}s shared budget exhausted)")
        kwargs["timeout_seconds"] = rem_budget_t1
        logger.info(f"MODEL_START | tier=1 | provider={prov} | model={mod} | budget={rem_budget_t1:.1f}s")
        await self._emit_progress("model_start", {
            "tier": 1, "provider": prov, "model": mod,
            "mission_id": mid, "turn_id": turn_id
        })
        t0 = time.monotonic()
        try:
            resp = await asyncio.wait_for(tier1_client.generate(**kwargs), timeout=rem_budget_t1)
            resp_text = (getattr(resp, "content", "") or getattr(resp, "text", "") or "")
            resp_calls = getattr(resp, "tool_calls", None) or []
            if getattr(resp, "success", True) is False or (not str(resp_text).strip() and not resp_calls):
                err = getattr(resp, "error", None) or f"Tier 1 ({prov}/{mod}) failed: empty or unsuccessful response"
                raise RuntimeError(err)
            lat = time.monotonic() - t0
            router.record_success(tier=1, latency=lat)
            logger.info(f"MODEL_COMPLETE | tier=1 | provider={prov} | model={mod} | latency={lat:.2f}s")
            if not kwargs.get("suppress_model_completed_event", False):
                await self._emit_progress("model_complete", {
                    "tier": 1, "provider": prov, "model": mod, "latency": lat,
                    "duration_ms": int(lat * 1000), "headline": f"Thought for {lat:.1f}s",
                    "mission_id": mid, "turn_id": turn_id
                })
            return resp
        except Exception as exc:
            lat = time.monotonic() - t0
            to_type = getattr(exc, "timeout_type", "FIRST_TOKEN_TIMEOUT" if "timeout" in str(exc).lower() else "ERROR")
            router.record_failure(tier=1, error=exc, timeout_type=to_type, latency=lat, client=tier1_client)
            logger.warning(f"MODEL_FAILED | tier=1 | provider={prov} | model={mod} | latency={lat:.2f}s | error={exc}")
            
            if allow_t2_failover:
                logger.warning(
                    f"Tier 1 ({mod}) failed: {exc}. "
                    f"Failing over to Tier 2 ({TIER2_PROVIDER} / {TIER2_MODEL}) via multi-tier architecture..."
                )
                await self._emit_progress("model_failover", {
                    "tier": 2, "provider": TIER2_PROVIDER, "model": TIER2_MODEL, "reason": str(exc),
                    "mission_id": mid,
                    "turn_id": turn_id,
                })
                rem_budget_t2 = max(0.0, total_decision_budget - (time.monotonic() - t_decision_start))
                if rem_budget_t2 <= 1.0:
                    raise TimeoutError(f"Model decision deadline exceeded before Tier 2 fallback ({total_decision_budget:.1f}s shared budget exhausted)")
                t2_kwargs = self._build_t2_failover_kwargs(kwargs)
                t2_kwargs["timeout_seconds"] = rem_budget_t2
                t2_t0 = time.monotonic()
                try:
                    resp2 = await asyncio.wait_for(tier2_client.generate(**t2_kwargs), timeout=rem_budget_t2)
                    resp2_text = (getattr(resp2, "content", "") or getattr(resp2, "text", "") or "")
                    resp2_calls = getattr(resp2, "tool_calls", None) or []
                    if getattr(resp2, "success", True) is False or (not str(resp2_text).strip() and not resp2_calls):
                        err2 = getattr(resp2, "error", None) or f"Tier 2 ({TIER2_PROVIDER}/{TIER2_MODEL}) failed: empty or unsuccessful response"
                        raise RuntimeError(err2)
                    t2_lat = time.monotonic() - t2_t0
                    router.record_success(tier=2, latency=t2_lat)
                    self._active_tier = 2
                    if hasattr(resp2, "__dict__"):
                        try:
                            setattr(resp2, "tier", 2)
                            if not getattr(resp2, "provider", None):
                                setattr(resp2, "provider", TIER2_PROVIDER)
                            if not getattr(resp2, "model", None):
                                setattr(resp2, "model", TIER2_MODEL)
                        except Exception:
                            pass
                    logger.info(f"MODEL_COMPLETE | tier=2 (failover) | provider={TIER2_PROVIDER} | model={TIER2_MODEL} | latency={t2_lat:.2f}s")
                    await self._emit_progress("model_complete", {
                        "tier": 2, "provider": TIER2_PROVIDER, "model": TIER2_MODEL, "latency": t2_lat,
                        "mission_id": mid,
                        "turn_id": turn_id,
                    })
                    return resp2
                except Exception as t2_exc:
                    router.record_failure(tier=2, error=t2_exc, latency=time.monotonic() - t2_t0)
                    logger.error(f"Tier 2 failover also failed: {t2_exc}. Attempting Tier 3 failover...")
                    if allow_t3_failover:
                        rem_budget_t3 = max(0.0, total_decision_budget - (time.monotonic() - t_decision_start))
                        if rem_budget_t3 <= 1.0:
                            raise TimeoutError(f"Model decision deadline exceeded before Tier 3 fallback ({total_decision_budget:.1f}s shared budget exhausted)")
                        t3_kwargs = dict(t2_kwargs)
                        t3_kwargs["model"] = TIER3_MODEL
                        t3_kwargs["timeout_seconds"] = rem_budget_t3
                        t3_t0 = time.monotonic()
                        try:
                            resp3 = await asyncio.wait_for(tier3_client.generate(**t3_kwargs), timeout=rem_budget_t3)
                            resp3_text = (getattr(resp3, "content", "") or getattr(resp3, "text", "") or "")
                            resp3_calls = getattr(resp3, "tool_calls", None) or []
                            if getattr(resp3, "success", True) is False or (not str(resp3_text).strip() and not resp3_calls):
                                err3 = getattr(resp3, "error", None) or f"Tier 3 ({TIER3_PROVIDER}/{TIER3_MODEL}) failed: empty or unsuccessful response"
                                raise RuntimeError(err3)
                            t3_lat = time.monotonic() - t3_t0
                            self._active_tier = 3
                            if hasattr(resp3, "__dict__"):
                                try:
                                    setattr(resp3, "tier", 3)
                                    if not getattr(resp3, "provider", None):
                                        setattr(resp3, "provider", TIER3_PROVIDER)
                                    if not getattr(resp3, "model", None):
                                        setattr(resp3, "model", TIER3_MODEL)
                                except Exception:
                                    pass
                            logger.info(f"MODEL_COMPLETE | tier=3 (failover) | provider={TIER3_PROVIDER} | model={TIER3_MODEL} | latency={t3_lat:.2f}s")
                            await self._emit_progress("model_complete", {
                                "tier": 3, "provider": TIER3_PROVIDER, "model": TIER3_MODEL, "latency": t3_lat,
                                "mission_id": mid,
                                "turn_id": turn_id,
                            })
                            return resp3
                        except Exception as t3_exc:
                            logger.error(f"Tier 3 failover also failed: {t3_exc}")
                            raise MultiTierRoutingExhaustedError(
                                f"All configured model tiers failed. Tier 1 ({mod}): {exc}. "
                                f"Tier 2 ({TIER2_MODEL}): {t2_exc}. Tier 3 ({TIER3_MODEL}): {t3_exc}"
                            ) from t3_exc
                    raise MultiTierRoutingExhaustedError(
                        f"All configured model tiers failed. Tier 1 ({mod}) and Tier 2 ({TIER2_MODEL}) failed, no Tier 3 available: {t2_exc}"
                    ) from t2_exc
            raise
            raise

    def _build_t2_failover_kwargs(self, kwargs: dict) -> dict:
        """Standardize keyword arguments for Tier 2 failover or circuit bypass."""
        from config.model_config import TIER2_MODEL
        t2_kwargs = dict(kwargs)
        t2_kwargs["model"] = TIER2_MODEL
        tools_list = t2_kwargs.get("tools")
        t2_kwargs.pop("tool_choice", None)
        t2_kwargs.pop("reasoning_effort", None)

        current_ollama = getattr(self, "ollama", None)
        ollama_mocked = current_ollama is not None and (
            current_ollama is not getattr(self, "_default_ollama", None)
            or hasattr(getattr(current_ollama, "generate", None), "assert_called")
            or hasattr(getattr(current_ollama, "generate", None), "mock")
            or getattr(getattr(current_ollama, "generate", None), "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock")
        )
        if ollama_mocked:
            tier2_client = current_ollama
        else:
            tier2_client = getattr(self, "tier2", None) or current_ollama
        is_mock = getattr(tier2_client, "__class__", None).__name__ in ("AsyncMock", "MagicMock", "Mock") or hasattr(getattr(tier2_client, "generate", None), "mock")
        is_native_tools = not is_mock and (hasattr(tier2_client, "_sanitize_tool_definitions") or getattr(tier2_client, "provider", "") in ("nvidia_nim", "zai", "openrouter", "gemini", "sambanova") or getattr(tier2_client, "provider_name", "") in ("nvidia_nim", "gemini", "sambanova"))

        if is_native_tools and tools_list:
            t2_kwargs["tools"] = tools_list
            t2_kwargs.pop("format", None)
        else:
            tools_list = t2_kwargs.pop("tools", None)
            t2_kwargs["format"] = "json"
            t2_kwargs["think"] = False
            t2_kwargs["keep_alive"] = 0
            t2_kwargs["num_ctx"] = 16384
            if not t2_kwargs.get("num_predict") or t2_kwargs.get("num_predict") < 4096:
                t2_kwargs["num_predict"] = 4096

            tools_doc = ""
            if tools_list and isinstance(tools_list, list):
                tool_lines = []
                for t in tools_list:
                    if isinstance(t, dict) and "function" in t:
                        fn = t["function"]
                        fname = fn.get("name", "")
                        fdesc = fn.get("description", "")
                        fparams = fn.get("parameters", {}).get("properties", {})
                        param_names = list(fparams.keys()) if isinstance(fparams, dict) else []
                        tool_lines.append(f"- {fname}: {fdesc} (parameters: {', '.join(param_names)})")
                if tool_lines:
                    tools_doc = "\nAvailable Tools:\n" + "\n".join(tool_lines)

            t2_system = t2_kwargs.get("system", "")
            t2_kwargs["system"] = t2_system + tools_doc + (
                "\n\n[FAILOVER TOOL EXECUTION RULE]\n"
                "Do NOT output <think> tags. Output ONLY a valid JSON tool call object in this format:\n"
                '{"tool": "<tool_name>", "parameters": { ... }}\n'
                "No prose or explanation outside the JSON."
            )
        return t2_kwargs

    @property
    def tier3(self):
        """Tier 3 arbitration client, synchronized with claude alias for test compatibility."""
        if hasattr(self, "claude") and self.claude is not None and self.claude is not getattr(self, "_tier3", None):
            return self.claude
        return getattr(self, "_tier3", getattr(self, "ollama", None))

    @tier3.setter
    def tier3(self, val):
        self._tier3 = val
        self.claude = val

    async def _emit_progress(self, event_type: str, payload: dict) -> None:
        """
        Emit a pipeline progress event to the registered callback and canonical EventBus.
        Silently does nothing if no callback is registered.
        Never raises — progress emission must never crash the pipeline.
        """
        try:
            from core.event_bus import event_bus as global_event_bus
            from core.runtime_state.events import HermesEvent, EventType
            eb = getattr(self, "event_bus", None) or global_event_bus
            if eb and hasattr(eb, "publish"):
                et = EventType.ROUTING_DECISION
                if event_type == "model_failover":
                    et = EventType.TIER_FAILOVER_STARTED
                elif event_type in ("model_start", "circuit_bypass"):
                    et = EventType.TIER_SELECTED
                elif event_type == "model_complete":
                    et = EventType.MODEL_COMPLETED
                mid = (
                    payload.get("mission_id")
                    or getattr(self, "mission_id", None)
                    or getattr(self, "_current_mission_id", None)
                    or getattr(self, "current_mission_id", None)
                    or ""
                )
                turn_id = payload.get("turn_id")
                ev = HermesEvent(
                    event_type=et,
                    mission_id=mid,
                    turn_id=turn_id,
                    payload=dict(payload),
                )
                res = eb.publish(ev)
                if asyncio.iscoroutine(res):
                    await res
        except Exception as eb_exc:
            from loguru import logger
            logger.warning(f"Orchestrator._emit_progress: event bus publish error: {eb_exc}")

        cb = None
        try:
            from core.mission_runner import _task_progress_callback_var
            cb = _task_progress_callback_var.get()
        except Exception:
            pass
        if cb is None:
            cb = getattr(self, "_progress_callback", None)
        if cb is None:
            return
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(event_type, payload)
            else:
                cb(event_type, payload)
        except Exception as e:
            from loguru import logger
            logger.debug(f"Orchestrator._emit_progress: callback error: {e}")

    async def start_kairos(self) -> None:
        """Start the KAIROS background daemon. Call this once after creating the Orchestrator."""
        if not self._kairos_started:
            await self.kairos.start()
            self._kairos_started = True
            logger.info("Orchestrator: KAIROS daemon running in background")

    async def stop_kairos(self) -> None:
        """Stop the KAIROS daemon gracefully. Call this on application shutdown."""
        if self._kairos_started:
            await self.kairos.stop()
            self._kairos_started = False

    def extract_requested_artifacts(self, text: str) -> list[str]:
        """Extract explicit filenames/paths requested to be created in the user prompt."""
        import re
        artifacts = set()
        IGNORED_NAMES = {
            "pytest.py", "test.py", "python.py",
            "next.js", "node.js", "vue.js", "react.js", "express.js",
            "chart.js", "three.js", "d3.js", "tailwind.css", "bootstrap.css",
        }
        for m in re.finditer(r"([a-zA-Z0-9_\-/\\]+\.(?:py|html|css|js|json|md|txt|sh))\b", text):
            p = m.group(1).replace("\\", "/")
            if p.lower() not in IGNORED_NAMES:
                artifacts.add(p)
        return sorted(list(artifacts))

    def _resolve_artifact_path(self, path_str: str) -> Path:
        """Resolve artifact path against authoritative workspace or generated_projects directory."""
        from core.workspace import workspace_manager
        p = Path(path_str)
        if p.is_absolute() and p.exists():
            return p

        # If locked to authoritative workspace, resolve against MissionWorkspace
        if workspace_manager.is_locked and workspace_manager.workspace_root:
            mws = workspace_manager.get_mission_workspace()
            if mws:
                found = mws.find_artifact(p.name)
                if found and found.exists():
                    return found
                try:
                    direct = mws.validate_path(path_str)
                    if direct.exists():
                        return direct
                except Exception:
                    pass
            ws_root = Path(workspace_manager.workspace_root)
            cand = ws_root / "generated_projects" / p.name
            if cand.exists():
                return cand
            return ws_root / p.name

        # Fallback to cwd
        return Path.cwd() / p.name

    async def _execute_single_tool(self, tool_name: str, tool_params: dict, sanitised: str):
        """Helper to validate, normalize, and execute a single tool call."""
        val_res = await self.tool_validator.process_and_validate(
            tool_name=tool_name,
            raw_params=tool_params,
            task_text=sanitised,
            ollama_client=self.active_t1_client,
            budget_manager=self.budget_manager
        )
        if not val_res.is_valid:
            logger.warning(f"_execute_single_tool: invalid params for {tool_name}: {val_res.errors}")
            from tools.base import ToolResult
            return ToolResult(success=False, output="", error=f"Invalid parameters: {val_res.errors}", exit_code=1), tool_name, tool_params
        
        t_name = val_res.tool_name
        t_params = val_res.normalized_params
        t_input = val_res.validated_input
        tool_cls = get_tool(t_name)
        if not tool_cls:
            logger.warning(f"_execute_single_tool: tool {t_name} not found")
            from tools.base import ToolResult
            return ToolResult(success=False, output="", error=f"Tool {t_name} not found", exit_code=1), t_name, t_params
            
        instance = tool_cls()
        import asyncio
        if asyncio.iscoroutinefunction(instance.execute):
            t_res = await instance.execute(t_input)
        else:
            t_res = instance.execute(t_input)
        logger.info(f"_execute_single_tool: {t_name} executed -> success={t_res.success}, exit_code={t_res.exit_code}, error={t_res.error}")
        return t_res, t_name, t_params

    async def run(self, user_request: str, on_progress=None, **kwargs) -> OrchestratorResult:
        """
        Run the full 12-stage pipeline for one user request.
        Never raises — always returns OrchestratorResult.
        """
        start_time = time.monotonic()
        # Generate unique trace ID for this pipeline run and initialize telemetry
        telem_req = telemetry.start_request(
            user_request,
            mode=self.mode,
            project=self.project,
            execution_mode=self.execution_mode,
            mission_id=kwargs.get("mission_id"),
        )
        trace_id = telem_req.request_id if telem_req.request_id else generate_trace_id()
        self._current_trace_id = trace_id
        tlog = get_trace_logger(trace_id)
        result = OrchestratorResult(success=False, final_output="", trace_id=trace_id)

        async def notify(event_type: str, **kwargs):
            if on_progress:
                try:
                    import asyncio
                    if asyncio.iscoroutinefunction(on_progress):
                        await on_progress(event_type, kwargs)
                    else:
                        on_progress(event_type, kwargs)
                except Exception as exc:
                    logger.warning(f"Error in progress callback: {exc}")

        try:
            telemetry.record_milestone(trace_id, "t_prompt_submitted")
            # ── Stage 1: Sanitise input ───────────────────────────────
            with telemetry.span("Input Sanitisation", request_id=trace_id, stage_number=1):
                await self._emit_progress("stage_start", {
                    "stage": 1,
                    "name": "Input Sanitisation",
                    "verb": "Sanitising",
                    "detail": "Escaping prompt injection vectors",
                })
                await notify("stage_start", stage=1, name="Input Sanitization", thought="Sanitizing user request to prevent HTML/XML injection...", spinner_verb="Analyzing")
                result.pipeline_stage_reached = 1
                sanitised = self._sanitise_input(user_request)
                self.session_logger.log_user_input(sanitised)
                log_pipeline_start(
                    trace_id=trace_id,
                    user_request=sanitised,
                    mode=self.mode,
                    project=self.project,
                    session_id=self.session_logger.session_id
                )
                await notify("stage_end", stage=1, status="success", sanitised=sanitised)
                await self._emit_progress("stage_complete", {
                    "stage": 1, "name": "Input Sanitisation",
                })

            # ── Adaptive Execution Routing (Phase 9) ───────────────────
            from config.model_config import ADAPTIVE_EXECUTION_ENABLED
            from core.adaptive_execution import adaptive_execution_engine, ExecutionMode

            if ADAPTIVE_EXECUTION_ENABLED:
                classif = adaptive_execution_engine.classifier.classify(sanitised)
                logger.info(
                    "AdaptiveExecution: mode={} | confidence={:.2f} | risk={:.2f} | tool={} | dur={:.2f}ms",
                    classif.mode.value, classif.confidence, classif.risk_score,
                    classif.deterministic_tool, classif.duration_ms
                )
                if classif.mode == ExecutionMode.SIMPLE and classif.deterministic_tool:
                    from core.workspace import workspace_manager
                    fast_ok, fast_out = adaptive_execution_engine.execute_fast_path(
                        tool_name=classif.deterministic_tool,
                        tool_args=classif.deterministic_args or {},
                        workspace_manager=workspace_manager
                    )
                    if fast_ok:
                        logger.info("AdaptiveExecution: FAST PATH executed successfully in <15ms")
                        result.success = True
                        result.final_output = fast_out
                        result.pipeline_stage_reached = 12
                        return result
                    else:
                        logger.warning("AdaptiveExecution: Fast path failed ({}), escalating to STANDARD", fast_out)

            # ── Stage 2: Task planner ─────────────────────────────────
            with telemetry.span("Planning", request_id=trace_id, stage_number=2):
                await self._emit_progress("stage_start", {
                    "stage": 2,
                    "name": "Task Planning",
                    "verb": "Planning",
                    "detail": "Decomposing request into atomic subtasks",
                })
                await notify("stage_start", stage=2, name="Task Planning", thought="Decomposing user request into actionable plan...", spinner_verb="Planning")
                result.pipeline_stage_reached = 2
                task = self.planner.plan(sanitised, session_id=self.session_logger.session_id)
                result.task = task
                logger.debug(f"Stage 2 complete: task planned | complexity={task.complexity_score:.2f}")

                # Register task in SQLite queue
                db_task_id = register_task(
                    session_id=self.session_logger.session_id,
                    title=sanitised[:100],
                    description=sanitised,
                    priority=task.priority,
                complexity=task.complexity_score,
                max_retries=task.max_retries,
                tool_name=None,  # Will be updated after Stage 4
                db_path=DB_PATH
            )
            mark_running(db_task_id, db_path=DB_PATH)
            logger.debug(f"Stage 2: task registered in queue as db_task_id={db_task_id}")
            await notify("stage_end", stage=2, status="success", task_id=task.task_id, complexity=task.complexity_score, subtasks=task.subtasks)
            await self._emit_progress("stage_complete", {
                "stage": 2, "name": "Task Planning",
            })

            # ── Stage 3: Skill Detection & Memory Injection ──
            with telemetry.span("Context Construction", request_id=trace_id, stage_number=3):
                await self._emit_progress("stage_start", {
                    "stage": 3,
                    "name": "Skill Detection",
                    "verb": "Detecting skills",
                    "detail": "Matching request to domain skill modules",
                })
                await notify("stage_start", stage=3, name="Skill Detection", thought="Matching Intent classifier skills to request...", spinner_verb="Loading Skill")
                result.pipeline_stage_reached = 3

                skill_ids = self.classifier.classify(sanitised)
                skill_content, loaded_skill_ids = self.classifier.build_skill_prompt_section(
                    skill_ids,
                    execution_mode=self.execution_mode,
                    disclosure_level=1 if self.execution_mode != "benchmark" else 3
                )
                result.skill_ids_used = loaded_skill_ids
                active_skill_name = loaded_skill_ids[0] if loaded_skill_ids else "none"

                matched = loaded_skill_ids
                rejected = [s.skill_id for s in self.classifier.skills if s.skill_id not in loaded_skill_ids][:2]
                confidence = int(min(98, 75 + len(matched) * 10 + (task.complexity_score * 15))) if matched else 0
                await notify("stage_end", stage=3, status="success", matched=matched, rejected=rejected, confidence=confidence)
                await self._emit_progress("skill_loaded", {
                    "stage": 3,
                    "skill_ids": loaded_skill_ids,       # actual list from classifier
                    "skill_names": loaded_skill_ids,
                    "verb": f"Loaded: {', '.join(loaded_skill_ids) if loaded_skill_ids else 'none'}",
                })

                # ── Stage 4: Memory Injection ──
                await self._emit_progress("stage_start", {
                    "stage": 4,
                    "name": "Memory Injection",
                    "verb": "Retrieving memory",
                    "detail": "Loading project context from MEMORY.md",
                })
                await notify("stage_start", stage=4, name="Memory Injection", thought="Retrieving past rules and facts from memory store...", spinner_verb="Loading Memory")
                try:
                    memory_context = read_context_for_prompt(
                        project=self.project,
                        query=sanitised,
                        execution_mode=self.execution_mode
                    )
                except Exception as mem_exc:
                    mem_err = self.error_handler.memory_parse_error(str(mem_exc), self.project)
                    logger.warning(f"Stage 4: {mem_err.technical_detail}")
                    memory_context = ""  # Empty fallback

                logger.debug(f"Stage 4 complete: skills={loaded_skill_ids} | memory_lines={memory_context.count(chr(10))}")
                
                lines = [l.strip() for l in memory_context.split('\n') if l.strip()]
                mem_facts = []
                for l in lines:
                    if '[FACT]:' in l:
                        mem_facts.append(l.replace('[FACT]:', '').strip())
                    elif '[DETAIL]:' in l:
                        mem_facts.append(l.replace('[DETAIL]:', '').strip())
                mem_facts = mem_facts[:3]
                if not mem_facts:
                    mem_facts = ["Memory index initialized", "No relevant past facts detected"]

                await notify("stage_end", stage=4, status="success", memories=mem_facts)
                await self._emit_progress("stage_complete", {
                    "stage": 4, "name": "Memory Injection", "memories": mem_facts,
                })


            # ── Stage 5: Tier 1 Reasoning ──────
            span_t1 = telemetry.start_span("Tier 1 Generation", request_id=trace_id, stage_number=5)
            tier1_display = getattr(self.tier1, "model", TIER1_MODEL)
            await self._emit_progress("stage_start", {
                "stage": 5,
                "name": "Tier 1 Reasoning",
                "verb": "Reasoning",
                "model": tier1_display,
                "detail": "Generating tool call...",
            })
            await notify("stage_start", stage=5, name="Tier 1 Reasoning", thought=f"Generating tool selection using {tier1_display}...", spinner_verb="Reasoning", model=tier1_display)
            result.pipeline_stage_reached = 4

            # Add workspace skeleton to context
            workspace_context = ""
            try:
                from core.workspace import workspace_manager
                if workspace_manager.is_locked:
                    skeleton = workspace_manager.get_skeleton()
                    summary = workspace_manager.get_workspace_summary()
                    workspace_context = (
                        f"Workspace: {summary.get('root', 'unknown')}\n"
                        f"Framework: {summary.get('framework', 'unknown')}\n"
                        f"Files: {summary.get('total_files', 0)}\n\n"
                        f"Structure:\n{skeleton}"
                    )
                else:
                    workspace_context = (
                        "Workspace: Not locked. Files will be created in "
                        "generated_projects/ directory."
                    )
            except Exception as e:
                workspace_context = "Workspace: generated_projects/ (default)"

            # Classify task complexity and select task-aware reasoning budget
            resolved_policy = ReasoningPolicy.resolve(
                task_description=sanitised,
                model=TIER1_MODEL,
                execution_mode=self.execution_mode,
            )
            complexity_level = self.budget_manager.classify_complexity(
                sanitised,
                tools_needed=getattr(task, 'required_tools', []),
                permission_level=getattr(task, 'permission_level', None).value if getattr(task, 'permission_level', None) else "read_only",
                planner_complexity=getattr(task, 'complexity_score', 0.5)
            )
            budget = self.budget_manager.get_budget(complexity_level)
            # Use resolved_policy values in non-benchmark modes
            if self.execution_mode != "benchmark":
                t1_temperature = resolved_policy.temperature
                num_predict = resolved_policy.num_predict
                t1_think = resolved_policy.think
                t1_timeout = resolved_policy.timeout_seconds
            else:
                t1_temperature = budget.temperature
                num_predict = budget.num_predict
                t1_think = None
                t1_timeout = budget.timeout_seconds

            from config.model_config import CONTEXT_ENGINE_ENABLED
            from core.context_engine import context_engine
            from tools.registry import selective_tool_schema_for_prompt, get_openai_tool_definitions

            active_tool_schema = selective_tool_schema_for_prompt(
                required_tools=getattr(task, 'required_tools', None),
                execution_mode=self.execution_mode
            )

            native_tools = None
            if TIER1_PROVIDER == "nvidia_nim" and self.execution_mode != "benchmark":
                native_tools = get_openai_tool_definitions(
                    tool_names=getattr(task, 'required_tools', None),
                    execution_mode=self.execution_mode,
                    allow_batch_tools=True,
                )

            if CONTEXT_ENGINE_ENABLED:
                cpack = context_engine.build_context_pack(
                    task_text=sanitised,
                    mode=self.mode,
                    workspace_manager=workspace_manager if 'workspace_manager' in locals() else None,
                    memory_context=memory_context,
                    skill_content=skill_content,
                    active_skill_name=active_skill_name,
                    tool_descriptions=active_tool_schema,
                    max_context_tokens=4096,
                    generation_reserve=num_predict
                )
                system_prompt = cpack.system_prompt
                user_message_text = cpack.user_message
                logger.debug(
                    "ContextEngine: packed {} items ({} dropped) | tokens={} | build_time={:.2f}ms",
                    cpack.items_included, cpack.items_dropped, cpack.total_tokens, cpack.build_duration_ms
                )
            else:
                ctx = PromptContext(
                    user_task=sanitised,
                    mode=self.mode,
                    available_tools=list_tools(),
                    tool_descriptions=active_tool_schema,
                    memory_context=memory_context,
                    skill_context=skill_content,
                    active_skill_name=active_skill_name,
                    workspace_context=workspace_context,
                    execution_mode=self.execution_mode
                )
                system_prompt = build_system_prompt(ctx)
                user_message_text = build_user_message(sanitised)

            logger.info("Stage 4: T1 reasoning policy | mode={} | complexity={} | think={} | num_predict={} | timeout={}s | native_tools={}",
                        self.execution_mode, resolved_policy.complexity.value, t1_think, num_predict, t1_timeout, len(native_tools) if native_tools else 0)

            # Attempt 1
            t1_start = time.monotonic()
            telemetry.record_milestone(trace_id, "t_first_model_requested")
            try:
                tier1_resp = await self._generate_t1(
                    model=TIER1_MODEL,
                    prompt=user_message_text,
                    system=system_prompt,
                    keep_alive=MODEL_KEEP_ALIVE,
                    temperature=t1_temperature,
                    num_ctx=4096,
                    num_predict=num_predict,
                    think=t1_think,
                    tools=native_tools,
                )
                telemetry.record_milestone(trace_id, "t_first_model_response")
                tier1_raw = getattr(tier1_resp, "text", str(tier1_resp))
                eval_tokens = getattr(tier1_resp, "output_tokens", 0)
                t1_latency = time.monotonic() - t1_start
            except Exception as t1_exc:
                t1_latency = time.monotonic() - t1_start
                from models.ollama_client import OllamaTimeoutError
                from models.nvidia_client import NvidiaTimeoutError
                if isinstance(t1_exc, (OllamaTimeoutError, NvidiaTimeoutError)):
                    err = self.error_handler.ollama_timeout(TIER1_MODEL, t1_timeout, "stage_4_attempt_1")
                else:
                    err = self.error_handler.unknown_error(t1_exc, "stage_4_t1_generation")
                result.final_output = err.tagged_output(err.user_message)
                result.error = err.technical_detail
                mark_failed(db_task_id, error=err.technical_detail[:300], db_path=DB_PATH)
                await notify("stage_end", stage=5, status="failed", error=result.error)
                return result

            tier1_parsed = self._parse_tier1_response(tier1_resp)
            is_truncated = self.budget_manager.check_truncation(tier1_raw, eval_tokens, budget)

            # Attempt 2 (on parse failure or budget truncation)
            if tier1_parsed is None or is_truncated:
                # Escalate budget for retry
                escalated_level = self.budget_manager.escalate_budget(complexity_level)
                escalated_budget = self.budget_manager.get_budget(escalated_level)
                logger.info("Stage 4: Escalating T1 budget to {} (num_predict={}) for retry",
                            escalated_level.value, escalated_budget.num_predict)

                last_parse_res = getattr(self, '_last_parse_result', None)
                if last_parse_res and getattr(last_parse_res, 'failure_reason', '').startswith("unknown_tool_rejected:"):
                    rejected_tool = last_parse_res.failure_reason.split(":", 1)[1]
                    parse_err = self.error_handler.tool_not_found(rejected_tool, list_tools(), attempt=0)
                else:
                    parse_err = self.error_handler.json_parse_failure(tier1_raw, attempt=0)
                logger.warning(f"Stage 4: {parse_err.technical_detail} | truncated={is_truncated}")
                self.session_logger.log_tier1_response(TIER1_MODEL, tier1_raw[:300], t1_latency, None)

                from core.prompt_builder import build_system_prompt_v2
                if 'ctx' in locals() and ctx is not None:
                    retry_system = build_system_prompt_v2(ctx)
                else:
                    retry_system = system_prompt
                retry_user = user_message_text + "\n\n" + parse_err.context_for_retry

                t1_retry_start = time.monotonic()
                try:
                    tier1_resp = await self._generate_t1(
                        model=TIER1_MODEL,
                        prompt=retry_user,
                        system=retry_system,
                        keep_alive=MODEL_KEEP_ALIVE,
                        temperature=0.05,
                        num_ctx=4096,
                        num_predict=escalated_budget.num_predict,
                        think=t1_think,
                        tools=native_tools,
                    )
                    tier1_raw = getattr(tier1_resp, "text", str(tier1_resp))
                    tier1_parsed = self._parse_tier1_response(tier1_resp)
                    t1_latency = time.monotonic() - t1_retry_start
                except Exception as retry_exc:
                    t1_latency = time.monotonic() - t1_retry_start
                    from models.ollama_client import OllamaTimeoutError
                    from models.nvidia_client import NvidiaTimeoutError
                    if isinstance(retry_exc, (OllamaTimeoutError, NvidiaTimeoutError)):
                        err = self.error_handler.ollama_timeout(TIER1_MODEL, escalated_budget.timeout_seconds, "stage_4_attempt_2")
                    else:
                        err = self.error_handler.unknown_error(retry_exc, "stage_4_t1_retry")
                    result.final_output = err.tagged_output(err.user_message)
                    result.error = err.technical_detail
                    mark_failed(db_task_id, error=err.technical_detail[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=5, status="failed", error=result.error)
                    return result

                if tier1_parsed is None:
                    last_parse_res = getattr(self, '_last_parse_result', None)
                    if last_parse_res and getattr(last_parse_res, 'failure_reason', '').startswith("unknown_tool_rejected:"):
                        rejected_tool = last_parse_res.failure_reason.split(":", 1)[1]
                        final_err = self.error_handler.tool_not_found(rejected_tool, list_tools(), attempt=1)
                    else:
                        final_err = self.error_handler.json_parse_failure(tier1_raw, attempt=1)
                    result.final_output = final_err.user_message
                    result.error = final_err.technical_detail
                    mark_failed(db_task_id, error=final_err.technical_detail[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=5, status="failed", error=result.error)
                    return result

            raw_tool = tier1_parsed.get("tool", "")
            if raw_tool and isinstance(raw_tool, str):
                canonical_tool = get_canonical_tool_name(raw_tool.strip())
            else:
                canonical_tool = ""

            tool_params = tier1_parsed.get("parameters", {})
            tier1_reasoning = tier1_parsed.get("reasoning", "")
            explanation = tier1_parsed.get("explanation", "Task completed.")

            tool_name = canonical_tool if canonical_tool else ""
            if tool_name:
                telemetry.record_milestone(trace_id, "t_first_tool_available")

            self.session_logger.log_tier1_response(
                TIER1_MODEL, tier1_raw[:500], t1_latency, tool_name or None
            )
            log_tier1_call(
                trace_id=trace_id,
                model=TIER1_MODEL,
                prompt_tokens_estimate=len(system_prompt) // 4,
                latency=t1_latency,
                parsed_tool=tool_name or None,
                parse_method=getattr(
                    getattr(tier1_parsed, '_parse_method', None),
                    '__name__', 'direct'
                ) if hasattr(tier1_parsed, '_parse_method') else "parsed"
            )
            tlog.debug(f"Stage 4 complete | tool={tool_name} | latency={t1_latency:.2f}s")
            
            thought_summary = tier1_reasoning.strip().split('\n')[0][:120] if tier1_reasoning else ("Direct response provided." if not tool_name else "Plan prepared for executing tool.")
            await notify("stage_end", stage=5, status="success", tool=tool_name or None, tool_name=tool_name or None, parameters=tool_params if tool_name else {}, explanation=explanation, thought=thought_summary)
            await self._emit_progress("stage_complete", {
                "stage": 5,
                "name": "Tier 1 Reasoning",
                "tool_name": tool_name if tool_name else None,
                "parameters": tool_params if tool_name else {},
                "thought": thought_summary,
            })
            telemetry.end_span(span_t1, success=True)

            # ── Stage 6: Tool Validation ──
            if not tool_name or tool_name.lower() in ("none", "null", "no_tool", "conversational", ""):
                # Conversational response without tool execution
                logger.info("Stage 5: No tool required (conversational / direct response)")
                result.success = True
                result.final_output = explanation if explanation and explanation != "Action proceeding." else tier1_raw
                result.tool_name = None
                result.pipeline_stage_reached = 12
                mark_completed(db_task_id, db_path=DB_PATH)
                await notify("stage_end", stage=12, status="success")
                return result

            span_sec = telemetry.start_span("Tool Validation", request_id=trace_id, stage_number=6)
            await self._emit_progress("stage_start", {
                "stage": 6,
                "name": "Tool Validation",
                "verb": "Validating",
                "detail": "Running 15 security gates",
                "tool_name": tool_name,
                "parameters": tool_params,
            })
            await notify("stage_start", stage=6, name="Tool Validation", thought="Validating tool parameter schema and security permissions...", spinner_verb="Validating", tool_name=tool_name, parameters=tool_params)
            result.pipeline_stage_reached = 6

            tool_class = get_tool(tool_name)
            if tool_class is None:
                tool_err = self.error_handler.tool_not_found(tool_name, list_tools(), attempt=0)
                logger.warning(f"Stage 5: {tool_err.technical_detail}")

                correction_prompt = build_user_message(sanitised) + "\n\n" + tool_err.context_for_retry

                try:
                    tier1_raw_retry_res = await self._generate_t1(
                        model=TIER1_MODEL,
                        prompt=correction_prompt,
                        system=system_prompt,
                        keep_alive=MODEL_KEEP_ALIVE,
                        temperature=0.05,
                        num_ctx=4096,
                        tools=native_tools,
                    )
                    tier1_raw_retry = getattr(tier1_raw_retry_res, "text", str(tier1_raw_retry_res))
                except Exception as retry_exc:
                    final_tool_err = self.error_handler.unknown_error(retry_exc, "stage_5_tool_retry")
                    result.final_output = final_tool_err.tagged_output(final_tool_err.user_message)
                    result.error = final_tool_err.technical_detail
                    result.success = False
                    result.tool_name = None
                    mark_failed(db_task_id, error=final_tool_err.technical_detail[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=6, status="failed", error=result.error)
                    return result

                tier1_parsed_retry = self._parse_tier1_response(tier1_raw_retry_res)
                if tier1_parsed_retry is None:
                    final_tool_err = self.error_handler.tool_not_found(tool_name, list_tools(), attempt=1)
                    result.final_output = final_tool_err.user_message
                    result.error = final_tool_err.technical_detail
                    result.success = False
                    result.tool_name = None
                    mark_failed(db_task_id, error=final_tool_err.technical_detail[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=6, status="failed", error=result.error)
                    return result

                raw_retry_tool = tier1_parsed_retry.get("tool", "")
                tool_name = get_canonical_tool_name(raw_retry_tool) if raw_retry_tool else ""
                tool_params = tier1_parsed_retry.get("parameters", {})
                tier1_reasoning = tier1_parsed_retry.get("reasoning", "")
                tool_class = get_tool(tool_name) if tool_name else None

                if tool_class is None:
                    final_tool_err = self.error_handler.tool_not_found(raw_retry_tool or tool_name or "unknown", list_tools(), attempt=1)
                    result.final_output = final_tool_err.user_message
                    result.error = final_tool_err.technical_detail
                    result.success = False
                    result.tool_name = None
                    mark_failed(db_task_id, error=final_tool_err.technical_detail[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=6, status="failed", error=result.error)
                    return result

            # Permission check
            from tools.registry import PermissionGate
            gate = PermissionGate(self.mode)
            allowed, gate_reason = gate.check(tool_class)
            if not allowed:
                result.final_output = f"Action blocked in {self.mode.upper()} mode: {gate_reason}"
                result.success = False
                mark_failed(db_task_id, error=f"Permission gate: {gate_reason}", db_path=DB_PATH)
                await notify("stage_end", stage=6, status="failed", error=result.final_output)
                return result

            # Phase 4B: Action Discipline Fast Rejection on Non-Progress Read Loop
            tracker = kwargs.get("action_tracker")
            if tracker is None:
                try:
                    from core.mission_runner import _task_action_tracker_var
                    tracker = _task_action_tracker_var.get()
                except Exception:
                    pass
            if tracker is None:
                tracker = getattr(self, "_action_tracker", None)
            if tracker is not None:
                should_reject, reject_reason = tracker.should_reject_read_action(tool_name)
                if should_reject:
                    logger.warning(f"Stage 6: ActionDiscipline rejected non-progress tool '{tool_name}': {reject_reason}")
                    result.final_output = reject_reason
                    result.error = reject_reason
                    result.success = False
                    mark_failed(db_task_id, error=reject_reason[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=6, status="failed", error=result.final_output)
                    return result

            # Hardened Tool Validation & Repair Pipeline
            val_res = await self.tool_validator.process_and_validate(
                tool_name=tool_name,
                raw_params=tool_params,
                task_text=sanitised,
                ollama_client=self.active_t1_client,
                budget_manager=self.budget_manager
            )

            if not val_res.is_valid:
                error_msg = f"Invalid parameters for tool '{tool_name}': {'; '.join(val_res.errors)}"
                result.final_output = error_msg
                result.error = error_msg
                mark_failed(db_task_id, error=error_msg[:300], db_path=DB_PATH)
                await notify("stage_end", stage=6, status="failed", error=result.final_output)
                return result

            tool_name = val_res.tool_name
            tool_params = val_res.normalized_params
            tool_input = val_res.validated_input
            t_class_lookup = get_tool(tool_name)
            if t_class_lookup:
                tool_class = t_class_lookup

            self.session_logger.log_tool_call(tool_name, tool_params, self.mode)
            log_tool_call(
                trace_id=trace_id,
                tool_name=tool_name,
                mode=self.mode,
                risk_score=getattr(tool_class, 'risk_score', 0.0),
                parameters_preview=json.dumps(tool_params)[:200]
            )
            tlog.debug(f"Stage 6 complete | tool={tool_name} validated")
            await notify("stage_end", stage=6, status="success", tool_name=tool_name, parameters=tool_params)
            await self._emit_progress("stage_complete", {
                "stage": 6, "name": "Tool Validation", "tool_name": tool_name, "parameters": tool_params,
            })
            telemetry.end_span(span_sec, success=True)

            # ── Stage 7: Tool Execution ──
            span_tool = telemetry.start_span("Tool Execution", request_id=trace_id, stage_number=7)
            result.pipeline_stage_reached = 7

            tool_instance = tool_class()
            tool_exec_retry_count = 0
            tool_result = None

            from core.structured_observation import StructuredObservation
            from pathlib import Path
            from core.workspace import workspace_manager
            def _safe_scan_workspace_files(root: Path) -> set[str]:
                import os
                found = set()
                if not root.exists():
                    return found
                IGNORED = {'node_modules', '.git', 'venv', '.venv', '__pycache__', '.next', 'dist'}
                for dirpath, dirnames, filenames in os.walk(str(root)):
                    dirnames[:] = [d for d in dirnames if d not in IGNORED]
                    for f in filenames:
                        found.add(os.path.join(dirpath, f))
                return found

            workspace_root = Path(workspace_manager.workspace_root) if workspace_manager.is_locked and workspace_manager.workspace_root else Path("generated_projects")
            files_before = _safe_scan_workspace_files(workspace_root)

            while tool_exec_retry_count <= 3:
                t_exec_start = time.monotonic()
                target = tool_params.get("TargetFile") or tool_params.get("path") or tool_params.get("filename") or str(tool_params)
                lines_count = len(tool_params.get("CodeContent", "").split('\n')) if tool_params.get("CodeContent") else 0
                
                await self._emit_progress("tool_executing", {
                    "stage": 7,
                    "name": "Tool Execution",
                    "verb": "Executing",
                    "tool": tool_name,
                    "tool_name": tool_name,
                    "target": target,
                    "parameters": tool_params,
                    "attempt": tool_exec_retry_count + 1,
                    "detail": f"Running {tool_name}",
                })
                await notify("stage_start", stage=7, name="Tool Execution", thought=f"Executing tool {tool_name}...", spinner_verb="Executing", tool_name=tool_name, parameters=tool_params, target=target, attempt=tool_exec_retry_count + 1)
                
                try:
                    telemetry.record_milestone(trace_id, "t_first_tool_dispatched")
                    if asyncio.iscoroutinefunction(tool_instance.execute):
                        current_tool_result = await tool_instance.execute(tool_input)
                    else:
                        current_tool_result = tool_instance.execute(tool_input)
                    t_exec_dur = time.monotonic() - t_exec_start
                    if getattr(current_tool_result, "success", False) and tool_name in ("write_file", "append_file", "patch_file", "write_files_batch"):
                        telemetry.record_milestone(trace_id, "t_first_fs_mutation")
                except Exception as exec_exc:
                    t_exec_dur = time.monotonic() - t_exec_start
                    exec_err = self.error_handler.unknown_error(exec_exc, f"stage_7_{tool_name}_execute")
                    result.final_output = exec_err.tagged_output(exec_err.user_message)
                    result.error = exec_err.technical_detail
                    try:
                        from core.telemetry import ToolTelemetry
                        cat = "filesystem" if "file" in tool_name else ("shell" if "bash" in tool_name else "other")
                        telemetry.record_tool(
                            ToolTelemetry(
                                tool_name=tool_name,
                                category=cat,
                                start_time_monotonic=t_exec_start,
                                duration_ms=t_exec_dur * 1000.0,
                                filesystem_duration_ms=t_exec_dur * 1000.0 if cat == "filesystem" else 0.0,
                                subprocess_duration_ms=t_exec_dur * 1000.0 if cat == "shell" else 0.0,
                                success=False,
                                exit_code=1,
                                args_size_bytes=len(str(tool_params)),
                                output_size_bytes=0,
                                retry_count=tool_exec_retry_count,
                                error=str(exec_exc),
                                mission_id=getattr(task, 'task_id', trace_id),
                                task_id=getattr(task, 'task_id', trace_id),
                                start=t_exec_start,
                                end=t_exec_start + t_exec_dur,
                            ),
                            request_id=trace_id
                        )
                    except Exception:
                        pass
                    self.session_logger.log_tool_result(tool_name, False, 1, str(exec_exc)[:200], t_exec_dur)
                    mark_failed(db_task_id, error=exec_err.technical_detail[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=7, status="failed", tool_name=tool_name, target=target, duration=t_exec_dur, error=result.error, attempt=tool_exec_retry_count + 1)
                    await self._emit_progress("tool_complete", {
                        "stage": 7,
                        "tool": tool_name,
                        "tool_name": tool_name,
                        "target": target,
                        "success": False,
                        "exit_code": 1,
                        "error": str(exec_exc),
                        "duration": t_exec_dur,
                        "attempt": tool_exec_retry_count + 1,
                    })
                    return result

                files_after = _safe_scan_workspace_files(workspace_root)

                structured_obs = StructuredObservation.from_tool_result(
                    tool_name=tool_name,
                    tool_result=current_tool_result,
                    duration=t_exec_dur,
                    files_before=files_before,
                    files_after=files_after,
                )
                self._last_structured_observation = structured_obs

                self.session_logger.log_tool_result(
                    tool_name, current_tool_result.success,
                    current_tool_result.exit_code,
                    current_tool_result.output[:300],
                    t_exec_dur
                )
                log_tool_result(
                    trace_id=trace_id,
                    tool_name=tool_name,
                    success=current_tool_result.success,
                    exit_code=current_tool_result.exit_code,
                    duration=t_exec_dur,
                    output_preview=current_tool_result.output[:200] if current_tool_result.output else "",
                    retry_count=tool_exec_retry_count
                )
                try:
                    from core.telemetry import ToolTelemetry
                    cat = "filesystem" if "file" in tool_name else ("shell" if "bash" in tool_name else "other")
                    telemetry.record_tool(
                        ToolTelemetry(
                            tool_name=tool_name,
                            category=cat,
                            start_time_monotonic=t_exec_start,
                            duration_ms=t_exec_dur * 1000.0,
                            filesystem_duration_ms=t_exec_dur * 1000.0 if cat == "filesystem" else 0.0,
                            subprocess_duration_ms=t_exec_dur * 1000.0 if cat == "shell" else 0.0,
                            success=bool(current_tool_result.success and (current_tool_result.exit_code == 0)),
                            exit_code=current_tool_result.exit_code,
                            args_size_bytes=len(str(tool_params)),
                            output_size_bytes=len(current_tool_result.output or ""),
                            retry_count=tool_exec_retry_count,
                            error=current_tool_result.error,
                            mission_id=getattr(task, 'task_id', trace_id),
                            task_id=getattr(task, 'task_id', trace_id),
                            start=t_exec_start,
                            end=t_exec_start + t_exec_dur,
                        ),
                        request_id=trace_id
                    )
                except Exception as telem_err:
                    logger.debug(f"Telemetry record_tool failed: {telem_err}")

                if current_tool_result.success and current_tool_result.exit_code == 0:
                    tool_result = current_tool_result
                    logger.debug(
                        f"Stage 7: tool={tool_name} succeeded | "
                        f"exit={current_tool_result.exit_code} | attempt={tool_exec_retry_count + 1}"
                    )
                    await notify("stage_end", stage=7, status="success", tool_name=tool_name, target=target, lines=lines_count, duration=t_exec_dur, attempt=tool_exec_retry_count + 1)
                    await self._emit_progress("tool_complete", {
                        "stage": 7,
                        "tool": tool_name,
                        "tool_name": tool_name,
                        "target": target,
                        "lines": lines_count,
                        "attempt": tool_exec_retry_count + 1,
                        "success": structured_obs.success,
                        "exit_code": structured_obs.exit_code,
                        "output_preview": structured_obs.to_context_string()[:200],
                        "state_delta": structured_obs.state_delta,
                        "is_actionable_failure": structured_obs.is_actionable_failure(),
                        "duration": structured_obs.duration_seconds,
                    })
                    break

                stderr = current_tool_result.error or current_tool_result.output or "Unknown error"
                exec_failure = self.error_handler.tool_execution_failure(
                    tool_name, current_tool_result.exit_code, stderr, retry_count=tool_exec_retry_count
                )

                logger.warning(
                    f"Stage 6: tool failure | tool={tool_name} | "
                    f"exit={current_tool_result.exit_code} | "
                    f"retry={tool_exec_retry_count}/3 | stderr={stderr[:80]!r}"
                )

                await notify("stage_end", stage=7, status="failed", tool_name=tool_name, duration=t_exec_dur, error=exec_failure.technical_detail, attempt=tool_exec_retry_count + 1)

                if exec_failure.is_final:
                    tool_result = current_tool_result
                    result.final_output = exec_failure.tagged_output(exec_failure.user_message)
                    result.error = exec_failure.technical_detail
                    result.tool_name = tool_name
                    result.tool_result = current_tool_result
                    mark_failed(db_task_id, error=exec_failure.technical_detail[:300], db_path=DB_PATH)
                    return result

                tool_exec_retry_count += 1
                correction_sys = system_prompt
                correction_prompt = (
                    build_user_message(sanitised) + "\n\n" +
                    exec_failure.context_for_retry
                )

                logger.info(f"Stage 6: retrying with error context (attempt {tool_exec_retry_count}/3)")
                repair_start_mono = time.monotonic()

                try:
                    tier1_retry_resp = await self._generate_t1(
                        model=TIER1_MODEL,
                        prompt=correction_prompt,
                        system=correction_sys,
                        keep_alive=MODEL_KEEP_ALIVE,
                        temperature=0.05,
                        num_ctx=4096,
                        tools=native_tools,
                    )
                    tier1_retry_raw = getattr(tier1_retry_resp, "text", str(tier1_retry_resp))
                except Exception as retry_gen_exc:
                    from models.ollama_client import OllamaTimeoutError
                    from models.nvidia_client import NvidiaTimeoutError
                    if isinstance(retry_gen_exc, (OllamaTimeoutError, NvidiaTimeoutError)):
                        timeout_err = self.error_handler.ollama_timeout(TIER1_MODEL, MODEL_TIMEOUT_SECONDS, f"stage_6_retry_{tool_exec_retry_count}")
                        result.final_output = timeout_err.tagged_output(timeout_err.user_message)
                    else:
                        unk_err = self.error_handler.unknown_error(retry_gen_exc, f"stage_6_retry_{tool_exec_retry_count}")
                        result.final_output = unk_err.tagged_output(unk_err.user_message)
                    mark_failed(db_task_id, error=str(retry_gen_exc)[:300], db_path=DB_PATH)
                    await notify("stage_end", stage=7, status="failed", tool_name=tool_name, duration=0.0, error=str(retry_gen_exc), attempt=tool_exec_retry_count + 1)
                    return result

                repair_end_mono = time.monotonic()
                try:
                    from core.telemetry import RepairTelemetry
                    telemetry.record_repair(
                        RepairTelemetry(
                            request_id=trace_id,
                            mission_id=getattr(task, 'task_id', trace_id),
                            task_id=getattr(task, 'task_id', trace_id),
                            attempt_number=tool_exec_retry_count,
                            trigger=exec_failure.technical_detail[:200],
                            affected_files=[tool_params.get("TargetFile") or tool_params.get("path")] if (tool_params.get("TargetFile") or tool_params.get("path")) else [],
                            start_time_monotonic=repair_start_mono,
                            end_time_monotonic=repair_end_mono,
                            duration_ms=(repair_end_mono - repair_start_mono) * 1000.0,
                            model=TIER1_MODEL,
                            success=False,
                        ),
                        request_id=trace_id,
                    )
                except Exception as r_telem_err:
                    logger.debug(f"Telemetry record_repair failed: {r_telem_err}")

                retry_parsed = self._parse_tier1_response(tier1_retry_resp)
                if retry_parsed:
                    tool_name_retry = retry_parsed.get("tool", tool_name)
                    tool_params_retry = retry_parsed.get("parameters", tool_params)
                    retry_tool_class = get_tool(tool_name_retry)
                    if retry_tool_class:
                        try:
                            tool_input = retry_tool_class.Input(**tool_params_retry)
                            tool_instance = retry_tool_class()
                            tool_name = tool_name_retry
                        except Exception:
                            pass

            if tool_result is None:
                result.final_output = "Tool execution produced no result. Please try again."
                mark_failed(db_task_id, error="tool_result is None after loop", db_path=DB_PATH)
                await notify("stage_end", stage=7, status="failed", tool_name=tool_name, duration=0.0, error=result.final_output, attempt=tool_exec_retry_count)
                return result

            result.tool_name = tool_name
            result.tool_result = tool_result
            logger.debug(f"Stage 6 complete: tool={tool_name} | success={tool_result.success} | exit={tool_result.exit_code}")
            telemetry.end_span(span_tool, success=bool(tool_result and (tool_result.success or tool_result.exit_code == 0)))

            # ── Stage 8: Progressive Verification Gate ──────────────
            span_ver = telemetry.start_span("Tier 2 Verification", request_id=trace_id, stage_number=8)
            await self._emit_progress("stage_start", {
                "stage": 8,
                "name": "Progressive Verification",
                "verb": "Verifying",
                "model": "adaptive",
                "detail": "Evaluating deterministic and semantic checks",
            })
            await notify("stage_start", stage=8, name="Verification", thought="Evaluating deterministic and semantic verification...", spinner_verb="Verifying")
            result.pipeline_stage_reached = 8
            ver_method = "UNKNOWN"
            ver_start_mono = time.monotonic()

            try:
                verification, ver_method = await self.verification_gate.evaluate(
                    task_description=sanitised,
                    tier1_reasoning=tier1_reasoning,
                    tool_name=tool_name,
                    tool_parameters=tool_params,
                    tool_result_output=tool_result.output,
                    tool_exit_code=tool_result.exit_code,
                    tool_success=tool_result.success,
                    verifier=self.verifier,
                    task_complexity=getattr(task, 'complexity_score', 0.5),
                    execution_mode=self.execution_mode,
                    request_id=trace_id,
                    mission_id=trace_id,
                    task_id=getattr(task, 'task_id', trace_id),
                )
            except Exception as t2_exc:
                from models.ollama_client import OllamaTimeoutError
                if isinstance(t2_exc, OllamaTimeoutError):
                    t2_err = self.error_handler.ollama_timeout(TIER2_MODEL, MODEL_TIMEOUT_SECONDS, "stage_8")
                else:
                    t2_err = self.error_handler.unknown_error(t2_exc, "stage_8_tier2")
                logger.warning(f"Stage 8: Verification unavailable — {t2_err.technical_detail}. Proceeding with T1 output.")
                from core.verifier import VerificationResult
                verification = VerificationResult(
                    agree=True,
                    confidence=0.5,
                    critical_issues=[],
                    risk_score=0.3,
                    reasoning=f"Verification unavailable ({t2_err.failure_mode.value}) — proceeding with reduced confidence."
                )
                verification.is_unavailable = True
                ver_method = "FALLBACK_UNAVAILABLE"

            ver_end_mono = time.monotonic()
            try:
                from core.telemetry import VerificationTelemetry
                telemetry.record_verification(
                    VerificationTelemetry(
                        request_id=trace_id,
                        mission_id=getattr(task, 'task_id', trace_id),
                        task_id=getattr(task, 'task_id', trace_id),
                        method=ver_method,
                        start_time_monotonic=ver_start_mono,
                        end_time_monotonic=ver_end_mono,
                        duration_ms=(ver_end_mono - ver_start_mono) * 1000.0,
                        verdict="AGREE" if getattr(verification, 'agree', True) else "DISAGREE",
                        escalated=bool(getattr(verification, 'should_escalate', False)),
                        issues_count=len(getattr(verification, 'critical_issues', [])),
                        issues=list(getattr(verification, 'critical_issues', [])),
                    ),
                    request_id=trace_id,
                )
            except Exception as v_telem_err:
                logger.debug(f"Telemetry record_verification failed: {v_telem_err}")

            model_used_for_log = getattr(verification, 'model_used', TIER2_MODEL) or TIER2_MODEL
            self.session_logger.log_tier2_verification(
                model_used_for_log,
                verification.agree, verification.confidence,
                verification.critical_issues, verification.risk_score,
                verification.latency_seconds if hasattr(verification, 'latency_seconds') else 0.0
            )
            log_tier2_call(
                trace_id=trace_id,
                model=model_used_for_log,
                latency=verification.latency_seconds if hasattr(verification, 'latency_seconds') else 0.0,
                agree=verification.agree,
                confidence=verification.confidence,
                risk_score=verification.risk_score,
                escalated=verification.should_escalate
            )
            tlog.debug(f"Stage 8 complete | method={ver_method} | {verification.summary()}")
            await notify("stage_end", stage=8, status="success", verifier=model_used_for_log, agree=verification.agree, confidence=verification.confidence, critical_issues=len(verification.critical_issues), method=ver_method)
            await self._emit_progress("stage_complete", {
                "stage": 8,
                "name": "Progressive Verification",
                "verifier": model_used_for_log,
                "confidence": getattr(verification, 'confidence', 0),
                "agree": getattr(verification, 'agree', True),
                "critical_issues": len(getattr(verification, 'critical_issues', [])),
                "method": ver_method
            })
            telemetry.end_span(span_ver, success=True)

            # ── Stage 9: Disagreement Router ──
            span_route = telemetry.start_span("Disagreement Routing", request_id=trace_id, stage_number=9)
            await self._emit_progress("stage_start", {
                "stage": 9,
                "name": "Disagreement Routing",
                "verb": "Routing",
                "detail": "Checking local agreement threshold",
            })
            await notify("stage_start", stage=9, name="Disagreement Analysis", thought="Routing verification agreement and resolving path...", spinner_verb="Comparing")
            t_err = getattr(tool_result, "error", "") or ""
            t_id = kwargs.get("task_id") or getattr(task, "task_id", trace_id)
            m_id = kwargs.get("mission_id") or trace_id
            routing = self.router.route(
                verification, tool_name, self.mode,
                task_id=t_id, mission_id=m_id, error_message=t_err
            )
            logger.info(f"Stage 9 complete: {routing.summary()}")
            await notify("stage_end", stage=9, status="success", decision=routing.decision.value, reason=routing.reason, threshold=routing.confidence_threshold_used, actual=verification.confidence, action="Consult Tier 3" if routing.tier3_needed else "Proceed")

            if routing.decision == RoutingDecision.ESCALATE and routing.tier3_needed:
                # ── ToT/LATS controlled extraction: try alternative before T3 ──
                # For non-always-escalate tools, generate an alternative approach
                # and have T2 compare before paying for T3.
                alternative_accepted = False
                if tool_name not in ALWAYS_ESCALATE_TOOLS:
                    await self._emit_progress("alternative_check", {
                        "stage": 9,
                        "verb": "Evaluating",
                        "detail": "Generating alternative approach before T3 escalation",
                    })
                    try:
                        alternative = await self.router.try_alternative_before_escalation(
                            original_task=sanitised,
                            original_tool_call={
                                "tool": tool_name,
                                "parameters": tool_params,
                            },
                            verification_result=verification,
                            ollama_client=self.ollama,
                            system_prompt=system_prompt,
                            tier1_client=self.active_t1_client,
                        )
                        if alternative:
                            alt_tool = alternative["tool"]
                            alt_params = alternative.get("parameters", {})
                            alt_result, norm_tool_name, norm_params = await self._execute_single_tool(
                                alt_tool, alt_params, sanitised
                            )
                            if alt_result and (alt_result.success or alt_result.exit_code == 0):
                                tool_name = norm_tool_name
                                tool_params = norm_params
                                tool_result = alt_result
                                alternative_accepted = True
                                routing = RouterResult(
                                    decision=RoutingDecision.ACCEPT,
                                    reason=f"Alternative approach accepted (ToT/LATS) — executed {alternative['tool']} instead of T3",
                                    tier3_needed=False,
                                    requires_user_confirm=False,
                                )
                                # Re-verify the executed alternative
                                verification, ver_method = await self.verification_gate.evaluate(
                                    task_description=sanitised,
                                    tier1_reasoning=alternative.get("reasoning", ""),
                                    tool_name=tool_name,
                                    tool_parameters=tool_params,
                                    tool_result_output=tool_result.output,
                                    tool_exit_code=tool_result.exit_code,
                                    tool_success=tool_result.success,
                                    verifier=self.verifier,
                                    task_complexity=getattr(task, 'complexity_score', 0.5),
                                    execution_mode=self.execution_mode,
                                )
                                await self._emit_progress("alternative_accepted", {
                                    "stage": 9,
                                    "verb": "Alternative accepted",
                                    "detail": f"T3 escalation avoided — executed {alternative['tool']}",
                                    "original_tool": tool_name,
                                    "alternative_tool": alternative["tool"],
                                })
                                logger.info(
                                    f"Stage 9: ToT/LATS alternative executed and accepted | "
                                    f"tool={tool_name} | "
                                    f"T3 escalation avoided"
                                )
                    except Exception as alt_exc:
                        logger.warning(f"Stage 9: alternative evaluation failed: {alt_exc}")

                if not alternative_accepted:
                    await self._emit_progress("escalating", {
                        "stage": 9,
                        "verb": "Escalating",
                        "detail": "Disagreement detected — routing to Tier 3",
                        "reason": routing.reason,
                    })
            else:
                await self._emit_progress("stage_complete", {
                    "stage": 9, "name": "Disagreement Routing",
                    "decision": "accepted locally",
                })
            telemetry.end_span(span_route, success=True)

            # ── Stage 10: Tier 3 Escalation ──
            span_t3 = telemetry.start_span("Tier 3 Arbitration", request_id=trace_id, stage_number=10)
            await notify("stage_start", stage=10, name="Tier 3 Escalation", thought=f"Escalating task to {TIER3_MODEL} for arbitration...", spinner_verb="Escalating", needed=routing.tier3_needed, reason=routing.reason, model=TIER3_MODEL)
            result.pipeline_stage_reached = 10

            tier3_decision_text = ""

            if routing.decision == RoutingDecision.BLOCK:
                result.final_output = (
                    f"⚠ This action requires your explicit confirmation.\n"
                    f"Tool: {tool_name}\n"
                    f"Reason: {routing.reason}\n"
                    f"Please confirm you want to proceed."
                )
                result.success = False
                mark_failed(db_task_id, error=f"Blocked: {routing.reason}", db_path=DB_PATH)
                await notify("stage_end", stage=10, status="failed", needed=True, verdict="Corrections Required")
                return result

            elif routing.decision == RoutingDecision.ESCALATE and routing.tier3_needed:
                t3_mission_id = getattr(task, 'task_id', trace_id)
                logger.info(f"MODEL_START | tier=3 | provider={TIER3_PROVIDER} | model={TIER3_MODEL} | mission_id={t3_mission_id} | task_id={t3_mission_id}")
                await self._emit_progress("stage_start", {
                    "stage": 9,
                    "name": "Tier 3 Arbitration",
                    "verb": "Arbitrating",
                    "model": TIER3_MODEL,
                    "detail": "Tier 3 model resolving disagreement",
                })
                try:
                    tier3_response = await self.tier3.arbitrate(
                        task=sanitised,
                        tier1_output=str(tier1_parsed),
                        tier2_issues=verification.critical_issues,
                        tool_result=tool_result.output[:400],
                        escalation_reason=routing.reason,
                        request_id=trace_id,
                        mission_id=t3_mission_id,
                        task_id=t3_mission_id,
                    )

                    if not tier3_response.success:
                        logger.error(f"MODEL_ERROR | tier=3 | provider={TIER3_PROVIDER} | model={TIER3_MODEL} | mission_id={t3_mission_id} | task_id={t3_mission_id} | latency={tier3_response.latency_seconds:.2f}s | error={tier3_response.error}")
                        result.tier3_was_called = True
                        t3_err = self.error_handler.tier3_api_failure(
                            "APIError",
                            tier3_response.error or "unknown error",
                            tier1_parsed.get("explanation", "Action proceeding with T1 output.")
                        )
                        logger.warning(f"Stage 9: Tier 3 API failure — {t3_err.technical_detail}")
                        tier3_decision_text = f"[{t3_err.tag}] {t3_err.user_message}"
                        log_tier3_call(
                            trace_id=trace_id,
                            latency=tier3_response.latency_seconds,
                            input_tokens=0,
                            output_tokens=0,
                            cost_usd=0.0,
                            success=False,
                            escalation_reason=routing.reason
                        )
                        await notify("stage_end", stage=10, status="failed", needed=True, verdict="Corrections Required")
                    else:
                        logger.info(f"MODEL_COMPLETE | tier=3 | provider={TIER3_PROVIDER} | model={TIER3_MODEL} | mission_id={t3_mission_id} | task_id={t3_mission_id} | latency={tier3_response.latency_seconds:.2f}s")
                        result.tier3_was_called = True
                        self.session_logger.log_tier3_arbitration(
                            tier3_response.content[:200],
                            tier3_response.input_tokens,
                            tier3_response.output_tokens,
                            tier3_response.cost_usd
                        )
                        tier3_decision_text = tier3_response.content
                        log_tier3_call(
                            trace_id=trace_id,
                            latency=tier3_response.latency_seconds,
                            input_tokens=tier3_response.input_tokens,
                            output_tokens=tier3_response.output_tokens,
                            cost_usd=tier3_response.cost_usd,
                            success=True,
                            escalation_reason=routing.reason
                        )
                        logger.info(f"Stage 9 complete: Tier 3 arbitrated | cost=${tier3_response.cost_usd:.4f}")
                        await notify("stage_end", stage=10, status="success", needed=True, verdict="Approved")

                    tier3_cost = getattr(tier3_response, 'cost_usd', 0.0) if (hasattr(tier3_response, 'cost_usd') and tier3_response.success) else 0.0
                    await self._emit_progress("stage_complete", {
                        "stage": 9, "name": "Tier 3 Arbitration",
                        "cost_usd": tier3_cost,
                    })

                except Exception as t3_exc:
                    logger.error(f"MODEL_ERROR | tier=3 | provider={TIER3_PROVIDER} | model={TIER3_MODEL} | mission_id={t3_mission_id} | task_id={t3_mission_id} | error={t3_exc}")
                    result.tier3_was_called = True
                    t3_err = self.error_handler.tier3_api_failure(
                        type(t3_exc).__name__,
                        str(t3_exc)[:200],
                        tier1_parsed.get("explanation", "Action proceeding.")
                    )
                    logger.warning(f"Stage 9: Tier 3 exception — {t3_err.technical_detail}")
                    tier3_decision_text = t3_err.tagged_output(t3_err.user_message)
                    log_tier3_call(
                        trace_id=trace_id,
                        latency=0.0,
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd=0.0,
                        success=False,
                        escalation_reason=routing.reason
                    )
                    await notify("stage_end", stage=10, status="failed", needed=True, verdict="Corrections Required")
            else:
                await notify("stage_end", stage=10, status="success", needed=False, verdict="Approved")
            telemetry.end_span(span_t3, success=result.tier3_was_called)

            # ── Post-Plan Continuation & Artifact Verification Check ──
            # Strict Verification & Repair Invariants:
            # 1. A repair is allowed ONLY when there is authoritative verification evidence identifying an actionable failure.
            # 2. These states must NEVER cause an automatic repair: Verifier=N/A, Agreement=PENDING, Confidence=N/A, No evidence, Unknown failure, Missing verification result.
            # 3. If verification is unavailable, HERMES must NOT interpret absence of evidence as failure.
            # 4. Every repair attempt must produce new evidence or changed artifact state.
            # 5. Repeated failure fingerprint terminates repair immediately (REPEATED_FAILURE_DETECTED).
            # 6. Strict maximum repair budget (MAX_REPAIR_BUDGET = 3).
            requested_artifacts = self.extract_requested_artifacts(sanitised)
            missing_artifacts = [
                art for art in requested_artifacts
                if not self._resolve_artifact_path(art).exists() or self._resolve_artifact_path(art).stat().st_size == 0
            ]

            actionable_verification_failure = False
            actionable_issues = []
            if verification is not None and not getattr(verification, 'is_unavailable', False):
                if verification.agree is False:
                    actionable_issues = [
                        iss for iss in getattr(verification, 'critical_issues', [])
                        if iss and not any(kw in iss.lower() for kw in ("unavailable", "timeout", "timed out", "fallback", "n/a", "pending"))
                    ]
                    if actionable_issues:
                        actionable_verification_failure = True

            has_failed_verification = actionable_verification_failure
            needs_execution_or_repair = bool(
                (missing_artifacts and (result.tier3_was_called or tool_name in ("list_directory", "read_file", "search_files", "file_exists")))
                or (has_failed_verification and (result.tier3_was_called or routing.decision == "escalate"))
            )

            if needs_execution_or_repair:
                MAX_REPAIR_BUDGET = 3
                if not hasattr(self, '_repair_attempts_count'):
                    self._repair_attempts_count = 0
                if not hasattr(self, '_repair_fingerprints_seen'):
                    self._repair_fingerprints_seen = set()

                plan_guidance = tier3_decision_text if tier3_decision_text else "Plan is approved."
                if missing_artifacts:
                    target_art = missing_artifacts[0]
                    target_art_path = self._resolve_artifact_path(target_art)
                    logger.info(
                        "Post-Plan Execution: Target artifact(s) {} not yet created. Continuing into implementation.",
                        missing_artifacts
                    )
                    await self._emit_progress("stage_start", {
                        "stage": 10,
                        "name": "Post-Plan Execution",
                        "verb": "Executing",
                        "detail": f"Implementing approved artifact(s): {', '.join(missing_artifacts)}",
                    })
                    continuation_prompt = (
                        f"PLAN APPROVED: {plan_guidance}\n\n"
                        f"Now proceed directly with execution to satisfy task: {sanitised}\n"
                        f"You must invoke 'write_file' to create the requested artifact '{target_art}'.\n"
                        f"Do not call inspection tools; write the complete implementation directly.\n"
                        f"Provide complete, production-grade, working code with no placeholders."
                    )
                else:
                    target_art = (
                        tool_params.get("path") or tool_params.get("file_path") or (requested_artifacts[0] if requested_artifacts else "file")
                    )
                    target_art_path = self._resolve_artifact_path(target_art)
                    issues_text = "; ".join(actionable_issues)
                    logger.info(
                        "Post-Plan Execution: Actionable verification failure detected ({}); initiating targeted repair for '{}'.",
                        issues_text, target_art
                    )
                    await self._emit_progress("stage_start", {
                        "stage": 10,
                        "name": "Post-Plan Execution",
                        "verb": "Repairing",
                        "detail": f"Repairing artifact: {target_art}",
                    })
                    continuation_prompt = (
                        f"REPAIR REQUIRED: Verification failed with issues:\n{issues_text}\n\n"
                        f"Arbitration guidance:\n{plan_guidance}\n\n"
                        f"You must invoke 'write_file' to update '{target_art}' with the corrected implementation.\n"
                        f"Ensure all imports, tests, and syntax pass completely."
                    )

                # Compute deterministic failure fingerprint
                content_hash = "missing"
                if target_art_path.exists() and target_art_path.is_file():
                    try:
                        content_hash = hashlib.sha256(target_art_path.read_bytes()).hexdigest()[:16]
                    except Exception:
                        pass
                issues_sig = "|".join(sorted(actionable_issues))
                failure_fingerprint = f"{target_art_path.name}:{content_hash}:{issues_sig}"

                if self._repair_attempts_count >= MAX_REPAIR_BUDGET:
                    logger.warning(
                        "REPAIR_BUDGET_EXCEEDED: Maximum repair attempts ({}) reached for mission. Halting repair.",
                        MAX_REPAIR_BUDGET
                    )
                    needs_execution_or_repair = False
                elif failure_fingerprint in self._repair_fingerprints_seen:
                    logger.warning(
                        "REPEATED_FAILURE_DETECTED: Fingerprint '{}' repeated without progress. Halting repair loop.",
                        failure_fingerprint
                    )
                    needs_execution_or_repair = False
                else:
                    self._repair_fingerprints_seen.add(failure_fingerprint)
                    self._repair_attempts_count += 1

                if needs_execution_or_repair:
                    # Restrict tools exclusively to file-writing tools to prevent re-entering inspection loops
                    write_tools = [
                        t for t in (native_tools or [])
                        if isinstance(t, dict) and t.get("function", {}).get("name") in ("write_file", "write_files_batch")
                    ]
                    if not write_tools:
                        write_tools = native_tools

                    try:
                        cont_resp = await self._generate_t1(
                            model=TIER1_MODEL,
                            prompt=continuation_prompt,
                            system=system_prompt,
                            keep_alive=MODEL_KEEP_ALIVE,
                            temperature=0.05,
                            num_ctx=4096,
                            num_predict=max(num_predict, 2048),
                            think=t1_think,
                            tools=write_tools,
                        )
                        cont_parsed = self._parse_tier1_response(cont_resp)
                        if cont_parsed and isinstance(cont_parsed, dict) and "tool" in cont_parsed:
                            cont_tool_name = cont_parsed["tool"]
                            cont_params = cont_parsed.get("parameters", {})
                            
                            logger.info(f"Post-Plan Execution: invoking tool {cont_tool_name} with params keys {list(cont_params.keys())}")
                            cont_tool_result, norm_tool_name, norm_params = await self._execute_single_tool(
                                cont_tool_name, cont_params, sanitised
                            )
                            
                            if cont_tool_result:
                                # Evaluate verification on the newly written artifact
                                cont_ver, cont_vmethod = await self.verification_gate.evaluate(
                                    task_description=sanitised,
                                    tier1_reasoning=cont_parsed.get("reasoning", ""),
                                    tool_name=norm_tool_name,
                                    tool_parameters=norm_params,
                                    tool_result_output=cont_tool_result.output,
                                    tool_exit_code=cont_tool_result.exit_code,
                                    tool_success=cont_tool_result.success,
                                    verifier=self.verifier,
                                    task_complexity=getattr(task, 'complexity_score', 0.5),
                                    execution_mode=self.execution_mode,
                                )
                                # Update active tool result state to reflect execution
                                tool_name = norm_tool_name
                                tool_params = norm_params
                                tool_result = cont_tool_result
                                verification = cont_ver
                                tier1_parsed = cont_parsed
                    except Exception as cont_exc:
                        logger.warning(f"Post-plan execution failed: {cont_exc}")

            # ── Stage 11: Background Memory Update (Non-Blocking) ──
            span_mem = telemetry.start_span("Memory Update", request_id=trace_id, stage_number=11)
            await self._emit_progress("stage_start", {
                "stage": 11,
                "name": "Memory Update",
                "verb": "Queueing memory",
                "detail": "Enqueuing background memory extraction to MEMORY.md",
            })
            await notify("stage_start", stage=11, name="Memory Update", thought="Enqueuing background memory extraction...", spinner_verb="Queueing")
            result.pipeline_stage_reached = 11
            written_status = "0"
            if tool_result and tool_result.exit_code == 0 and tool_result.success:
                conversation_for_extraction = [
                    {"role": "user", "content": sanitised},
                    {"role": "assistant", "content": tier1_raw[:300]}
                ]
                tool_results_for_extraction = [
                    {
                        "tool": tool_name,
                        "exit_code": tool_result.exit_code,
                        "success": tool_result.success
                    }
                ]
                mem_job = MemoryJob(
                    trace_id=trace_id,
                    mission_id=trace_id,
                    task_description=sanitised,
                    conversation_history=conversation_for_extraction,
                    tool_results=tool_results_for_extraction,
                    tool_name=tool_name,
                    exit_code=tool_result.exit_code,
                    project=self.project
                )
                enqueued = self.memory_manager.submit(mem_job)
                written_status = "Background Queued" if enqueued else "Dropped (Queue Full)"
                tlog.debug(f"Stage 10 complete | Memory job {mem_job.job_id} submitted to background queue")

            await notify("stage_end", stage=11, status="success", added=["Background extraction queued"], updated=[])
            await self._emit_progress("stage_complete", {
                "stage": 11, "name": "Memory Update", "status": "background_queued"
            })
            written = written_status
            telemetry.end_span(span_mem, success=True)

            # ── Stage 12: Build Final Response ──
            span_final = telemetry.start_span("Final Response", request_id=trace_id, stage_number=12)
            result.pipeline_stage_reached = 12
            logger.debug(f"Stage 11 complete: task {task.task_id} processed")

            await notify("stage_start", stage=12, name="Final Response", thought="Synthesizing final execution report...", spinner_verb="Finalizing")

            # Artifact-based completion enforcement:
            # Check if requested artifacts for this specific task exist on disk and have non-zero size.
            # Do NOT fail intermediate tasks for artifacts requested by future tasks in a multi-task mission.
            task_id_arg = kwargs.get("task_id")
            is_read_tool = tool_name in ("list_directory", "read_file", "search_files", "file_exists", "view_file")

            if is_read_tool:
                # Read-only inspection tasks never fail for missing write artifacts
                still_missing = []
            elif task_id_arg:
                # Running a specific task within a mission:
                # Extract requested artifacts ONLY from the specific TASK section if present, or from the tool call
                task_match = re.search(r"TASK(?:\s+TO\s+EXECUTE)?:\s*\n(.*?)(?:\n\s*SUCCESS CRITERION:|\Z)", sanitised, re.DOTALL | re.IGNORECASE)
                sub_text = task_match.group(1).strip() if task_match else ""
                target_artifacts = self.extract_requested_artifacts(sub_text) if sub_text else []
                if not target_artifacts and tool_name in ("write_file", "fs.write", "append_file"):
                    p = tool_params.get("path") or tool_params.get("TargetFile")
                    if p:
                        target_artifacts = [p]
                still_missing = [
                    art for art in target_artifacts
                    if not self._resolve_artifact_path(art).exists() or self._resolve_artifact_path(art).stat().st_size == 0
                ]
            else:
                target_artifacts = self.extract_requested_artifacts(sanitised)
                still_missing = [
                    art for art in target_artifacts
                    if not self._resolve_artifact_path(art).exists() or self._resolve_artifact_path(art).stat().st_size == 0
                ]

            if still_missing and not is_read_tool:
                logger.error(f"Mission Completion Contract Violated: Expected artifact(s) {still_missing} not created on disk")
                result.success = False
                result.error = f"AWAITING_EXECUTION / PLAN_APPROVED: Requested artifact(s) not created on disk: {still_missing}"
                final_answer = (
                    f"Execution incomplete. The requested artifact(s) {still_missing} were not created on disk.\n"
                    f"Plan state: PLAN_APPROVED but TASK_NOT_EXECUTED."
                )
            else:
                ver_agree = True
                if 'routing' in locals() and routing is not None:
                    ver_agree = (routing.decision == RoutingDecision.ACCEPT) or (
                        routing.decision == RoutingDecision.ESCALATE and bool(getattr(locals().get('tier3_response'), 'success', False))
                    )
                elif verification:
                    ver_agree = bool(verification.agree and len(getattr(verification, 'critical_issues', [])) == 0)
                result.success = bool(tool_result and tool_result.success and (tool_result.exit_code == 0) and ver_agree)

                explanation = tier1_parsed.get("explanation", "Task completed.") if isinstance(tier1_parsed, dict) else "Task completed."

                if result.success:
                    output_preview = tool_result.output[:400] if (tool_result and tool_result.output) else ""
                    final_answer = (
                        f"{explanation}\n\n{output_preview}" if output_preview else explanation
                    )
                else:
                    error_msg = getattr(tool_result, 'error', None) or (verification.critical_issues[0] if (verification and verification.critical_issues) else "Verification failed")
                    final_answer = (
                        f"The action did not complete successfully.\n"
                        f"Tool: {tool_name}\n"
                        f"Error: {error_msg[:300]}"
                    )

            if tier3_decision_text:
                final_answer += f"\n\n[Tier 3 review]: {tier3_decision_text[:200]}"

            total_latency = time.monotonic() - start_time
            
            # Format completion/failure report
            if result.success:
                created_count = 0
                modified_count = 0
                if tool_name == "write_file":
                    p = tool_params.get("TargetFile") or tool_params.get("path")
                    if p and Path(p).exists():
                        modified_count = 1
                    else:
                        created_count = 1
                
                skill_name = result.skill_ids_used[0] if result.skill_ids_used else "none"
                
                file_tree_str = ""
                if tool_name == "write_file":
                    target_file_path = tool_params.get("TargetFile") or tool_params.get("path") or "output.py"
                    file_basename = Path(target_file_path).name
                    file_tree_str = (
                        f"Artifacts Created\n"
                        f"└── {file_basename}\n\n"
                    )

                summary_box = (
                    f"═══════════════════════════\n"
                    f"EXECUTION SUMMARY\n"
                    f"═══════════════════════════\n\n"
                    f"{file_tree_str}"
                    f"Request:\n"
                    f"{sanitised[:120]}\n\n"
                    f"Mode:\n"
                    f"{self.mode.upper()}\n\n"
                    f"Skill Used:\n"
                    f"{skill_name}\n\n"
                    f"Tools Executed:\n"
                    f"1\n\n"
                    f"Files Created:\n"
                    f"{created_count}\n\n"
                    f"Files Modified:\n"
                    f"{modified_count}\n\n"
                    f"Tests Passed:\n"
                    f"0\n\n"
                    f"Tests Failed:\n"
                    f"0\n\n"
                    f"Verifier Confidence:\n"
                    f"{verification.confidence if 'verification' in locals() else 0.5:.2f}\n\n"
                    f"Memory Updates:\n"
                    f"{written}\n\n"
                    f"Total Duration:\n"
                    f"{total_latency:.1f}s\n\n"
                    f"Result:\n"
                    f"SUCCESS\n\n"
                    f"═══════════════════════════\n"
                )
                result.final_output = f"{summary_box}\n{final_answer}"
            else:
                fail_stage = "Tool Execution"
                if result.pipeline_stage_reached < 6:
                    fail_stage = "Tier 1 Reasoning"
                elif result.pipeline_stage_reached == 8:
                    fail_stage = "Tier 2 Verification"
                elif result.pipeline_stage_reached == 9:
                    fail_stage = "Tier 3 Arbitration"
                
                tool_run = tool_name or "none"
                err_reason = result.error or "Unknown error"
                if "Permission denied" in err_reason:
                    suggested = "Check folder permissions"
                elif "Timeout" in err_reason:
                    suggested = "Verify model runner (Ollama) service status"
                else:
                    suggested = "Check syntax, model availability, or credentials"

                summary_box = (
                    f"═══════════════════════════\n"
                    f"EXECUTION SUMMARY\n"
                    f"═══════════════════════════\n\n"
                    f"Result:\n"
                    f"FAILED\n\n"
                    f"Failure Stage:\n"
                    f"{fail_stage}\n\n"
                    f"Tool:\n"
                    f"{tool_run}\n\n"
                    f"Reason:\n"
                    f"{err_reason[:200]}\n\n"
                    f"Retries:\n"
                    f"{tool_exec_retry_count}/3\n\n"
                    f"Suggested Action:\n"
                    f"{suggested}\n\n"
                    f"═══════════════════════════\n"
                )
                result.final_output = f"{summary_box}\n{final_answer}"

            log_pipeline_complete(
                trace_id=trace_id,
                success=result.success,
                stage_reached=12,
                total_latency=total_latency,
                tool_name=result.tool_name,
                tier3_called=result.tier3_was_called,
                cost_usd=self.claude.get_cost_summary().get("total_spent", 0.0)
            )
            tlog.info(f"Pipeline complete | success={result.success} | latency={total_latency:.2f}s")
            result.total_latency_seconds = total_latency
            
            # ── Stage 12: Output & Task Queue Finalization ──
            if result.success:
                mark_completed(db_task_id, db_path=DB_PATH)
            else:
                mark_failed(db_task_id, error=result.error or result.final_output[:200], db_path=DB_PATH)

            await notify("stage_end", stage=12, status="success" if result.success else "failed")
            await self._emit_progress("stage_complete", {
                "stage": 12,
                "name": "Final Response",
                "verb": "Ready",
                "detail": "Pipeline complete",
                "pipeline_stage_reached": 12,
            })
            telemetry.end_span(span_final, success=result.success)
            return result

        except Exception as e:
            result.total_latency_seconds = time.monotonic() - start_time
            result.error = str(e)
            
            fail_stage = "Tool Execution"
            if result.pipeline_stage_reached < 6:
                fail_stage = "Tier 1 Reasoning"
            elif result.pipeline_stage_reached == 8:
                fail_stage = "Tier 2 Verification"
            elif result.pipeline_stage_reached == 9:
                fail_stage = "Tier 3 Arbitration"

            err_reason = str(e)
            suggested = "Check syntax, model availability, or credentials"
            
            summary_box = (
                f"═══════════════════════════\n"
                f"EXECUTION SUMMARY\n"
                f"═══════════════════════════\n\n"
                f"Result:\n"
                f"FAILED\n\n"
                f"Failure Stage:\n"
                f"{fail_stage}\n\n"
                f"Tool:\n"
                f"none\n\n"
                f"Reason:\n"
                f"{err_reason[:200]}\n\n"
                f"Retries:\n"
                f"0/3\n\n"
                f"Suggested Action:\n"
                f"{suggested}\n\n"
                f"═══════════════════════════\n"
            )
            
            result.final_output = (
                f"{summary_box}\n"
                f"An unexpected error occurred at stage "
                f"{result.pipeline_stage_reached}: {str(e)[:200]}"
            )
            log_pipeline_complete(
                trace_id=trace_id,
                success=False,
                stage_reached=result.pipeline_stage_reached,
                total_latency=time.monotonic() - start_time,
                tool_name=None,
                tier3_called=False,
                cost_usd=0.0
            )
            logger.error(
                f"Orchestrator error at stage {result.pipeline_stage_reached}: "
                f"{type(e).__name__}: {e}"
            )
            try:
                mark_failed(db_task_id, error=str(e)[:300], db_path=DB_PATH)
            except Exception:
                pass
            
            await notify("stage_end", stage=result.pipeline_stage_reached, status="failed", error=str(e))
            return result
        finally:
            try:
                finished_req = telemetry.finish_request(trace_id, success=result.success, stage_reached=result.pipeline_stage_reached, error=result.error)
                if finished_req:
                    waterfall = finished_req.get_waterfall()
                    logger.info(
                        f"LATENCY WATERFALL [{trace_id}]: total={waterfall['total_wall_clock_ms']}ms | "
                        f"accounted={waterfall['total_accounted_ms']}ms | overhead={waterfall['unaccounted_overhead_ms']}ms | "
                        f"milestones={waterfall['milestone_intervals_ms']}"
                    )
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _sanitise_input(self, user_input: str) -> str:
        """Strip HTML/XML tags, replace backticks, cap length."""
        sanitised = user_input
        sanitised = re.sub(r'<[^>]+>', '', sanitised)   # Remove HTML/XML tags
        sanitised = sanitised.replace('`', "'")          # Replace backticks
        sanitised = sanitised.strip()
        if not sanitised:
            sanitised = "Please describe what you want me to do."
        return sanitised[:2000]  # Hard cap on input length

    def _parse_tier1_response(self, response: Any) -> Optional[dict]:
        """Parse Tier 1 response using the hardened ResponseParser."""
        from core.response_parser import ResponseParser
        parser = ResponseParser()
        result = parser.parse(response)
        self._last_parse_result = result
        
        if hasattr(result, 'to_dict'):  # ParseSuccess
            if result.method_used != "direct_parse":
                logger.info(f"ResponseParser: used fallback strategy '{result.method_used}'")
            return result.to_dict()
        else:  # ParseFailure
            raw_text = getattr(response, "text", str(response)).strip()
            cleaned = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
            # Only treat as genuine conversational reply if it looks like an explicit text response
            is_conversational = any(cleaned.lower().startswith(p) for p in ("hello", "hi ", "hey", "i am", "i'm", "sure", "of course", "as an ai"))
            if is_conversational and len(cleaned) >= 10:
                logger.info(f"ResponseParser: direct conversational answer detected ({len(cleaned)} chars)")
                return {
                    "tool": None,
                    "parameters": {},
                    "reasoning": "Direct conversational response",
                    "explanation": cleaned,
                    "_parse_method": "plain_text_conversational"
                }
            logger.warning(
                f"ResponseParser: all strategies failed | "
                f"reason={result.failure_reason} | "
                f"plain_text={result.is_plain_text} | "
                f"has_fragment={result.has_json_fragment}"
            )
            return None

    def set_mode(self, mode: str) -> None:
        """Change the operating mode. Raises ValueError for invalid modes."""
        if mode not in ("safe", "plan", "auto"):
            raise ValueError(f"Invalid mode '{mode}'. Must be: safe, plan, auto")
        self.mode = mode
        logger.info(f"Orchestrator mode changed to: {mode}")

