"""
HERMES v4.0 — Full Integration Test
Tests the complete mission execution chain:
  WorkspaceManager → MissionPlanner → ContextBuilder → MissionRunner → TUI events
No real Ollama required — all LLM calls mocked.
"""
import asyncio
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.workspace import WorkspaceManager
from core.mission_planner import MissionPlanner, TaskState
from core.mission_runner import MissionRunner, MissionEvent
from core.context_builder import ContextBuilder


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def project_workspace(tmp_path):
    """Create a realistic Flask project structure for testing."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "from flask import Flask\nfrom src.models import db\n"
        "app = Flask(__name__)\n\n"
        "class Config:\n    DATABASE_URI = 'sqlite:///app.db'\n"
    )
    (tmp_path / "src" / "models.py").write_text(
        "from flask_sqlalchemy import SQLAlchemy\n"
        "db = SQLAlchemy()\n\n"
        "class User(db.Model):\n"
        "    id = db.Column(db.Integer, primary_key=True)\n"
        "    username = db.Column(db.String(80))\n"
        "    email = db.Column(db.String(120))\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "requirements.txt").write_text(
        "flask==3.0.0\nflask-sqlalchemy\npytest\n"
    )
    (tmp_path / "README.md").write_text("# MyProject\n")
    return tmp_path


@pytest.fixture
def workspace(project_workspace):
    wm = WorkspaceManager()
    wm.lock(str(project_workspace))
    return wm


def make_mock_orchestrator(success_sequence: list[bool] = None):
    """
    Create a mock orchestrator that returns alternating success/failure results.
    Default: all succeed.
    """
    from core.orchestrator import OrchestratorResult

    if success_sequence is None:
        success_sequence = [True] * 20  # Default all succeed

    call_counter = [0]

    async def mock_run(prompt: str):
        idx = min(call_counter[0], len(success_sequence) - 1)
        success = success_sequence[idx]
        call_counter[0] += 1

        return OrchestratorResult(
            success=success,
            final_output=f"Task {'completed' if success else 'failed'}: {prompt[:50]}",
            tool_name="write_file" if success else "bash_exec",
            tool_result=MagicMock(
                success=success,
                exit_code=0 if success else 1,
                output=f"Written successfully" if success else "",
                error=None if success else "command failed",
            ),
            task=None,
            skill_ids_used=["flask-rest-api"] if "flask" in prompt.lower() else [],
            tier3_was_called=False,
            total_latency_seconds=1.2,
            error=None if success else "execution failed",
            pipeline_stage_reached=12 if success else 5,
            trace_id=f"test-{call_counter[0]:04d}",
        )

    orch = AsyncMock()
    orch.run = AsyncMock(side_effect=mock_run)
    orch.claude = MagicMock()
    orch.claude.get_cost_summary = MagicMock(
        return_value={"total_spent": 0.05, "cap": 25.0, "remaining": 24.95}
    )
    return orch, call_counter


# ── Core unit tests ───────────────────────────────────────────────────────────

def test_workspace_indexes_project(workspace, project_workspace):
    assert workspace.is_locked
    assert workspace.index is not None
    assert workspace.index.total_files >= 4
    assert workspace.index.framework_detected in ("Python", "Flask")
    files = list(workspace.index.files.keys())
    assert any("app.py" in f for f in files)
    assert any("models.py" in f for f in files)
    assert not any("__pycache__" in f for f in files)


def test_context_builder_respects_budget(workspace, project_workspace):
    from core.context_builder import ContextBuilder, TOKEN_BUDGET_TOTAL
    builder = ContextBuilder(workspace)
    planner = MissionPlanner()
    mission = planner.plan("Add JWT authentication to the Flask API")
    ctx = builder.build(mission.tasks[0], mission)
    assert ctx.total_tokens <= TOKEN_BUDGET_TOTAL + 300  # small slack
    rendered = ctx.to_string()
    assert len(rendered) > 100
    assert "CURRENT TASK" in rendered


def test_mission_planner_decomposes_complex_prompt():
    planner = MissionPlanner()
    prompt = (
        "1. Create Flask project structure\n"
        "2. Build SQLite user model\n"
        "3. Add JWT authentication routes\n"
        "4. Write pytest test suite\n"
        "5. Generate README documentation"
    )
    mission = planner.plan(prompt)
    assert len(mission.tasks) == 5
    assert len(mission.execution_order) == 5
    # No task should have itself as a dependency
    for task in mission.tasks:
        assert task.task_id not in task.depends_on


def test_skill_detection_across_all_5_tasks():
    planner = MissionPlanner()
    tasks_map = {
        "Build Flask REST API with SQLite": "flask-rest-api",
        "Write pytest tests for auth routes": "pytest-generation",
        "Git commit and push to GitHub": "git-workflow",
        "Security audit the login endpoint": "security-audit",
        "Debug the NameError in models.py": "debugging",
    }
    for prompt, expected_skill in tasks_map.items():
        mission = planner.plan(prompt)
        task = mission.tasks[0]
        assert task.skill_hint == expected_skill, (
            f"Prompt '{prompt}' expected skill '{expected_skill}' "
            f"but got '{task.skill_hint}'"
        )


# ── Mission execution tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_5_task_mission_all_succeed(workspace):
    """Complete 5-task mission where all tasks succeed."""
    planner = MissionPlanner()
    prompt = (
        "1. Create Flask app structure\n"
        "2. Build User model with SQLAlchemy\n"
        "3. Add authentication routes\n"
        "4. Write pytest tests\n"
        "5. Generate README"
    )
    mission = planner.plan(prompt)
    assert len(mission.tasks) == 5

    orch, counter = make_mock_orchestrator([True] * 5)

    queue = asyncio.Queue()
    runner = MissionRunner(orch, workspace, event_queue=queue)

    with patch("core.mission_runner.workspace_manager", workspace):
        result = await runner.run(mission)

    assert result.success is True
    assert result.tasks_completed == 5
    assert result.tasks_failed == 0
    assert counter[0] == 5  # Exactly 5 orchestrator calls
    assert result.walkthrough_text != ""
    assert "MISSION COMPLETE" in result.walkthrough_text


@pytest.mark.asyncio
async def test_5_task_mission_with_one_retry(workspace):
    """Task 2 fails once then succeeds on retry."""
    planner = MissionPlanner()
    mission = planner.plan(
        "1. Create folders\n2. Write app.py\n3. Write models.py\n"
        "4. Write tests\n5. Push to GitHub"
    )

    # Task 2 fails first time (index 1), succeeds on retry (index 5)
    success_seq = [True, False, True, True, True, True, True, True]
    orch, counter = make_mock_orchestrator(success_seq)

    queue = asyncio.Queue()
    runner = MissionRunner(orch, workspace, event_queue=queue)

    with patch("core.mission_runner.workspace_manager", workspace):
        result = await runner.run(mission)

    assert counter[0] >= 6  # At least one retry happened
    assert result.walkthrough_text != ""


@pytest.mark.asyncio
async def test_events_contain_all_lifecycle_types(workspace):
    """Verify all expected event types are emitted during mission."""
    planner = MissionPlanner()
    mission = planner.plan("1. Create app.py\n2. Write tests")
    orch, _ = make_mock_orchestrator([True, True])

    queue = asyncio.Queue()
    runner = MissionRunner(orch, workspace, event_queue=queue)

    with patch("core.mission_runner.workspace_manager", workspace):
        await runner.run(mission)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    event_types = {e.event_type for e in events}
    required_types = {
        "mission_start",
        "task_start",
        "task_complete",
        "mission_complete",
    }
    missing = required_types - event_types
    assert not missing, f"Missing event types: {missing}"


@pytest.mark.asyncio
async def test_abort_stops_after_current_task(workspace):
    """Abort signal stops the mission at the next checkpoint."""
    planner = MissionPlanner()
    mission = planner.plan(
        "1. Create folders\n2. Write app.py\n3. Write models.py\n"
        "4. Write routes.py\n5. Write tests"
    )
    orch, counter = make_mock_orchestrator([True] * 10)

    abort = asyncio.Event()
    queue = asyncio.Queue()
    runner = MissionRunner(orch, workspace, event_queue=queue, abort_event=abort)

    # Set abort immediately
    abort.set()

    with patch("core.mission_runner.workspace_manager", workspace):
        result = await runner.run(mission)

    assert result.success is False
    assert result.error == "Aborted by user"
    assert counter[0] == 0  # No tasks ran


@pytest.mark.asyncio
async def test_workspace_boundary_blocks_illegal_write(workspace, project_workspace):
    """
    Verify that a tool attempting to write outside workspace
    gets blocked by workspace boundary enforcement.
    """
    from tools.file_tools import WriteFileTool

    tool = WriteFileTool()
    with patch("tools.file_tools.workspace_manager", workspace):
        result = await tool.execute_async(
            WriteFileTool.Input(path="../../etc/hermes_evil_test.txt", content="evil")
        )
    assert result.success is False
    assert "SECURITY" in result.error
    # Verify file was NOT created
    assert not Path("/etc/hermes_evil_test.txt").exists()


@pytest.mark.asyncio
async def test_context_continuity_across_tasks(workspace):
    """Verify that recent outputs are passed to subsequent task contexts."""
    from core.context_builder import ContextBuilder
    builder = ContextBuilder(workspace)
    planner = MissionPlanner()
    mission = planner.plan("1. Create app.py\n2. Add routes to app.py")
    tasks = mission.tasks

    # Build context for task 1
    ctx1 = builder.build(tasks[0], mission)
    assert "CURRENT TASK" in ctx1.to_string()

    # Mark task 1 complete
    mission.mark_task_complete(tasks[0].task_id)

    # Build context for task 2 — should show task 1 as completed
    ctx2 = builder.build(
        tasks[1], mission,
        previous_outputs=["Created app.py with Flask factory pattern"]
    )
    rendered2 = ctx2.to_string()
    assert "ALREADY COMPLETED" in rendered2 or tasks[0].title in rendered2


# ── MissionDriver integration ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mission_driver_full_flow(workspace, project_workspace):
    """Test MissionDriver.run_mission end-to-end."""
    from kairos.mission_driver import MissionDriver

    orch, counter = make_mock_orchestrator([True] * 5)

    driver = MissionDriver(orch)
    with patch("kairos.mission_driver.global_workspace", workspace):
        driver._workspace_initialised = True

        with patch("core.mission_runner.workspace_manager", workspace):
            result = await driver.run_mission(
                "1. Create Flask app\n2. Write models\n3. Add routes"
            )

    assert result is not None
    assert result.tasks_total == 3
    assert counter[0] == 3


# ── Smoke test: complete v4.0 system ─────────────────────────────────────────

def test_all_v4_components_importable():
    """All new v4.0 components must import cleanly."""
    imports = [
        ("core.workspace",         ["WorkspaceManager", "workspace_manager", "WorkspaceBoundaryError"]),
        ("core.mission_planner",   ["MissionPlanner", "Mission", "MissionTask", "TaskState"]),
        ("core.mission_runner",    ["MissionRunner", "MissionEvent", "MissionResult"]),
        ("core.context_builder",   ["ContextBuilder", "AssembledContext", "estimate_tokens"]),
        ("kairos.mission_driver",  ["MissionDriver"]),
        ("ui.panels.startup",      ["StartupScreen"]),
    ]
    import importlib
    failures = []
    for module_path, symbols in imports:
        try:
            mod = importlib.import_module(module_path)
            for sym in symbols:
                if not hasattr(mod, sym):
                    failures.append(f"{module_path}.{sym} not found")
        except ImportError as e:
            failures.append(f"{module_path}: {e}")

    assert not failures, f"Import failures:\n" + "\n".join(failures)


def test_mission_result_walkthrough_structure():
    """Walkthrough must contain all required sections."""
    import asyncio
    from core.mission_planner import MissionPlanner, TaskState
    from core.mission_runner import MissionRunner
    from core.workspace import WorkspaceManager
    from unittest.mock import AsyncMock, MagicMock

    planner = MissionPlanner()
    mission = planner.plan("Create Flask API")

    orch, _ = make_mock_orchestrator([True])
    runner = MissionRunner(orch, WorkspaceManager())

    result = asyncio.run(runner.run(mission))
    wt = result.walkthrough_text
    assert "━" in wt or "MISSION" in wt
    assert "Time:" in wt or "Cost:" in wt
