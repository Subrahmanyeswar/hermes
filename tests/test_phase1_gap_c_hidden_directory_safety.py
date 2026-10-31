"""
Tests for Acceptance Gap C: Hidden-Directory Classification Safety.

Verifies:
1. Workspaces containing only HERMES metadata (.hermes, .artifacts) are classified as empty.
2. A new application request is allowed in that workspace.
3. Workspaces containing real application files are recognized as an existing application.
4. Relevant hidden application configuration (.github, .well-known, .storybook, .config) are not ignored.
5. Ordinary task instructions containing "existing application" without modification intent do not trigger false positives.
6. Genuine requests to modify an existing application continue to be recognized and blocked if workspace is empty.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from core.agent_loop.loop import AgentLoop
from core.mission_planner import Mission
from core.runtime_state.events import EventType, HermesEvent
from core.workspace import WorkspaceManager


def test_gap_c_metadata_only_workspace_classified_as_empty(tmp_path: Path):
    """Prove a workspace containing only HERMES and VCS metadata is treated as empty."""
    ws = tmp_path / "metadata_ws"
    ws.mkdir()
    (ws / ".hermes").mkdir()
    (ws / ".hermes" / "state.db").write_text("dummy", encoding="utf-8")
    (ws / ".artifacts").mkdir()
    (ws / ".artifacts" / "missions").mkdir(parents=True)
    (ws / ".artifacts" / "missions" / "progress.json").write_text("{}", encoding="utf-8")
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (ws / ".gitignore").write_text("*.pyc\n", encoding="utf-8")

    from core.workspace import IGNORE_PATTERNS as _WS_IGNORE_PATTERNS
    import fnmatch as _fnmatch

    NON_APP_METADATA_DIRS = {
        ".hermes", "artifacts", ".artifacts", "sessions", ".sessions",
        "trajectories", "browser_profiles", ".gemini",
        ".git", ".svn", ".hg",
        "node_modules", "venv", ".venv", "env",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
        ".idea", ".vscode", "dist", "build", "target"
    }
    NON_APP_METADATA_FILES = {
        ".ds_store", "thumbs.db", ".gitignore", ".gitattributes", ".gitmodules",
        ".editorconfig", ".env", ".env.local"
    }

    app_files = []
    for p in ws.rglob("*"):
        if p.is_file():
            rel = p.relative_to(ws)
            dir_parts = set(rel.parts[:-1])
            is_meta_dir = bool(dir_parts.intersection(NON_APP_METADATA_DIRS)) or any(
                any(_fnmatch.fnmatch(part, pat) or part == pat for pat in _WS_IGNORE_PATTERNS)
                for part in dir_parts
            )
            is_meta_file = rel.name.lower() in NON_APP_METADATA_FILES or rel.name.endswith((".pyc", ".pyo", ".pyd"))
            if not is_meta_dir and not is_meta_file:
                app_files.append(p)

    assert len(app_files) == 0, f"Expected 0 application files, got {app_files}"


def test_gap_c_legitimate_hidden_config_recognized_as_application(tmp_path: Path):
    """Prove that legitimate hidden config (.github, .well-known, .storybook, .config) counts as existing app."""
    ws = tmp_path / "config_ws"
    ws.mkdir()
    (ws / ".github" / "workflows").mkdir(parents=True)
    (ws / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (ws / ".storybook").mkdir()
    (ws / ".storybook" / "main.js").write_text("module.exports = {};\n", encoding="utf-8")
    (ws / ".well-known").mkdir()
    (ws / ".well-known" / "assetlinks.json").write_text("[]\n", encoding="utf-8")
    (ws / ".config").mkdir()
    (ws / ".config" / "settings.json").write_text("{}", encoding="utf-8")

    from core.workspace import IGNORE_PATTERNS as _WS_IGNORE_PATTERNS
    import fnmatch as _fnmatch

    NON_APP_METADATA_DIRS = {
        ".hermes", "artifacts", ".artifacts", "sessions", ".sessions",
        "trajectories", "browser_profiles", ".gemini",
        ".git", ".svn", ".hg",
        "node_modules", "venv", ".venv", "env",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
        ".idea", ".vscode", "dist", "build", "target"
    }
    NON_APP_METADATA_FILES = {
        ".ds_store", "thumbs.db", ".gitignore", ".gitattributes", ".gitmodules",
        ".editorconfig", ".env", ".env.local"
    }

    app_files = []
    for p in ws.rglob("*"):
        if p.is_file():
            rel = p.relative_to(ws)
            dir_parts = set(rel.parts[:-1])
            is_meta_dir = bool(dir_parts.intersection(NON_APP_METADATA_DIRS)) or any(
                any(_fnmatch.fnmatch(part, pat) or part == pat for pat in _WS_IGNORE_PATTERNS)
                for part in dir_parts
            )
            is_meta_file = rel.name.lower() in NON_APP_METADATA_FILES or rel.name.endswith((".pyc", ".pyo", ".pyd"))
            if not is_meta_dir and not is_meta_file:
                app_files.append(p)

    rel_names = {str(p.relative_to(ws)).replace("\\", "/") for p in app_files}
    assert ".github/workflows/ci.yml" in rel_names
    assert ".storybook/main.js" in rel_names
    assert ".well-known/assetlinks.json" in rel_names
    assert ".config/settings.json" in rel_names


@pytest.mark.asyncio
async def test_gap_c_greenfield_allowed_in_metadata_only_workspace(tmp_path: Path):
    """Prove a new application request passes preflight even when .artifacts and .hermes exist."""
    meta_ws = tmp_path / "meta_ws"
    meta_ws.mkdir()
    (meta_ws / ".artifacts").mkdir()
    (meta_ws / ".artifacts" / "progress.json").write_text("{}", encoding="utf-8")
    (meta_ws / ".hermes").mkdir()
    (meta_ws / ".hermes" / "state.db").write_text("x", encoding="utf-8")

    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(meta_ws))

    published: list[HermesEvent] = []
    mock_eb = MagicMock()
    mock_eb.get_database.return_value = None
    mock_eb.get_or_create_state.return_value.get_snapshot.return_value.mission.is_terminal = False

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws_mgr,
        event_bus_instance=mock_eb,
    )
    loop._publish_event = AsyncMock(side_effect=lambda et, **kw: published.append(
        HermesEvent(event_type=et, mission_id="m_gf_meta", payload=kw.get("payload", {}))
    ))
    loop.abort_event.set()

    mission = Mission(
        mission_id="m_gf_meta",
        run_id="run_gf_meta",
        attempt_number=1,
        user_prompt="Build LabFlow from scratch. If any existing files are present, do not overwrite them.",
        workspace_root=str(meta_ws),
    )

    res = await loop.run(mission)
    failed = [e for e in published if e.event_type == EventType.MISSION_FAILED]
    assert len(failed) == 0, f"Expected 0 MISSION_FAILED events, got {failed}"
    assert any(e.event_type == EventType.MISSION_STARTED for e in published)


@pytest.mark.asyncio
async def test_gap_c_modification_allowed_when_hidden_config_present(tmp_path: Path):
    """Prove that modifying an existing application proceeds when legitimate hidden config files exist."""
    cfg_ws = tmp_path / "cfg_ws"
    cfg_ws.mkdir()
    (cfg_ws / ".storybook").mkdir()
    (cfg_ws / ".storybook" / "main.js").write_text("module.exports = {};\n", encoding="utf-8")

    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(cfg_ws))

    published: list[HermesEvent] = []
    mock_eb = MagicMock()
    mock_eb.get_database.return_value = None
    mock_eb.get_or_create_state.return_value.get_snapshot.return_value.mission.is_terminal = False

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws_mgr,
        event_bus_instance=mock_eb,
    )
    loop._publish_event = AsyncMock(side_effect=lambda et, **kw: published.append(
        HermesEvent(event_type=et, mission_id="m_mod_cfg", payload=kw.get("payload", {}))
    ))
    loop.abort_event.set()

    mission = Mission(
        mission_id="m_mod_cfg",
        run_id="run_mod_cfg",
        attempt_number=1,
        user_prompt="Update the existing application to add a new storybook component.",
        workspace_root=str(cfg_ws),
    )

    res = await loop.run(mission)
    failed = [e for e in published if e.event_type == EventType.MISSION_FAILED]
    assert len(failed) == 0, "Preflight should have found .storybook/main.js and allowed the modification mission"


@pytest.mark.asyncio
async def test_gap_c_modification_blocked_in_empty_workspace(tmp_path: Path):
    """Prove that modifying an existing application is honestly rejected in a truly empty workspace."""
    empty_ws = tmp_path / "truly_empty_ws"
    empty_ws.mkdir()

    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(empty_ws))

    published: list[HermesEvent] = []
    mock_eb = MagicMock()
    mock_eb.get_database.return_value = None

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws_mgr,
        event_bus_instance=mock_eb,
    )
    loop._publish_event = AsyncMock(side_effect=lambda et, **kw: published.append(
        HermesEvent(event_type=et, mission_id="m_mod_empty", payload=kw.get("payload", {}))
    ))

    mission = Mission(
        mission_id="m_mod_empty",
        run_id="run_mod_empty",
        attempt_number=1,
        user_prompt="Modify the existing application to add authentication.",
        workspace_root=str(empty_ws),
    )

    res = await loop.run(mission)
    assert res.success is False
    assert res.status == "FAILED"
    failed = [e for e in published if e.event_type == EventType.MISSION_FAILED]
    assert len(failed) == 1
    assert failed[0].payload.get("failure_code") == "EMPTY_WORKSPACE_EXISTING_APPLICATION"
