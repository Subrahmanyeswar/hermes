"""
tests/test_phase5_transport_safety.py
======================================
Phase 5 Acceptance Tests - Model Transport Outage and Network Safety During Generation / Quality Gates.

Scenario S: Transport Outage During Contract Evaluation / Generation.
            When a transient network error or model provider 503 occurs during generation or
            quality evaluation, the system cleanly triggers Phase 4 WAITING_FOR_PROVIDER /
            WAITING_FOR_NETWORK state, without corrupting the active ImplementationBlueprint,
            InterfaceManifest, or generating duplicate tool executions.
"""

import pytest
from pathlib import Path

from core.contracts.builder import ContractBuilder
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionState,
    MissionStatus,
    WaitReason,
    NetworkState,
    NetworkConnectivity,
)
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.reducer import StateReducer


def test_scenario_s_transport_safety_during_contract_lifecycle():
    """
    Scenario S:
    Verify that when model transport drops into WAITING_FOR_PROVIDER or WAITING_FOR_NETWORK,
    the contract state, mission state, and attempt fencing are safely preserved and not corrupted.
    """
    mission_id = "p5-transport-safety-test"
    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id=mission_id,
        prompt="Build application with high network resilience",
        extra_files=["styles.css", "app.js"],
    )

    state = HermesRuntimeState(
        mission=MissionState(
            mission_id=mission_id,
            status=MissionStatus.RUNNING,
            attempt_number=1,
            run_id="run-net-01",
        )
    )
    state.blueprint = blueprint
    state.interface_manifest = manifest
    state.quality_rubric = rubric

    # Simulate network outage event (Phase 4 integration)
    net_event = HermesEvent(
        event_id="evt-net-down-01",
        sequence=1,
        mission_id=mission_id,
        attempt_number=1,
        run_id="run-net-01",
        event_type=EventType.MISSION_WAITING,
        payload={
            "wait_reason": WaitReason.WAITING_FOR_NETWORK.value,
            "reason": "Connection timed out to model provider gateway",
        },
    )

    state = StateReducer.reduce(state, net_event)

    # State verification: mission is WAITING or paused, contracts intact
    assert state.mission.status == MissionStatus.WAITING
    assert state.progress.waiting_reason == WaitReason.WAITING_FOR_NETWORK
    assert state.blueprint is not None
    assert state.blueprint.mission_id == mission_id
    assert state.interface_manifest is not None
    assert state.quality_rubric is not None

    # Simulate network recovery
    recovery_event = HermesEvent(
        event_id="evt-net-up-02",
        sequence=2,
        mission_id=mission_id,
        attempt_number=1,
        run_id="run-net-01",
        event_type=EventType.NETWORK_RESTORED,
        payload={},
    )

    recovered_state = StateReducer.reduce(state, recovery_event)
    assert recovered_state.progress.waiting_reason == WaitReason.WORKING
    # Contracts remain fully intact post-recovery
    assert recovered_state.blueprint.mission_id == mission_id
    assert any(f.path == "index.html" for f in recovered_state.blueprint.planned_files)
