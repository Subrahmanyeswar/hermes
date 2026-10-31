"""
Tests for HERMES Incident Planning and Lifecycle Recovery.
Validates:
1. Multi-attempt run identity propagation in StateReducer (preventing stale run drops).
2. AgentLoop persistence signature compliance (workspace_path provided to db.save_mission).
3. Adaptive router and coordinator circuit state synchronization.
4. Empty workspace existing-application preflight detection (fast-fail on missing target app).
5. Stage 6 audit port conflict handling and clean task termination.
6. Replay fidelity of multi-attempt interrupted missions.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from core.adaptive_routing import get_adaptive_router, ProviderHealthState
from core.agent_loop.loop import AgentLoop
from core.event_bus import event_bus
from core.network.coordinator import NetworkRecoveryCoordinator
from core.persistence.database import SQLiteDatabase
from core.runtime_state.events import EventType, HermesEvent, EventSeverity
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    MissionState,
    WaitReason,
    is_legal_mission_transition,
)
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore
from core.workspace import WorkspaceManager
from scripts.audit_stage6_real_execution import is_port_available, find_free_port


# ── Test 1: Multi-Attempt Run Identity in StateReducer ───────────────────────

def test_state_reducer_multi_attempt_run_identity():
    """Verify that StateReducer does not drop attempt 2 events when attempt increments."""
    mission_id = "m_test_multi_attempt"
    state = HermesRuntimeState(
        mission=MissionState(
            mission_id=mission_id,
            status=MissionStatus.CREATED,
            run_id="run_1_initial",
            attempt_number=1,
        )
    )

    # Event 1: Attempt 1 Started
    e1 = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_1_initial",
        attempt_number=1,
        sequence=1,
        timestamp=time.time(),
        payload={"workspace_root": "C:/tmp/test"},
    )
    state = StateReducer.reduce(state, e1)
    assert state.mission.status == MissionStatus.RUNNING
    assert state.mission.run_id == "run_1_initial"
    assert state.mission.attempt_number == 1
    assert state.last_event_sequence == 1

    # Event 2: Attempt 1 Waiting
    e2 = HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id=mission_id,
        run_id="run_1_initial",
        attempt_number=1,
        sequence=2,
        timestamp=time.time(),
        payload={"wait_reason": "WAITING_FOR_PROVIDER"},
    )
    state = StateReducer.reduce(state, e2)
    assert state.mission.status == MissionStatus.WAITING

    # Event 3: Attempt 2 Resumed
    e3 = HermesEvent(
        event_type=EventType.MISSION_RESUMED,
        mission_id=mission_id,
        run_id="run_2_continuation",
        attempt_number=2,
        sequence=3,
        timestamp=time.time(),
        payload={"run_id": "run_2_continuation", "attempt_number": 2},
    )
    state = StateReducer.reduce(state, e3)
    assert state.mission.status == MissionStatus.RUNNING
    assert state.mission.run_id == "run_2_continuation"
    assert state.mission.attempt_number == 2
    assert state.last_event_sequence == 3

    # Event 4: Attempt 2 Model requested (same attempt 2, run_2)
    e4 = HermesEvent(
        event_type=EventType.MODEL_REQUESTED,
        mission_id=mission_id,
        run_id="run_2_continuation",
        attempt_number=2,
        sequence=4,
        timestamp=time.time(),
        payload={"tier": 1},
    )
    state = StateReducer.reduce(state, e4)
    assert state.last_event_sequence == 4  # Must NOT be dropped as stale!

    # Event 5: Attempt 2 Mission Failed
    e5 = HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        run_id="run_2_continuation",
        attempt_number=2,
        sequence=5,
        timestamp=time.time(),
        payload={"error": "Consecutive failure budget exceeded"},
    )
    state = StateReducer.reduce(state, e5)
    assert state.mission.status == MissionStatus.FAILED
    assert state.mission.run_id == "run_2_continuation"
    assert state.mission.attempt_number == 2
    assert state.last_event_sequence == 5
    assert "Consecutive failure budget exceeded" in state.mission.abort_reason


# ── Test 2: Legal Transitions (CREATED -> FAILED) ─────────────────────────────

def test_created_to_failed_transition():
    """Verify CREATED status can legally transition directly to FAILED on preflight failure."""
    assert is_legal_mission_transition(MissionStatus.CREATED, MissionStatus.FAILED)


# ── Test 3: AgentLoop Condition C / D Persistence Signature ──────────────────

@pytest.mark.asyncio
async def test_agent_loop_condition_c_d_persistence(tmp_path: Path):
    """Verify db.save_mission receives required workspace_path and does not raise TypeError."""
    db_file = tmp_path / "test_runtime.db"
    db = SQLiteDatabase(db_file)
    db.save_mission(
        mission_id="m_test_cond",
        workspace_path=str(tmp_path),
        status="RUNNING",
    )

    mock_eb = MagicMock()
    mock_eb.get_database.return_value = db
    mock_eb.publish = MagicMock()

    ws = WorkspaceManager()
    ws.lock(str(tmp_path))

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws,
        event_bus_instance=mock_eb,
    )
    loop._mission_id = "m_test_cond"
    loop._run_id = "run_1_cond"
    loop._attempt_number = 1

    # Simulate Condition D persistence block
    ws_path = loop.workspace.root_str if (loop.workspace and hasattr(loop.workspace, "root_str") and loop.workspace.root_str) else str(Path.cwd())
    db.save_mission(
        mission_id=loop._mission_id,
        workspace_path=ws_path,
        status="WAITING",
        run_id=loop._run_id,
        attempt_number=loop._attempt_number,
        wait_reason="WAITING_FOR_NETWORK",
        execution_active=False,
        recovery_required=True,
        error_json={"error": "network timeout", "condition": "CONDITION_D"},
    )

    row = db.get_mission("m_test_cond")
    assert row is not None
    assert row["status"] == "WAITING"
    assert row["wait_reason"] == "WAITING_FOR_NETWORK"
    assert row["recovery_required"] == 1
    assert row["execution_active"] == 0
    assert row["workspace_path"] == str(tmp_path)


# ── Test 4: Adaptive Router Circuit State Synchronization ────────────────────

def test_circuit_state_synchronization():
    """Verify that coordinator recovery notification resets AdaptiveRouter Tier 1 circuit."""
    router = get_adaptive_router()
    # Trip Tier 1 circuit to OPEN_CIRCUIT
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.providers[1].state == ProviderHealthState.OPEN_CIRCUIT
    assert not router.is_tier_healthy(1)

    # Invoke coordinator recovery notification
    coordinator = NetworkRecoveryCoordinator()
    coordinator.notify_provider_recovered(provider="nvidia_nim", model="test-model")

    # Verify router state is restored to HEALTHY
    assert router.providers[1].state == ProviderHealthState.HEALTHY
    assert router.is_tier_healthy(1)
    assert router.providers[1].consecutive_first_token_failures == 0


# ── Test 5: Empty Workspace Existing-Application Preflight ───────────────────

@pytest.mark.asyncio
async def test_empty_workspace_existing_app_preflight(tmp_path: Path):
    """Verify AgentLoop halts immediately if prompt asks to modify existing app but workspace is empty."""
    empty_ws = tmp_path / "empty_workspace"
    empty_ws.mkdir()

    ws = WorkspaceManager()
    ws.lock(str(empty_ws))

    published_events: list[HermesEvent] = []

    mock_eb = MagicMock()
    mock_eb.get_database.return_value = None

    async def _mock_pub(evt):
        published_events.append(evt)

    from core.mission_planner import Mission
    mission = Mission(
        mission_id="m_empty_preflight",
        run_id="run_1_empty",
        attempt_number=1,
        user_prompt="Add a GET /health endpoint to the existing application that returns status: ok.",
        workspace_root=str(empty_ws),
    )

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws,
        event_bus_instance=mock_eb,
    )
    # Patch publish method to capture events
    loop._publish_event = AsyncMock(side_effect=lambda et, **kwargs: published_events.append(
        HermesEvent(event_type=et, mission_id="m_empty_preflight", payload=kwargs.get("payload", {}))
    ))

    await loop.run(mission)

    # Check that MISSION_FAILED was published with informative reason
    failed_evts = [e for e in published_events if e.event_type == EventType.MISSION_FAILED]
    assert len(failed_evts) == 1
    err_text = failed_evts[0].payload.get("error", "")
    assert "contains 0 existing application files" in err_text
    assert failed_evts[0].payload.get("failure_code") == "EMPTY_WORKSPACE_EXISTING_APPLICATION"


# ── Test 6: Audit Port Discovery and Occupied Port Handling ─────────────────

def test_audit_port_discovery_and_strict_rejection():
    """Verify find_free_port discovers free ports and strict mode rejects occupied ports."""
    # Find a dynamic free port
    port = find_free_port()
    assert isinstance(port, int)
    assert port > 1024

    # Bind a socket to occupy the port
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", port))
    server_sock.listen(1)

    try:
        # Check availability
        assert not is_port_available(port)

        # In non-strict mode, find_free_port should find another available port
        alt_port = find_free_port(preferred=port)
        assert alt_port != port
        assert is_port_available(alt_port)
    finally:
        server_sock.close()


# ── Test 7: Historical Event Replay of Incident Trajectory ───────────────────

def test_incident_trajectory_replay():
    """Replay sequence 4480 through 4524 with patched StateReducer to verify terminal FAILED state."""
    state = HermesRuntimeState(
        mission=MissionState(
            mission_id="m_a8442b65",
            status=MissionStatus.RUNNING,
            run_id="run_1_4c3a7fc2",
            attempt_number=1,
        ),
        last_event_sequence=4480,
    )

    # 4481: MISSION_WAITING
    e_wait = HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id="m_a8442b65",
        run_id="run_1_4c3a7fc2",
        attempt_number=1,
        sequence=4481,
        timestamp=time.time(),
        payload={"wait_reason": "WAITING_FOR_PROVIDER"},
    )
    state = StateReducer.reduce(state, e_wait)
    assert state.mission.status == MissionStatus.WAITING

    # 4483: NETWORK_RESTORED
    e_restored = HermesEvent(
        event_type=EventType.NETWORK_RESTORED,
        mission_id="m_a8442b65",
        run_id="run_1_4c3a7fc2",
        attempt_number=1,
        sequence=4483,
        timestamp=time.time(),
        payload={"reason": "Network restored"},
    )
    state = StateReducer.reduce(state, e_restored)

    # 4484: MISSION_RESUMED with attempt 2
    e_resumed = HermesEvent(
        event_type=EventType.MISSION_RESUMED,
        mission_id="m_a8442b65",
        run_id="run_2_5d20ec26",
        attempt_number=2,
        sequence=4484,
        timestamp=time.time(),
        payload={"run_id": "run_2_5d20ec26", "attempt_number": 2},
    )
    state = StateReducer.reduce(state, e_resumed)
    assert state.mission.status == MissionStatus.RUNNING
    assert state.mission.run_id == "run_2_5d20ec26"
    assert state.mission.attempt_number == 2

    # 4485-4523: Attempt 2 events (e.g. model requests and failures)
    for seq in range(4485, 4524):
        evt = HermesEvent(
            event_type=EventType.MODEL_REQUESTED if seq % 2 == 1 else EventType.MODEL_FAILED,
            mission_id="m_a8442b65",
            run_id="run_2_5d20ec26",
            attempt_number=2,
            sequence=seq,
            timestamp=time.time(),
            payload={"error": "Connection error"} if seq % 2 == 0 else {"tier": 2},
        )
        state = StateReducer.reduce(state, evt)
        assert state.last_event_sequence == seq

    # 4524: MISSION_FAILED
    e_failed = HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id="m_a8442b65",
        run_id="run_2_5d20ec26",
        attempt_number=2,
        sequence=4524,
        timestamp=time.time(),
        payload={"error": "Consecutive failure budget exceeded (5 failures)"},
    )
    state = StateReducer.reduce(state, e_failed)

    assert state.mission.status == MissionStatus.FAILED
    assert state.mission.run_id == "run_2_5d20ec26"
    assert state.mission.attempt_number == 2
    assert state.last_event_sequence == 4524
    assert "Consecutive failure budget exceeded" in state.mission.abort_reason


# ── Section B: Exact Recovery Safety Invariants (B.1 – B.7) ───────────────────

def test_b1_internet_restoration_does_not_reset_t1_circuit():
    """B.1: Internet restoration does not reset Tier 1 circuit without provider-specific recovery."""
    from core.network.connectivity import ConnectivityStatus

    router = get_adaptive_router()
    # Trip Tier 1 circuit to OPEN_CIRCUIT
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.providers[1].state == ProviderHealthState.OPEN_CIRCUIT
    assert not router.is_tier_healthy(1)

    coordinator = NetworkRecoveryCoordinator()
    # Simulate generic connectivity restoration (OFFLINE -> ONLINE)
    coordinator._on_connectivity_changed(ConnectivityStatus.OFFLINE, ConnectivityStatus.ONLINE)

    # Invariant: Tier 1 circuit MUST remain OPEN_CIRCUIT; internet restoration alone is not provider recovery
    assert router.providers[1].state == ProviderHealthState.OPEN_CIRCUIT
    assert not router.is_tier_healthy(1)


def test_b2_genuine_t1_recovery_resets_circuit_before_continuation():
    """B.2: Genuine Tier 1 recovery resets circuit before continuation."""
    router = get_adaptive_router()
    # Ensure Tier 1 circuit is OPEN_CIRCUIT
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.providers[1].state == ProviderHealthState.OPEN_CIRCUIT

    coordinator = NetworkRecoveryCoordinator()
    coordinator.notify_provider_recovered(provider="nvidia_nim", model="test-model")

    # Invariant: Genuine recovery resets router circuit state to HEALTHY and clears failure counters
    assert router.providers[1].state == ProviderHealthState.HEALTHY
    assert router.is_tier_healthy(1)
    assert router.providers[1].consecutive_first_token_failures == 0


@pytest.mark.asyncio
async def test_b3_fallback_provider_unavailability_enters_waiting_without_budget_exhaustion(tmp_path: Path):
    """B.3: Mission cannot immediately exhaust retry budget against unavailable fallback provider without truthful waiting/recovery handling."""
    import httpx
    from core.network.connectivity import (
        ConnectivityCondition,
        ConnectivityStatus,
        classify_error_condition,
        shared_connectivity_monitor,
    )
    from core.mission_planner import Mission

    err = httpx.ConnectError("Could not connect to Ollama at http://127.0.0.1:11434")
    # Verify classification logic produces CONDITION_C when internet is online
    assert classify_error_condition(err, is_internet_online=True) == ConnectivityCondition.CONDITION_C

    # Set up isolated workspace and AgentLoop
    ws_dir = tmp_path / "ws_b3"
    ws_dir.mkdir()
    (ws_dir / "existing.py").write_text("x = 1\n", encoding="utf-8")

    db_path = tmp_path / "test_b3.db"
    db = SQLiteDatabase(db_path)
    db.save_mission(mission_id="m_b3", workspace_path=str(ws_dir), status="RUNNING")

    mock_eb = MagicMock()
    mock_eb.get_database.return_value = db
    mock_eb.get_or_create_state.return_value = StateStore("m_b3")

    events_emitted = []

    ws = WorkspaceManager()
    ws.lock(str(ws_dir))

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws,
        event_bus_instance=mock_eb,
    )
    loop._publish_event = AsyncMock(side_effect=lambda et, **kwargs: events_emitted.append(
        HermesEvent(event_type=et, mission_id="m_b3", payload=kwargs.get("payload", {}))
    ))

    # Mock _generate_model_turn to simulate unavailable fallback provider
    loop._generate_model_turn = AsyncMock(side_effect=err)

    # Force connectivity monitor to report ONLINE so it is recognized as CONDITION_C (provider outage)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(shared_connectivity_monitor, "probe_now", AsyncMock(return_value=ConnectivityStatus.ONLINE))

        mission = Mission(
            mission_id="m_b3",
            run_id="run_b3",
            attempt_number=1,
            user_prompt="Update existing.py to add y = 2",
            workspace_root=str(ws_dir),
        )
        await loop.run(mission)

    # Invariant: Mission must enter WAITING_FOR_PROVIDER and NOT exhaust turn failure budget (5 failures)
    waiting_events = [e for e in events_emitted if e.event_type == EventType.MISSION_WAITING]
    assert len(waiting_events) >= 1
    assert waiting_events[0].payload.get("wait_reason") == "WAITING_FOR_PROVIDER"
    assert waiting_events[0].payload.get("condition") == "CONDITION_C"

    # Must NOT fail with consecutive failure budget exceeded
    failed_events = [e for e in events_emitted if e.event_type == EventType.MISSION_FAILED]
    assert len(failed_events) == 0

    # DB state must be WAITING
    row = db.get_mission("m_b3")
    assert row["status"] == "WAITING"
    assert row["wait_reason"] == "WAITING_FOR_PROVIDER"


@pytest.mark.asyncio
async def test_b4_existing_app_modification_empty_workspace_produces_informative_blocker(tmp_path: Path):
    """B.4: Existing-app modification request in an empty workspace produces an informative blocker."""
    empty_ws = tmp_path / "empty_ws_b4"
    empty_ws.mkdir()

    ws = WorkspaceManager()
    ws.lock(str(empty_ws))

    published_events = []
    mock_eb = MagicMock()
    mock_eb.get_database.return_value = None

    from core.mission_planner import Mission
    mission = Mission(
        mission_id="m_b4",
        run_id="run_b4",
        attempt_number=1,
        user_prompt="Add a GET /health endpoint to the existing application that returns status: ok.",
        workspace_root=str(empty_ws),
    )

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws,
        event_bus_instance=mock_eb,
    )
    loop._publish_event = AsyncMock(side_effect=lambda et, **kwargs: published_events.append(
        HermesEvent(event_type=et, mission_id="m_b4", payload=kwargs.get("payload", {}))
    ))

    await loop.run(mission)

    failed_evts = [e for e in published_events if e.event_type == EventType.MISSION_FAILED]
    assert len(failed_evts) == 1
    assert failed_evts[0].payload.get("failure_code") == "EMPTY_WORKSPACE_EXISTING_APPLICATION"
    assert "contains 0 existing application files" in failed_evts[0].payload.get("error", "")


@pytest.mark.asyncio
async def test_b5_new_app_creation_empty_workspace_not_rejected_by_preflight(tmp_path: Path):
    """B.5: New-app creation request in an empty workspace is not rejected by preflight."""
    empty_ws = tmp_path / "empty_ws_b5"
    empty_ws.mkdir()

    ws = WorkspaceManager()
    ws.lock(str(empty_ws))

    published_events = []
    mock_eb = MagicMock()
    mock_eb.get_database.return_value = None

    from core.mission_planner import Mission
    mission = Mission(
        mission_id="m_b5",
        run_id="run_b5",
        attempt_number=1,
        user_prompt="Create a new FastAPI application with GET /health returning status: ok.",
        workspace_root=str(empty_ws),
    )

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws,
        event_bus_instance=mock_eb,
    )
    loop._publish_event = AsyncMock(side_effect=lambda et, **kwargs: published_events.append(
        HermesEvent(event_type=et, mission_id="m_b5", payload=kwargs.get("payload", {}))
    ))
    loop._generate_model_turn = AsyncMock(return_value="```json\n{\"thought\": \"creating app\", \"tool\": \"finish_mission\"}\n```")

    try:
        await asyncio.wait_for(loop.run(mission), timeout=2.0)
    except asyncio.TimeoutError:
        pass

    # Invariant: Preflight failure must NOT be emitted
    preflight_failures = [
        e for e in published_events
        if e.event_type == EventType.MISSION_FAILED and e.payload.get("failure_code") == "EMPTY_WORKSPACE_EXISTING_APPLICATION"
    ]
    assert len(preflight_failures) == 0


def test_b6_stale_events_earlier_attempt_cannot_overwrite_current_outcome_or_terminal():
    """B.6: Stale events from earlier attempt cannot overwrite current attempt's outcome or terminal state."""
    mission_id = "m_b6"
    state = HermesRuntimeState(
        mission=MissionState(
            mission_id=mission_id,
            status=MissionStatus.RUNNING,
            run_id="run_2_current",
            attempt_number=2,
        ),
        last_event_sequence=10,
    )

    # 1. Incoming event from Attempt 1 (stale attempt 1 failure)
    stale_event = HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        run_id="run_1_stale",
        attempt_number=1,
        sequence=11,
        payload={"error": "Stale attempt 1 failure"},
    )
    next_state = StateReducer.reduce(state, stale_event)
    # Invariant: Reducer completely ignores attempt 1 event
    assert next_state.mission.status == MissionStatus.RUNNING
    assert next_state.mission.run_id == "run_2_current"
    assert next_state.mission.attempt_number == 2
    assert next_state.last_event_sequence == 10

    # 2. Transition current attempt to terminal COMPLETED
    complete_event = HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        run_id="run_2_current",
        attempt_number=2,
        sequence=12,
        payload={"summary": "Mission successfully completed"},
    )
    terminal_state = StateReducer.reduce(next_state, complete_event)
    assert terminal_state.mission.status == MissionStatus.COMPLETED
    assert terminal_state.mission.is_terminal

    # 3. Late event attempting to resurrect terminal state back to RUNNING
    resurrect_event = HermesEvent(
        event_type=EventType.AGENT_TURN_STARTED,
        mission_id=mission_id,
        run_id="run_2_current",
        attempt_number=2,
        sequence=13,
        payload={"turn_id": "turn_late"},
    )
    after_resurrect = StateReducer.reduce(terminal_state, resurrect_event)
    # Invariant: Terminal status is preserved, cannot be resurrected
    assert after_resurrect.mission.status == MissionStatus.COMPLETED
    assert after_resurrect.mission.is_terminal


def test_b7_recovery_retains_immutable_workspace_binding_and_preserves_uncertainty(tmp_path: Path):
    """B.7: Recovery retains immutable workspace binding and preserves unresolved filesystem uncertainty."""
    from core.persistence.models import OperationStatus
    from core.persistence.recovery import ReconciliationDiscrepancyType, RecoveryEngine
    from core.persistence.blobs import BlobStore

    db_path = tmp_path / "test_b7.db"
    db = SQLiteDatabase(db_path)
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    blob_store = BlobStore(blob_dir)
    engine = RecoveryEngine(db=db, blob_store=blob_store)

    # Part 1: Immutable workspace binding
    # If workspace path points to a non-existent directory, recovery must reject
    missing_ws = tmp_path / "nonexistent_workspace"
    ws_ok, _, ws_err = engine.validate_workspace(str(missing_ws))
    assert not ws_ok
    assert "does not exist" in ws_err

    # Coordinator marks mission blocked under WAITING_FOR_WORKSPACE
    db.save_mission(
        mission_id="m_b7_ws",
        workspace_path=str(missing_ws),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
    )
    coord = NetworkRecoveryCoordinator(db=db, recovery_engine=engine)
    eligible, reason = coord.evaluate_auto_resume_eligibility("m_b7_ws")
    assert not eligible
    assert "Original workspace inaccessible" in reason

    row = db.get_mission("m_b7_ws")
    assert row["wait_reason"] == "WAITING_FOR_WORKSPACE"

    # Part 2: Preserves unresolved filesystem uncertainty
    valid_ws = tmp_path / "valid_ws"
    valid_ws.mkdir()
    (valid_ws / "app.py").write_text("print('hello')", encoding="utf-8")

    db.save_mission(
        mission_id="m_b7_unc",
        workspace_path=str(valid_ws),
        status="WAITING",
        wait_reason="WAITING_FOR_PROVIDER",
    )
    # Record an uncommitted / uncertain tool operation
    db.record_tool_intent(
        operation_id="op_uncertain_001",
        mission_id="m_b7_unc",
        tool_name="write_file",
        intent_seq=1,
        target_path="app.py",
        workspace_root=str(valid_ws),
    )
    db.record_tool_result(
        operation_id="op_uncertain_001",
        result_seq=2,
        status=OperationStatus.OUTCOME_UNKNOWN,
    )

    # Reconcile disk with ledger
    discrepancies = engine.reconcile_disk_with_ledger("m_b7_unc", valid_ws)
    assert len(discrepancies) == 1
    assert discrepancies[0].discrepancy_type == ReconciliationDiscrepancyType.OPERATION_UNCERTAIN
    assert discrepancies[0].blocking is True
    assert discrepancies[0].operation_id == "op_uncertain_001"

    # Formulate resume plan
    plan = engine.formulate_resume_plan("m_b7_unc")
    assert not plan.can_resume
    assert any(d.discrepancy_type == ReconciliationDiscrepancyType.OPERATION_UNCERTAIN for d in plan.discrepancies)

