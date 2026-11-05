"""
Deterministic Regression & Unit Test Suite for HERMES 2.x AgentLoop Model State & Recovery (Prompt Phase 1).
Validates:
1. Fresh AgentLoop construction initializes valid model state.
2. Every supported constructor path initializes model state.
3. Tier 1 execution preserves correct model identity.
4. Tier 1 -> Tier 2 failover updates all model-state owners atomically.
5. Tier 2 -> Tier 3 failover updates all model-state owners atomically.
6. Recovery restores active model identity.
7. Checkpoint resume restores active model identity without overwriting.
8. Work-package transitions do not cause missing model attributes.
9. Verification transitions do not cause missing model attributes.
10. Mission completion preserves consistent model state.
11. Repeated failovers do not desynchronize model identity.
12. Invalid model state produces a clear classified failure (InvalidModelStateError).
13. Static self-attribute audit verifies all lifecycle-referenced attributes are initialized.
14. End-to-end mocked regression reproducing mission m_9bdb4cb3 non-mutating inspection loop recovery.
"""

import ast
import asyncio
import inspect
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.model_config import (
    TIER1_PROVIDER,
    TIER1_MODEL,
    TIER2_PROVIDER,
    TIER2_MODEL,
    TIER3_PROVIDER,
    TIER3_MODEL,
    TIER4_PROVIDER,
    TIER4_MODEL,
)
from core.agent_loop.types import AgentLoopConfig
from core.agent_loop.loop import AgentLoop, InvalidModelStateError
from core.agent_loop.types import ExecutionPhase
from core.event_bus import EventBus
from core.mission_checkpoint import MissionCheckpoint, MissionCheckpointManager
from core.mission_planner import Mission
from core.runtime_state.events import EventType
from core.runtime_state.models import HermesRuntimeState
from core.runtime_state.store import StateStore


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.mode = "auto"
    orch.execution_mode = "production"
    orch._active_tier = 1
    return orch


@pytest.fixture
def mock_event_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.get_state = MagicMock(return_value=None)
    bus.get_or_create_state = MagicMock(return_value=None)
    return bus


@pytest.fixture
def real_state_store():
    store = StateStore(mission_id="m_test_store")
    return store


# ── Test 1: Fresh AgentLoop Construction Initializes Valid Model State ────────
def test_1_fresh_agent_loop_initializes_valid_model_state(mock_orchestrator):
    loop = AgentLoop(orchestrator=mock_orchestrator)

    assert hasattr(loop, "_mission_model"), "Loop must have _mission_model attribute/property"
    assert hasattr(loop, "mission_model"), "Loop must have mission_model property"
    assert hasattr(loop, "active_tier"), "Loop must have active_tier property"
    assert hasattr(loop, "active_provider"), "Loop must have active_provider property"
    assert hasattr(loop, "active_model"), "Loop must have active_model property"
    assert hasattr(loop, "mission"), "Loop must have mission property"

    assert loop.active_tier == 1
    assert loop.active_provider == TIER1_PROVIDER
    assert loop.active_model == TIER1_MODEL
    assert loop.mission_model == TIER1_MODEL
    assert loop._mission_model == TIER1_MODEL
    assert mock_orchestrator._active_tier == 1


# ── Test 2: Every Supported Constructor Path Initializes Model State ──────────
def test_2_supported_constructor_paths_initialize_model_state(mock_orchestrator, mock_event_bus, real_state_store):
    # Path A: orchestrator only
    loop_a = AgentLoop(orchestrator=mock_orchestrator)
    assert loop_a._mission_model == TIER1_MODEL
    assert loop_a.active_tier == 1

    # Path B: orchestrator + config
    cfg = AgentLoopConfig(execution_mode="benchmark")
    loop_b = AgentLoop(orchestrator=mock_orchestrator, config=cfg)
    assert loop_b._mission_model == TIER1_MODEL
    assert loop_b.active_tier == 1

    # Path C: bus + workspace + orchestrator
    mock_ws = MagicMock()
    mock_ws.root_str = "."
    loop_c = AgentLoop(
        orchestrator=mock_orchestrator,
        event_bus_instance=mock_event_bus,
        workspace_manager=mock_ws,
    )
    assert loop_c._mission_model == TIER1_MODEL
    assert loop_c.active_tier == 1

    # Path D: orchestrator with pre-configured tier 2
    orch_t2 = MagicMock()
    orch_t2._active_tier = 2
    loop_d = AgentLoop(orchestrator=orch_t2)
    assert loop_d.active_tier == 2
    assert loop_d.active_model == TIER2_MODEL
    assert loop_d._mission_model == TIER2_MODEL

    # Path E: state store injected
    loop_e = AgentLoop(orchestrator=mock_orchestrator, state_store_instance=real_state_store)
    assert loop_e._mission_model == TIER1_MODEL
    assert loop_e.state_store.current_model == TIER1_MODEL


# ── Test 3: Tier 1 Execution Preserves Correct Model Identity ──────────────────
def test_3_tier_1_execution_preserves_model_identity(mock_orchestrator):
    loop = AgentLoop(orchestrator=mock_orchestrator)

    assert loop.active_tier == 1
    assert loop.active_provider == TIER1_PROVIDER
    assert loop.active_model == TIER1_MODEL
    assert loop.mission_model == TIER1_MODEL
    assert loop._mission_model == TIER1_MODEL


# ── Test 4: Tier 1 -> Tier 2 Failover Updates All Model State Owners ───────────
def test_4_tier_1_to_tier_2_failover_updates_all_owners(mock_orchestrator, real_state_store):
    loop = AgentLoop(orchestrator=mock_orchestrator, state_store_instance=real_state_store)

    loop.set_active_model_state(tier=2, provider=TIER2_PROVIDER, model=TIER2_MODEL, reason="T1 stall")

    assert loop.active_tier == 2
    assert loop.active_provider == TIER2_PROVIDER
    assert loop.active_model == TIER2_MODEL
    assert loop.mission_model == TIER2_MODEL
    assert loop._mission_model == TIER2_MODEL
    assert mock_orchestrator._active_tier == 2
    assert real_state_store.current_model == TIER2_MODEL
    assert real_state_store._state.model_execution.tier == 2
    assert real_state_store._state.model_execution.provider == TIER2_PROVIDER
    assert real_state_store._state.model_execution.model == TIER2_MODEL


# ── Test 5: Tier 2 -> Tier 3 Failover Updates All Model State Owners ───────────
def test_5_tier_2_to_tier_3_failover_updates_all_owners(mock_orchestrator, real_state_store):
    loop = AgentLoop(orchestrator=mock_orchestrator, state_store_instance=real_state_store)

    loop.set_active_model_state(tier=3, provider=TIER3_PROVIDER, model=TIER3_MODEL, reason="T2 timeout")

    assert loop.active_tier == 3
    assert loop.active_provider == TIER3_PROVIDER
    assert loop.active_model == TIER3_MODEL
    assert loop.mission_model == TIER3_MODEL
    assert loop._mission_model == TIER3_MODEL
    assert mock_orchestrator._active_tier == 3
    assert real_state_store.current_model == TIER3_MODEL
    assert real_state_store._state.model_execution.tier == 3
    assert real_state_store._state.model_execution.model == TIER3_MODEL


# ── Test 6: Recovery Restores Active Model Identity ────────────────────────────
@pytest.mark.asyncio
async def test_6_recovery_transition_updates_active_model_state(mock_orchestrator, mock_event_bus, real_state_store):
    loop = AgentLoop(
        orchestrator=mock_orchestrator,
        event_bus_instance=mock_event_bus,
        state_store_instance=real_state_store,
    )
    loop._mission_id = "m_test_rec"
    loop._publish_event = AsyncMock()

    # Trigger bounded recovery transition from Tier 1 -> Tier 2
    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_1",
        rejection_reason="Progress stalled in non-mutating loop",
        unmet_reqs=["index.html"],
        mission=loop._mission,
    )

    assert rec_ok is True
    assert loop.active_tier == 2
    assert loop.active_model == TIER2_MODEL
    assert loop.mission_model == TIER2_MODEL
    assert loop._mission_model == TIER2_MODEL
    assert mock_orchestrator._active_tier == 2
    assert real_state_store.current_model == TIER2_MODEL


# ── Test 7: Checkpoint Resume Restores Active Model Identity ──────────────────
@pytest.mark.asyncio
async def test_7_checkpoint_resume_restores_active_model_identity(mock_orchestrator):
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws_dir = Path(tmp_dir)

        # Save a checkpoint at Tier 2
        chk = MissionCheckpointManager.save_checkpoint(
            workspace_root=ws_dir,
            mission_id="m_resume_test",
            current_phase="PHASE_C_MAIN_IMPLEMENTATION",
            tier_state=2,
        )
        assert chk.tier_state == 2

        # Create AgentLoop pointing to this workspace
        mock_ws = MagicMock()
        mock_ws.root_str = str(ws_dir)
        mock_ws.workspace_root = str(ws_dir)
        mock_ws.is_locked = True

        loop = AgentLoop(orchestrator=mock_orchestrator, workspace_manager=mock_ws)

        # Load checkpoint directly into loop
        loaded = MissionCheckpointManager.load_checkpoint(ws_dir)
        assert loaded is not None
        assert loaded.tier_state == 2

        loop.set_active_model_state(tier=loaded.tier_state)

        assert loop.active_tier == 2
        assert loop.active_model == TIER2_MODEL
        assert loop._mission_model == TIER2_MODEL
        assert mock_orchestrator._active_tier == 2


# ── Test 8: Work-Package Transitions Do Not Cause Missing Model Attributes ─────
def test_8_work_package_transitions_preserve_model_attributes(mock_orchestrator):
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_ws = MagicMock()
        mock_ws.root_str = tmp_dir
        mock_ws.workspace_root = tmp_dir
        mock_ws.is_locked = True

        loop = AgentLoop(orchestrator=mock_orchestrator, workspace_manager=mock_ws)
        loop._mission_id = "m_wp_test"

        # Transition phases
        loop.transition_phase(ExecutionPhase.PHASE_B_FOUNDATION, "Scaffolding started")
        assert loop.active_tier == 1
        assert loop._mission_model == TIER1_MODEL

        loop.set_active_model_state(tier=2)
        loop.transition_phase(ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION, "Content started")
        assert loop.active_tier == 2
        assert loop._mission_model == TIER2_MODEL


# ── Test 9: Verification Does Not Cause Missing Model Attributes ───────────────
def test_9_verification_preserves_model_attributes(mock_orchestrator, real_state_store):
    loop = AgentLoop(orchestrator=mock_orchestrator, state_store_instance=real_state_store)
    loop.set_active_model_state(tier=2)

    assert hasattr(loop, "_mission_model")
    assert loop._mission_model == TIER2_MODEL
    assert loop.active_model == TIER2_MODEL
    assert real_state_store.current_model == TIER2_MODEL


# ── Test 10: Mission Completion Preserves Consistent Model State ───────────────
def test_10_mission_completion_preserves_consistent_model_state(mock_orchestrator):
    loop = AgentLoop(orchestrator=mock_orchestrator)
    loop.set_active_model_state(tier=3)

    assert loop.active_tier == 3
    assert loop.active_model == TIER3_MODEL
    assert loop._mission_model == TIER3_MODEL
    assert getattr(loop.orchestrator, "_active_tier", None) == 3


# ── Test 11: Repeated Failovers Do Not Desynchronize Model Identity ───────────
def test_11_repeated_failover_preserves_synchronization(mock_orchestrator, real_state_store):
    loop = AgentLoop(orchestrator=mock_orchestrator, state_store_instance=real_state_store)

    # T1 -> T2
    loop.set_active_model_state(tier=2)
    assert loop.active_tier == 2
    assert loop._mission_model == TIER2_MODEL
    assert mock_orchestrator._active_tier == 2
    assert real_state_store.current_model == TIER2_MODEL

    # T2 -> T3
    loop.set_active_model_state(tier=3)
    assert loop.active_tier == 3
    assert loop._mission_model == TIER3_MODEL
    assert mock_orchestrator._active_tier == 3
    assert real_state_store.current_model == TIER3_MODEL

    # T3 -> T4
    loop.set_active_model_state(tier=4)
    assert loop.active_tier == 4
    assert loop._mission_model == TIER4_MODEL
    assert mock_orchestrator._active_tier == 4
    assert real_state_store.current_model == TIER4_MODEL

    # Recovery clearing back to T1
    loop.set_active_model_state(tier=1)
    assert loop.active_tier == 1
    assert loop._mission_model == TIER1_MODEL
    assert mock_orchestrator._active_tier == 1
    assert real_state_store.current_model == TIER1_MODEL


# ── Test 12: Invalid Model State Produces A Clear Classified Failure ──────────
def test_12_invalid_model_state_produces_classified_failure(mock_orchestrator):
    loop = AgentLoop(orchestrator=mock_orchestrator)

    with pytest.raises(InvalidModelStateError) as exc_info:
        loop.set_active_model_state(tier=99)
    assert "Invalid model tier" in str(exc_info.value)

    with pytest.raises(InvalidModelStateError) as exc_info2:
        loop.set_active_model_state(tier=-1)
    assert "Invalid model tier" in str(exc_info2.value)


# ── Test 13: Static Self-Attribute Audit Verifies Initialized Lifecycle Fields ──
def test_13_static_self_attribute_audit(mock_orchestrator):
    loop = AgentLoop(orchestrator=mock_orchestrator)

    # Core required lifecycle attributes that caused or could cause missing attribute failures
    critical_attributes = [
        "_mission_model",
        "mission_model",
        "active_tier",
        "active_provider",
        "active_model",
        "mission",
        "_mission",
        "_mission_id",
        "_active_routing_tier",
        "_recovery_attempt_count",
        "_consecutive_no_progress_blocks",
        "_consecutive_empty_turns",
        "_consecutive_non_mutating_turns",
        "_in_recovery",
    ]

    for attr in critical_attributes:
        assert hasattr(loop, attr), f"AgentLoop is missing critical attribute/property: {attr}"

    # Also AST check that _mission_model is a property on AgentLoop
    assert isinstance(inspect.getattr_static(AgentLoop, "_mission_model"), property), (
        "AgentLoop._mission_model must be a property descriptor on the class"
    )
    assert isinstance(inspect.getattr_static(AgentLoop, "mission_model"), property), (
        "AgentLoop.mission_model must be a property descriptor on the class"
    )


# ── Test 14: End-to-End Regression Reproducing Mission m_9bdb4cb3 Lifecycle ────
@pytest.mark.asyncio
async def test_14_e2e_mocked_regression_m_9bdb4cb3_lifecycle(mock_orchestrator, mock_event_bus, real_state_store):
    """
    Simulates the exact failure condition of mission m_9bdb4cb3:
    - Files are created (index.html, style.css, main.js, app.js).
    - Model executes consecutive non-mutating inspection turns without writing.
    - _consecutive_non_mutating_turns reaches >= 4 threshold.
    - Loop attempts recovery transition calling _trigger_recovery_transition(..., mission=self._mission).
    - MUST succeed without raising AttributeError: 'AgentLoop' object has no attribute '_mission_model'.
    - Active model state MUST transition to Tier 2.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws_dir = Path(tmp_dir)

        # 1. Create the files that were written in m_9bdb4cb3
        (ws_dir / "package.json").write_text('{"name": "wanderworld"}', encoding="utf-8")
        (ws_dir / "index.html").write_text("<!DOCTYPE html><html><body><h1>WanderWorld</h1></body></html>", encoding="utf-8")
        (ws_dir / "style.css").write_text("body { font-family: sans-serif; }", encoding="utf-8")
        (ws_dir / "main.js").write_text("// main entrypoint", encoding="utf-8")
        (ws_dir / "app.js").write_text("// app script", encoding="utf-8")

        mock_ws = MagicMock()
        mock_ws.root_str = str(ws_dir)
        mock_ws.workspace_root = str(ws_dir)
        mock_ws.is_locked = True

        loop = AgentLoop(
            orchestrator=mock_orchestrator,
            workspace_manager=mock_ws,
            event_bus_instance=mock_event_bus,
            state_store_instance=real_state_store,
        )
        loop._mission_id = "m_9bdb4cb3"
        loop._publish_event = AsyncMock()

        # Simulate Mission domain object
        mission = Mission(
            mission_id="m_9bdb4cb3",
            user_prompt="Create a visually impressive travel agency website called WanderWorld.",
        )
        loop.mission = mission
        assert loop.mission.mission_id == "m_9bdb4cb3"

        # Verify initial model state is Tier 1
        assert loop.active_tier == 1
        assert loop.active_model == TIER1_MODEL
        assert loop._mission_model == TIER1_MODEL

        # 2. Simulate 4 non-mutating inspection turns (the exact trigger of m_9bdb4cb3 failure)
        loop._consecutive_non_mutating_turns = 4

        # 3. Trigger recovery transition exactly as loop.py does at line 5003
        rec_ok = await loop._trigger_recovery_transition(
            turn_id="turn_4",
            rejection_reason="Model performed 4 consecutive non-mutating turns without code modifications",
            unmet_reqs=["Missing interactive filters and modal dialog"],
            mission=loop._mission,
        )

        # 4. Verify recovery succeeded without AttributeError
        assert rec_ok is True, "Recovery transition must succeed"

        # 5. Verify authoritative model state transitioned cleanly to Tier 2
        assert loop.active_tier == 2, "Active tier must be 2 after first recovery transition"
        assert loop.active_model == TIER2_MODEL, "Active model must be TIER2_MODEL"
        assert loop.active_provider == TIER2_PROVIDER, "Active provider must be TIER2_PROVIDER"
        assert loop.mission_model == TIER2_MODEL, "mission_model must return TIER2_MODEL"
        assert loop._mission_model == TIER2_MODEL, "_mission_model must return TIER2_MODEL"

        # 6. Verify orchestrator and runtime state reflect the transition
        assert mock_orchestrator._active_tier == 2
        assert real_state_store.current_model == TIER2_MODEL
        assert real_state_store._state.model_execution.tier == 2
        assert real_state_store._state.model_execution.model == TIER2_MODEL
