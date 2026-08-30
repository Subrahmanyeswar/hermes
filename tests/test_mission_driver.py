# tests/test_mission_driver.py

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from kairos.mission_driver import MissionDriver
from core.mission_planner import TaskState
from core.workspace import workspace_manager as global_workspace


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.claude = MagicMock()
    orch.claude.get_cost_summary.return_value = {"total_spent": 0.05}
    orch_res = MagicMock()
    orch_res.success = True
    orch_res.pipeline_stage_reached = 6
    orch_res.final_output = "Task completed successfully."
    orch_res.tool_name = "write_file"
    orch_res.tier3_was_called = False
    orch_res.trace_id = "trace-123"
    orch_res.tool_result = MagicMock(output="File written")
    orch.run = AsyncMock(return_value=orch_res)
    return orch


@pytest.mark.asyncio
async def test_initialise_workspace_cwd(mock_orchestrator):
    driver = MissionDriver(mock_orchestrator)
    summary = await driver.initialise_workspace()
    assert summary.get("locked") is True
    assert summary.get("root") is not None


@pytest.mark.asyncio
async def test_run_mission_flow(mock_orchestrator, tmp_path):
    driver = MissionDriver(mock_orchestrator)
    await driver.initialise_workspace(str(tmp_path))
    (tmp_path / "api.py").write_text("print('api')")
    (tmp_path / "test_api.py").write_text("def test_api(): pass")

    result = await driver.run_mission("Create api.py and write unit tests")
    assert result.success is True
    assert result.tasks_total == 2
    assert result.tasks_completed == 2
    assert driver.current_mission is not None
    assert len(driver.get_mission_status_lines()) == 2


@pytest.mark.asyncio
async def test_abort_mission(mock_orchestrator, tmp_path):
    driver = MissionDriver(mock_orchestrator)
    await driver.initialise_workspace(str(tmp_path))

    # Trigger abort
    driver._current_runner = MagicMock()
    driver._abort_event = asyncio.Event()
    driver.abort_current_mission()
    driver._current_runner.abort.assert_called_once()
