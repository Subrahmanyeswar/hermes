# tests/test_tool_workspace_enforcement.py

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.workspace import WorkspaceManager, workspace_manager as global_wm


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path):
    """Lock the global workspace manager to a temp dir for each test."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# app\n")
    global_wm.lock(str(tmp_path))
    yield tmp_path
    # Reset after test
    global_wm.workspace_root = None
    global_wm._locked = False
    global_wm.index = None


@pytest.mark.asyncio
async def test_write_file_inside_workspace_succeeds(isolated_workspace):
    from tools.file_tools import WriteFileTool
    tool = WriteFileTool()
    result = await tool.execute_async(
        WriteFileTool.Input(path="src/new_file.py", content="x = 1\n")
    )
    assert result.success is True
    assert (isolated_workspace / "src" / "new_file.py").exists()


@pytest.mark.asyncio
async def test_write_file_outside_workspace_blocked(isolated_workspace):
    from tools.file_tools import WriteFileTool
    tool = WriteFileTool()
    result = await tool.execute_async(
        WriteFileTool.Input(path="../../etc/evil.py", content="malicious")
    )
    assert result.success is False
    assert "SECURITY" in result.error
    assert result.exit_code == 126


@pytest.mark.asyncio
async def test_read_file_outside_workspace_blocked(isolated_workspace):
    from tools.file_tools import ReadFileTool
    tool = ReadFileTool()
    result = await tool.execute_async(
        ReadFileTool.Input(path="../../../etc/passwd")
    )
    assert result.success is False
    assert "SECURITY" in result.error


@pytest.mark.asyncio
async def test_read_file_inside_workspace_succeeds(isolated_workspace):
    from tools.file_tools import ReadFileTool
    tool = ReadFileTool()
    result = await tool.execute_async(
        ReadFileTool.Input(path="src/app.py")
    )
    assert result.success is True
    assert "# app" in result.output


@pytest.mark.asyncio
async def test_write_file_creates_parent_directories(isolated_workspace):
    from tools.file_tools import WriteFileTool
    tool = WriteFileTool()
    result = await tool.execute_async(
        WriteFileTool.Input(path="deep/nested/new.py", content="y = 2\n")
    )
    assert result.success is True
    assert (isolated_workspace / "deep" / "nested" / "new.py").exists()


@pytest.mark.asyncio
async def test_write_file_absolute_path_outside_blocked(isolated_workspace):
    from tools.file_tools import WriteFileTool
    tool = WriteFileTool()
    result = await tool.execute_async(
        WriteFileTool.Input(path="/tmp/hermes_test_escape.py", content="x=1")
    )
    assert result.success is False
    assert "SECURITY" in result.error


def test_workspace_index_refreshes_after_write(isolated_workspace):
    import asyncio
    from tools.file_tools import WriteFileTool
    tool = WriteFileTool()
    asyncio.run(tool.execute_async(
        WriteFileTool.Input(path="newly_created.py", content="z = 3\n")
    ))
    # Index should contain the new file
    assert "newly_created.py" in global_wm.index.files


def test_bash_exec_runs_in_workspace_dir(isolated_workspace):
    from tools.shell_tools import BashExecTool
    tool = BashExecTool()
    result = tool.execute(BashExecTool.Input(command="pwd"))
    assert result.success is True
    assert str(isolated_workspace).lower() in result.output.lower()
