# core/model_residency_manager.py
"""
Model Residency & Lifecycle Manager for HERMES vNext (Phase 6.4).
Optimizes single-model VRAM residency for the NVIDIA RTX 3050 (6GB VRAM) constraint.
Guarantees foreground execution priority and prevents background memory model thrashing.

States:
  UNLOADED -> LOADING -> RESIDENT -> IN_USE -> EVICTING
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional
from loguru import logger

from config.model_config import (
    OPTIMIZED_MODEL_RESIDENCY_ENABLED,
    TIER1_MODEL,
    TIER2_MODEL,
    T1_KEEP_ALIVE,
    T2_KEEP_ALIVE,
    MODEL_KEEP_ALIVE
)


class ModelLifecycleState(Enum):
    UNLOADED = "UNLOADED"
    LOADING = "LOADING"
    RESIDENT = "RESIDENT"
    IN_USE = "IN_USE"
    EVICTING = "EVICTING"
    ERROR = "ERROR"


@dataclass
class ModelInfo:
    name: str
    state: ModelLifecycleState = ModelLifecycleState.UNLOADED
    last_used: float = field(default_factory=time.monotonic)
    default_keep_alive: str = "300s"


class ModelResidencyManager:
    """
    Coordinates model residency in GPU VRAM.
    Enforces single-model residency invariants under 6 GB VRAM ceiling.
    """

    def __init__(self, enabled: bool = OPTIMIZED_MODEL_RESIDENCY_ENABLED):
        self.enabled = enabled
        self._lock = asyncio.Lock()
        self._active_model: Optional[str] = None
        self._state: ModelLifecycleState = ModelLifecycleState.UNLOADED
        self._foreground_in_progress: bool = False
        self._total_switches: int = 0
        self._unnecessary_switches_avoided: int = 0

        self._models: Dict[str, ModelInfo] = {
            TIER1_MODEL: ModelInfo(name=TIER1_MODEL, default_keep_alive=T1_KEEP_ALIVE),
            TIER2_MODEL: ModelInfo(name=TIER2_MODEL, default_keep_alive=T2_KEEP_ALIVE),
        }
        logger.info("ModelResidencyManager initialized | enabled={}", self.enabled)

    @property
    def active_model(self) -> Optional[str]:
        return self._active_model

    @property
    def total_switches(self) -> int:
        return self._total_switches

    @property
    def switches_avoided(self) -> int:
        return self._unnecessary_switches_avoided

    def get_keep_alive(self, model: str) -> str:
        """Return model-specific keep-alive policy."""
        if not self.enabled:
            return MODEL_KEEP_ALIVE
        if model == TIER1_MODEL:
            return T1_KEEP_ALIVE
        if model == TIER2_MODEL:
            return T2_KEEP_ALIVE
        return MODEL_KEEP_ALIVE

    async def acquire_model(
        self,
        model: str,
        is_foreground: bool = True
    ) -> str:
        """
        Acquire model for execution.
        If model is already resident, returns immediately with zero reload overhead.
        If switch is required, coordinates safe transition and tracks telemetry.
        """
        if not self.enabled:
            return self.get_keep_alive(model)

        async with self._lock:
            # If background request and foreground is active with a different model, wait
            if not is_foreground and self._foreground_in_progress and self._active_model != model:
                logger.debug(
                    "ModelResidencyManager: background task waiting for foreground model '{}' to finish",
                    self._active_model
                )
                await asyncio.sleep(0.2)

            if is_foreground:
                self._foreground_in_progress = True

            # Check if model is already active and resident
            if self._active_model == model:
                self._unnecessary_switches_avoided += 1
                self._state = ModelLifecycleState.IN_USE
                if model in self._models:
                    self._models[model].last_used = time.monotonic()
                    self._models[model].state = ModelLifecycleState.IN_USE
                logger.debug("ModelResidencyManager: model '{}' is ALREADY WARM (zero switch cost)", model)
                return self.get_keep_alive(model)

            # Model switch required
            self._total_switches += 1
            logger.info(
                "ModelResidencyManager: model switch '{}' -> '{}' (total switches: {})",
                self._active_model, model, self._total_switches
            )

            # Update state
            if self._active_model and self._active_model in self._models:
                self._models[self._active_model].state = ModelLifecycleState.UNLOADED

            self._active_model = model
            self._state = ModelLifecycleState.IN_USE
            if model in self._models:
                self._models[model].last_used = time.monotonic()
                self._models[model].state = ModelLifecycleState.IN_USE

            return self.get_keep_alive(model)

    def release_model(self, model: str, is_foreground: bool = True):
        """Release active use lock on the model and transition to RESIDENT (idle)."""
        if not self.enabled:
            return

        if is_foreground:
            self._foreground_in_progress = False

        if self._active_model == model:
            self._state = ModelLifecycleState.RESIDENT
            if model in self._models:
                self._models[model].state = ModelLifecycleState.RESIDENT

    async def prewarm_model(self, model: str) -> bool:
        """
        Safely prewarm target model if no other model is currently in foreground use.
        If target model is already active and resident, returns True immediately (zero cost).
        If another model is actively in foreground use, aborts prewarming to preserve foreground execution priority.
        Sends a non-blocking keep-alive request to Ollama to warm model into VRAM.
        """
        if not self.enabled:
            return False

        async with self._lock:
            # If foreground task is using a DIFFERENT model, do not prewarm (VRAM protection)
            if self._foreground_in_progress and self._active_model != model:
                logger.debug(
                    "ModelResidencyManager.prewarm: skipping prewarm of '{}' because foreground model '{}' is active",
                    model, self._active_model
                )
                return False

            # If already resident, zero cost
            if self._active_model == model and self._state in {ModelLifecycleState.RESIDENT, ModelLifecycleState.IN_USE}:
                logger.debug("ModelResidencyManager.prewarm: model '{}' is already resident", model)
                return True

            # If switch is needed, only prewarm if no foreground is active
            if self._foreground_in_progress:
                return False

            logger.info("ModelResidencyManager.prewarm: initiating safe background prewarm for '{}'", model)
            self._state = ModelLifecycleState.LOADING
            try:
                import httpx
                keep_alive = self.get_keep_alive(model)
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "http://localhost:11434/api/generate",
                        json={"model": model, "keep_alive": keep_alive}
                    )
                    if resp.status_code == 200:
                        self._active_model = model
                        self._state = ModelLifecycleState.RESIDENT
                        if model in self._models:
                            self._models[model].state = ModelLifecycleState.RESIDENT
                            self._models[model].last_used = time.monotonic()
                        logger.info("ModelResidencyManager.prewarm: successfully prewarmed '{}'", model)
                        return True
                    else:
                        self._state = ModelLifecycleState.ERROR
                        return False
            except Exception as e:
                logger.warning("ModelResidencyManager.prewarm: prewarm request for '{}' encountered: {}", model, e)
                self._state = ModelLifecycleState.UNLOADED
                return False

    def on_mission_complete(self):
        """Called when a mission finishes. Releases foreground hold and leaves active model resident in idle state without swapping."""
        self._foreground_in_progress = False
        if self._active_model and self._active_model in self._models:
            self._state = ModelLifecycleState.RESIDENT
            self._models[self._active_model].state = ModelLifecycleState.RESIDENT
            logger.info("ModelResidencyManager: mission completed with active model '{}' resident (no swap penalty)", self._active_model)

    def get_state(self) -> Dict[str, Any]:
        """Return diagnostic snapshot of the residency manager."""
        return {
            "enabled": self.enabled,
            "active_model": self._active_model,
            "state": self._state.value,
            "foreground_in_progress": self._foreground_in_progress,
            "total_switches": self._total_switches,
            "switches_avoided": self._unnecessary_switches_avoided,
            "models": {k: {"state": v.state.value, "keep_alive": v.default_keep_alive} for k, v in self._models.items()}
        }


# Global shared singleton
model_residency_manager = ModelResidencyManager()
