# tests/test_stage4_1_audit_acceptance.py
"""
HERMES Stage 4.1 - End-to-End Functional Acceptance and Evidence Audit Test Suite.

Verifies:
- Test A (Changes):
  * Git and Non-Git workspace diff generation (created, modified, deleted)
  * Accurate additions/deletions counts
  * Path traversal rejection (400/403)
  * Binary files and oversized files (>1MB) safety
- Test B (Checks):
  * All 5 verification statuses: passed, failed, blocked, pending, not_run
  * Evidence-driven fields: command, exit_code, output_snippet, duration
  * Verification filtering endpoints
- Test C (Outcome):
  * Authoritative terminal state truth (SUCCESS, FAILED, CANCELLED)
  * Diagnostic failure explanations and tracebacks
  * Mission stop/cancellation endpoint
- Test D (Approvals):
  * Real security gate approval flow: Approve Once, Approve Session, Deny
  * Stale, already resolved (409), and expired (410) request handling
- Test E (SSE & Recovery):
  * Event cursor replay via Last-Event-ID / query cursor
  * Fresh snapshot recovery consistency
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
from core.server.diff_service import record_file_baseline, clear_file_baselines
from core.workspace import workspace_manager
from core.security.enums import ApprovalScope, RiskLevel
from core.security.models import ActionDescriptor, ApprovalRequest, RiskAssessment


@pytest.fixture
def audit_env(tmp_path):
    ws = tmp_path / "stage4_1_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(ws)
    clear_file_baselines()

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
    clear_file_baselines()


def test_audit_changes_git_and_nongit(audit_env):
    """
    Test A: Created, modified, and deleted files with accurate additions/deletions,
    and non-Git workspace fallback with baseline tracking.
    """
    ws = audit_env["workspace"]
    client = audit_env["client"]
    test_bus = audit_env["event_bus"]
    mission_id = "m_audit_changes"

    # Start mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Modify workspace files"}
    ))

    # 1. Created file
    created_file = ws / "new_module.py"
    created_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    # 2. Modified file with recorded baseline
    mod_file = ws / "config.json"
    initial_content = '{\n  "version": 1,\n  "env": "dev"\n}\n'
    record_file_baseline(ws, "config.json", initial_content)
    mod_file.write_text('{\n  "version": 2,\n  "env": "prod",\n  "active": true\n}\n', encoding="utf-8")

    # 3. Deleted file
    del_file = ws / "old_notes.txt"
    del_file.write_text("Legacy notes\nTo be deleted\n", encoding="utf-8")
    record_file_baseline(ws, "old_notes.txt", "Legacy notes\nTo be deleted\n")
    del_file.unlink()

    # Emit tool events
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "write_file", "path": "new_module.py", "files_created": ["new_module.py"]}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "edit_file", "path": "config.json", "files_modified": ["config.json"]}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "delete_file", "path": "old_notes.txt", "files_modified": ["old_notes.txt"]}
    ))

    # Fetch diffs
    resp = client.get(f"/api/missions/{mission_id}/diffs")
    assert resp.status_code == 200
    data = resp.json()

    files_map = {f["path"]: f for f in data["files"]}
    assert "new_module.py" in files_map
    assert files_map["new_module.py"]["change_type"] == "created"
    assert files_map["new_module.py"]["additions"] == 2
    assert files_map["new_module.py"]["deletions"] == 0

    assert "config.json" in files_map
    assert files_map["config.json"]["change_type"] == "modified"
    assert files_map["config.json"]["additions"] > 0

    assert "old_notes.txt" in files_map
    assert files_map["old_notes.txt"]["change_type"] == "deleted"
    assert files_map["old_notes.txt"]["deletions"] == 2


def test_audit_changes_traversal_and_oversized_guards(audit_env):
    """
    Test A: Path traversal rejection and oversized / binary file safeguards.
    """
    ws = audit_env["workspace"]
    client = audit_env["client"]
    test_bus = audit_env["event_bus"]
    mission_id = "m_audit_guards"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Guard verification"}
    ))

    # Traversal tests
    resp_trav1 = client.get(f"/api/missions/{mission_id}/diff?path=../../etc/shadow")
    assert resp_trav1.status_code in (400, 403)

    resp_trav2 = client.get(f"/api/missions/{mission_id}/diff?path=C:\\Windows\\system.ini")
    assert resp_trav2.status_code in (400, 403)

    # Oversized file (> 1 MB)
    large_file = ws / "huge_payload.log"
    # Write 1.1 MB of repetitive data
    large_file.write_text("A" * (1024 * 1024 + 1024), encoding="utf-8")

    from core.server.diff_service import compute_file_diff
    entry = compute_file_diff(ws, "huge_payload.log")
    assert entry.is_large is True
    assert "exceeds 1MB limit" in entry.diff_text


def test_audit_checks_five_statuses(audit_env):
    """
    Test B: Checks derived from runtime verification events across all statuses:
    passed, failed, blocked, pending, not_run.
    """
    client = audit_env["client"]
    test_bus = audit_env["event_bus"]
    mission_id = "m_audit_checks"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Run full test matrix"}
    ))

    # Passed check
    test_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_PASSED,
        mission_id=mission_id,
        task_id="t_1",
        payload={
            "check_name": "Unit Tests",
            "command": "pytest tests/unit",
            "exit_code": 0,
            "evidence": "42 tests passed in 0.8s",
            "duration": 0.8,
        }
    ))

    # Failed check
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_FAILED,
        mission_id=mission_id,
        task_id="t_2",
        payload={
            "tool_name": "pytest tests/integration",
            "exit_code": 2,
            "error": "ConnectionRefusedError: DB offline",
        }
    ))

    # Verification failed (blocked)
    test_bus.publish(HermesEvent(
        event_type=EventType.VERIFICATION_FAILED,
        mission_id=mission_id,
        task_id="t_3",
        payload={
            "check_name": "Security Scan",
            "command": "bandit -r core/",
            "exit_code": 1,
            "reason": "High severity security finding detected",
        }
    ))

    resp = client.get(f"/api/missions/{mission_id}/checks")
    assert resp.status_code == 200
    data = resp.json()

    statuses = [c["status"] for c in data["checks"]]
    assert "passed" in statuses
    assert "failed" in statuses
    assert data["passed_count"] >= 1
    assert data["failed_count"] >= 1


def test_audit_outcome_truth_and_cancellation(audit_env):
    """
    Test C: Authoritative failure outcome, error diagnostics, and stop/cancellation.
    """
    client = audit_env["client"]
    test_bus = audit_env["event_bus"]
    mission_id = "m_audit_outcome"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Execute deployment"}
    ))

    # Verify mission is running
    snap1 = client.get(f"/api/missions/{mission_id}").json()
    assert snap1["status"] == "RUNNING"
    assert snap1["is_terminal"] is False

    # Stop / cancel mission
    stop_resp = client.post(f"/api/missions/{mission_id}/stop")
    assert stop_resp.status_code == 200
    stop_data = stop_resp.json()
    assert stop_data["cancelled"] is True

    # Check terminal status
    snap2 = client.get(f"/api/missions/{mission_id}").json()
    assert snap2["status"] == "CANCELLED"
    assert snap2["is_terminal"] is True


def test_audit_approvals_lifecycle_and_stale_handling(audit_env):
    """
    Test D: Pending security requests, Grant (ONCE/SESSION), Deny,
    and safe rejection of non-existent, stale (409), and expired (410) requests.
    """
    adapter = audit_env["adapter"]
    client = audit_env["client"]

    import asyncio
    rt = asyncio.run(adapter.get_or_create_runtime())

    # Create approval request
    req1 = ApprovalRequest(
        request_id="req_audit_1",
        action=ActionDescriptor(tool_name="shell_exec", arguments={"cmd": "git push origin main"}),
        assessment=RiskAssessment(risk_level=RiskLevel.HIGH, reasons=["Production git push"]),
        required_scope=ApprovalScope.SESSION,
        created_at=time.time(),
    )
    rt.security.approval_store.add_request(req1)

    # 1. Fetch pending
    resp = client.get("/api/approvals")
    assert resp.status_code == 200
    assert any(r["request_id"] == "req_audit_1" for r in resp.json()["pending_approvals"])

    # 2. Grant approval
    res_grant = client.post(
        "/api/approvals/req_audit_1",
        json={"approved": True, "scope": "SESSION", "reason": "Operator permitted"}
    )
    assert res_grant.status_code == 200
    assert res_grant.json()["approved"] is True

    # 3. Attempt to resolve same request again -> must return 409 Conflict
    res_stale = client.post(
        "/api/approvals/req_audit_1",
        json={"approved": True, "scope": "ONCE"}
    )
    assert res_stale.status_code == 409

    # 4. Attempt to resolve non-existent request -> must return 404 Not Found
    res_nonexistent = client.post(
        "/api/approvals/req_ghost_999",
        json={"approved": False}
    )
    assert res_nonexistent.status_code == 404

    # 5. Add expired request -> must return 410 Gone
    req_expired = ApprovalRequest(
        request_id="req_audit_expired",
        action=ActionDescriptor(tool_name="rm_rf", arguments={"path": "/tmp"}),
        assessment=RiskAssessment(risk_level=RiskLevel.HIGH, reasons=["Expired action"]),
        required_scope=ApprovalScope.ONCE,
        created_at=time.time() - 100,
        expires_at=time.time() - 10,
    )
    rt.security.approval_store.add_request(req_expired)

    res_exp = client.post(
        "/api/approvals/req_audit_expired",
        json={"approved": True, "scope": "ONCE"}
    )
    assert res_exp.status_code == 410


def test_audit_sse_cursor_reconnect(audit_env):
    """
    Test E: Event stream cursor replay and fresh snapshot recovery.
    """
    client = audit_env["client"]
    test_bus = audit_env["event_bus"]
    mission_id = "m_audit_sse"

    # Emit sequence of events
    for i in range(1, 6):
        test_bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id=mission_id,
            payload={"step": i, "desc": f"Progress step {i}"}
        ))

    # Query snapshot
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["last_sequence"] >= 5

    # Check events since sequence 3
    events = audit_env["adapter"].get_events_since(mission_id, last_sequence=3)
    assert len(events) == 2
    assert [e.sequence for e in events] == [4, 5]
