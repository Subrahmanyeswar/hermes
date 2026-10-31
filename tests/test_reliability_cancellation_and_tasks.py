import pytest
import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

from core.event_bus import EventBus, HermesEvent, EventType
from core.runtime_state.models import MissionStatus, TaskStatus, RequirementCategory, RequirementPriority
from core.workspace_registry import workspace_registry
from core.agent_loop.behavioral_verifier import TechnologyAwareBehavioralVerifier


@pytest.mark.asyncio
async def test_plan_tasks_populated_on_requirement_and_plan_created():
    bus = EventBus()
    mission_id = f"m_test_plan_{int(time.time()*1000)}"

    # 1. Emit REQUIREMENT_CREATED
    req_event = HermesEvent(
        event_type=EventType.REQUIREMENT_CREATED,
        mission_id=mission_id,
        payload={
            "requirement_id": "req_1_hero",
            "title": "Hero Section Implementation",
            "description": "Build luxury hero section with CTA",
            "category": "functional",
            "priority": "HIGH",
        }
    )
    bus.publish(req_event)

    state_store = bus.get_state(mission_id)
    assert state_store is not None
    snap = state_store.get_snapshot()
    assert "req_1_hero" in snap.requirements
    assert "req_1_hero" in snap.tasks
    assert snap.tasks["req_1_hero"].title == "Hero Section Implementation"
    assert snap.tasks["req_1_hero"].status == TaskStatus.PENDING

    # 2. Emit REQUIREMENT_COMPLETED
    comp_event = HermesEvent(
        event_type=EventType.REQUIREMENT_COMPLETED,
        mission_id=mission_id,
        payload={"requirement_id": "req_1_hero", "reason": "Verified"}
    )
    bus.publish(comp_event)

    snap2 = state_store.get_snapshot()
    assert snap2.tasks["req_1_hero"].status == TaskStatus.COMPLETED


def test_workspace_registry_dynamic_file_count(tmp_path):
    from core.workspace_registry import WorkspaceRegistry
    reg = WorkspaceRegistry(registry_file=tmp_path / "test_workspaces.json")
    ws_dir = tmp_path / "dynamic_ws"
    ws_dir.mkdir()

    # Add workspace when empty
    reg.register_or_select(ws_dir)
    ws_list = reg.list_workspaces()
    matched = [w for w in ws_list if Path(w["path"]).resolve() == ws_dir.resolve()]
    assert len(matched) == 1
    assert matched[0]["total_files"] == 0

    # Create files on disk
    (ws_dir / "index.html").write_text("<!DOCTYPE html><html><body><h1>Test</h1></body></html>", encoding="utf-8")
    (ws_dir / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
    (ws_dir / "app.js").write_text("console.log('hi');", encoding="utf-8")

    # Call list_workspaces again - file count must update dynamically
    updated_list = reg.list_workspaces()
    updated_matched = [w for w in updated_list if Path(w["path"]).resolve() == ws_dir.resolve()]
    assert len(updated_matched) == 1
    assert updated_matched[0]["total_files"] == 3


def test_behavioral_verifier_image_validation(tmp_path):
    ws = tmp_path / "web_ws"
    ws.mkdir()
    (ws / "styles.css").write_text("body { background: #000; }", encoding="utf-8")
    (ws / "app.js").write_text(
        "document.addEventListener('DOMContentLoaded', () => { "
        "  const btn = document.getElementById('btn'); "
        "  const box = document.querySelector('.box'); "
        "  if (btn) btn.onclick = () => { box.innerHTML = '<p>Updated</p>'; }; "
        "});",
        encoding="utf-8"
    )

    # 1. HTML with broken hallucinated 404 URL
    bad_html = """<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="styles.css"></head>
<body>
  <h1>Test</h1>
  <button id="btn">Click</button>
  <img src="https://images.unsplash.com/photo-1600185350955-0c6c0c0c2c5c?auto=format" alt="car" />
  <script src="app.js"></script>
</body>
</html>"""
    (ws / "index.html").write_text(bad_html, encoding="utf-8")

    res = TechnologyAwareBehavioralVerifier.verify_vanilla_web(ws, "Build luxury car website")
    assert not res.passed
    assert any("broken" in iss.lower() or "dummy" in iss.lower() for iss in res.issues)

    # 2. Fix with verified local image
    img_dir = ws / "assets" / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "hero.jpg").write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00"*200) # Valid dummy jpeg bytes > 100 bytes

    good_html = """<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="styles.css"></head>
<body>
  <h1>Test</h1>
  <button id="btn">Click</button>
  <img src="assets/images/hero.jpg" alt="car" />
  <script src="app.js"></script>
</body>
</html>"""
    (ws / "index.html").write_text(good_html, encoding="utf-8")

    res_good = TechnologyAwareBehavioralVerifier.verify_vanilla_web(ws, "Build luxury car website")
    assert res_good.passed


def test_snapshot_requirements_fallback_and_terminal_walkthrough(tmp_path):
    from core.persistence.database import SQLiteDatabase
    from core.server.runtime_adapter import RuntimeAdapter
    from core.server.app import create_app
    from starlette.testclient import TestClient

    ws = tmp_path / "test_ws"
    ws.mkdir()
    isolated_db = SQLiteDatabase(tmp_path / "snap_test.db")
    bus = EventBus(enabled=True, db=isolated_db)
    adapter = RuntimeAdapter(event_bus=bus)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    mission_id = "m_snap_fallback_01"
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Build car showcase website"}
    ))
    bus.publish(HermesEvent(
        event_type=EventType.REQUIREMENT_CREATED,
        mission_id=mission_id,
        payload={
            "requirement_id": "req_hero",
            "title": "Automotive Hero Section",
            "description": "Exotic car hero",
        }
    ))
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={
            "reason": "All contracts verified",
            "files_created": ["index.html", "styles.css", "app.js"]
        }
    ))

    resp = client.get(f"/api/missions/{mission_id}")
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["is_terminal"] is True
    assert snap["status"] == "COMPLETED"
    assert len(snap["tasks"]) >= 1
    assert snap["tasks"][0]["task_id"] == "req_hero"
    assert snap["final_output"] is not None
    assert "Mission Completed Successfully" in snap["final_output"]
    assert "Launch Instructions" in snap["final_output"]
