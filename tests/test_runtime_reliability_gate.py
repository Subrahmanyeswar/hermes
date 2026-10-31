"""
HERMES — Runtime Truth and Reliability Gate Test Suite (Tests A through F)
Enforces:
  Test A: Actual Path error regression (line 461 / 1639 in mission_runner.py)
  Test B: Tool exception cannot produce successful completion
  Test C: Required file writing verification (file must exist and be non-empty)
  Test D: Missing output detection (simulated missing output blocks completion)
  Test E: Exception propagation and clean terminal failure state
  Test F: Legitimate no-change (read-only) tasks still pass
"""

import asyncio
import os
import tempfile
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.mission_planner import MissionPlanner, Mission, MissionTask, TaskState, TaskPriority
from core.mission_runner import MissionRunner, MissionEvent, MissionPhase, MissionResult
from core.workspace import WorkspaceManager, workspace_manager
from core.orchestrator import Orchestrator, OrchestratorResult
from tools.base import BaseTool, ToolResult
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Test Helpers & Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def make_mock_orch(
    success: bool = True,
    output: str = "Done.",
    error: str = None,
    tool_name: str = "write_file",
    exit_code: int = 0,
    stage: int = 12,
):
    orch = AsyncMock()
    tool_res = ToolResult(
        success=success,
        exit_code=exit_code,
        output=output if success else "",
        error=error if not success else "",
    )
    orch.run = AsyncMock(return_value=OrchestratorResult(
        success=success,
        final_output=output if success else (error or "Tool failed"),
        tool_name=tool_name,
        tool_result=tool_res,
        task=None,
        skill_ids_used=[],
        tier3_was_called=False,
        total_latency_seconds=0.1,
        error=error if not success else None,
        pipeline_stage_reached=stage,
        trace_id="test_trace",
    ))
    orch.claude = MagicMock()
    orch.claude.get_cost_summary = MagicMock(return_value={"total_spent": 0.0})
    orch.execution_mode = "strict"
    return orch


# ─────────────────────────────────────────────────────────────────────────────
# Test A — The actual Path error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_path_error_regression(tmp_path):
    """
    Test A: Exercise the operation that previously raised NameError: name 'Path' is not defined.
    Locks a workspace to tmp_path, creates a mission with expected target files,
    runs the mission to completion, and confirms line 461 in mission_runner.py
    executes without NameError.
    """
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('hello world')\n", encoding="utf-8")

    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    planner = MissionPlanner()
    mission = planner.plan(
        "Create a hello.py file",
        workspace_root=str(tmp_path),
        execution_mode="strict",
    )
    # Ensure task targets hello.py
    for t in mission.tasks:
        t.target_paths = ["hello.py"]

    orch = make_mock_orch(success=True, output="Created hello.py", tool_name="write_file")
    runner = MissionRunner(orch, wm)

    # Must execute all the way through SUMMARIZING (line 461) without raising NameError
    result = await runner.run(mission)
    assert isinstance(result, MissionResult)
    assert result.success is True
    assert "Missing required artifacts" not in (result.error or "")


# ─────────────────────────────────────────────────────────────────────────────
# Test B — A tool exception cannot produce successful completion
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b_tool_exception_cannot_produce_success(tmp_path):
    """
    Test B: A deterministic failing tool invocation (exception or exit_code!=0)
    must NOT produce successful completion. Diagnostic info must be preserved.
    """
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    task = MissionTask(
        title="Run failing tool",
        description="Execute a failing operation",
        priority=TaskPriority.HIGH,
        max_retries=1,
    )
    mission = Mission(
        mission_id="test_b_mission",
        user_prompt="Run failing tool",
        tasks=[task],
        execution_order=[task.task_id],
        workspace_root=str(tmp_path),
    )

    # Tool execution fails explicitly with error
    orch = make_mock_orch(
        success=False,
        output="",
        error="CRITICAL_TOOL_ERROR: Subprocess crash with exit code 1",
        tool_name="shell.bash",
        exit_code=1,
        stage=6,
    )
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)

    # Must NOT report success
    assert result.success is False
    assert result.status == "FAILED"
    assert task.state == TaskState.FAILED
    assert "CRITICAL_TOOL_ERROR" in (task.error_message or "") or "failed" in (result.error or "").lower()


# ─────────────────────────────────────────────────────────────────────────────
# Test C — Required file writing verification
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_c_required_file_writing_verification(tmp_path):
    """
    Test C: File creation task must only be marked completed when the file
    actually exists on disk, is non-empty (>10 bytes), and satisfies verification.
    """
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    task_file = "app.py"
    target_disk_path = tmp_path / task_file

    task = MissionTask(
        title="Create app.py",
        description="Write a complete Flask app to app.py",
        priority=TaskPriority.CRITICAL,
        target_paths=[task_file],
        max_retries=1,
    )
    mission = Mission(
        mission_id="test_c_mission",
        user_prompt="Create app.py",
        tasks=[task],
        execution_order=[task.task_id],
        workspace_root=str(tmp_path),
        project_root_path=str(tmp_path),
    )

    # Simulate tool writing the actual file to disk during execution
    target_disk_path.write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")

    orch = make_mock_orch(
        success=True,
        output=f"Written 45 characters to {task_file}",
        tool_name="write_file",
        exit_code=0,
    )
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)

    assert result.success is True
    assert target_disk_path.exists()
    assert target_disk_path.stat().st_size > 10
    assert task.state == TaskState.COMPLETED


# ─────────────────────────────────────────────────────────────────────────────
# Test D — Missing output detection (Blocks completion)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_d_missing_output_blocks_completion(tmp_path):
    """
    Test D: When a task requires file creation but the file is NOT created on disk
    (simulated no-op write or failed creation), HERMES must detect the missing file
    and reject completion.
    """
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    task_file = "missing_artifact.py"
    target_disk_path = tmp_path / task_file
    # Ensure file does NOT exist
    if target_disk_path.exists():
        target_disk_path.unlink()

    task = MissionTask(
        title="Create missing_artifact.py",
        description="Write missing_artifact.py to disk",
        priority=TaskPriority.HIGH,
        target_paths=[task_file],
        max_retries=1,
    )
    mission = Mission(
        mission_id="test_d_mission",
        user_prompt="Create missing_artifact.py",
        tasks=[task],
        execution_order=[task.task_id],
        workspace_root=str(tmp_path),
        project_root_path=str(tmp_path),
    )

    # Orchestrator claims success, but NO file was written to disk
    orch = make_mock_orch(
        success=True,
        output=f"Pretended to write {task_file}",
        tool_name="write_file",
        exit_code=0,
    )
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)

    # Must detect missing file and refuse completion
    assert result.success is False
    assert not target_disk_path.exists()
    assert result.status == "FAILED"
    assert "missing" in (result.error or "").lower() or "not written" in (result.error or "").lower()


# ─────────────────────────────────────────────────────────────────────────────
# Test E — Exception propagation and recovery
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e_runtime_exception_handled_cleanly(tmp_path):
    """
    Test E: Simulate an unexpected runtime exception during task execution.
    Verify that the runtime handles it cleanly without leaving a zombie or corrupted state.
    """
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    task = MissionTask(
        title="Crashing task",
        description="Task that triggers unexpected internal exception",
        priority=TaskPriority.HIGH,
        max_retries=1,
    )
    mission = Mission(
        mission_id="test_e_mission",
        user_prompt="Crashing task",
        tasks=[task],
        execution_order=[task.task_id],
        workspace_root=str(tmp_path),
    )

    orch = AsyncMock()
    orch.run = AsyncMock(side_effect=RuntimeError("Simulated internal runtime failure"))
    orch.claude = MagicMock()
    orch.claude.get_cost_summary = MagicMock(return_value={"total_spent": 0.0})

    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)

    # Must cleanly catch and handle failure
    assert isinstance(result, MissionResult)
    assert result.success is False
    assert result.status == "FAILED"
    assert task.state == TaskState.FAILED
    assert "Simulated internal runtime failure" in (task.error_message or "")


# ─────────────────────────────────────────────────────────────────────────────
# Test F — Legitimate no-change (read-only) tasks still pass
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f_legitimate_read_only_task_passes(tmp_path):
    """
    Test F: A read-only / inspection task (list_directory, search, etc.)
    does not create files, but must succeed when the operation succeeded.
    """
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    # Create a file for the read-only task to inspect
    (tmp_path / "README.md").write_text("# Test Workspace\n", encoding="utf-8")

    task = MissionTask(
        title="List directory contents",
        description="Inspect and list files in the workspace directory",
        priority=TaskPriority.NORMAL,
        max_retries=1,
    )
    mission = Mission(
        mission_id="test_f_mission",
        user_prompt="List files in directory",
        tasks=[task],
        execution_order=[task.task_id],
        workspace_root=str(tmp_path),
        project_root_path=str(tmp_path),
    )

    orch = make_mock_orch(
        success=True,
        output="README.md (17 bytes)",
        tool_name="list_directory",
        exit_code=0,
    )
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)

    assert result.success is True
    assert task.state == TaskState.COMPLETED
    assert result.status == "COMPLETE"
