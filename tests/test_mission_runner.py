import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.mission_planner import MissionPlanner, Mission, TaskState
from core.mission_runner import MissionRunner, MissionEvent, MissionPhase
from core.workspace import WorkspaceManager


def make_mock_orchestrator(success: bool = True, stage: int = 12):
    from core.orchestrator import OrchestratorResult
    orch = AsyncMock()
    orch.run = AsyncMock(return_value=OrchestratorResult(
        success=success,
        final_output="Done." if success else "Failed.",
        tool_name="write_file",
        tool_result=None,
        task=None,
        skill_ids_used=[],
        tier3_was_called=False,
        total_latency_seconds=1.0,
        error=None if success else "Tool failed",
        pipeline_stage_reached=stage,
        trace_id="test1234",
    ))
    orch.claude = MagicMock()
    orch.claude.get_cost_summary = MagicMock(return_value={"total_spent": 0.01})
    return orch


@pytest.fixture
def event_loop_fixture():
    return asyncio.new_event_loop()


@pytest.mark.asyncio
async def test_single_task_mission_completes():
    planner = MissionPlanner()
    mission = planner.plan("Create a hello.py file")
    orch = make_mock_orchestrator(success=True)
    wm = WorkspaceManager()
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)
    assert result.success is True
    assert result.tasks_completed >= 1


@pytest.mark.asyncio
async def test_multi_task_mission_runs_all_tasks():
    planner = MissionPlanner()
    mission = planner.plan(
        "1. Create app.py\n2. Create models.py\n3. Create routes.py"
    )
    orch = make_mock_orchestrator(success=True)
    wm = WorkspaceManager()
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)
    assert result.tasks_completed == result.tasks_total


@pytest.mark.asyncio
async def test_failed_task_triggers_retry():
    planner = MissionPlanner()
    mission = planner.plan("Create the Flask application")
    # First call fails, second succeeds
    from core.orchestrator import OrchestratorResult
    mock_orch = AsyncMock()
    call_count = 0

    async def side_effect(prompt):
        nonlocal call_count
        call_count += 1
        success = call_count > 1  # Fail first, succeed after
        return OrchestratorResult(
            success=success, final_output="ok" if success else "fail",
            tool_name="write_file", tool_result=None, task=None,
            skill_ids_used=[], tier3_was_called=False,
            total_latency_seconds=0.5,
            error=None if success else "first attempt failed",
            pipeline_stage_reached=12 if success else 4, trace_id="abc"
        )

    mock_orch.run = AsyncMock(side_effect=side_effect)
    mock_orch.claude = MagicMock()
    mock_orch.claude.get_cost_summary = MagicMock(return_value={"total_spent": 0.0})
    wm = WorkspaceManager()
    runner = MissionRunner(mock_orch, wm)
    result = await runner.run(mission)
    assert call_count >= 2  # At least one retry happened


@pytest.mark.asyncio
async def test_abort_stops_mission():
    planner = MissionPlanner()
    mission = planner.plan(
        "1. Create app.py\n2. Create models.py\n3. Create routes.py\n4. Create config.py"
    )
    orch = make_mock_orchestrator(success=True)
    wm = WorkspaceManager()
    abort_event = asyncio.Event()
    runner = MissionRunner(orch, wm, abort_event=abort_event)
    abort_event.set()  # Abort immediately
    result = await runner.run(mission)
    assert result.error == "Aborted by user"
    assert result.success is False


@pytest.mark.asyncio
async def test_events_emitted_during_mission():
    planner = MissionPlanner()
    mission = planner.plan("Create hello.py")
    orch = make_mock_orchestrator(success=True)
    wm = WorkspaceManager()
    queue = asyncio.Queue()
    runner = MissionRunner(orch, wm, event_queue=queue)
    await runner.run(mission)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    event_types = {e.event_type for e in events}
    assert "mission_start" in event_types
    assert "task_start" in event_types
    assert "mission_complete" in event_types or "mission_failed" in event_types


@pytest.mark.asyncio
async def test_walkthrough_generated_after_completion():
    planner = MissionPlanner()
    mission = planner.plan("Create the app")
    orch = make_mock_orchestrator(success=True)
    wm = WorkspaceManager()
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)
    assert result.walkthrough_text != ""
    assert "MISSION" in result.walkthrough_text


@pytest.mark.asyncio
async def test_result_has_correct_fields():
    planner = MissionPlanner()
    mission = planner.plan("Create hello.py")
    orch = make_mock_orchestrator(success=True)
    wm = WorkspaceManager()
    runner = MissionRunner(orch, wm)
    result = await runner.run(mission)
    assert hasattr(result, "mission_id")
    assert hasattr(result, "tasks_completed")
    assert hasattr(result, "total_cost_usd")
    assert hasattr(result, "walkthrough_text")
    assert result.total_latency_seconds >= 0


@pytest.mark.asyncio
async def test_generate_commit_message_types():
    planner = MissionPlanner()
    wm = WorkspaceManager()
    runner = MissionRunner(MagicMock(), wm)

    # feat
    m1 = planner.plan("Build Flask API")
    assert runner._generate_commit_message(m1).startswith("feat:")

    # fix
    m2 = planner.plan("Fix bug in database connection")
    assert runner._generate_commit_message(m2).startswith("fix:")

    # test
    m3 = planner.plan("Write unit tests for authentication")
    assert runner._generate_commit_message(m3).startswith("test:")

    # docs
    m4 = planner.plan("Add readme documentation")
    assert runner._generate_commit_message(m4).startswith("docs:")


@pytest.mark.asyncio
async def test_post_mission_git_summary_empty_when_not_locked():
    wm = WorkspaceManager()
    runner = MissionRunner(MagicMock(), wm)
    planner = MissionPlanner()
    mission = planner.plan("Create code")
    summary = await runner.post_mission_git_summary(mission)
    assert summary == ""

