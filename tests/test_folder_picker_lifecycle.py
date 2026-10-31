# tests/test_folder_picker_lifecycle.py
"""
Deterministic Acceptance Test Suite for HERMES Folder Picker Lifecycle:
1. Normal folder selection & workspace registration
2. User cancellation handling (no error, state preserved)
3. Failed dialog initialization recovery (no stale lock, subsequent request succeeds)
4. Race condition & duplicate click protection (prevents competing pickers)
5. Project isolation (no files modified on folder pick)
6. Desktop station affinity & foreground configuration
"""

import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pytest
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.server.app import create_app
from core.server.folder_picker import FolderPickerManager, folder_picker_manager
from core.server.runtime_adapter import RuntimeAdapter
from core.persistence.database import SQLiteDatabase


@pytest.fixture
def test_app_env(tmp_path):
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    isolated_db = SQLiteDatabase(tmp_path / "test_state.db")
    test_bus = EventBus(enabled=True, db=isolated_db)
    adapter = RuntimeAdapter(event_bus=test_bus)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return {
        "workspace": ws,
        "adapter": adapter,
        "app": app,
        "client": client,
        "tmp_path": tmp_path,
    }


def test_a_normal_folder_selection(test_app_env):
    """Test A: Normal folder selection returns valid workspace and updates registry."""
    client = test_app_env["client"]
    target_dir = test_app_env["tmp_path"] / "my_project"
    target_dir.mkdir()
    (target_dir / "app.py").write_text("print('hello')", encoding="utf-8")

    with patch.object(
        folder_picker_manager,
        "pick_directory",
        new=AsyncMock(return_value=(False, str(target_dir), None)),
    ):
        resp = client.post("/api/workspaces/pick-folder")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is False
        assert data["error"] is None
        assert Path(data["path"]).resolve() == target_dir.resolve()
        assert data["name"] == "my_project"

        # Verify workspaces listing includes it
        ws_resp = client.get("/api/workspaces")
        assert ws_resp.status_code == 200
        workspaces = ws_resp.json()["workspaces"]
        paths = [w["path"] for w in workspaces]
        assert str(target_dir.resolve()) in paths


def test_b_cancellation_preserves_state(test_app_env):
    """Test B: Cancellation leaves current workspace untouched and returns no error."""
    client = test_app_env["client"]

    with patch.object(
        folder_picker_manager,
        "pick_directory",
        new=AsyncMock(return_value=(True, None, None)),
    ):
        resp = client.post("/api/workspaces/pick-folder")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is True
        assert data["error"] is None
        assert data["path"] is None


def test_c_failed_initialization_releases_busy_state(test_app_env):
    """Test C: Failed dialog initialization returns actionable error and releases lock."""
    client = test_app_env["client"]

    # First call fails
    with patch.object(
        folder_picker_manager,
        "pick_directory",
        new=AsyncMock(return_value=(True, None, "OS dialog failed to initialize")),
    ):
        resp = client.post("/api/workspaces/pick-folder")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is True
        assert data["error"] == "OS dialog failed to initialize"

    # Immediately ensure picker manager is not active
    assert folder_picker_manager.is_dialog_active() is False

    # Second call succeeds normally
    target_dir = test_app_env["tmp_path"] / "recovery_project"
    target_dir.mkdir()
    with patch.object(
        folder_picker_manager,
        "pick_directory",
        new=AsyncMock(return_value=(False, str(target_dir), None)),
    ):
        resp2 = client.post("/api/workspaces/pick-folder")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["cancelled"] is False
        assert Path(data2["path"]).resolve() == target_dir.resolve()


def test_d_duplicate_clicks_prevent_competing_pickers(test_app_env):
    """Test D: When a dialog is genuinely active, concurrent requests are rejected."""
    client = test_app_env["client"]

    # Mock is_dialog_active to True to simulate another in-flight native dialog
    with patch.object(folder_picker_manager, "is_dialog_active", return_value=True):
        resp = client.post("/api/workspaces/pick-folder")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is True
        assert data["error"] == "A folder picker dialog is already open."

    # When dialog closes, is_dialog_active becomes False and subsequent request works
    with patch.object(folder_picker_manager, "is_dialog_active", return_value=False):
        with patch.object(
            folder_picker_manager,
            "pick_directory",
            new=AsyncMock(return_value=(True, None, None)),
        ):
            resp2 = client.post("/api/workspaces/pick-folder")
            assert resp2.status_code == 200
            assert resp2.json()["cancelled"] is True
            assert resp2.json()["error"] is None


def test_e_manager_real_process_tracking():
    """Test E: FolderPickerManager correctly detects dead vs alive processes."""
    mgr = FolderPickerManager()
    assert mgr.is_dialog_active() is False

    class FakeProc:
        def __init__(self, retcode):
            self.returncode = retcode

    # If proc is running (returncode is None)
    mgr._active_proc = FakeProc(None)
    assert mgr.is_dialog_active() is True

    # If proc has terminated (returncode is 0)
    mgr._active_proc = FakeProc(0)
    assert mgr.is_dialog_active() is False
    assert mgr._active_proc is None


def test_f_project_isolation(test_app_env):
    """Test F: Selecting a workspace does not alter, move, or delete any of its contents."""
    client = test_app_env["client"]
    project_dir = test_app_env["tmp_path"] / "isolated_project"
    project_dir.mkdir()
    sample_file = project_dir / "data.txt"
    sample_file.write_text("critical content", encoding="utf-8")

    with patch.object(
        folder_picker_manager,
        "pick_directory",
        new=AsyncMock(return_value=(False, str(project_dir), None)),
    ):
        resp = client.post("/api/workspaces/pick-folder")
        assert resp.status_code == 200

    assert sample_file.exists()
    assert sample_file.read_text(encoding="utf-8") == "critical content"
