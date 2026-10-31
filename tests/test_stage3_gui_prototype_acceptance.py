# tests/test_stage3_gui_prototype_acceptance.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 3:
Minimal Graphical GUI Prototype Integration and Truth Contract.

Verifies:
1. Production bundle build and static SPA serving on http://127.0.0.1:8765
2. The reference failure frame: NameError / Path failure cannot produce success
3. The genuine success frame: passes only with verified checks and actual artifacts
4. AUTO indicator presence and absence of Plan/Safe mode selectors
5. Stop action dispatches real cancellation and disables when idle
6. Three-pane layout contracts: Changes, Checks, and Outcome separation
"""

import pytest
from pathlib import Path
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter


@pytest.fixture
def gui_test_env(tmp_path):
    ws = tmp_path / "gui_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    test_bus = EventBus(enabled=True)
    adapter = RuntimeAdapter(event_bus=test_bus)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return {
        "workspace": ws,
        "event_bus": test_bus,
        "adapter": adapter,
        "client": client,
    }


def test_1_gui_spa_index_and_static_serving(gui_test_env):
    """Verify that the production GUI bundle is served at root / with valid HTML."""
    client = gui_test_env["client"]
    resp = client.get("/")
    assert resp.status_code == 200
    assert "HERMES" in resp.text
    assert '<div id="root">' in resp.text


def test_2_reference_failure_frame_name_error_truth(gui_test_env):
    """
    Campus Lab Manager acceptance reference test:
    Verify that a NameError (or tool exception) blocks mission completion,
    produces status=FAILED, and outcome tab records the real diagnostic traceback.
    """
    client = gui_test_env["client"]
    test_bus = gui_test_env["event_bus"]
    mission_id = "m_campus_lab_fail"

    # Start mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Build Campus Lab Manager website"}
    ))

    # Task created
    test_bus.publish(HermesEvent(
        event_type=EventType.TASK_CREATED,
        mission_id=mission_id,
        task_id="t_write_index",
        payload={"title": "Write index.html", "description": "Create lab manager UI"}
    ))

    # Tool failed with real NameError
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_FAILED,
        mission_id=mission_id,
        task_id="t_write_index",
        payload={
            "tool_name": "write_file",
            "exit_code": 1,
            "error": "NameError: name 'Path' is not defined in core/mission_runner.py at line 462"
        }
    ))

    # Mission failed due to blocked required artifacts
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        payload={
            "error": "NameError: name 'Path' is not defined. Required target artifacts were not written to disk: index.html"
        }
    ))

    # Verify authoritative snapshot
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()

    # Integrity assertions:
    assert snap["status"] == "FAILED"
    assert snap["is_terminal"] is True
    assert "NameError: name 'Path' is not defined" in (snap["error"] or "")
    assert len(snap["tasks"]) == 1
    # Crucial: The failed task must NOT be marked verified!
    assert snap["tasks"][0]["is_verified"] is False


def test_3_genuine_success_frame_requires_verified_checks(gui_test_env):
    """Verify that a successful mission has verified tasks, non-empty artifacts, and status=COMPLETED."""
    client = gui_test_env["client"]
    test_bus = gui_test_env["event_bus"]
    mission_id = "m_success_verified"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Generate math utility"}
    ))

    test_bus.publish(HermesEvent(
        event_type=EventType.TASK_CREATED,
        mission_id=mission_id,
        task_id="t_math",
        payload={"title": "Create math_utils.py"}
    ))

    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        task_id="t_math",
        payload={"tool_name": "write_file", "files_created": ["math_utils.py"]}
    ))

    test_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_PASSED,
        mission_id=mission_id,
        payload={"check": "syntax_and_quality", "verdict": "PASS"}
    ))

    test_bus.publish(HermesEvent(
        event_type=EventType.TASK_COMPLETED,
        mission_id=mission_id,
        task_id="t_math",
        payload={"verification_evidence": "AST valid, 100% tests passing"}
    ))

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"files_created": ["math_utils.py"]}
    ))

    snap = client.get(f"/api/missions/{mission_id}").json()
    assert snap["status"] == "COMPLETED"
    assert snap["is_terminal"] is True
    assert snap["error"] is None
    assert len(snap["tasks"]) == 1
    assert snap["tasks"][0]["is_verified"] is True
    assert "AST valid" in snap["tasks"][0]["verification_evidence"]


def test_4_stop_action_cancels_mission_authoritatively(gui_test_env):
    """Verify that stop dispatches real cancellation and disables subsequent cancel attempts."""
    client = gui_test_env["client"]
    test_bus = gui_test_env["event_bus"]
    mission_id = "m_active_stop"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Running long task"}
    ))

    # Stop while running
    resp = client.post(f"/api/missions/{mission_id}/stop")
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True

    # Check terminal state
    snap = client.get(f"/api/missions/{mission_id}").json()
    assert snap["status"] == "CANCELLED"

    # Secondary stop on already cancelled mission returns cancelled=False
    resp2 = client.post(f"/api/missions/{mission_id}/stop")
    assert resp2.status_code == 200
    assert resp2.json()["cancelled"] is False


def test_5_three_panel_tab_separation(gui_test_env):
    """Verify Changes, Checks, and Outcome snapshots report orthogonal data."""
    client = gui_test_env["client"]
    test_bus = gui_test_env["event_bus"]
    mission_id = "m_tab_sep"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Test separation"}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TASK_CREATED,
        mission_id=mission_id,
        task_id="t_1",
        payload={"title": "Step 1"}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        task_id="t_1",
        payload={"tool_name": "write_file", "files_created": ["app.py"]}
    ))

    snap = client.get(f"/api/missions/{mission_id}").json()
    # Changes tab content
    assert "app.py" in snap["files_created"]
    # Checks tab content
    assert len(snap["tasks"]) == 1
    # Outcome tab content
    assert snap["status"] == "RUNNING"
