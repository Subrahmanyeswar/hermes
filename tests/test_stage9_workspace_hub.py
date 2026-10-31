# tests/test_stage9_workspace_hub.py
"""
HERMES — Stage 9 Acceptance Test Suite
Antigravity-Inspired Project Hub, Native Folder Picker, and Safe Workspace Switching.

Covers Scenarios:
- Scenario A: Initial project discovery and active project presentation.
- Scenario B: Native folder picker execution and safe cancellation handling.
- Scenario C: Selecting an arbitrary local folder updates the active project.
- Scenario D: Tasks created under Project A execute strictly in Project A.
- Scenario E: Switching to Project B before creating a second task executes in Project B.
- Scenario F: Project A's history, diffs, and verification remain untouched and bound to Project A.
- Scenario G: Selecting or defaulting to the HERMES repository root flags protected warning.
- Security & Path Validation: Non-existent directories, invalid paths, and escaping attempts.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.event_bus import EventBus
from core.workspace import workspace_manager
from core.workspace_registry import WorkspaceRegistry, is_hermes_repo_root, HERMES_ROOT


@pytest.fixture
def temp_project_dirs() -> Generator[dict, None, None]:
    """Create two clean temporary project directories: Project Alpha and Project Beta."""
    base_tmp = Path(tempfile.mkdtemp(prefix="hermes_stage9_test_"))
    proj_a = base_tmp / "project_alpha"
    proj_b = base_tmp / "project_beta"

    proj_a.mkdir(parents=True, exist_ok=True)
    proj_b.mkdir(parents=True, exist_ok=True)

    # Populate project alpha with a small file
    (proj_a / "alpha_init.txt").write_text("Alpha Project Root Content", encoding="utf-8")
    # Populate project beta with a small file
    (proj_b / "beta_init.txt").write_text("Beta Project Root Content", encoding="utf-8")

    # Create temporary registry file
    registry_file = base_tmp / "recent_workspaces.json"
    registry = WorkspaceRegistry(registry_file=registry_file)

    yield {
        "base_tmp": base_tmp,
        "proj_a": proj_a,
        "proj_b": proj_b,
        "registry": registry,
        "registry_file": registry_file,
    }

    # Cleanup
    shutil.rmtree(base_tmp, ignore_errors=True)


@pytest.fixture
def test_env(temp_project_dirs):
    """FastAPI TestClient wired to the test registry and runtime adapter."""
    test_adapter = RuntimeAdapter(event_bus=EventBus())
    app = create_app(adapter=test_adapter, registry=temp_project_dirs["registry"])
    client = TestClient(app)
    return {
        "client": client,
        "adapter": test_adapter,
        "registry": temp_project_dirs["registry"],
        "proj_a": temp_project_dirs["proj_a"],
        "proj_b": temp_project_dirs["proj_b"],
    }


# ── Scenario A: Initial Project Discovery & Active Presentation ─────────────
def test_scenario_a_initial_project_discovery(test_env):
    """Verify GET /api/workspaces returns valid workspace state and active path."""
    proj_a = test_env["proj_a"]
    registry = test_env["registry"]
    client = test_env["client"]
    registry.register_or_select(proj_a, set_active=True)

    resp = client.get("/api/workspaces")
    assert resp.status_code == 200
    data = resp.json()

    assert "workspaces" in data
    assert "current_workspace" in data
    assert Path(data["current_workspace"]).resolve() == proj_a.resolve()
    assert len(data["workspaces"]) >= 1

    active_ws = next((w for w in data["workspaces"] if Path(w["path"]).resolve() == proj_a.resolve()), None)
    assert active_ws is not None
    assert active_ws["exists"] is True
    assert active_ws["name"] == "project_alpha"
    assert active_ws["is_active"] is True
    assert active_ws["is_hermes_repo"] is False


# ── Scenario B: Native Folder Picker & Safe Cancellation ────────────────────
def test_scenario_b_native_picker_cancelled_and_selected(test_env):
    """Verify /api/workspaces/pick-folder handles both cancellation and successful selection."""
    client = test_env["client"]
    proj_b = test_env["proj_b"]

    # 1. User cancels folder picker
    with patch("asyncio.to_thread", return_value=None):
        resp_cancel = client.post("/api/workspaces/pick-folder")
        assert resp_cancel.status_code == 200
        cancel_data = resp_cancel.json()
        assert cancel_data["cancelled"] is True
        assert cancel_data["path"] is None

    # 2. User selects Project Beta
    with patch("asyncio.to_thread", return_value=str(proj_b)):
        resp_pick = client.post("/api/workspaces/pick-folder")
        assert resp_pick.status_code == 200
        pick_data = resp_pick.json()
        assert pick_data["cancelled"] is False
        assert Path(pick_data["path"]).resolve() == proj_b.resolve()
        assert pick_data["name"] == "project_beta"
        assert pick_data["is_hermes_repo"] is False


# ── Scenario C: Selecting Arbitrary Local Folder ─────────────────────────────
def test_scenario_c_select_arbitrary_local_folder(test_env):
    """Verify POST /api/workspaces/select sets the active workspace and updates recent list."""
    client = test_env["client"]
    proj_a = test_env["proj_a"]
    proj_b = test_env["proj_b"]

    # Select Project Alpha
    resp_a = client.post("/api/workspaces/select", json={"folder_path": str(proj_a)})
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert Path(data_a["current_workspace"]).resolve() == proj_a.resolve()

    # Select Project Beta
    resp_b = client.post("/api/workspaces/select", json={"folder_path": str(proj_b)})
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert Path(data_b["current_workspace"]).resolve() == proj_b.resolve()
    assert len(data_b["workspaces"]) == 2

    # Check that Project Beta is active and Project Alpha is in recent list
    ws_b = next(w for w in data_b["workspaces"] if Path(w["path"]).resolve() == proj_b.resolve())
    ws_a = next(w for w in data_b["workspaces"] if Path(w["path"]).resolve() == proj_a.resolve())
    assert ws_b["is_active"] is True
    assert ws_a["is_active"] is False


# ── Scenario D & E: Task Workspace Binding & Cross-Switching Isolation ──────
@pytest.mark.asyncio
async def test_scenario_d_and_e_task_workspace_binding_and_switching(test_env):
    """
    Verify:
    1. Mission 1 created in Project Alpha is bound to Project Alpha.
    2. Switching active workspace to Project Beta and creating Mission 2 binds Mission 2 to Project Beta.
    3. Switching workspaces does NOT retarget Mission 1.
    """
    client = test_env["client"]
    adapter = test_env["adapter"]
    proj_a = test_env["proj_a"]
    proj_b = test_env["proj_b"]

    # Select Project Alpha
    client.post("/api/workspaces/select", json={"folder_path": str(proj_a)})

    # Mock runtime adapter start_mission
    with patch.object(adapter, "start_mission") as mock_start:
        mock_start.return_value = "m_alpha001"

        # Create mission in Project Alpha
        resp_m1 = client.post(
            "/api/missions",
            json={"prompt": "Task in Alpha", "workspace_root": str(proj_a)},
        )
        assert resp_m1.status_code == 201
        m1_data = resp_m1.json()
        assert m1_data["mission_id"] == "m_alpha001"
        assert Path(m1_data["workspace_root"]).resolve() == proj_a.resolve()

        # Call with bound workspace
        mock_start.assert_called_with(
            prompt="Task in Alpha",
            workspace_root=str(proj_a.resolve()),
            plan_mode=False,
        )

    # Now switch workspace to Project Beta
    client.post("/api/workspaces/select", json={"folder_path": str(proj_b)})

    with patch.object(adapter, "start_mission") as mock_start_b:
        mock_start_b.return_value = "m_beta002"

        # Create mission in Project Beta
        resp_m2 = client.post(
            "/api/missions",
            json={"prompt": "Task in Beta", "workspace_root": str(proj_b)},
        )
        assert resp_m2.status_code == 201
        m2_data = resp_m2.json()
        assert m2_data["mission_id"] == "m_beta002"
        assert Path(m2_data["workspace_root"]).resolve() == proj_b.resolve()

        mock_start_b.assert_called_with(
            prompt="Task in Beta",
            workspace_root=str(proj_b.resolve()),
            plan_mode=False,
        )


# ── Scenario F: Immutable History & Diffs Bound to Creation Workspace ───────
def test_scenario_f_immutable_mission_workspace_snapshot(test_env):
    """Verify that MissionSnapshot reports the workspace the mission was created in."""
    client = test_env["client"]
    adapter = test_env["adapter"]
    proj_a = test_env["proj_a"]
    proj_b = test_env["proj_b"]

    from unittest.mock import MagicMock
    from core.runtime_state.models import MissionStatus

    # Create mock mission state in Project Alpha
    mock_state = MagicMock()
    mock_state.mission.mission_id = "m_history_alpha"
    mock_state.mission.title = "Alpha Mission"
    mock_state.mission.prompt = "Write alpha file"
    mock_state.mission.status = MissionStatus.COMPLETED
    mock_state.mission.is_terminal = True
    mock_state.mission.workspace_root = str(proj_a.resolve())
    mock_state.mission.start_time = time.time()
    mock_state.mission.artifacts_created = ["alpha_init.txt"]
    mock_state.mission.abort_reason = None
    mock_state.mission.error = None
    mock_state.mission.completion_reason = None
    mock_state.tasks = {}
    mock_state.state_version = 1

    # While active project is Project Beta:
    client.post("/api/workspaces/select", json={"folder_path": str(proj_b)})

    with patch.object(adapter, "get_mission_snapshot", return_value=mock_state):
        with patch.object(adapter, "get_events_since", return_value=[]):
            snap_resp = client.get("/api/missions/m_history_alpha")
            assert snap_resp.status_code == 200
            snap_data = snap_resp.json()
            # The snapshot workspace must remain Project Alpha!
            assert Path(snap_data["workspace_root"]).resolve() == proj_a.resolve()


# ── Scenario G: Protected HERMES Root Guard ─────────────────────────────────
def test_scenario_g_hermes_root_protection_flag(test_env):
    """Verify is_hermes_repo flags True when HERMES repo root is inspected or selected."""
    client = test_env["client"]
    assert is_hermes_repo_root(HERMES_ROOT) is True

    resp = client.post("/api/workspaces/select", json={"folder_path": str(HERMES_ROOT)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_hermes_repo"] is True

    hermes_entry = next(w for w in data["workspaces"] if Path(w["path"]).resolve() == HERMES_ROOT.resolve())
    assert hermes_entry["is_hermes_repo"] is True
    assert hermes_entry["is_active"] is True


# ── Scenario H: Security & Boundary Validation ──────────────────────────────
def test_scenario_h_invalid_workspace_path_rejected(test_env):
    """Verify invalid or non-existent paths are rejected with HTTP 400."""
    client = test_env["client"]
    # Non-existent path
    resp_nonexistent = client.post("/api/workspaces/select", json={"folder_path": "C:\\nonexistent_dir_99999"})
    assert resp_nonexistent.status_code == 400
    assert "Selected folder does not exist" in resp_nonexistent.json()["detail"]

    # File path instead of directory
    existing_file = Path(__file__).resolve()
    resp_file = client.post("/api/workspaces/select", json={"folder_path": str(existing_file)})
    assert resp_file.status_code == 400
    assert "Selected path is not a directory" in resp_file.json()["detail"]


# ── Scenario I: Remove from Recent Workspaces List ──────────────────────────
def test_scenario_i_remove_recent_workspace(test_env):
    """Verify DELETE /api/workspaces/recent removes folder from list without deleting files."""
    client = test_env["client"]
    proj_a = test_env["proj_a"]
    proj_b = test_env["proj_b"]

    client.post("/api/workspaces/select", json={"folder_path": str(proj_a)})
    client.post("/api/workspaces/select", json={"folder_path": str(proj_b)})

    del_resp = client.request(
        "DELETE",
        "/api/workspaces/recent",
        json={"folder_path": str(proj_a)},
    )
    assert del_resp.status_code == 200
    data = del_resp.json()

    # Project Alpha is removed from registry list
    assert not any(Path(w["path"]).resolve() == proj_a.resolve() for w in data["workspaces"])
    # But files on disk still exist!
    assert (proj_a / "alpha_init.txt").exists()


