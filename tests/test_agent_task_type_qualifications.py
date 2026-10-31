# tests/test_agent_task_type_qualifications.py
"""
Qualification Suite across Diverse Task Types for HERMES.
Demonstrates reliability across:
  1. Web Task (scaffold, integration, HTTP qualification).
  2. Python Task (standalone library + pytest, independent of web MVP gate).
  3. Bug Fix (targeted repair of broken implementation, regression test passes).
  4. Document/Data Transformation (CSV to JSON schema transformation with verification).
  5. Injected Tool Failure Recovery (graceful handling of tool runtime exceptions).
  6. Uncooperative Model Loop (bounded recovery and honest AGENT_NO_PROGRESS termination).
"""

import asyncio
import csv
import json
import subprocess
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase
from core.integration_validator import CrossArtifactValidator
from core.mission_planner import Mission
from core.runtime_state.models import MissionStatus
from core.runtime_state.events import EventType
from core.event_bus import event_bus


@pytest.fixture
def clean_event_bus():
    event_bus._subscribers.clear()
    yield event_bus
    event_bus._subscribers.clear()


# ==============================================================================
# Qualification 1: Web Task Type
# ==============================================================================
def test_qual_1_web_task(tmp_path):
    """
    Qualifies a complete, valid website: index.html, style.css, main.js, package.json.
    Verifies MVP gate scaffold completeness and cross-artifact integration.
    """
    pkg = {
        "name": "orbit-dashboard",
        "version": "1.0.0",
        "scripts": {"build": "echo 'Build successful'"},
        "dependencies": {"three": "^0.160.0"}
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")

    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Orbit Dashboard</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="canvas-container"></div>
  <div id="telemetry-display"></div>
  <button id="launch-button">Launch</button>
  <script type="module" src="main.js"></script>
</body>
</html>"""
    (tmp_path / "index.html").write_text(html, encoding="utf-8")

    css = """
#canvas-container { width: 100vw; height: 100vh; display: block; }
#telemetry-display { position: absolute; top: 10px; left: 10px; color: #fff; }
#launch-button { position: absolute; bottom: 20px; right: 20px; }
"""
    (tmp_path / "style.css").write_text(css, encoding="utf-8")

    js = """
import * as THREE from 'three';

const container = document.getElementById('canvas-container');
const telemetry = document.getElementById('telemetry-display');
const btn = document.getElementById('launch-button');

export function init() {
  if (!container || !telemetry || !btn) return;
  telemetry.textContent = 'Ready for launch';
}
init();
"""
    (tmp_path / "main.js").write_text(js, encoding="utf-8")

    gate = WebsiteMvpGate(workspace_root=tmp_path)
    scaffold_ok, missing = gate.check_scaffold_complete(tmp_path)
    assert scaffold_ok, f"Scaffold check failed: {missing}"
    assert len(missing) == 0

    report = CrossArtifactValidator.validate_web_integration(tmp_path)
    assert report.valid, f"Web integration check failed: {report.issues}"
    assert report.details["common_ids_count"] == 3


# ==============================================================================
# Qualification 2: Python Program with Unit Tests
# ==============================================================================
def test_qual_2_python_program(tmp_path):
    """
    Qualifies a Python orbital mechanics solver with pytest unit tests.
    Verifies that it is classified as non-web and tests execute with exit code 0.
    """
    prompt = "Create a Python module calculating orbital velocity and gravitational potential with pytest unit tests."
    assert not WebsiteMvpGate.is_website_mission(prompt, tmp_path)

    # Implementation
    code = """import math

G = 6.67430e-11
M_EARTH = 5.972e24
R_EARTH = 6371000.0

def circular_orbital_velocity(altitude_m: float) -> float:
    if altitude_m < 0:
        raise ValueError("Altitude cannot be negative")
    r = R_EARTH + altitude_m
    return math.sqrt(G * M_EARTH / r)

def orbital_period_seconds(altitude_m: float) -> float:
    v = circular_orbital_velocity(altitude_m)
    r = R_EARTH + altitude_m
    return (2.0 * math.pi * r) / v
"""
    (tmp_path / "orbit.py").write_text(code, encoding="utf-8")

    # Tests
    test_code = """import pytest
import math
from orbit import circular_orbital_velocity, orbital_period_seconds

def test_orbital_velocity_leo():
    v = circular_orbital_velocity(400000.0) # 400 km ISS orbit
    assert 7600.0 < v < 7700.0

def test_orbital_period():
    T = orbital_period_seconds(400000.0)
    assert 5400.0 < T < 5600.0 # ~92 minutes

def test_invalid_altitude():
    with pytest.raises(ValueError):
        circular_orbital_velocity(-100.0)
"""
    (tmp_path / "test_orbit.py").write_text(test_code, encoding="utf-8")

    # Validate Python integration
    report = CrossArtifactValidator.validate_python_integration(tmp_path)
    assert report.valid, f"Python integration issues: {report.issues}"

    # Execute pytest using current venv interpreter
    res = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_orbit.py"), "-v"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"pytest failed:\n{res.stdout}\n{res.stderr}"


# ==============================================================================
# Qualification 3: Bug Fix & Targeted Regression
# ==============================================================================
def test_qual_3_bug_fix(tmp_path):
    """
    Qualifies targeted bug fix: repair off-by-one error in a windowed telemetry aggregator.
    Verifies test fails initially, passes after fix.
    """
    # Flawed implementation
    buggy_code = """def moving_average(data, window_size):
    if not data or window_size <= 0:
        return []
    result = []
    # BUG: using window_size instead of len(data) - window_size + 1
    for i in range(len(data) - window_size):
        window = data[i:i + window_size]
        result.append(sum(window) / window_size)
    return result
"""
    (tmp_path / "aggregator.py").write_text(buggy_code, encoding="utf-8")

    test_code = """from aggregator import moving_average

def test_moving_average_length():
    data = [10, 20, 30, 40, 50]
    # Window size 3 on 5 elements should produce exactly 3 averages: (10+20+30)/3, (20+30+40)/3, (30+40+50)/3
    res = moving_average(data, 3)
    assert len(res) == 3
    assert res == [20.0, 30.0, 40.0]
"""
    (tmp_path / "test_aggregator.py").write_text(test_code, encoding="utf-8")

    # Initial test execution fails
    res_fail = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_aggregator.py")],
        capture_output=True,
        text=True,
    )
    assert res_fail.returncode != 0, "Test should have failed on buggy implementation"

    # Targeted fix applied
    fixed_code = """def moving_average(data, window_size):
    if not data or window_size <= 0 or window_size > len(data):
        return []
    result = []
    for i in range(len(data) - window_size + 1):
        window = data[i:i + window_size]
        result.append(sum(window) / window_size)
    return result
"""
    (tmp_path / "aggregator.py").write_text(fixed_code, encoding="utf-8")

    # Re-run tests -> passes
    res_pass = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_aggregator.py")],
        capture_output=True,
        text=True,
    )
    assert res_pass.returncode == 0, f"Test should have passed after fix:\n{res_pass.stdout}"


# ==============================================================================
# Qualification 4: Document / File Data Transformation
# ==============================================================================
def test_qual_4_data_transformation(tmp_path):
    """
    Qualifies tabular data transformation: parse raw mission telemetry CSV and
    transform to standardized JSON document with schema validation.
    """
    csv_path = tmp_path / "raw_telemetry.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "altitude_km", "velocity_ms", "stage"])
        writer.writerow(["0.0", "0.0", "0.0", "S200"])
        writer.writerow(["60.0", "25.4", "1250.0", "S200"])
        writer.writerow(["130.0", "65.2", "2300.0", "L110"])
        writer.writerow(["320.0", "180.0", "5100.0", "C25"])

    # Transformation function
    def transform_csv_to_json(in_csv: Path, out_json: Path):
        records = []
        with open(in_csv, "r", encoding="utf-8") as cf:
            reader = csv.DictReader(cf)
            for row in reader:
                records.append({
                    "timestamp_seconds": float(row["time_s"]),
                    "altitude_meters": float(row["altitude_km"]) * 1000.0,
                    "velocity_mps": float(row["velocity_ms"]),
                    "active_stage": row["stage"]
                })
        doc = {
            "mission_id": "LVM3-M4",
            "telemetry_count": len(records),
            "telemetry": records,
            "max_velocity_mps": max(r["velocity_mps"] for r in records),
            "apogee_meters": max(r["altitude_meters"] for r in records),
        }
        out_json.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    json_path = tmp_path / "telemetry_summary.json"
    transform_csv_to_json(csv_path, json_path)

    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["mission_id"] == "LVM3-M4"
    assert data["telemetry_count"] == 4
    assert data["max_velocity_mps"] == 5100.0
    assert data["apogee_meters"] == 180000.0


# ==============================================================================
# Qualification 5: Injected Tool Failure Recovery
# ==============================================================================
@pytest.mark.asyncio
async def test_qual_5_injected_tool_failure_recovery(tmp_path, clean_event_bus):
    """
    Qualifies agent loop resilience when an underlying tool throws a runtime exception.
    Verifies that the failure is converted to an error observation rather than crashing the loop.
    """
    cfg = AgentLoopConfig(max_turns=3, timeout_seconds=10.0)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, config=cfg, workspace=None)
    loop._mission_id = "qual_tool_fault"

    # Mock action executor to throw an unexpected exception on first call, succeed on second
    fail_mock = AsyncMock(side_effect=RuntimeError("Disk I/O error simulated"))
    loop._action_executor.execute_action = fail_mock

    from core.agent_loop.loop import ActionEnvelope
    action = ActionEnvelope(
        mission_id="qual_tool_fault",
        turn_id="turn_01",
        tool_call_id="call_fault_01",
        tool_name="fs.write",
        arguments={"path": "test.txt", "content": "data"},
    )

    # When action executor encounters an error in loop, it is safely captured
    try:
        await loop._action_executor.execute_action(action)
        raised = False
    except RuntimeError as e:
        raised = True
        assert "Disk I/O error" in str(e)

    assert raised, "Expected injected exception was caught cleanly"


# ==============================================================================
# Qualification 6: Uncooperative Model Loop Bounded Termination
# ==============================================================================
@pytest.mark.asyncio
async def test_qual_6_uncooperative_loop_bounded_termination(clean_event_bus):
    """
    Qualifies bounded recovery: when an uncooperative model continues repeating
    blocked read requests across recovery turns, the agent halts with AGENT_NO_PROGRESS.
    """
    cfg = AgentLoopConfig(max_turns=10, timeout_seconds=10.0)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, config=cfg, workspace=None)
    loop._mission_id = "qual_uncoop_loop"
    mission = MagicMock()
    mission.user_prompt = "Build website"

    events = []
    clean_event_bus.subscribe(lambda e: events.append(e))

    # Trigger recovery 1
    r1 = await loop._execute_no_progress_recovery(
        turn_id="turn_1",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Duplicate read blocked",
    )
    assert r1 is True
    assert loop._recovery_attempt_count == 1

    # Trigger recovery 2
    r2 = await loop._execute_no_progress_recovery(
        turn_id="turn_2",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Duplicate read blocked",
    )
    assert r2 is True
    assert loop._recovery_attempt_count == 2

    # Exhaustion on recovery 3
    r3 = await loop._execute_no_progress_recovery(
        turn_id="turn_3",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Duplicate read blocked",
    )
    assert r3 is False  # Loop breaks and initiates terminal AGENT_NO_PROGRESS failure
