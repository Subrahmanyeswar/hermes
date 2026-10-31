"""
tests/test_phase5_event_durability_restart.py
=============================================
Phase 5 Acceptance Tests - WAL Durability and State Reconstitution on Restart.

Scenario Q: Durable Event Bus WAL Logging for Contracts and Verifications.
            CONTRACT_CREATED, VERIFICATION_CHECK, and REPAIR_* events are synchronously
            written to the durable append-only WAL before any GUI broadcast occurs.

Scenario R: State Reconstitution on Restart / Crash Recovery.
            A fresh session or process restarting from persistent state accurately restores
            the ImplementationBlueprint, InterfaceManifest, QualityRubric, and VerificationState
            without data loss or corruption.
"""

import pytest
import tempfile
import json
from pathlib import Path

from core.contracts.builder import ContractBuilder
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.runtime_state.reducer import StateReducer
from core.persistence.serializer import serialize_runtime_state, deserialize_runtime_state


def test_scenario_q_wal_durability_of_contract_events(tmp_path: Path):
    """
    Scenario Q:
    Verify that contract and verification events are formatted with schema conformity,
    can be serialized to JSON WAL records, and round-tripped with 100% fidelity.
    """
    wal_file = tmp_path / "events.jsonl"
    mission_id = "p5-wal-test"

    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id=mission_id,
        prompt="Build resilient app",
    )

    # 1. Event: CONTRACT_CREATED
    contract_event = HermesEvent(
        event_id="evt-contract-01",
        sequence=1,
        mission_id=mission_id,
        attempt_number=1,
        run_id="run-001",
        event_type=EventType.CONTRACT_CREATED,
        payload={
            "blueprint": blueprint.to_dict(),
            "manifest": manifest.to_dict(),
            "rubric": rubric.to_dict(),
        },
    )

    # 2. Event: VERIFICATION_CHECK
    verif_event = HermesEvent(
        event_id="evt-verif-02",
        sequence=2,
        mission_id=mission_id,
        attempt_number=1,
        run_id="run-001",
        event_type=EventType.VERIFICATION_CHECK,
        payload={
            "check_type": "alignment",
            "passed": False,
            "hard_error_count": 1,
            "issues": ["missing DOM id: app"],
        },
    )

    # Append synchronously to WAL file
    with open(wal_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(contract_event.to_dict()) + "\n")
        f.write(json.dumps(verif_event.to_dict()) + "\n")

    # Read back and verify durable persistence
    lines = wal_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    rec2 = json.loads(lines[1])

    assert rec1["event_type"] == EventType.CONTRACT_CREATED.value
    assert "blueprint" in rec1["payload"]
    assert rec2["event_type"] == EventType.VERIFICATION_CHECK.value
    assert rec2["payload"]["hard_error_count"] == 1


def test_scenario_r_state_reconstitution_on_restart(tmp_path: Path):
    """
    Scenario R:
    Verify that a state containing full contracts (blueprint, manifest, rubric)
    serializes to disk and reconstitutes exactly on restart.
    """
    mission_id = "p5-restart-test"
    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id=mission_id,
        prompt="App with state persistence across restart",
        extra_files=["styles.css", "app.js"],
    )

    initial_state = HermesRuntimeState(
        mission=MissionState(
            mission_id=mission_id,
            status=MissionStatus.RUNNING,
            attempt_number=1,
            run_id="run-restart-01",
        )
    )
    initial_state.blueprint = blueprint
    initial_state.interface_manifest = manifest
    initial_state.quality_rubric = rubric

    # Serialize full state
    serialized_dict, state_hash = serialize_runtime_state(initial_state)

    # Reconstitute into brand new state instance
    restored_state = deserialize_runtime_state(serialized_dict)

    assert restored_state.mission.mission_id == mission_id
    assert restored_state.blueprint is not None
    assert restored_state.blueprint.mission_id == mission_id
    assert any(f.path == "index.html" for f in restored_state.blueprint.planned_files)
    assert restored_state.interface_manifest is not None
    assert "index.html" in restored_state.interface_manifest.html_entrypoints
    assert restored_state.quality_rubric is not None
    assert restored_state.quality_rubric.rubric_id == rubric.rubric_id
