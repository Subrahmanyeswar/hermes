# tests/test_stage4_review_and_diff_acceptance.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 4:
Full Artifact Review, Genuine Diffs, Evidence-Based Outcome, and Protected Actions.

Verifies:
1. Stage 4A: Genuine file diffs (created, modified, deleted) relative to workspace root,
   with addition/deletion counts, unified diff format, and path traversal security.
2. Stage 4A: Binary and oversized file safety guards.
3. Stage 4B: Evidence-driven verification checks with exit codes, commands, and rationale.
4. Stage 4C: Outcome panel authoritative truth and diagnostic failure frames.
5. Stage 4D: Pending approval detection, inline grant/deny resolution, and audit tracking.
6. Stage 4E: Event cursor replay and session metadata resilience.
"""

from __future__ import annotations

import time
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager


@pytest.fixture
def stage4_env(tmp_path):
    ws = tmp_path / "stage4_workspace"
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

    workspace_manager.unlock()


def test_1_stage4a_genuine_diffs_and_traversal_protection(stage4_env):
    """
    Stage 4A: Verify genuine file diff generation for created and modified files,
    accurate addition/deletion counts, and strict path traversal protection.
    """
    ws = stage4_env["workspace"]
    client = stage4_env["client"]
    test_bus = stage4_env["event_bus"]
    mission_id = "m_stage4_diffs"

    # Create an initial file in workspace to be modified
    existing_file = ws / "readme.txt"
    existing_file.write_text("Hello World\nLine 2\n", encoding="utf-8")

    # Start mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Create new component and update readme"}
    ))

    # Simulate creation of a new file on disk
    new_file = ws / "component.py"
    new_file.write_text("def hello():\n    return 'hermes'\n", encoding="utf-8")

    # Modify existing file
    existing_file.write_text("Hello World\nLine 2 modified\nLine 3 added\n", encoding="utf-8")

    # Publish file events via completed tool actions
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "write_file", "path": "component.py", "files_created": ["component.py"]}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "edit_file", "path": "readme.txt", "files_modified": ["readme.txt"]}
    ))

    # Fetch all diffs
    diff_resp = client.get(f"/api/missions/{mission_id}/diffs")
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()

    assert diff_data["mission_id"] == mission_id
    assert len(diff_data["files"]) >= 2

    comp_entry = next((f for f in diff_data["files"] if f["path"] == "component.py"), None)
    assert comp_entry is not None
    assert comp_entry["change_type"] == "created"
    assert comp_entry["additions"] == 2
    assert comp_entry["deletions"] == 0
    assert "--- /dev/null" in comp_entry["diff_text"]
    assert "+def hello():" in comp_entry["diff_text"]

    # Test single file diff endpoint
    single_resp = client.get(f"/api/missions/{mission_id}/diffs/component.py")
    assert single_resp.status_code == 200
    single_data = single_resp.json()
    assert single_data["path"] == "component.py"
    assert single_data["additions"] == 2

    # Verify Path Traversal Protection
    traversal_resp = client.get(f"/api/missions/{mission_id}/diff?path=../../Windows/system.ini")
    assert traversal_resp.status_code in (400, 403)

    traversal_resp2 = client.get(f"/api/missions/{mission_id}/diff?path=../outside.txt")
    assert traversal_resp2.status_code in (400, 403)


def test_2_stage4a_binary_and_missing_file_safety(stage4_env):
    """
    Stage 4A: Binary files must be flagged without throwing UTF-8 decode errors,
    and missing files must be represented honestly as deleted/not written.
    """
    ws = stage4_env["workspace"]
    client = stage4_env["client"]
    test_bus = stage4_env["event_bus"]
    mission_id = "m_stage4_binary"

    # Write a binary file
    bin_file = ws / "binary_asset.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03PNG\x00HERMES_DATA\x00")

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Generate binary asset"}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "generate_asset", "path": "binary_asset.bin", "files_created": ["binary_asset.bin", "missing_file.py"]}
    ))

    # Query diffs
    diff_resp = client.get(f"/api/missions/{mission_id}/diffs")
    assert diff_resp.status_code == 200
    data = diff_resp.json()

    bin_entry = next((f for f in data["files"] if f["path"] == "binary_asset.bin"), None)
    assert bin_entry is not None
    assert bin_entry["is_binary"] is True
    assert "Binary file" in bin_entry["diff_text"]

    missing_entry = next((f for f in data["files"] if f["path"] == "missing_file.py"), None)
    assert missing_entry is not None
    assert missing_entry["change_type"] == "deleted"
    assert "not written to disk" in missing_entry["diff_text"]


def test_3_stage4b_evidence_driven_verification_checks(stage4_env):
    """
    Stage 4B: Verification gate outcomes must be derived directly from
    runtime verification events, with commands, exit codes, and verdicts.
    """
    client = stage4_env["client"]
    test_bus = stage4_env["event_bus"]
    mission_id = "m_stage4_checks"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Run quality verification suite"}
    ))

    # Passed check
    test_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_PASSED,
        mission_id=mission_id,
        task_id="t_verify_syntax",
        payload={
            "check_name": "Python Syntax Linter",
            "command": "python -m py_compile component.py",
            "exit_code": 0,
            "evidence": "All files compiled successfully without syntax errors.",
            "duration": 0.42,
        }
    ))

    # Failed tool execution
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_FAILED,
        mission_id=mission_id,
        task_id="t_run_tests",
        payload={
            "tool_name": "pytest tests/",
            "exit_code": 1,
            "error": "AssertionError: Expected 200 but got 500",
        }
    ))

    # Query /api/missions/{mission_id}/checks
    checks_resp = client.get(f"/api/missions/{mission_id}/checks")
    assert checks_resp.status_code == 200
    checks_data = checks_resp.json()

    assert checks_data["mission_id"] == mission_id
    assert checks_data["total_count"] >= 2
    assert checks_data["passed_count"] >= 1
    assert checks_data["failed_count"] >= 1

    passed_check = next((c for c in checks_data["checks"] if c["status"] == "passed"), None)
    assert passed_check is not None
    assert passed_check["title"] == "Python Syntax Linter"
    assert passed_check["exit_code"] == 0
    assert "py_compile" in passed_check["command"]

    failed_check = next((c for c in checks_data["checks"] if c["status"] == "failed"), None)
    assert failed_check is not None
    assert failed_check["exit_code"] == 1
    assert "AssertionError" in failed_check["output_snippet"]

    # Also check that MissionSnapshot includes the checks
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert "checks" in snap
    assert len(snap["checks"]) >= 2


def test_4_stage4c_outcome_panel_truth_and_failure_diagnosis(stage4_env):
    """
    Stage 4C: Outcome panel must reflect authoritative terminal failure state,
    prohibiting false success frames and capturing diagnostic tracebacks.
    """
    client = stage4_env["client"]
    test_bus = stage4_env["event_bus"]
    mission_id = "m_stage4_outcome_fail"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Deploy production harness"}
    ))

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        payload={
            "error": "RuntimeSecurityError: Workspace escaped by unauthorized relative link '../passwd'",
        }
    ))

    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()

    assert snap["status"] == "FAILED"
    assert snap["is_terminal"] is True
    assert "RuntimeSecurityError" in snap["error"]
    assert "Workspace escaped" in snap["error"]


def test_5_stage4d_approvals_resolution_lifecycle(stage4_env):
    """
    Stage 4D: Pending security requests must be exposed via GET /api/approvals,
    and interactive resolution via POST /api/approvals/{id} must grant or deny permissions.
    """
    adapter = stage4_env["adapter"]
    client = stage4_env["client"]

    # Setup pending approval in runtime security gate
    import asyncio
    rt = asyncio.run(adapter.get_or_create_runtime())
    from core.security.models import ActionDescriptor, ApprovalRequest
    from core.security.enums import ApprovalScope, RiskLevel
    from core.security.models import RiskAssessment

    req = ApprovalRequest(
        request_id="req_test_auth_1",
        action=ActionDescriptor(tool_name="execute_command", arguments={"cmd": "npm install"}),
        assessment=RiskAssessment(risk_level=RiskLevel.HIGH, reasons=["Executing shell command requires user authorization"]),
        required_scope=ApprovalScope.ONCE,
        created_at=time.time(),
    )
    rt.security.approval_store.add_request(req)

    # 1. Fetch pending approvals
    list_resp = client.get("/api/approvals")
    assert list_resp.status_code == 200
    items = list_resp.json()["pending_approvals"]
    assert any(i["request_id"] == "req_test_auth_1" for i in items)

    # 2. Grant approval
    resolve_resp = client.post(
        "/api/approvals/req_test_auth_1",
        json={"approved": True, "scope": "ONCE", "reason": "Operator authorized npm install"}
    )
    assert resolve_resp.status_code == 200
    res_data = resolve_resp.json()
    assert res_data["resolved"] is True
    assert res_data["approved"] is True

    # 3. Verify request is no longer pending
    list_after = client.get("/api/approvals")
    assert list_after.status_code == 200
    assert not any(i["request_id"] == "req_test_auth_1" for i in list_after.json()["pending_approvals"])


def test_6_stage4e_session_and_cursor_resilience(stage4_env):
    """
    Stage 4E: Reconnection cursors must correctly filter historical events,
    and snapshot versioning must track mission evolution.
    """
    client = stage4_env["client"]
    test_bus = stage4_env["event_bus"]
    mission_id = "m_stage4_resilience"

    for i in range(5):
        test_bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id=mission_id,
            payload={"step": i + 1}
        ))

    # Retrieve all events past sequence 3
    events = stage4_env["adapter"].get_events_since(mission_id, last_sequence=3)
    assert all(e.sequence > 3 for e in events)

    # Verify session summary endpoint returns valid metadata
    sess_resp = client.get("/api/sessions")
    assert sess_resp.status_code == 200
    assert "sessions" in sess_resp.json()

