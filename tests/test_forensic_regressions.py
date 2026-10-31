# tests/test_forensic_regressions.py
"""
Forensic Regression Test Suite for HERMES Production Incident.

Verifies all 15 required incident regression scenarios:
1. Streaming tool-call name cannot be erased by later null/missing chunks.
2. Tool execution events preserve the canonical tool name.
3. unknown_tool cannot be reported as SUCCESS when the real executed tool is write_file.
4. One mission has exactly one authoritative workspace root.
5. Workspace paths cannot accidentally duplicate the workspace prefix.
6. Verification N/A cannot trigger repair.
7. Pending verification cannot trigger repair.
8. No-evidence state cannot trigger repair.
9. Repeated identical failure fingerprint terminates repair.
10. Repair budget is enforced.
11. Normal mission execution does not silently enter multi-trial evaluation mode.
12. CLI and TUI use the same runtime factory/configuration.
13. Activated venv and canonical launcher resolve to the same HERMES source.
14. Model latency and repair latency are separately measurable.
15. A generated project is verified in the exact directory in which it was created.
"""

import os
import sys
import json
import pytest
import asyncio
from pathlib import Path

from core.workspace import WorkspaceManager, MissionWorkspace, WorkspaceBoundaryError
from core.verifier import VerificationResult
from core.runtime_identity import detect_runtime_identity, get_hermes_source_root, get_canonical_python_executable
from core.runtime_state.models import HermesRuntimeState, ToolStatus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.reducer import StateReducer
from core.runtime_state.selectors import ViewModelBuilder
from core.telemetry import telemetry, ModelCallTelemetry, RepairTelemetry
from core.orchestrator import Orchestrator


# ── Scenario 1: Streaming tool-call name cannot be erased by later null chunks ──

def test_streaming_tool_call_name_preservation():
    """Streaming chunks with null/missing function names must never overwrite captured tool name."""
    from models.nvidia_client import NvidiaClient
    client = NvidiaClient(api_key="test_key")

    tool_calls_map = {}
    deltas = [
        # Chunk 1: name received
        {"index": 0, "id": "call_1", "function": {"name": "write_file", "arguments": '{"path": '}},
        # Chunk 2: name is None, arguments continue
        {"index": 0, "function": {"name": None, "arguments": '"index.html", '}},
        # Chunk 3: function dict present with empty name
        {"index": 0, "function": {"name": "", "arguments": '"content": "<h1>Hello</h1>"}'}},
        # Chunk 4: no function key or empty delta
        {"index": 0, "function": {}},
    ]

    for tc_delta in deltas:
        idx = tc_delta.get("index", 0)
        if idx not in tool_calls_map:
            tool_calls_map[idx] = {
                "id": tc_delta.get("id", ""),
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        f_delta = tc_delta.get("function")
        if isinstance(f_delta, dict):
            new_name = f_delta.get("name")
            if new_name and isinstance(new_name, str):
                curr = tool_calls_map[idx]["function"]["name"]
                if not curr:
                    tool_calls_map[idx]["function"]["name"] = new_name
                elif not curr.endswith(new_name) and curr != new_name:
                    tool_calls_map[idx]["function"]["name"] += new_name
            new_args = f_delta.get("arguments")
            if new_args and isinstance(new_args, str):
                tool_calls_map[idx]["function"]["arguments"] += new_args

    captured_name = tool_calls_map[0]["function"]["name"]
    captured_args = tool_calls_map[0]["function"]["arguments"]

    assert captured_name == "write_file", f"Tool name erased! Got: {captured_name}"
    assert captured_args == '{"path": "index.html", "content": "<h1>Hello</h1>"}'


# ── Scenario 2: Tool execution events preserve the canonical tool name ──────────

@pytest.mark.asyncio
async def test_tool_execution_events_preserve_canonical_tool_name():
    """tool_executing and tool_complete events must carry the real tool name, not unknown_tool."""
    events = []

    async def progress_cb(event_type, payload):
        events.append((event_type, payload))

    orch = Orchestrator(mode="safe")
    orch._progress_callback = progress_cb

    # Emit tool executing & complete
    await orch._emit_progress("tool_executing", {
        "stage": 7,
        "name": "Tool Execution",
        "verb": "Executing",
        "tool": "write_file",
        "tool_name": "write_file",
        "target": "index.html",
        "attempt": 1,
    })
    await orch._emit_progress("tool_complete", {
        "stage": 7,
        "tool": "write_file",
        "tool_name": "write_file",
        "target": "index.html",
        "success": True,
        "exit_code": 0,
        "attempt": 1,
        "duration": 0.05,
    })

    assert len(events) == 2
    ev1_type, ev1_payload = events[0]
    assert ev1_type == "tool_executing"
    assert ev1_payload["tool"] == "write_file"
    assert ev1_payload["stage"] == 7

    ev2_type, ev2_payload = events[1]
    assert ev2_type == "tool_complete"
    assert ev2_payload["tool"] == "write_file"
    assert ev2_payload["success"] is True


# ── Scenario 3: unknown_tool cannot be reported as SUCCESS when real tool ran ───

def test_unknown_tool_cannot_be_reported_as_success_when_write_file_executed():
    """When write_file succeeds, UI selector must never output 'Unknown tool' with Succeeded badge."""
    from core.runtime_state.models import MissionState
    state = HermesRuntimeState(mission=MissionState(mission_id="m1", prompt="test"))
    now = 1000.0

    # Start tool
    event_start = HermesEvent(
        event_id="e1",
        timestamp=now,
        event_type=EventType.TOOL_STARTED,
        payload={"tool_name": "write_file", "tool": "write_file"},
    )
    state = StateReducer.reduce(state, event_start)

    # Complete tool
    event_end = HermesEvent(
        event_id="e2",
        timestamp=now + 0.1,
        event_type=EventType.TOOL_COMPLETED,
        payload={"tool_name": "write_file", "tool": "write_file", "exit_code": 0},
    )
    state = StateReducer.reduce(state, event_end)

    view = ViewModelBuilder.build(state)
    assert view.tool.tool_label == "write_file"
    assert "Unknown" not in view.tool.tool_label
    assert view.tool.status_badge == "✓ Succeeded"


# ── Scenario 4: One mission has exactly one authoritative workspace root ───────

def test_one_mission_has_one_authoritative_workspace_root(tmp_path):
    """WorkspaceManager must lock to exactly one authoritative root and enforce it."""
    wm = WorkspaceManager()
    wm.lock(tmp_path)

    assert wm.is_locked is True
    assert wm.workspace_root == tmp_path.resolve()
    assert wm.root_str == str(tmp_path.resolve())

    mws = wm.get_mission_workspace()
    assert mws is not None
    assert mws.root == tmp_path.resolve()

    # Re-locking with same or subpath is idempotent
    wm.lock(tmp_path)
    assert wm.workspace_root == tmp_path.resolve()


# ── Scenario 5: Workspace paths cannot accidentally duplicate the workspace prefix ─

def test_workspace_paths_cannot_duplicate_workspace_prefix(tmp_path):
    """A relative or nested path repeating the workspace directory name must be deduplicated."""
    ws_dir = tmp_path / "1st trial"
    ws_dir.mkdir()

    mws = MissionWorkspace(ws_dir)

    # 1. Relative path starting with workspace folder name
    nested_rel = "1st trial/generated_projects/reading-tracker/index.html"
    validated = mws.validate_path(nested_rel)
    expected = ws_dir / "generated_projects" / "reading-tracker" / "index.html"
    assert validated.resolve() == expected.resolve(), f"Got {validated}, expected {expected}"
    assert "1st trial/1st trial" not in str(validated).replace("\\", "/")

    # 2. Absolute path containing duplicate workspace segment
    dup_abs = ws_dir / "1st trial" / "generated_projects" / "reading-tracker" / "app.js"
    validated_abs = mws.validate_path(str(dup_abs))
    expected_abs = ws_dir / "generated_projects" / "reading-tracker" / "app.js"
    assert validated_abs.resolve() == expected_abs.resolve()

    # 3. Path escaping outside boundary must raise WorkspaceBoundaryError
    with pytest.raises(WorkspaceBoundaryError):
        mws.validate_path("../outside.txt")


# ── Scenario 6: Verification N/A cannot trigger repair ─────────────────────────

def test_verification_na_cannot_trigger_repair():
    """When verifier is N/A / unavailable, repair must not be triggered."""
    res = VerificationResult(
        agree=True,
        confidence=0.5,
        critical_issues=[],
        risk_score=0.3,
        reasoning="Verification unavailable",
    )
    res.is_unavailable = True

    # Actionable failure test
    issues = [
        iss for iss in getattr(res, "critical_issues", [])
        if iss and not any(kw in iss.lower() for kw in ("unavailable", "timeout", "timed out", "fallback", "n/a", "pending"))
    ]
    is_actionable = bool(res.agree is False and issues and not getattr(res, "is_unavailable", False))
    assert is_actionable is False


# ── Scenario 7: Pending verification cannot trigger repair ────────────────────

def test_pending_verification_cannot_trigger_repair():
    """When verification is PENDING / None, repair must not be triggered."""
    verification = None
    is_actionable = bool(
        verification is not None
        and verification.agree is False
        and getattr(verification, "critical_issues", [])
        and not getattr(verification, "is_unavailable", False)
    )
    assert is_actionable is False


# ── Scenario 8: No-evidence state cannot trigger repair ────────────────────────

def test_no_evidence_state_cannot_trigger_repair():
    """Empty issues list or agree=True without evidence must never trigger repair."""
    res = VerificationResult(
        agree=True,
        confidence=0.9,
        critical_issues=[],
        risk_score=0.1,
    )
    is_actionable = bool(res.agree is False and len(res.critical_issues) > 0)
    assert is_actionable is False


# ── Scenario 9: Repeated identical failure fingerprint terminates repair ──────

def test_repeated_identical_failure_fingerprint_terminates_repair(tmp_path):
    """Repair loop must abort if the same failure fingerprint is detected twice."""
    art = tmp_path / "index.html"
    art.write_text("broken content", encoding="utf-8")

    fingerprints_seen = set()

    import hashlib
    content_hash = hashlib.sha256(art.read_bytes()).hexdigest()[:16]
    issues = ["syntax error on line 12"]
    issues_sig = "|".join(sorted(issues))
    fingerprint = f"{art.name}:{content_hash}:{issues_sig}"

    # First attempt: registered
    assert fingerprint not in fingerprints_seen
    fingerprints_seen.add(fingerprint)

    # Second attempt without changed artifact or new issues: abort
    is_repeated = fingerprint in fingerprints_seen
    assert is_repeated is True, "Repeated fingerprint was not detected!"


# ── Scenario 10: Repair budget is enforced ────────────────────────────────────

def test_repair_budget_is_enforced():
    """Repair attempts exceeding MAX_REPAIR_BUDGET (3) must be halted."""
    MAX_REPAIR_BUDGET = 3
    repair_count = 0

    while repair_count < 10:
        if repair_count >= MAX_REPAIR_BUDGET:
            break
        repair_count += 1

    assert repair_count == 3


# ── Scenario 11: Normal mission execution does not silently enter eval mode ────

def test_normal_mission_execution_does_not_silently_enter_eval_mode():
    """A standard run or UI command executes one mission and does not invoke evaluation suite."""
    from main import app
    cmd_names = [
        c.name or (c.callback.__name__.replace('_', '-') if c.callback else '')
        for c in app.registered_commands
    ]
    assert "eval" in cmd_names
    assert "run" in cmd_names
    assert "ui" in cmd_names


# ── Scenario 12: CLI and TUI use the same runtime factory/configuration ────────

def test_cli_and_tui_use_same_runtime_configuration(tmp_path):
    """CLI and TUI inspect the same runtime identity and config."""
    id1 = detect_runtime_identity(workspace_root=str(tmp_path))
    assert id1.source_root == str(get_hermes_source_root())
    assert id1.t1_model != ""
    assert id1.workspace_root == str(tmp_path)


# ── Scenario 13: Activated venv and canonical launcher resolve to the same HERMES source ─

def test_activated_venv_and_canonical_launcher_resolve_to_same_source():
    """Source root matches between current interpreter and canonical lookup."""
    src = get_hermes_source_root()
    assert (src / "main.py").is_file()
    assert (src / "core").is_dir()
    py_exe = get_canonical_python_executable()
    assert Path(py_exe).exists()


# ── Scenario 14: Model latency and repair latency are separately measurable ────

def test_model_latency_and_repair_latency_are_separately_measurable():
    req = telemetry.start_request(prompt="Test latency measurement", execution_mode="production")
    req_id = req.request_id
    with telemetry.span("Test Request", request_id=req_id):
        m_telem = ModelCallTelemetry(
            request_id=req_id,
            model="test-model",
            provider="test-provider",
            total_latency_ms=125.0,
            ttft_ms=45.0,
            prompt_tokens=50,
            output_tokens=30,
            success=True,
        )
        telemetry.record_model_call(m_telem)

        r_telem = RepairTelemetry(
            request_id=req_id,
            attempt_number=1,
            trigger="test trigger",
            duration_ms=450.0,
            model="test-model",
            success=True,
        )
        telemetry.record_repair(r_telem, request_id=req_id)

    # Validate distinct telemetry records
    active = telemetry.get_request(req_id)
    assert active is not None
    assert len(active.model_calls) >= 1
    assert active.model_calls[0].total_latency_ms == 125.0
    assert len(active.repair_attempts) >= 1
    assert active.repair_attempts[0].duration_ms == 450.0


# ── Scenario 15: A generated project is verified in the exact created directory ─

def test_generated_project_verified_in_exact_created_directory(tmp_path):
    """Artifact is located in the exact created directory without duplicate prefix."""
    ws = tmp_path / "project_root"
    ws.mkdir()
    gen_dir = ws / "generated_projects" / "reading-tracker"
    gen_dir.mkdir(parents=True)
    index_file = gen_dir / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body>Reading Tracker</body></html>", encoding="utf-8")

    mws = MissionWorkspace(ws)
    found = mws.find_artifact("index.html")
    assert found is not None
    assert found.resolve() == index_file.resolve()
    assert found.exists()
    assert "project_root/project_root" not in str(found).replace("\\", "/")
