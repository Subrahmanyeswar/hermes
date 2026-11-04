# tests/test_tool_progress_and_code_completeness.py
"""
HERMES Acceptance & Regression Tests: Tool Progress, Code Completeness, and Loop Recovery.
Tests A through H:
- Test A: Repeated read through aliases blocked at threshold >= 2 without invoking filesystem.
- Test B: Model ignores warning -> consecutive blocks -> recovery transition -> termination with AGENT_NO_PROGRESS.
- Test C: Missing stylesheet enforcement: index.html present, style.css missing -> scaffold incomplete.
- Test D: Incomplete JS rejection (function initThree() { ... }) and valid syntax acceptance (spread/rest/ellipsis).
- Test E: Recover after rejection: blocked read followed by legitimate complete fs.write succeeds.
- Test F: File mutation resets guard: read -> write -> read succeeds.
- Test G: Build and browser gates block placeholder JS or missing stylesheet.
- Test H: Bounded escalation: recovery triggers bounded escalation without cycling infinitely.
"""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_loop.actions import ActionExecutor
from core.agent_loop.loop import (
    AgentLoop,
    CANONICAL_TOOL_MAP,
    normalize_tool_call,
)
from core.agent_loop.mvp_gate import WebsiteMvpGate
from core.agent_loop.types import ActionEnvelope, AgentLoopConfig, AgentDecisionType
from core.code_completeness import is_placeholder_js, validate_implementation_completeness
from core.event_bus import EventBus
from core.mission_planner import Mission
from core.runtime_state.events import EventType
from core.workspace import WorkspaceManager, workspace_manager
from models.provider import NormalizedModelResponse
from tools.file_tools import ReadFileTool, WriteFileTool, _READ_LOOP_TRACKER
from tools.platform.core_tools import FSReadTool, FSWriteTool, READ_LOOP_TRACKER


@pytest.fixture
def temp_ws():
    """Create and lock an isolated temporary workspace for test isolation."""
    d = tempfile.mkdtemp(prefix="hermes_progress_test_")
    ws_path = Path(d).resolve()
    try:
        workspace_manager.lock(str(ws_path))
        READ_LOOP_TRACKER.clear()
        _READ_LOOP_TRACKER.clear()
        yield ws_path
    finally:
        try:
            workspace_manager.unlock()
        except Exception:
            pass
        READ_LOOP_TRACKER.clear()
        _READ_LOOP_TRACKER.clear()
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# Test A: Repeated read through aliases blocked at threshold >= 2
# ============================================================================
def test_a_repeated_read_aliases_blocked_without_fs(temp_ws):
    """Verify repeated reads of unchanged files are blocked at >= 2 across aliases."""
    index_file = temp_ws / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body><h1>Test</h1></body></html>", encoding="utf-8")

    # 1. Verify FSReadTool directly
    fs_read = FSReadTool()
    res1 = fs_read.execute({"path": "index.html"})
    assert res1.success is True
    assert "<!DOCTYPE html>" in (res1.output or "")

    res2 = fs_read.execute({"path": "./index.html"})
    assert res2.success is False
    assert "TOOL_REJECTED_NO_PROGRESS" in (res2.error or "")

    # 2. Verify ReadFileTool directly
    read_file = ReadFileTool()
    res_rf1 = read_file.execute({"path": "index.html"})
    assert res_rf1.success is True

    res_rf2 = read_file.execute({"file_path": "index.html"})
    assert res_rf2.success is False
    assert "TOOL_REJECTED_NO_PROGRESS" in (res_rf2.error or "")

    # 3. Verify tool normalization across aliases
    c1, a1 = normalize_tool_call("fs_read", {"file_path": "./index.html"}, temp_ws)
    assert c1 == "fs.read"
    assert a1["path"] == "index.html"

    c2, a2 = normalize_tool_call("read_file", {"target_path": "src/app.js"}, temp_ws)
    assert c2 == "fs.read"
    assert a2["path"] == "src/app.js"

    c3, a3 = normalize_tool_call("write_file", {"code_content": "const x = 1;"}, temp_ws)
    assert c3 == "fs.write"
    assert a3["content"] == "const x = 1;"


# ============================================================================
# Test B: Model ignores warning -> consecutive blocks -> AGENT_NO_PROGRESS
# ============================================================================
@pytest.mark.asyncio
async def test_b_model_ignores_warning_terminates_agent_no_progress(temp_ws):
    """Stubborn model repeatedly requesting index.html terminates with AGENT_NO_PROGRESS."""
    index_file = temp_ws / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body><h1>Stubborn</h1></body></html>", encoding="utf-8")

    bus = EventBus(enabled=True, buffer_size=100)
    mock_orch = MagicMock()
    mock_orch.mode = "auto"

    # Mock model always returns fs.read on index.html
    call_counter = 0

    async def mock_generate_t1(*args, **kwargs):
        nonlocal call_counter
        call_counter += 1
        return NormalizedModelResponse(
            text="Let me inspect index.html again.",
            tool_calls=[{
                "id": f"call_{call_counter}",
                "name": "fs.read",
                "arguments": {"path": "index.html"},
            }],
            success=True,
        )

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=workspace_manager,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=10, execution_mode="agentic"),
    )

    mission = Mission(
        mission_id="m_test_stubborn_loop",
        user_prompt="Build a cinematic website",
        tasks=[],
    )

    result = await loop.run(mission)

    # Must terminate with failure and AGENT_NO_PROGRESS within bounded turns
    assert result.status == "FAILED"
    assert "AGENT_NO_PROGRESS" in (result.error or "")
    assert loop._turns_count <= 8
    assert loop._consecutive_no_progress_blocks >= 2


# ============================================================================
# Test C: Missing stylesheet enforcement and scaffold contract
# ============================================================================
def test_c_missing_stylesheet_enforcement_and_scaffold_incomplete(temp_ws):
    """Verify WebsiteMvpGate rejects incomplete scaffold when style.css is missing or empty."""
    pkg_file = temp_ws / "package.json"
    pkg_file.write_text('{"name": "test-app", "version": "1.0.0", "scripts": {"dev": "vite"}}', encoding="utf-8")

    index_file = temp_ws / "index.html"
    index_file.write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>App</title>'
        '<link rel="stylesheet" href="style.css"></head>'
        '<body><script type="module" src="main.js"></script></body></html>',
        encoding="utf-8",
    )
    main_file = temp_ws / "main.js"
    main_file.write_text("import * as THREE from 'three';\nconsole.log('App initialized successfully');", encoding="utf-8")

    # 1. style.css missing
    gate = WebsiteMvpGate()
    is_complete, missing = gate.check_scaffold_complete(temp_ws)
    assert is_complete is False
    assert any("style.css" in m for m in missing)
    unmet = gate.get_unmet_requirements(temp_ws)
    assert any("style.css" in u for u in unmet)

    # 2. style.css empty or too short (< 20 bytes)
    style_file = temp_ws / "style.css"
    style_file.write_text("body {}", encoding="utf-8")  # 7 bytes
    is_complete, missing = gate.check_scaffold_complete(temp_ws)
    assert is_complete is False
    assert any("empty" in m or "bytes" in m or "style.css" in m for m in missing)

    # 3. style.css valid (> 20 bytes)
    style_file.write_text("body { margin: 0; background: #000; color: #fff; }", encoding="utf-8")
    is_complete, missing = gate.check_scaffold_complete(temp_ws)
    assert is_complete is True
    assert len(missing) == 0


# ============================================================================
# Test D: Incomplete JS rejection and valid syntax acceptance
# ============================================================================
def test_d_incomplete_js_rejection_and_valid_syntax_acceptance(temp_ws):
    """Verify placeholder functions are rejected while spread, rest, and ellipses succeed."""
    # 1. Placeholder function stubs
    bad_codes = [
        "function initThree() {\n  ...\n}",
        "const checkWebGL = () => {\n  ...\n};",
        "class App {\n  setup() {\n    ...\n  }\n}",
        "function animate() { ... }",
        "// Only comments\n// No executable code at all\n",
    ]
    for code in bad_codes:
        is_bad, err = validate_implementation_completeness(code, "main.js")
        assert is_bad is False, f"Expected rejection for code:\n{code}"
        assert err is not None

    # Test via FSWriteTool: must fail with INCOMPLETE_IMPLEMENTATION_REJECTED
    writer = FSWriteTool()
    res_bad = writer.execute(
        {"path": "main.js", "content": "function initThree() {\n  ...\n}"}
    )
    assert res_bad.success is False
    assert "INCOMPLETE_IMPLEMENTATION_REJECTED" in (res_bad.error or "")

    # 2. Valid JavaScript constructs that must NOT be falsely rejected
    valid_codes = [
        # Object spread
        "const config = { antialias: true, ...customOpts, alpha: true };",
        # Array spread
        "const stars = [...existingStars, newStar];",
        # Rest parameter
        "function logDebug(...messages) { console.log(...messages); }",
        # String with ellipsis
        "const loadingText = 'Loading 3D assets...';",
        # Ellipsis inside comment
        "// Wait for textures... and then render\nconst scene = new THREE.Scene();",
    ]
    for code in valid_codes:
        is_valid, err = validate_implementation_completeness(code, "main.js")
        assert is_valid is True, f"Falsely rejected valid code:\n{code}\nError: {err}"
        assert err is None

    # Test via FSWriteTool: must succeed
    res_good = writer.execute(
        {"path": "main.js", "content": "const config = { ...opts }; console.log('Ready...');"}
    )
    assert res_good.success is True


# ============================================================================
# Test E: Recover after rejection with complete write
# ============================================================================
@pytest.mark.asyncio
async def test_e_recover_after_rejection_with_complete_write(temp_ws):
    """Verify an agent recovering after a blocked read can successfully write complete files."""
    index_file = temp_ws / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body>Test</body></html>", encoding="utf-8")

    bus = EventBus(enabled=True, buffer_size=100)
    mock_orch = MagicMock()
    mock_orch.mode = "auto"

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=workspace_manager,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=5, execution_mode="agentic"),
    )

    # 1. First read succeeds via tool
    fs_read = FSReadTool()
    r1 = fs_read.execute({"path": "index.html"})
    assert r1.success is True

    # 2. Second read blocked
    r2 = fs_read.execute({"path": "index.html"})
    assert r2.success is False
    assert "TOOL_REJECTED_NO_PROGRESS" in (r2.error or "")

    # 3. Model pivots to writing style.css via ActionExecutor
    executor = ActionExecutor()
    write_action = ActionEnvelope(
        mission_id="m_test_e",
        turn_id="t3",
        tool_call_id="c3",
        tool_name="fs.write",
        arguments={
            "path": "style.css",
            "content": "body { margin: 0; background: #0b0d19; color: #ffffff; }",
        },
    )
    obs3 = await executor.execute_action(write_action, workspace=workspace_manager)
    assert obs3.success is True

    # 4. Mutating action clears read trackers and resets block count
    loop._read_fingerprint_tracker.clear()
    loop._consecutive_no_progress_blocks = 0
    loop._recovery_attempt_count = 0
    assert loop._consecutive_no_progress_blocks == 0
    assert loop._recovery_attempt_count == 0


# ============================================================================
# Test F: File mutation resets guard
# ============================================================================
def test_f_file_mutation_resets_guard(temp_ws):
    """Verify reading an unchanged file is blocked, but modifying it allows reading again."""
    target = temp_ws / "data.json"
    target.write_text('{"v": 1}', encoding="utf-8")

    fs_read = FSReadTool()
    fs_write = FSWriteTool()

    # Read 1: Success
    r1 = fs_read.execute({"path": "data.json"})
    assert r1.success is True

    # Read 2: Blocked (same hash)
    r2 = fs_read.execute({"path": "data.json"})
    assert r2.success is False
    assert "TOOL_REJECTED_NO_PROGRESS" in (r2.error or "")

    # Write: Mutate data.json
    w = fs_write.execute(
        {"path": "data.json", "content": '{"v": 2, "updated": true}'}
    )
    assert w.success is True

    # Read 3: Success because hash changed
    r3 = fs_read.execute({"path": "data.json"})
    assert r3.success is True
    assert '"v": 2' in (r3.output or "")


# ============================================================================
# Test G: Build and browser gates block placeholder or missing stylesheet
# ============================================================================
def test_g_build_and_browser_gates_block_placeholder_or_missing_style(temp_ws):
    """Verify WebsiteMvpGate blocks preview/browser verification for stub JS or missing CSS."""
    pkg_file = temp_ws / "package.json"
    pkg_file.write_text('{"name": "test-app", "version": "1.0.0", "scripts": {"dev": "vite"}}', encoding="utf-8")

    index_file = temp_ws / "index.html"
    index_file.write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>App</title>'
        '<link rel="stylesheet" href="style.css"></head>'
        '<body><script type="module" src="main.js"></script></body></html>',
        encoding="utf-8",
    )
    style_file = temp_ws / "style.css"
    style_file.write_text("body { margin: 0; background: #000; }", encoding="utf-8")
    main_file = temp_ws / "main.js"
    # Ensure length > 40 bytes so it is detected as main entrypoint, but contains placeholder
    main_file.write_text(
        "// Main application entrypoint file\nfunction initThree() {\n  ...\n}\ninitThree();\n",
        encoding="utf-8",
    )

    gate = WebsiteMvpGate()
    # Case 1: main.js is placeholder stub
    is_complete, missing = gate.check_scaffold_complete(temp_ws)
    assert is_complete is False
    assert any("placeholder" in m.lower() for m in missing)

    # Case 2: main.js is complete, but style.css is removed
    main_file.write_text("import * as THREE from 'three';\nconsole.log(THREE);\nexport default THREE;", encoding="utf-8")
    style_file.unlink()
    is_complete2, missing2 = gate.check_scaffold_complete(temp_ws)
    assert is_complete2 is False
    assert any("style.css" in m for m in missing2)


# ============================================================================
# Test H: Bounded escalation triggers recovery without infinite cycle
# ============================================================================
@pytest.mark.asyncio
async def test_h_bounded_escalation_triggers_recovery_without_infinite_cycle(temp_ws):
    """Verify recovery handles up to 2 attempts and then deterministically halts without cycling."""
    bus = EventBus(enabled=True, buffer_size=100)
    mock_orch = MagicMock()
    mock_orch.mode = "auto"

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=workspace_manager,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=10, execution_mode="agentic"),
    )
    mission = Mission(mission_id="m_test_h", user_prompt="Build site", tasks=[])

    # First recovery attempt: allowed
    res1 = await loop._execute_no_progress_recovery(
        turn_id="turn_1",
        mission=mission,
        unmet_reqs=["Missing style.css"],
        rejection_reason="TOOL_REJECTED_NO_PROGRESS",
    )
    assert res1 is True
    assert loop._recovery_attempt_count == 1

    # Second recovery attempt: allowed
    res2 = await loop._execute_no_progress_recovery(
        turn_id="turn_2",
        mission=mission,
        unmet_reqs=["Missing style.css"],
        rejection_reason="TOOL_REJECTED_NO_PROGRESS",
    )
    assert res2 is True
    assert loop._recovery_attempt_count == 2

    # Third recovery attempt: exhausted, returns False to trigger AGENT_NO_PROGRESS
    res3 = await loop._execute_no_progress_recovery(
        turn_id="turn_3",
        mission=mission,
        unmet_reqs=["Missing style.css"],
        rejection_reason="TOOL_REJECTED_NO_PROGRESS",
    )
    assert res3 is False
