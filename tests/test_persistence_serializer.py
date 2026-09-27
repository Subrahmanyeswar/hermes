# tests/test_persistence_serializer.py
from core.persistence.serializer import serialize_runtime_state, deserialize_runtime_state, compute_state_hash
from core.runtime_state.models import HermesRuntimeState, TaskState, TaskStatus, RequirementState, RequirementStatus


def test_serializer_roundtrip():
    state = HermesRuntimeState.create_empty("mission_roundtrip", "sess_roundtrip")
    state.tasks["task_1"] = TaskState(
        task_id="task_1",
        mission_id="mission_roundtrip",
        title="Implement Parser",
        status=TaskStatus.COMPLETED,
    )
    state.requirements["req_1"] = RequirementState(
        requirement_id="req_1",
        goal_id="goal_mission_roundtrip",
        title="Zero-hang streaming",
        status=RequirementStatus.VERIFIED,
    )

    data, state_hash = serialize_runtime_state(state)
    assert isinstance(state_hash, str) and len(state_hash) == 64

    # Deserialization must recreate identical logical models
    recovered = deserialize_runtime_state(data)
    assert recovered.mission.mission_id == "mission_roundtrip"
    assert "task_1" in recovered.tasks
    assert recovered.tasks["task_1"].status == TaskStatus.COMPLETED
    assert "req_1" in recovered.requirements
    assert recovered.requirements["req_1"].status == RequirementStatus.VERIFIED

    # State hash of recovered state must match
    _, recovered_hash = serialize_runtime_state(recovered)
    assert recovered_hash == state_hash
