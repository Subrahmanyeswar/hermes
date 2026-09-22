import pytest
import os
import tempfile
import asyncio
from pathlib import Path
from tools.file_tools import WriteFilesBatchTool, BatchFileItem
from core.workspace import workspace_manager, WorkspaceBoundaryError
from tools.registry import PermissionGate, get_tool


@pytest.fixture
def temp_workspace(tmp_path):
    ws = tmp_path / "test_ws"
    ws.mkdir()
    old_locked = workspace_manager.is_locked
    old_root = workspace_manager.workspace_root
    workspace_manager.lock(ws)
    yield ws
    # Restore
    if old_locked and old_root:
        workspace_manager.lock(old_root)
    else:
        workspace_manager.unlock()


def test_write_files_batch_single_file(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="single.txt", content="Hello single", mode="overwrite")
        ]
    )
    result = tool.execute(inp)
    assert result.success is True
    assert (temp_workspace / "single.txt").read_text(encoding="utf-8") == "Hello single"


def test_write_files_batch_two_files(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="a.txt", content="Content A", mode="overwrite"),
            BatchFileItem(path="b.txt", content="Content B", mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is True
    assert (temp_workspace / "a.txt").read_text(encoding="utf-8") == "Content A"
    assert (temp_workspace / "b.txt").read_text(encoding="utf-8") == "Content B"


def test_write_files_batch_three_files(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="index.html", content="<html></html>", mode="overwrite"),
            BatchFileItem(path="styles.css", content="body {}", mode="overwrite"),
            BatchFileItem(path="app.js", content="console.log('ok')", mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is True
    assert (temp_workspace / "index.html").exists()
    assert (temp_workspace / "styles.css").exists()
    assert (temp_workspace / "app.js").exists()


def test_write_files_batch_creates_subdirectories(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="src/components/Button.tsx", content="export const Button = () => null;", mode="overwrite"),
            BatchFileItem(path="src/styles/main.css", content="* { box-sizing: border-box; }", mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is True
    assert (temp_workspace / "src" / "components" / "Button.tsx").exists()
    assert (temp_workspace / "src" / "styles" / "main.css").exists()


def test_write_files_batch_rejects_more_than_three_files():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WriteFilesBatchTool.Input(
            files=[
                BatchFileItem(path="1.txt", content="1", mode="overwrite"),
                BatchFileItem(path="2.txt", content="2", mode="overwrite"),
                BatchFileItem(path="3.txt", content="3", mode="overwrite"),
                BatchFileItem(path="4.txt", content="4", mode="overwrite"),
            ]
        )


def test_write_files_batch_rejects_empty_files_list():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WriteFilesBatchTool.Input(files=[])


def test_write_files_batch_rejects_duplicate_paths(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="same.txt", content="First", mode="overwrite"),
            BatchFileItem(path="./same.txt", content="Second", mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is False
    assert "Duplicate path detected in batch" in result.error
    assert not (temp_workspace / "same.txt").exists()


def test_write_files_batch_rejects_path_traversal(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="safe.txt", content="Safe", mode="overwrite"),
            BatchFileItem(path="../../escape.txt", content="Danger", mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is False
    assert result.exit_code == 126
    assert "SECURITY:" in result.error
    # Ensure even the safe file was NOT created due to pre-validation failure
    assert not (temp_workspace / "safe.txt").exists()


def test_write_files_batch_rejects_placeholder_content(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="code.py", content="# full content here", mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is False
    assert "Rejected placeholder content" in result.error
    assert not (temp_workspace / "code.py").exists()


def test_write_files_batch_rejects_payload_exceeding_limit(temp_workspace):
    tool = WriteFilesBatchTool()
    chunk = "A" * 400_000
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="big1.txt", content=chunk, mode="overwrite"),
            BatchFileItem(path="big2.txt", content=chunk, mode="overwrite"),
            BatchFileItem(path="big3.txt", content=chunk, mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is False
    assert "Batch payload exceeds maximum limit" in result.error


def test_write_files_batch_permission_gate_blocks_safe_mode():
    gate = PermissionGate("safe")
    tool_cls = get_tool("write_files_batch")
    assert tool_cls is not None
    allowed, reason = gate.check(tool_cls)
    assert allowed is False
    assert "blocked in 'safe' mode" in reason


def test_write_files_batch_permission_gate_allows_auto_mode():
    gate = PermissionGate("auto")
    tool_cls = get_tool("write_files_batch")
    assert tool_cls is not None
    allowed, reason = gate.check(tool_cls)
    assert allowed is True


@pytest.mark.asyncio
async def test_write_files_batch_execute_async(temp_workspace):
    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="async1.txt", content="Async 1", mode="overwrite"),
            BatchFileItem(path="async2.txt", content="Async 2", mode="overwrite"),
        ]
    )
    result = await tool.execute_async(inp)
    assert result.success is True
    assert (temp_workspace / "async1.txt").read_text(encoding="utf-8") == "Async 1"
    assert (temp_workspace / "async2.txt").read_text(encoding="utf-8") == "Async 2"


def test_write_files_batch_append_mode(temp_workspace):
    p = temp_workspace / "log.txt"
    p.write_text("Header\n", encoding="utf-8")

    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="log.txt", content="Line 1\n", mode="append"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is True
    assert p.read_text(encoding="utf-8") == "Header\nLine 1\n"


def test_write_files_batch_rollback_on_commit_failure(temp_workspace, monkeypatch):
    # Pre-create file1
    f1 = temp_workspace / "file1.txt"
    f1.write_text("Original File 1", encoding="utf-8")

    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="file1.txt", content="Overwritten File 1", mode="overwrite"),
            BatchFileItem(path="file2.txt", content="New File 2", mode="overwrite"),
        ]
    )

    # Monkeypatch open to raise an exception when writing file2.txt
    real_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        if "file2.txt" in str(file) and "w" in mode:
            raise OSError("Simulated disk write failure on file2")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)

    result = tool.execute(inp)
    assert result.success is False
    assert "write_files_batch transaction failed and rolled back" in result.error

    # Verify rollback: file1 restored, file2 not present
    assert f1.read_text(encoding="utf-8") == "Original File 1"
    assert not (temp_workspace / "file2.txt").exists()


def test_write_files_batch_cleans_temporary_directories(temp_workspace):
    import tempfile
    staging_prefix = "hermes_batch_staging_"
    backup_prefix = "hermes_batch_backup_"
    temp_dir = Path(tempfile.gettempdir())

    tool = WriteFilesBatchTool()
    inp = WriteFilesBatchTool.Input(
        files=[
            BatchFileItem(path="clean1.txt", content="Clean 1", mode="overwrite"),
        ]
    )
    result = tool.execute(inp)
    assert result.success is True

    # Check that no leftover staging or backup directories exist
    leftover = [
        p for p in temp_dir.iterdir()
        if p.is_dir() and (p.name.startswith(staging_prefix) or p.name.startswith(backup_prefix))
    ]
    assert len(leftover) == 0
