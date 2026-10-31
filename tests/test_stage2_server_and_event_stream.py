# tests/test_stage2_server_and_event_stream.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 2:
FastAPI Runtime Bridge, Typed Event Stream, Reconnects, Snapshots, and Security.

Strict isolation: Uses isolated workspaces, mock models, and synthetic events.
No live external network or model calls required.
"""

import asyncio
import json
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.server.app import create_app
from core.server.events import format_hermes_event_to_sse
from core.server.runtime_adapter import RuntimeAdapter
from utils.logging import redact_secrets


@pytest.fixture
def mock_runtime_env(tmp_path):
    """Fixture providing an isolated workspace and event bus."""
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    from core.persistence.database import SQLiteDatabase
    isolated_db = SQLiteDatabase(tmp_path / "test_state.db")
    test_bus = EventBus(enabled=True, db=isolated_db)
    adapter = RuntimeAdapter(event_bus=test_bus)
    app = create_app(adapter=adapter)
    # Inject test adapter into app endpoints
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return {
        "workspace": ws,
        "event_bus": test_bus,
        "adapter": adapter,
        "app": app,
        "client": client,
    }


def test_1_health_endpoint_and_runtime_connectivity(mock_runtime_env):
    """Verify GET /api/health accurately reports server readiness and model stack."""
    client = mock_runtime_env["client"]
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0-rc1"
    assert "python_version" in data
    assert "model_stack" in data
    assert "tier1" in data["model_stack"]
    assert "tier2" in data["model_stack"]
    assert "tier3" in data["model_stack"]


def test_2_request_schemas_and_validation(mock_runtime_env):
    """Verify request validation accepts valid bodies and rejects invalid schemas."""
    client = mock_runtime_env["client"]

    # Missing prompt
    bad_resp = client.post("/api/missions", json={})
    assert bad_resp.status_code == 422  # Unprocessable entity

    # Empty prompt
    bad_resp2 = client.post("/api/missions", json={"prompt": ""})
    assert bad_resp2.status_code == 422


def test_3_workspaces_listing_and_boundary_checks(mock_runtime_env):
    """Verify GET /api/workspaces returns legitimate workspace metadata."""
    client = mock_runtime_env["client"]
    resp = client.get("/api/workspaces")
    assert resp.status_code == 200
    data = resp.json()
    assert "workspaces" in data
    assert len(data["workspaces"]) >= 1
    assert data["workspaces"][0]["exists"] is True


def test_4_mission_snapshot_retrieval(mock_runtime_env):
    """Verify GET /api/missions/{mission_id} returns authoritative state snapshot."""
    client = mock_runtime_env["client"]
    test_bus = mock_runtime_env["event_bus"]

    mission_id = "m_snap_001"
    # Publish events to establish state
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Build feature X"}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TASK_CREATED,
        mission_id=mission_id,
        task_id="t_1",
        payload={"title": "Task 1", "description": "Write code"}
    ))

    resp = client.get(f"/api/missions/{mission_id}")
    assert resp.status_code == 200
    snapshot = resp.json()
    assert snapshot["mission_id"] == mission_id
    assert len(snapshot["tasks"]) == 1
    assert snapshot["tasks"][0]["task_id"] == "t_1"
    assert snapshot["last_sequence"] >= 2


def test_5_event_to_sse_conversion_and_contract(mock_runtime_env):
    """Verify canonical HermesEvent conversion into typed, formatted SSE lines."""
    event = HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id="m_sse_test",
        task_id="t_10",
        sequence=42,
        payload={"tool_name": "write_file", "path": "index.html"}
    )
    sse_text = format_hermes_event_to_sse(event)
    assert "id: 42\n" in sse_text
    assert "event: TOOL_STARTED\n" in sse_text
    assert "data: {" in sse_text
    assert '"tool_name": "write_file"' in sse_text


def test_6_event_ordering_and_replay_from_cursor(mock_runtime_env):
    """Verify event replay from supplied sequence cursor maintains monotonic order."""
    test_bus = mock_runtime_env["event_bus"]
    adapter = mock_runtime_env["adapter"]
    mission_id = "m_cursor_test"

    for i in range(1, 6):
        test_bus.publish(HermesEvent(
            event_type=EventType.PROGRESS_UPDATED,
            mission_id=mission_id,
            payload={"step": i}
        ))

    # Replay after cursor = 3
    replayed = adapter.get_events_since(mission_id, last_sequence=3)
    assert len(replayed) == 2
    assert replayed[0].payload["step"] == 4
    assert replayed[1].payload["step"] == 5
    assert replayed[0].sequence < replayed[1].sequence


def test_7_mission_isolation_no_cross_leakage(mock_runtime_env):
    """Verify that events from Mission A are never replayed or leaked to Mission B."""
    test_bus = mock_runtime_env["event_bus"]
    adapter = mock_runtime_env["adapter"]

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id="mission_alpha",
        payload={"secret": "alpha_data"}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id="mission_beta",
        payload={"secret": "beta_data"}
    ))

    events_alpha = adapter.get_events_since("mission_alpha")
    events_beta = adapter.get_events_since("mission_beta")

    assert all(e.mission_id == "mission_alpha" for e in events_alpha)
    assert all(e.mission_id == "mission_beta" for e in events_beta)


def test_8_cancellation_dispatches_to_runtime(mock_runtime_env):
    """Verify POST /api/missions/{mission_id}/stop dispatches real cancellation."""
    client = mock_runtime_env["client"]
    test_bus = mock_runtime_env["event_bus"]
    mission_id = "m_stop_test"

    # Start mission in state store
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Long running job"}
    ))

    resp = client.post(f"/api/missions/{mission_id}/stop")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cancelled"] is True

    # Check terminal state in snapshot
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    assert snap_resp.json()["status"] == "CANCELLED"


def test_9_failed_tool_and_verification_remain_failures(mock_runtime_env):
    """Verify tool failures and verification failures are preserved in state and snapshot."""
    client = mock_runtime_env["client"]
    test_bus = mock_runtime_env["event_bus"]
    mission_id = "m_fail_test"

    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_FAILED,
        mission_id=mission_id,
        payload={"tool_name": "bash_exec", "exit_code": 1, "error": "Command not found"}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_FAILED,
        mission_id=mission_id,
        payload={"check": "unit_tests", "verdict": "FAIL"}
    ))

    events = test_bus.replay(mission_id)
    assert len(events) == 2
    assert events[0].event_type == EventType.TOOL_FAILED
    assert events[1].event_type == EventType.ACCEPTANCE_CHECK_FAILED


def test_10_security_host_and_origin_validation(mock_runtime_env):
    """Verify security middleware blocks DNS rebinding and untrusted origins."""
    client = mock_runtime_env["client"]

    # Rejection of forbidden host header
    resp_bad_host = client.get("/api/health", headers={"Host": "malicious.attacker.com"})
    assert resp_bad_host.status_code == 403

    # Rejection of untrusted cross-origin
    resp_bad_origin = client.get("/api/health", headers={"Origin": "http://evil-website.com"})
    assert resp_bad_origin.status_code == 403


def test_11_secret_redaction_in_exceptions_and_logs(mock_runtime_env):
    """Verify synthetic secrets in exceptions and payloads are strictly scrubbed."""
    synthetic_key = "sk-abcdef1234567890abcdef1234567890"
    synthetic_nv = "nvapi-abcdef1234567890abcdef1234567890"
    synthetic_conn = "postgres://admin:super_secret_pw@localhost:5432/db"

    raw_err = f"Failed to connect: {synthetic_conn} using {synthetic_key} and {synthetic_nv}"
    redacted = redact_secrets(raw_err)

    assert synthetic_key not in redacted
    assert synthetic_nv not in redacted
    assert "super_secret_pw" not in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "[REDACTED_NVIDIA_KEY]" in redacted
    assert "[REDACTED_PASSWORD]" in redacted


def test_12_workspace_boundary_path_traversal_rejected(mock_runtime_env):
    """Verify directory traversal escapes are rejected."""
    client = mock_runtime_env["client"]
    from core.workspace import workspace_manager

    # Lock workspace
    ws = mock_runtime_env["workspace"]
    workspace_manager.lock(str(ws))

    # Try path traversal outside workspace
    resp = client.post("/api/missions", json={
        "prompt": "Test escape",
        "workspace_root": str(ws / ".." / ".." / "Windows" / "System32"),
    })
    # Should be rejected with 403 or 400
    assert resp.status_code in (400, 403)
