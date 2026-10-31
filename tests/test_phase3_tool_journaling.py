# tests/test_phase3_tool_journaling.py
"""
Deterministic acceptance tests for HERMES Phase 3:
Durable Tool-Result Journaling, Write-Ahead Intent, and Safe File Operations.

Scenarios Covered:
A. Write-ahead intent barrier (intent committed durably before execution).
B. Intent persistence failure halts execution with ZERO physical side effects.
C. Tool result durability and correlation with operation identity and sequence numbers.
D. Result commit failure triggers OUTCOME_UNKNOWN / REQUIRES_RECONCILIATION protocol.
E. Duplicate tool dispatch rejection (replay and idempotency protection).
F. Interrupted operation inspection upon restart (reconciliation protocol).
G. Subprocess execution journaling with structured metadata (command, PID, exit code, duration).
"""

import os
import time
import uuid
import pytest
from pathlib import Path
from unittest.mock import patch

from core.event_bus import EventBus
from core.persistence.database import SQLiteDatabase
from core.persistence.models import OperationStatus, ToolPersistenceError
from core.agent_loop.actions import ActionExecutor
from core.agent_loop.types import ActionEnvelope, ActionStatus
from core.runtime_state.events import EventType
from core.workspace import WorkspaceManager
from tools.platform.file_identity import file_identity_cache


@pytest.fixture
def temp_workspace(tmp_path: Path):
    ws_dir = tmp_path / "test_workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    file_identity_cache.clear()
    wm = WorkspaceManager()
    wm.lock(ws_dir)
    yield wm
    wm.unlock()
    file_identity_cache.clear()


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "hermes_test_journal.db"
    db = SQLiteDatabase(db_file)
    yield db


@pytest.fixture
def test_bus(test_db: SQLiteDatabase):
    bus = EventBus(enabled=True, db=test_db)
    yield bus
    bus.flush()


@pytest.mark.asyncio
async def test_scenario_a_write_ahead_intent_committed_before_execution(
    temp_workspace: WorkspaceManager,
    test_db: SQLiteDatabase,
    test_bus: EventBus,
):
    """
    Scenario A: Write-Ahead Intent Barrier
    Validates that:
    1. Operation intent is committed to SQLite before physical execution occurs.
    2. Operation record in database has status INTENT_COMMITTED and monotonic intent_seq.
    3. After execution, result record is durably committed with matching operation_id and result_seq.
    """
    executor = ActionExecutor(mode="auto")
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    op_id = f"op_test_scenario_a_{uuid.uuid4().hex[:6]}"

    target_file = Path(temp_workspace.root_str) / "scenario_a.txt"
    assert not target_file.exists()

    action = ActionEnvelope(
        action_id=op_id,
        mission_id=mission_id,
        tool_name="fs.write",
        arguments={"path": "scenario_a.txt", "content": "Hello Scenario A\n"},
    )

    with patch("core.agent_loop.actions.event_bus", test_bus):
        obs = await executor.execute_action(action, workspace=temp_workspace)

    assert obs.success is True
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "Hello Scenario A\n"

    # Verify persistent database operation record
    record = test_db.get_tool_operation(op_id)
    assert record is not None
    assert record["operation_id"] == op_id
    assert record["mission_id"] == mission_id
    assert record["tool_name"] == "fs.write"
    assert record["status"] == OperationStatus.RESULT_COMMITTED.value
    assert record["intent_seq"] > 0
    assert record["result_seq"] is not None
    assert record["result_seq"] > record["intent_seq"]
    assert record["exit_code"] == 0
    assert "scenario_a.txt" in record["target_path"]


@pytest.mark.asyncio
async def test_scenario_b_intent_commit_failure_prevents_physical_execution(
    temp_workspace: WorkspaceManager,
    test_db: SQLiteDatabase,
    test_bus: EventBus,
):
    """
    Scenario B: Intent Commit Failure Halts Execution
    If writing the intent to the persistent store fails:
    1. Physical execution MUST NEVER occur.
    2. Target file MUST NOT be created or modified on disk.
    3. Action status is FAILED with a structured persistence barrier error.
    """
    executor = ActionExecutor(mode="auto")
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    op_id = f"op_test_scenario_b_{uuid.uuid4().hex[:6]}"
    target_file = Path(temp_workspace.root_str) / "should_not_exist.txt"

    action = ActionEnvelope(
        action_id=op_id,
        mission_id=mission_id,
        tool_name="fs.write",
        arguments={"path": "should_not_exist.txt", "content": "Never written\n"},
    )

    # Simulate database disk error on publish_durable during intent commit
    def failing_publish_durable(event):
        if event.event_type == EventType.TOOL_STARTED:
            raise ToolPersistenceError("DISK_I_O_ERROR: Simulated disk write failure on intent commit.")
        return test_bus.publish(event)

    with patch.object(test_bus, "publish_durable", side_effect=failing_publish_durable):
        with patch("core.agent_loop.actions.event_bus", test_bus):
            obs = await executor.execute_action(action, workspace=temp_workspace)

    assert obs.success is False
    assert "WRITE_AHEAD_BARRIER_FAILED" in (obs.error_message or "")
    assert not target_file.exists(), "Target file must NOT be written when intent commit fails!"


@pytest.mark.asyncio
async def test_scenario_c_result_durability_and_hash_correlation(
    temp_workspace: WorkspaceManager,
    test_db: SQLiteDatabase,
    test_bus: EventBus,
):
    """
    Scenario C: Result Durability and SHA-256 Hash Correlation
    1. Pre-existing file has known SHA-256.
    2. Edit operation captures prior hash in intent and post hash in result.
    3. Result record references identical operation_id and valid monotonic sequence numbers.
    """
    executor = ActionExecutor(mode="auto")
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    op_id = f"op_test_scenario_c_{uuid.uuid4().hex[:6]}"

    target_file = Path(temp_workspace.root_str) / "source_code.py"
    target_file.write_text("def run():\n    return 42\n", encoding="utf-8")
    import hashlib
    initial_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()

    # Read the file first to satisfy read-before-edit requirement
    file_identity_cache.record(target_file, encoding="utf-8")

    action = ActionEnvelope(
        action_id=op_id,
        mission_id=mission_id,
        tool_name="fs.edit",
        arguments={
            "path": "source_code.py",
            "old_string": "42",
            "new_string": "100",
        },
    )

    with patch("core.agent_loop.actions.event_bus", test_bus):
        obs = await executor.execute_action(action, workspace=temp_workspace)

    assert obs.success is True
    post_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
    assert post_hash != initial_hash

    # Verify journaled database record
    record = test_db.get_tool_operation(op_id)
    assert record is not None
    assert record["status"] == OperationStatus.RESULT_COMMITTED.value
    assert record["prior_hash"] == initial_hash
    assert record["post_hash"] == post_hash
    assert record["result_seq"] > record["intent_seq"]


@pytest.mark.asyncio
async def test_scenario_d_uncertain_outcome_protocol_on_result_commit_failure(
    temp_workspace: WorkspaceManager,
    test_db: SQLiteDatabase,
    test_bus: EventBus,
):
    """
    Scenario D: Uncertain Outcome Protocol (Side Effects Committed, Result Commit Failed)
    If a tool physical action executes, but committing its result fails:
    1. System marks the operation OUTCOME_UNKNOWN / REQUIRES_RECONCILIATION.
    2. Does NOT report false rollback or pretend nothing happened.
    3. Observation clearly informs agent that reconciliation is required before any retry.
    """
    executor = ActionExecutor(mode="auto")
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    op_id = f"op_test_scenario_d_{uuid.uuid4().hex[:6]}"
    target_file = Path(temp_workspace.root_str) / "uncertain.txt"

    action = ActionEnvelope(
        action_id=op_id,
        mission_id=mission_id,
        tool_name="fs.write",
        arguments={"path": "uncertain.txt", "content": "Physical write done\n"},
    )

    original_publish_durable = test_bus.publish_durable

    def failing_result_commit(event):
        if event.event_type in (EventType.TOOL_COMPLETED, EventType.TOOL_FAILED):
            raise ToolPersistenceError("CONNECTION_LOST: Cannot commit tool result to SQLite.")
        return original_publish_durable(event)

    with patch.object(test_bus, "publish_durable", side_effect=failing_result_commit):
        with patch("core.agent_loop.actions.event_bus", test_bus):
            obs = await executor.execute_action(action, workspace=temp_workspace)

    # Physical write DID occur
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "Physical write done\n"

    # But outcome was reported as uncertain / requires reconciliation
    assert obs.success is False
    assert obs.error_type == "OUTCOME_UNKNOWN"
    assert "REQUIRES_RECONCILIATION" in (obs.error_message or "")

    # Operation record in database is marked OUTCOME_UNKNOWN
    record = test_db.get_tool_operation(op_id)
    assert record is not None
    assert record["status"] == OperationStatus.OUTCOME_UNKNOWN.value


@pytest.mark.asyncio
async def test_scenario_e_duplicate_dispatch_rejection(
    temp_workspace: WorkspaceManager,
    test_db: SQLiteDatabase,
    test_bus: EventBus,
):
    """
    Scenario E: Duplicate Dispatch and Replay Protection
    Dispatching a second action with the identical operation_id is rejected
    to protect against replay loops and corrupted state.
    """
    executor = ActionExecutor(mode="auto")
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    op_id = f"op_dedup_{uuid.uuid4().hex[:6]}"

    action1 = ActionEnvelope(
        action_id=op_id,
        mission_id=mission_id,
        tool_name="fs.write",
        arguments={"path": "dedup.txt", "content": "First run\n"},
    )

    with patch("core.agent_loop.actions.event_bus", test_bus):
        obs1 = await executor.execute_action(action1, workspace=temp_workspace)
    assert obs1.success is True

    # Dispatch second action with IDENTICAL operation_id
    action2 = ActionEnvelope(
        action_id=op_id,
        mission_id=mission_id,
        tool_name="fs.write",
        arguments={"path": "dedup.txt", "content": "Second run\n"},
    )

    with patch("core.agent_loop.actions.event_bus", test_bus):
        obs2 = await executor.execute_action(action2, workspace=temp_workspace)

    assert obs2.success is False
    assert obs2.error_type == "DUPLICATE_OPERATION"
    assert "already committed" in (obs2.error_message or "")


def test_scenario_f_interrupted_operation_startup_reconciliation(
    temp_workspace: WorkspaceManager,
    test_db: SQLiteDatabase,
    test_bus: EventBus,
):
    """
    Scenario F: Interrupted Operation Inspection upon Startup
    If a process restarts while an operation intent is committed but not finalized:
    RuntimeAdapter.restore_persisted_missions() detects the incomplete intent
    and marks it OUTCOME_UNKNOWN / REQUIRES_RECONCILIATION without re-executing it.
    """
    from core.server.runtime_adapter import RuntimeAdapter
    mission_id = f"m_restart_{uuid.uuid4().hex[:6]}"
    op_id = f"op_interrupted_{uuid.uuid4().hex[:6]}"

    # Save a mission record marked active
    test_db.save_mission(
        mission_id=mission_id,
        workspace_path=str(temp_workspace.root_str),
        status="RUNNING",
        execution_active=True,
    )

    # Record an intent that was never followed by a result
    test_db.record_tool_intent(
        operation_id=op_id,
        mission_id=mission_id,
        tool_name="fs.write",
        intent_seq=42,
        arguments={"path": "interrupted.txt", "content": "incomplete"},
    )

    # Initial status is INTENT_COMMITTED
    initial_op = test_db.get_tool_operation(op_id)
    assert initial_op["status"] == OperationStatus.INTENT_COMMITTED.value

    # Instantiate RuntimeAdapter which runs restore_persisted_missions on startup
    with patch("core.server.runtime_adapter.global_event_bus", test_bus):
        adapter = RuntimeAdapter(event_bus=test_bus, workspace_manager=temp_workspace)

    # Verified: status was reconciled to OUTCOME_UNKNOWN
    reconciled_op = test_db.get_tool_operation(op_id)
    assert reconciled_op["status"] == OperationStatus.OUTCOME_UNKNOWN.value
    assert "REQUIRES_RECONCILIATION" in reconciled_op["error_message"]

    # Mission execution_active is reset to False and recovery_required set to True
    m_row = test_db.get_mission(mission_id)
    assert m_row["execution_active"] is False
    assert m_row["recovery_required"] is True


@pytest.mark.asyncio
async def test_scenario_g_subprocess_execution_journaling(
    temp_workspace: WorkspaceManager,
    test_db: SQLiteDatabase,
    test_bus: EventBus,
):
    """
    Scenario G: Subprocess Execution Journaling
    Executes a shell command via shell.bash through the ActionExecutor and verifies:
    1. Command intent is recorded before execution.
    2. Subprocess PID, exit code, duration, and stdout/stderr are captured in details and journaled.
    3. Result is durably recorded in tool_operations with matching operation_id.
    """
    executor = ActionExecutor(mode="auto")
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    op_id = f"op_shell_{uuid.uuid4().hex[:6]}"

    action = ActionEnvelope(
        action_id=op_id,
        mission_id=mission_id,
        tool_name="shell.bash",
        arguments={"command": "echo HERMES_PHASE3_SUBPROCESS_TEST"},
    )

    with patch("core.agent_loop.actions.event_bus", test_bus):
        obs = await executor.execute_action(action, workspace=temp_workspace)

    assert obs.success is True
    assert "HERMES_PHASE3_SUBPROCESS_TEST" in obs.content

    # Inspect persistent database record
    record = test_db.get_tool_operation(op_id)
    assert record is not None
    assert record["tool_name"] == "shell.bash"
    assert record["status"] == OperationStatus.RESULT_COMMITTED.value
    assert record["exit_code"] == 0
    assert record["duration_seconds"] is not None
    assert record["duration_seconds"] >= 0.0

    # Verify event bus journaled the event with details
    events = test_db.get_mission_events(mission_id)
    completed_events = [e for e in events if e["event_type"] == "TOOL_COMPLETED"]
    assert len(completed_events) == 1
    ev_payload = completed_events[0]["payload"]["payload"]
    assert ev_payload["operation_id"] == op_id
    assert "details" in ev_payload
    details = ev_payload["details"]
    assert details["command"] == "echo HERMES_PHASE3_SUBPROCESS_TEST"
    assert details["exit_code"] == 0
