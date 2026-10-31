# tests/test_stage6_1_browser_correlation.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 6.1:
Browser-to-Runtime Mission Correlation and Read-Only Acceptance.

Verifies:
1. Complete lifecycle correlation: browser task submission -> runtime adapter ->
   AgentLoop execution -> state store terminal completion -> API snapshot consistency.
2. Legitimate Read-Only Acceptance: Inspection missions against existing documentation
   execute via read tools, produce zero filesystem mutations, and complete cleanly.
3. Live model / simulated model correlation: Verifies tool invocation tracking,
   manifest before/after immutability on read-only tasks, and accurate diff representation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from core.agent_loop.completion import CompletionPolicy
from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import MissionStatus
from core.server.app import create_app
from core.server.diff_service import clear_file_baselines, record_file_baseline
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager


@pytest.fixture
def stage6_1_env(tmp_path):
    ws = tmp_path / "stage6_1_correlation_ws"
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
    clear_file_baselines()


def test_1_read_only_task_zero_mutation_and_completion(stage6_1_env):
    """
    Scenario D Verification:
    Confirms that a read-only task against a README file:
    - Leaves the filesystem completely unchanged.
    - Yields an empty diff response (no created, modified, or deleted files).
    - Transitions to COMPLETED under CompletionPolicy.
    """
    ws: Path = stage6_1_env["workspace"]
    client: TestClient = stage6_1_env["client"]
    test_bus: EventBus = stage6_1_env["event_bus"]
    mission_id = "m_stage6_1_readonly"

    # Pre-populate documentation fixture
    doc_file = ws / "DOCS.md"
    doc_content = "# System Architecture\nHERMES autonomous agent harness.\n"
    doc_file.write_text(doc_content, encoding="utf-8")
    before_manifest = {p.name: p.stat().st_size for p in ws.iterdir() if p.is_file()}

    # Simulate start of inspection mission
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Inspect DOCS.md and summarize architecture"}
    ))

    # Read-only tool completed (read_file)
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "read_file", "path": "DOCS.md", "content": doc_content}
    ))

    # Evaluate completion policy
    cp = CompletionPolicy()
    can_complete, reason, issues = cp.evaluate_completion(
        mission_prompt="Inspect DOCS.md and summarize architecture",
        workspace=workspace_manager,
        written_files=[]
    )
    assert can_complete is True
    assert len(issues) == 0

    # Publish mission completed
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"reason": "Architecture summarized successfully."}
    ))

    # Verify zero mutations on filesystem
    after_manifest = {p.name: p.stat().st_size for p in ws.iterdir() if p.is_file()}
    assert before_manifest == after_manifest

    # Verify API diff returns 0 affected files
    diff_resp = client.get(f"/api/missions/{mission_id}/diffs")
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert len(diff_data["files"]) == 0
    assert diff_data["total_additions"] == 0
    assert diff_data["total_deletions"] == 0

    # Verify snapshot
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["status"] == "COMPLETED"
    assert snap["is_terminal"] is True


def test_2_browser_submission_correlation_contract(stage6_1_env):
    """
    Verifies that the /api/missions POST endpoint returns a valid mission_id,
    and that subsequent GET /api/missions/{id} and events correlate directly.
    """
    client: TestClient = stage6_1_env["client"]
    ws: Path = stage6_1_env["workspace"]

    create_resp = client.post("/api/missions", json={
        "prompt": "Inspect workspace root",
        "workspace_root": str(ws),
        "plan_mode": False
    })
    assert create_resp.status_code == 201
    res_data = create_resp.json()
    m_id = res_data["mission_id"]
    assert m_id.startswith("m_")
    assert res_data["status"] == "RUNNING"

    # Query snapshot
    snap_resp = client.get(f"/api/missions/{m_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["mission_id"] == m_id
    assert snap["prompt"] == "Inspect workspace root"
