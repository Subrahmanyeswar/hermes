"""
Stage 5 Acceptance Tests: Windows Launch Experience, Runtime Lifecycle,
and Rollout Readiness.

Verifies:
1. Launcher detection of available port vs running HERMES server.
2. Protection of unrelated processes: does not kill arbitrary processes on port 8765.
3. Repeat launch idempotency: avoids spawning duplicate backend processes.
4. Clean stop behavior: terminates tracked HERMES server safely and cleans up PID file.
5. Approval Lifecycle Binding:
   - Terminated missions (completed/failed/cancelled) invalidate pending approvals.
   - Stale approvals cannot be approved or rejected (HTTP 410 Gone).
   - Approval requests require mission_id binding.
6. CLI entry points remain preserved (main.py help, version, serve, gui).
"""

import os
import sys
import time
import socket
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.server import launcher
from core.workspace import workspace_manager
from core.security.enums import ApprovalScope, RiskLevel
from core.security.models import ActionDescriptor, ApprovalRequest, RiskAssessment


@pytest.fixture
def test_env(tmp_path):
    ws = tmp_path / "stage5_test_ws"
    ws.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(ws)

    test_bus = EventBus(enabled=True)
    adapter = RuntimeAdapter(event_bus=test_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    yield {
        "workspace": ws,
        "event_bus": test_bus,
        "adapter": adapter,
        "client": client,
    }


# -------------------------------------------------------------------------
# Test 1: CLI Entry Points Preservation
# -------------------------------------------------------------------------

def test_cli_entry_points_preserved():
    """Verify that main.py CLI still exposes standard commands plus serve and gui."""
    from main import app as typer_app
    callback_names = [cmd.callback.__name__ for cmd in typer_app.registered_commands if cmd.callback]
    assert "version" in callback_names
    assert "serve" in callback_names
    assert "gui" in callback_names
    assert "diagnostics" in callback_names


# -------------------------------------------------------------------------
# Test 2: Approval Lifecycle Binding to Mission Status
# -------------------------------------------------------------------------

def test_approval_lifecycle_bound_to_mission_completion(test_env):
    """Verify that completing a mission invalidates its pending approvals."""
    client = test_env["client"]
    test_bus = test_env["event_bus"]
    adapter = test_env["adapter"]
    mission_id = "test-approval-binding-complete"

    import asyncio
    rt = asyncio.run(adapter.get_or_create_runtime())

    # Start mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Verify approval binding"}
    ))

    # Create an approval request bound to this mission
    req = ApprovalRequest(
        request_id="req_bind_complete",
        mission_id=mission_id,
        action=ActionDescriptor(tool_name="docker", arguments={"cmd": "docker push registry.internal/app:v2"}),
        assessment=RiskAssessment(risk_level=RiskLevel.HIGH, reasons=["Docker push action"]),
        required_scope=ApprovalScope.SESSION,
        created_at=time.time(),
    )
    rt.security.approval_store.add_request(req)

    # Check pending approvals API includes it
    resp = client.get("/api/approvals")
    assert resp.status_code == 200
    pending_ids = [item["request_id"] for item in resp.json()["pending_approvals"]]
    assert "req_bind_complete" in pending_ids

    # Complete mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"reason": "Task finished"}
    ))

    # Pending approvals API should now automatically invalidate and filter it out
    resp_after = client.get("/api/approvals")
    assert resp_after.status_code == 200
    pending_ids_after = [item["request_id"] for item in resp_after.json()["pending_approvals"]]
    assert "req_bind_complete" not in pending_ids_after

    # Attempting to resolve this approval must return HTTP 410 Gone
    resolve_resp = client.post(
        f"/api/approvals/{req.request_id}",
        json={"approved": True, "scope": "ONCE", "reason": "Late approve"}
    )
    assert resolve_resp.status_code == 410
    assert "terminated" in resolve_resp.json()["detail"].lower()


def test_approval_lifecycle_bound_to_mission_failure(test_env):
    """Verify that failing a mission invalidates its pending approvals."""
    client = test_env["client"]
    test_bus = test_env["event_bus"]
    adapter = test_env["adapter"]
    mission_id = "test-approval-binding-failed"

    import asyncio
    rt = asyncio.run(adapter.get_or_create_runtime())

    # Start mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Verify failure binding"}
    ))

    # Create an approval request bound to this mission
    req = ApprovalRequest(
        request_id="req_bind_failed",
        mission_id=mission_id,
        action=ActionDescriptor(tool_name="rm_rf", arguments={"path": "/critical/path"}),
        assessment=RiskAssessment(risk_level=RiskLevel.CRITICAL, reasons=["Dangerous file deletion"]),
        required_scope=ApprovalScope.ONE_ACTION,
        created_at=time.time(),
    )
    rt.security.approval_store.add_request(req)

    # Transition mission to FAILED
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        payload={"reason": "Mission failed execution"}
    ))

    # Verification: approval resolution must be rejected with 410
    resolve_resp = client.post(
        f"/api/approvals/{req.request_id}",
        json={"approved": False, "reason": "Dead mission"}
    )
    assert resolve_resp.status_code == 410

    # Ensure status in approval store is marked cancelled
    stored = rt.security.approval_store.get_request(req.request_id)
    assert stored.status == "CANCELLED"
    assert stored.resolved is True


# -------------------------------------------------------------------------
# Test 3: Port Conflict and Process Protection
# -------------------------------------------------------------------------

def test_unrelated_process_protection(monkeypatch):
    """
    Verify that if an unrelated third-party process occupies the port,
    HERMES launcher refuses to kill it and returns conflict code (1).
    """
    mock_status = {
        "in_use": True,
        "pid": 99999,
        "process_name": "third_party_app.exe",
        "is_hermes": False,
        "health": None,
    }
    monkeypatch.setattr(launcher, "get_port_status", lambda host, port: mock_status)

    # Launch should detect conflict and return 1
    code = launcher.launch_server(host="127.0.0.1", port=8765, open_browser=False)
    assert code == 1

    # Stop should refuse to kill unrelated process and return False
    ok = launcher.stop_server(port=8765)
    assert ok is False


# -------------------------------------------------------------------------
# Test 4: Duplicate Launch Idempotency
# -------------------------------------------------------------------------

def test_duplicate_launch_detected_when_server_already_healthy(monkeypatch):
    """
    Verify that launching when an existing HERMES server is already running and healthy
    does NOT spawn a duplicate process, but reuses existing server (return code 0).
    """
    mock_status = {
        "in_use": True,
        "pid": 55555,
        "process_name": "python.exe",
        "is_hermes": True,
        "health": {"status": "ok", "model_stack": {}},
    }
    monkeypatch.setattr(launcher, "get_port_status", lambda host, port: mock_status)

    code = launcher.launch_server(host="127.0.0.1", port=8765, open_browser=False)
    assert code == 0


# -------------------------------------------------------------------------
# Test 5: Clean Stop Behavior with Tracked PID
# -------------------------------------------------------------------------

def test_clean_stop_removes_pid_file(tmp_path, monkeypatch):
    """Verify that stopping HERMES cleans up the PID file."""
    fake_pid_file = tmp_path / "hermes_gui_server.pid"
    monkeypatch.setattr(launcher, "PID_FILE", fake_pid_file)

    fake_pid_file.write_text('{"pid": 12345}')

    class DummyProc:
        def __init__(self, pid):
            self.pid = pid
        def is_running(self):
            return True
        def terminate(self):
            pass
        def wait(self, timeout=None):
            pass

    mock_status = {
        "in_use": True,
        "pid": 12345,
        "process_name": "python.exe",
        "is_hermes": True,
        "health": {"status": "ok"},
    }
    monkeypatch.setattr(launcher, "get_port_status", lambda host, port: mock_status)
    monkeypatch.setattr(launcher, "check_port_in_use", lambda host, port: False)
    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: DummyProc(pid))

    ok = launcher.stop_server(port=8765)
    assert ok is True
    assert not fake_pid_file.exists()


# -------------------------------------------------------------------------
# Test 6: Status Check Contract
# -------------------------------------------------------------------------

def test_check_status_contract(monkeypatch):
    """Verify get_port_status returns accurate structured status dict."""
    monkeypatch.setattr(launcher, "check_port_in_use", lambda host, port: True)
    
    class DummyProc:
        def __init__(self):
            self.pid = 12345
        def name(self):
            return "python.exe"
        def cmdline(self):
            return ["python", "-m", "uvicorn", "core.server.app:app"]

    monkeypatch.setattr(launcher, "get_process_on_port", lambda port: DummyProc())
    monkeypatch.setattr(launcher, "verify_hermes_health", lambda host, port: {"status": "ok", "model_stack": {}})

    status = launcher.get_port_status("127.0.0.1", 8765)
    assert status["in_use"] is True
    assert status["is_hermes"] is True
    assert status["pid"] == 12345
    assert status["process_name"] == "python.exe"
    assert status["health"]["status"] == "ok"
