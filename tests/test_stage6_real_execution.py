# tests/test_stage6_real_execution.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 6:
Real Task Execution, Artifact Integrity, and End-to-End Mission Acceptance.

Verifies:
1. Scenario A: Genuine file creation with real pytest execution, positive diffs (+N / -0),
   and verified passing outcome.
2. Scenario B: Genuine file modification with real diff comparing prior to post state,
   correct addition/deletion counts, no false 'created' label, and verified check execution.
3. Scenario C: Verification failure remains failure: Non-zero exit code is preserved,
   outcome is FAILED (never COMPLETED), and diagnosis appears in state/outcome.
4. Scenario D: Legitimate read-only inspection passes without forced writes or fake errors.
5. Scenario E: Real cancellation / stop enforcement and security policy denial blocks
   unauthorized protected actions before physical execution.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from core.agent_loop.actions import ActionExecutor
from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
from core.agent_loop.types import ActionEnvelope, ActionStatus
from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import AcceptanceCheckStatus, MissionStatus
from core.security.enums import RiskLevel
from core.security.gate import SecurityGate
from core.security.models import ActionDescriptor, RiskAssessment
from core.server.app import create_app
from core.server.diff_service import clear_file_baselines, record_file_baseline
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager


@pytest.fixture
def stage6_env(tmp_path):
    ws = tmp_path / "stage6_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(ws)

    test_bus = EventBus(enabled=True)
    adapter = RuntimeAdapter(event_bus=test_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    yield {
        "workspace": ws,
        "ws_mgr": workspace_manager,
        "event_bus": test_bus,
        "adapter": adapter,
        "client": client,
    }

    workspace_manager.unlock()
    clear_file_baselines()


def test_scenario_a_file_creation_and_diff_integrity(stage6_env):
    """
    Scenario A: Genuine File Creation.
    Verifies that creating a new implementation file and test file in workspace:
    1. Produces real files on disk.
    2. API diff reports change_type='created' with positive additions and zero deletions.
    3. Running a real pytest command produces exit_code 0.
    4. Mission can successfully transition to COMPLETED.
    """
    ws: Path = stage6_env["workspace"]
    client: TestClient = stage6_env["client"]
    test_bus: EventBus = stage6_env["event_bus"]
    mission_id = "m_stage6_scenario_a"

    # Start mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Create math_utils.py with add function and test_math.py with unit test"}
    ))

    # Real file creation on disk
    math_file = ws / "math_utils.py"
    math_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    math_file.write_text(math_code, encoding="utf-8")

    test_file = ws / "test_math.py"
    test_code = "from math_utils import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    test_file.write_text(test_code, encoding="utf-8")

    # Publish tool completion events
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "write_file", "path": "math_utils.py", "files_created": ["math_utils.py"]}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "write_file", "path": "test_math.py", "files_created": ["test_math.py"]}
    ))

    # Query API /api/missions/{mission_id}/diffs
    resp = client.get(f"/api/missions/{mission_id}/diffs")
    assert resp.status_code == 200
    data = resp.json()
    files = data.get("files", [])
    file_map = {f["path"]: f for f in files}

    assert "math_utils.py" in file_map
    assert file_map["math_utils.py"]["change_type"] == "created"
    assert file_map["math_utils.py"]["additions"] > 0
    assert file_map["math_utils.py"]["deletions"] == 0

    assert "test_math.py" in file_map
    assert file_map["test_math.py"]["change_type"] == "created"
    assert file_map["test_math.py"]["additions"] > 0
    assert file_map["test_math.py"]["deletions"] == 0

    # Execute genuine pytest verification check
    py_res = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q"],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )
    assert py_res.returncode == 0
    assert "passed" in py_res.stdout

    # Publish verification check passed
    test_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_PASSED,
        mission_id=mission_id,
        payload={
            "check_name": "pytest unit test",
            "command": "pytest test_math.py",
            "exit_code": 0,
            "evidence": py_res.stdout.strip(),
        }
    ))

    # Publish mission completed
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"reason": "Scenario A: math utilities and tests verified."}
    ))

    # Verify snapshot reflects COMPLETED
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["status"] == "COMPLETED"


def test_scenario_b_file_modification_and_diff_accuracy(stage6_env):
    """
    Scenario B: Genuine File Modification.
    Verifies that modifying an existing file:
    1. Compares prior baseline vs modified content.
    2. Reports change_type='modified' (NEVER 'created').
    3. Accurately reports addition and deletion counts.
    """
    ws: Path = stage6_env["workspace"]
    client: TestClient = stage6_env["client"]
    test_bus: EventBus = stage6_env["event_bus"]
    mission_id = "m_stage6_scenario_b"

    # Pre-populate existing file in workspace
    target = ws / "greeting.py"
    initial_content = "def greet() -> str:\n    return 'Hello World'\n"
    target.write_text(initial_content, encoding="utf-8")
    record_file_baseline(ws, "greeting.py", initial_content)

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Update greeting to return Hello HERMES"}
    ))

    # Apply genuine edit on disk
    modified_content = "def greet() -> str:\n    return 'Hello HERMES'\n"
    target.write_text(modified_content, encoding="utf-8")

    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "edit_file", "path": "greeting.py", "files_modified": ["greeting.py"]}
    ))

    # Query API /api/missions/{mission_id}/diffs
    resp = client.get(f"/api/missions/{mission_id}/diffs")
    assert resp.status_code == 200
    diff_data = resp.json()
    files = diff_data.get("files", [])
    assert len(files) == 1
    g_diff = files[0]

    assert g_diff["path"] == "greeting.py"
    assert g_diff["change_type"] == "modified"
    assert g_diff["additions"] == 1
    assert g_diff["deletions"] == 1
    assert "-    return 'Hello World'" in g_diff["diff_text"]
    assert "+    return 'Hello HERMES'" in g_diff["diff_text"]


def test_scenario_c_verification_failure_remains_failure(stage6_env):
    """
    Scenario C: Verification Failure Remains Failure.
    Verifies that non-zero exit codes from real commands or unsatisfied criteria:
    1. Produce a non-zero exit code and error output.
    2. Check is registered as failed check.
    3. Mission transitions to FAILED (never falsely COMPLETED).
    4. Diagnostic failure reason is accessible via API.
    """
    ws: Path = stage6_env["workspace"]
    client: TestClient = stage6_env["client"]
    test_bus: EventBus = stage6_env["event_bus"]
    mission_id = "m_stage6_scenario_c"

    # Pre-populate failing test file
    failing_test = ws / "test_broken.py"
    failing_test.write_text("def test_impossible():\n    assert 1 == 2\n", encoding="utf-8")

    py_res = subprocess.run(
        [sys.executable, "-m", "pytest", str(failing_test), "-q"],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )
    assert py_res.returncode != 0
    assert "failed" in py_res.stdout.lower() or "error" in py_res.stdout.lower()

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Fix broken calculation"}
    ))

    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_FAILED,
        mission_id=mission_id,
        task_id="t_verify_test",
        payload={
            "tool_name": "pytest test_broken.py",
            "exit_code": py_res.returncode,
            "error": "AssertionError: assert 1 == 2",
        }
    ))

    # Query checks API to verify failed check
    checks_resp = client.get(f"/api/missions/{mission_id}/checks")
    assert checks_resp.status_code == 200
    chk_data = checks_resp.json()
    assert chk_data["failed_count"] >= 1

    # Mission fails authoritatively
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        payload={"error": f"Verification checks failed with exit code {py_res.returncode}"}
    ))

    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["status"] == "FAILED"
    assert "exit code" in snap["error"]


def test_scenario_d_legitimate_read_only_task(stage6_env):
    """
    Scenario D: Legitimate Read-Only Inspection.
    Verifies that a read-only inspection task:
    1. Can inspect existing fixtures without modifying files.
    2. CompletionPolicy evaluates True without requiring forced file creation.
    3. Mission completes without error.
    """
    ws: Path = stage6_env["workspace"]
    ws_mgr = stage6_env["ws_mgr"]
    test_bus: EventBus = stage6_env["event_bus"]
    mission_id = "m_stage6_scenario_d"

    # Setup read-only target file
    doc_file = ws / "README.md"
    doc_file.write_text("# Project Documentation\nAll tests pass.\n", encoding="utf-8")

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Inspect README.md and report documentation summary"}
    ))

    cp = CompletionPolicy()
    can_complete, reason, issues = cp.evaluate_completion(
        mission_prompt="Inspect README.md and report documentation summary",
        workspace=ws_mgr,
        written_files=[]
    )
    assert can_complete is True
    assert issues == []

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"reason": "Inspection finished. Documentation reviewed."}
    ))

    client: TestClient = stage6_env["client"]
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_scenario_e_cancellation_and_security_denial(stage6_env):
    """
    Scenario E: Cancellation & Security Approval Enforcement.
    Verifies:
    1. When abort_event is signaled, cancellation is registered.
    2. When a dangerous action (e.g. system path traversal) is evaluated,
       Harness policy denies it without executing physical action.
    """
    ws: Path = stage6_env["workspace"]
    ws_mgr = stage6_env["ws_mgr"]
    test_bus: EventBus = stage6_env["event_bus"]
    mission_id = "m_stage6_scenario_e"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Test cancellation and protected action gate"}
    ))

    # Test Stop / Cancellation event
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_CANCELLED,
        mission_id=mission_id,
        payload={"reason": "Operator triggered abort signal"}
    ))

    st_store = test_bus.get_or_create_state(mission_id)
    snapshot = st_store.get_snapshot()
    assert snapshot.mission.status == MissionStatus.CANCELLED

    # Test SecurityGate denial for destructive / unauthorized action
    sec_gate = SecurityGate()
    executor = ActionExecutor(mode="safe", security_gate=sec_gate)

    # Propose dangerous action (e.g. write to path traversal or root)
    action = ActionEnvelope(
        mission_id=mission_id,
        turn_id="turn_sec_1",
        tool_name="fs.write",
        arguments={"path": "../../../system32/cmd.exe", "content": "malicious"}
    )

    obs = await executor.execute_action(action, workspace=ws_mgr)
    assert obs.success is False
    assert action.status == ActionStatus.DENIED
    assert "traversal" in obs.summary.lower() or "denied" in obs.summary.lower() or "rejected" in obs.summary.lower()
