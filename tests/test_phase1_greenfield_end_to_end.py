"""
Tests for Acceptance Gap A: Genuine Greenfield End-to-End Execution.

Verifies:
1. Disposable workspace outside the HERMES repo with pre-existing HERMES metadata (.artifacts, .hermes).
2. Greenfield task: LabFlow campus laboratory management dashboard.
3. Preflight classifies task as greenfield creation (not modification).
4. Real ActionExecutor and registered WriteFileTool writes genuine index.html, style.css, and app.js to disk.
5. Real ReadFileTool reads the index.html file back through the tool interface.
6. Direct independent filesystem inspection verifies bytes on disk match.
7. Mission lifecycle reflects honest completion.
8. Injected execution failure test proves failures are honestly reported as failures, never successes.
9. Test directories are unique, inspected before use, and preserved for audit verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from core.agent_loop.actions import ActionExecutor
from core.agent_loop.decisions import AgentDecision, AgentDecisionType
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.event_bus import EventBus
from core.mission_planner import Mission
from core.persistence.database import SQLiteDatabase
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.store import StateStore
from core.workspace import workspace_manager
from tools.file_tools import ReadFileTool, WriteFileTool
from tools.platform.catalog import tool_catalog


LABFLOW_PROMPT = (
    "Build LabFlow, a campus laboratory management dashboard, using vanilla HTML, CSS, and JavaScript. "
    "Include laboratory listings, booking interactions, summary statistics and CSV export. "
    "Use localStorage for appropriate persistence and do not require external frameworks or network dependencies."
)

STYLE_CSS_CONTENT = """body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  margin: 0;
  padding: 20px;
  background-color: #f4f6f9;
  color: #1f2937;
}

.header {
  background: white;
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  margin-bottom: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 15px;
  margin-bottom: 20px;
}

.card {
  background: white;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
"""

APP_JS_CONTENT = """document.addEventListener("DOMContentLoaded", function() {
  console.log("LabFlow campus laboratory dashboard initialized.");

  var defaultLabs = [
    { id: 1, name: "Biochemistry Core Lab", capacity: 25, status: "available" },
    { id: 2, name: "Laser Optics Facility", capacity: 12, status: "occupied" },
    { id: 3, name: "Microbiology Suite", capacity: 18, status: "available" }
  ];

  if (!localStorage.getItem("labflow_labs")) {
    localStorage.setItem("labflow_labs", JSON.stringify(defaultLabs));
  }

  function renderDashboard() {
    var totalCard = document.getElementById("card-total");
    if (totalCard) {
      totalCard.innerHTML = "<h3>Total Labs: " + defaultLabs.length + "</h3>";
    }
    var list = document.getElementById("booking-list");
    if (list) {
      list.textContent = "Active bookings: 3 rooms operational.";
    }
  }

  renderDashboard();

  function exportCSV() {
    var labs = JSON.parse(localStorage.getItem("labflow_labs") || "[]");
    var csv = "id,name,capacity,status\\n" + labs.map(function(l) {
      return l.id + ',"' + l.name + '",' + l.capacity + ',' + l.status;
    }).join("\\n");
    console.log("Exported CSV:", csv);
  }

  var btn = document.getElementById("export-btn");
  if (btn) {
    btn.addEventListener("click", exportCSV);
  }
});
"""

INDEX_HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>LabFlow - Campus Laboratory Management</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="header">
    <h1>LabFlow Dashboard</h1>
    <p>Campus Laboratory Management &amp; Resource Allocation System</p>
  </div>
  <div class="stats-grid">
    <div class="card" id="card-total"><h3>Total Labs: 3</h3></div>
    <div class="card" id="card-available"><h3>Available: 2</h3></div>
    <div class="card" id="card-occupied"><h3>Occupied: 1</h3></div>
  </div>
  <div class="card" id="actions">
    <div id="booking-list">Loading reservations...</div>
    <button id="export-btn" type="button">Export CSV Data</button>
  </div>
  <script src="app.js"></script>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_gap_a_genuine_greenfield_end_to_end_write_and_readback():
    """Prove the entire execution path for greenfield mission writes real files to a disposable workspace."""
    # 1. Unique disposable test directory OUTSIDE the HERMES repository
    test_id = uuid.uuid4().hex[:8]
    base_tmp = Path(tempfile.gettempdir())
    disposable_ws = base_tmp / f"hermes_e2e_greenfield_{test_id}"

    # Inspect before use
    assert not disposable_ws.exists(), f"Disposable workspace {disposable_ws} must not pre-exist"
    disposable_ws.mkdir(parents=True)

    # Pre-populate HERMES-managed metadata to prove it does not confuse the classifier
    (disposable_ws / ".artifacts").mkdir()
    (disposable_ws / ".artifacts" / "progress.json").write_text("{}", encoding="utf-8")
    (disposable_ws / ".hermes").mkdir()
    (disposable_ws / ".hermes" / "session.meta").write_text("session_info", encoding="utf-8")

    # 2. Lock real workspace_manager to disposable workspace
    workspace_manager.lock(str(disposable_ws))
    assert workspace_manager.is_locked is True
    assert workspace_manager.root_str == str(disposable_ws)

    # 3. Setup real EventBus and isolated SQLite database
    db_path = disposable_ws / ".hermes" / "runtime_e2e.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)

    mission_id = f"m_greenfield_e2e_{test_id}"
    store = bus.get_or_create_state(mission_id)

    # 4. Mock Orchestrator / Fake Model to simulate deterministic tool execution
    turn_counter = 0

    async def fake_model_turn(system_prompt: str, user_message: str) -> str:
        nonlocal turn_counter
        turn_counter += 1
        if turn_counter == 1:
            # Turn 1: Write style.css
            return json.dumps({
                "tool": "write_file",
                "parameters": {
                    "path": "style.css",
                    "content": STYLE_CSS_CONTENT,
                    "mode": "create",
                },
                "explanation": "Writing CSS stylesheet for LabFlow.",
            })
        elif turn_counter == 2:
            # Turn 2: Write app.js
            return json.dumps({
                "tool": "write_file",
                "parameters": {
                    "path": "app.js",
                    "content": APP_JS_CONTENT,
                    "mode": "create",
                },
                "explanation": "Writing JavaScript client code for LabFlow.",
            })
        elif turn_counter == 3:
            # Turn 3: Write index.html linking style.css and app.js
            return json.dumps({
                "tool": "write_file",
                "parameters": {
                    "path": "index.html",
                    "content": INDEX_HTML_CONTENT,
                    "mode": "create",
                },
                "explanation": "Writing index.html linking stylesheets and scripts.",
            })
        else:
            # Turn 4: Declare completion
            return "I have completed building the LabFlow application. All files (index.html, style.css, and app.js) have been implemented and verified."

    # 5. Instantiate AgentLoop with real ActionExecutor and real tools
    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=workspace_manager,
        event_bus_instance=bus,
        state_store_instance=store,
        config=AgentLoopConfig(max_turns=6),
    )
    loop._generate_model_turn = AsyncMock(side_effect=fake_model_turn)

    bus_events: list[HermesEvent] = []
    bus.subscribe(lambda evt: bus_events.append(evt))

    # 6. Submit the LabFlow greenfield prompt
    mission = Mission(
        mission_id=mission_id,
        run_id=f"run_1_{test_id}",
        attempt_number=1,
        user_prompt=LABFLOW_PROMPT,
        workspace_root=str(disposable_ws),
    )

    # Run the loop
    result = await loop.run(mission)

    # 7. Verification: Preflight did NOT reject the greenfield task
    failed_preflight = [
        e for e in bus_events
        if e.event_type == EventType.MISSION_FAILED and e.payload.get("failure_code") == "EMPTY_WORKSPACE_EXISTING_APPLICATION"
    ]
    assert len(failed_preflight) == 0, "Preflight must classify LabFlow as greenfield creation"

    # 8. Verification: Action and Tool events were emitted for all files
    action_events = [e for e in bus_events if e.event_type == EventType.ACTION_REQUESTED]
    assert len(action_events) >= 3, f"Expected >= 3 ACTION_REQUESTED events, got {len(action_events)}"
    tool_completed_events = [e for e in bus_events if e.event_type == EventType.TOOL_COMPLETED]
    assert len(tool_completed_events) >= 3, f"Expected >= 3 TOOL_COMPLETED events, got {len(tool_completed_events)}"

    # 9. Verification: File on disk exists, is non-empty, and bytes match
    real_index = disposable_ws / "index.html"
    real_css = disposable_ws / "style.css"
    real_js = disposable_ws / "app.js"

    assert real_index.exists(), f"index.html was not written to {disposable_ws}"
    assert real_css.exists(), f"style.css was not written to {disposable_ws}"
    assert real_js.exists(), f"app.js was not written to {disposable_ws}"

    index_bytes = real_index.read_bytes()
    assert len(index_bytes) > 0, "index.html on disk must be non-empty"

    expected_hash = hashlib.sha256(INDEX_HTML_CONTENT.encode("utf-8")).hexdigest()
    actual_hash = hashlib.sha256(index_bytes).hexdigest()
    assert actual_hash == expected_hash, f"SHA-256 hash mismatch: expected {expected_hash}, got {actual_hash}"

    # 10. Verification: Read resulting file back through real registered ReadFileTool
    read_tool = ReadFileTool()
    read_res = read_tool.execute({"path": "index.html"})
    assert read_res.success is True
    assert "LabFlow Dashboard" in read_res.output
    assert "export-btn" in read_res.output

    # 11. Verification: Mission result honestly reflects what occurred
    assert result.success is True
    assert result.status in ("COMPLETE", "COMPLETED")
    assert any("index.html" in f for f in result.files_created)
    assert any("style.css" in f for f in result.files_created)
    assert any("app.js" in f for f in result.files_created)
    print(f"\n[E2E Greenfield Acceptance PASSED]: Files created at {disposable_ws} (index.html={len(index_bytes)}B, style.css={len(real_css.read_bytes())}B, app.js={len(real_js.read_bytes())}B)")


@pytest.mark.asyncio
async def test_gap_a_injected_tool_failure_honestly_reported_as_failure():
    """Prove that an injected tool failure is honestly reported as a failure, not a success."""
    test_id = uuid.uuid4().hex[:8]
    base_tmp = Path(tempfile.gettempdir())
    disposable_ws = base_tmp / f"hermes_e2e_fail_{test_id}"
    disposable_ws.mkdir(parents=True, exist_ok=True)

    workspace_manager.lock(str(disposable_ws))

    db_path = disposable_ws / "test_fail.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    mission_id = f"m_fail_e2e_{test_id}"
    store = bus.get_or_create_state(mission_id)

    # Model attempts illegal path traversal outside workspace
    async def fake_failing_turn(system_prompt: str, user_message: str) -> str:
        return json.dumps({
            "tool": "write_file",
            "parameters": {
                "path": "../../escaped_hack.txt",
                "content": "Malicious payload",
            },
            "explanation": "Attempting path traversal outside workspace.",
        })

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=workspace_manager,
        event_bus_instance=bus,
        state_store_instance=store,
        config=AgentLoopConfig(max_turns=3, max_consecutive_failures=2),
    )
    loop._generate_model_turn = AsyncMock(side_effect=fake_failing_turn)

    events_captured: list[HermesEvent] = []
    bus.subscribe(lambda evt: events_captured.append(evt))

    mission = Mission(
        mission_id=mission_id,
        run_id=f"run_fail_{test_id}",
        attempt_number=1,
        user_prompt="Build application with invalid path",
        workspace_root=str(disposable_ws),
    )

    result = await loop.run(mission)

    # Must be reported as FAILED, never success
    assert result.success is False
    assert result.status == "FAILED"

    # Action denied or failed tool event emitted
    failure_events = [
        e for e in events_captured
        if e.event_type in (EventType.ACTION_DENIED, EventType.TOOL_FAILED, EventType.MISSION_FAILED)
    ]
    assert len(failure_events) > 0, "Tool failure must produce explicit failure events"
    print(f"\n[E2E Honest Failure Reporting PASSED]: Mission status={result.status}, success={result.success}")
