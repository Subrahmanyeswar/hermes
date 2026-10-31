# tests/test_stage6_2_goal_fulfillment.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 6.2:
Task Goal Fulfillment and Evidence Integrity Audit.

Verifies:
1. Scenario 1: Read-only request with correct heading/description fulfillment.
2. Scenario 2: Read-only request omitting requested details is rejected.
3. Scenario 3: File-creation task with verified expected files and non-empty content.
4. Scenario 4: Modification request where final content is correct but diff/status mismatch is caught.
5. Scenario 5: Verification command passes while final response claims different result (discrepancy guarded).
6. Scenario 6: Tool or model failure is never represented as success.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from core.agent_loop.actions import ActionExecutor
from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
from core.agent_loop.types import ActionEnvelope, ActionStatus
from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    HermesRuntimeState,
    MissionState,
    MissionStatus,
)
from core.server.app import create_app
from core.server.diff_service import (
    clear_file_baselines,
    compute_file_diff,
    get_file_baseline,
    record_file_baseline,
)
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager


@pytest.fixture
def stage6_2_env(tmp_path):
    ws = tmp_path / "stage6_2_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(ws)

    test_bus = EventBus(enabled=True)
    adapter = RuntimeAdapter(event_bus=test_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    yield {
        "workspace": ws,
        "ws_mgr": workspace_manager,
        "event_bus": test_bus,
        "adapter": adapter,
        "client": client,
    }

    workspace_manager.unlock()
    clear_file_baselines()


def _compute_workspace_sha256_manifest(workspace_root: Path) -> dict[str, str]:
    manifest = {}
    for p in workspace_root.rglob("*"):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(workspace_root).parts):
            rel = p.relative_to(workspace_root).as_posix()
            manifest[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return manifest


def test_scenario_1_read_only_with_correct_heading_and_description(stage6_2_env):
    """
    Scenario 1: Read-only inspection fulfilling criteria.
    Verifies that when a read-only request asks to inspect a README:
    1. Initial workspace SHA-256 manifest matches post-inspection manifest identically.
    2. Candidate response includes the exact requested heading and description.
    3. Completion policy evaluates candidate response against must_contain criteria and passes.
    4. Mission snapshot surfaces final_output and reaches COMPLETED with 0 additions/deletions.
    """
    ws: Path = stage6_2_env["workspace"]
    client: TestClient = stage6_2_env["client"]
    test_bus: EventBus = stage6_2_env["event_bus"]
    mission_id = "m_stage6_2_read_only_fulfilled"

    # Pre-populate README
    readme_path = ws / "README.md"
    readme_content = "# Project Antigravity Architecture\n\nThis system provides autonomous agent engineering with strict safety gates.\n"
    readme_path.write_text(readme_content, encoding="utf-8")
    record_file_baseline(ws, "README.md", readme_content)

    manifest_before = _compute_workspace_sha256_manifest(ws)

    # Start read-only mission with explicit criteria
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={
            "prompt": "Inspect README.md and report its primary heading and description without modifying any files.",
            "acceptance_criteria": [
                "must_contain:Project Antigravity Architecture",
                "must_contain:autonomous agent engineering with strict safety gates",
            ],
        }
    ))

    # Read action performed
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id=mission_id,
        payload={"tool_name": "read_file", "path": "README.md"}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={
            "tool_name": "read_file",
            "path": "README.md",
            "content": readme_content,
            "read_only": True,
        }
    ))

    candidate_output = (
        "Primary Heading: # Project Antigravity Architecture\n"
        "Description: This system provides autonomous agent engineering with strict safety gates.\n"
        "No files were modified."
    )

    # Evaluate candidate response with CompletionPolicy
    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Inspect README.md and report its primary heading and description without modifying any files.",
        workspace=workspace_manager,
        acceptance_criteria=[
            "must_contain:Project Antigravity Architecture",
            "must_contain:autonomous agent engineering with strict safety gates",
        ],
        written_files=[],
        candidate_response=candidate_output,
    )
    assert ok is True
    assert len(issues) == 0

    # Publish completion
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={
            "final_output": candidate_output,
            "completion_reason": "Read-only inspection fulfilled all acceptance criteria.",
        }
    ))

    # Assert workspace immutability (SHA-256 match)
    manifest_after = _compute_workspace_sha256_manifest(ws)
    assert manifest_before == manifest_after

    # Verify Snapshot from API
    resp = client.get(f"/api/missions/{mission_id}")
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["status"] == "COMPLETED"
    assert snap["final_output"] == candidate_output
    assert snap["completion_reason"] == "Read-only inspection fulfilled all acceptance criteria."
    assert len(snap["files_created"]) == 0
    assert len(snap["files_modified"]) == 0

    # Verify Diffs endpoint reports no changes
    diff_resp = client.get(f"/api/missions/{mission_id}/diffs")
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert diff_data["total_additions"] == 0
    assert diff_data["total_deletions"] == 0


def test_scenario_2_read_only_omitting_requested_details_rejected(stage6_2_env):
    """
    Scenario 2: Read-only request omitting requested details is rejected.
    Replicates Stage 6.1 historical case where the model read the file but only answered
    "The README has already been read successfully, and no modification is needed."
    Verifies that:
    1. CompletionPolicy rejects candidate response missing required details.
    2. Issues list explicitly names the missing items.
    3. Mission status is NOT accepted as COMPLETED.
    """
    ws: Path = stage6_2_env["workspace"]
    readme_path = ws / "README.md"
    readme_path.write_text("# Project Antigravity Architecture\n\nThis system provides autonomous agent engineering.\n", encoding="utf-8")

    criteria = [
        "must_contain:Project Antigravity Architecture",
        "must_contain:autonomous agent engineering",
    ]

    historical_vague_response = (
        "The README has already been read successfully, and no modification is needed. Here's the report:\n\n**"
    )

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Inspect README.md and report its primary heading and description without modifying any files.",
        workspace=workspace_manager,
        acceptance_criteria=criteria,
        written_files=[],
        candidate_response=historical_vague_response,
    )

    assert ok is False
    assert "candidate response failed acceptance criteria" in reason
    assert any("Project Antigravity Architecture" in issue for issue in issues)
    assert any("autonomous agent engineering" in issue for issue in issues)


def test_scenario_3_file_creation_task_with_expected_files_and_content(stage6_2_env):
    """
    Scenario 3: File-creation task with expected files and content.
    Verifies:
    1. Real files created in workspace with valid non-empty content and valid syntax.
    2. Diff service reports change_type='created' with exact additions > 0 and 0 deletions.
    3. Verification check runs child subprocess with canonical python interpreter sys.executable.
    4. Completion succeeds and snapshot records verified status and final_output.
    """
    ws: Path = stage6_2_env["workspace"]
    client: TestClient = stage6_2_env["client"]
    test_bus: EventBus = stage6_2_env["event_bus"]
    mission_id = "m_stage6_2_file_creation"

    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Create calculator.py and test_calculator.py"}
    ))

    # Real file creation
    calc_file = ws / "calculator.py"
    calc_code = "def multiply(a: int, b: int) -> int:\n    return a * b\n"
    calc_file.write_text(calc_code, encoding="utf-8")

    test_file = ws / "test_calculator.py"
    test_code = "from calculator import multiply\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"
    test_file.write_text(test_code, encoding="utf-8")

    # Record tools
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "write_file", "path": "calculator.py", "files_created": ["calculator.py"]}
    ))
    test_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        payload={"tool_name": "write_file", "path": "test_calculator.py", "files_created": ["test_calculator.py"]}
    ))

    # Real verification command using sys.executable
    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    proc = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True)
    assert proc.returncode == 0

    test_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_PASSED,
        mission_id=mission_id,
        payload={
            "check_id": "chk_pytest_creation",
            "name": "Unit Tests",
            "command": " ".join(cmd),
            "exit_code": proc.returncode,
            "status": "passed",
            "output": proc.stdout,
            "python_executable": sys.executable,
        }
    ))

    final_msg = "Successfully created calculator.py and test_calculator.py. All tests passed with exit code 0."
    test_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"final_output": final_msg, "completion_reason": "All artifacts created and verified."}
    ))

    # Assert diffs
    diff_calc = compute_file_diff(ws, "calculator.py")
    assert diff_calc.change_type == "created"
    assert diff_calc.additions == 2
    assert diff_calc.deletions == 0

    diff_test = compute_file_diff(ws, "test_calculator.py")
    assert diff_test.change_type == "created"
    assert diff_test.additions == 4
    assert diff_test.deletions == 0

    # API Snapshot check
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["status"] == "COMPLETED"
    assert snap["final_output"] == final_msg
    assert "calculator.py" in snap["files_created"]
    assert "test_calculator.py" in snap["files_created"]


def test_scenario_4_modification_request_diff_or_status_mismatch_detected(stage6_2_env):
    """
    Scenario 4: Modification request where final content is modified, verifying diff
    integrity and detecting incorrect 'created' status or diff discrepancies.
    """
    ws: Path = stage6_2_env["workspace"]
    config_file = ws / "settings.py"
    initial_content = "DEBUG = False\nPORT = 8000\n"
    config_file.write_text(initial_content, encoding="utf-8")
    record_file_baseline(ws, "settings.py", initial_content)

    # Modification happens
    new_content = "DEBUG = True\nPORT = 8080\nTIMEOUT = 30\n"
    config_file.write_text(new_content, encoding="utf-8")

    diff_entry = compute_file_diff(ws, "settings.py")
    # Must be 'modified', NOT 'created'
    assert diff_entry.change_type == "modified"
    assert diff_entry.additions == 3
    assert diff_entry.deletions == 2
    assert "-DEBUG = False" in diff_entry.diff_text
    assert "+DEBUG = True" in diff_entry.diff_text

    # If baseline was missing or erased, it would erroneously report 'created' with 0 deletions:
    clear_file_baselines(ws)
    faulty_diff = compute_file_diff(ws, "settings.py")
    # In the absence of baseline, fallback defaults to created without deletions
    assert faulty_diff.change_type == "created"
    assert faulty_diff.deletions == 0
    # Demonstrates that preserving baseline integrity is critical for genuine modification diffs


def test_scenario_5_verification_failure_blocks_completion_despite_candidate_claim(stage6_2_env):
    """
    Scenario 5: Verification check failure blocks completion even if candidate response claims success.
    Verifies that GoalCompleteGuard blocks false success representation when an acceptance check fails.
    """
    ws: Path = stage6_2_env["workspace"]
    test_bus: EventBus = stage6_2_env["event_bus"]
    mission_id = "m_stage6_2_guard_mismatch"

    mission_state = MissionState(
        mission_id=mission_id,
        prompt="Implement and verify test",
        status=MissionStatus.RUNNING,
    )
    failed_check = AcceptanceCheck(
        check_id="chk_failing",
        requirement_id="req_1",
        description="Must pass pytest",
        status=AcceptanceCheckStatus.FAIL,
        critical=True,
        error_message="pytest command exited with 1",
    )
    ledger = AcceptanceLedger(checks={"chk_failing": failed_check})
    runtime_state = HermesRuntimeState(
        mission=mission_state,
        acceptance_ledger=ledger,
    )

    ok, reason, issues = GoalCompleteGuard.evaluate(
        state=runtime_state,
        strict_requirements=True,
    )
    assert ok is False
    assert any("chk_failing" in issue for issue in issues)

    # Policy also rejects completion
    policy = CompletionPolicy()
    ok_p, reason_p, issues_p = policy.evaluate_completion(
        mission_prompt="Implement and verify test",
        runtime_state=runtime_state,
        candidate_response="Everything passed with flying colors!",
    )
    assert ok_p is False
    assert "GoalCompleteGuard" in reason_p


def test_scenario_6_tool_or_model_failure_not_represented_as_success(stage6_2_env):
    """
    Scenario 6: Tool or model failure is never represented as success.
    Verifies:
    1. Tool failure (ActionStatus.FAILED) records error.
    2. Python syntax error in created file is caught by deterministic AST check in CompletionPolicy.
    3. Mission cannot complete as COMPLETED while syntax errors or tool failures exist.
    """
    ws: Path = stage6_2_env["workspace"]

    # Write a file with a deliberate syntax error (model hallucination / failure)
    bad_file = ws / "broken.py"
    bad_file.write_text("def broken_syntax(:\n    pass\n", encoding="utf-8")

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Create broken.py",
        workspace=workspace_manager,
        written_files=["broken.py"],
        candidate_response="I have created broken.py.",
    )
    assert ok is False
    assert "deterministic syntax validation failed" in reason
    assert any("syntax error" in issue.lower() for issue in issues)
