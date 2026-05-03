# tests/test_tools.py
# Test suite for tools/file_tools.py
# Run with: pytest tests/test_tools.py -v

from pathlib import Path

import pytest

from tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool
from tools.shell_tools import BashExecTool, RunPythonTool, RunTestsTool


def test_read_file_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ReadFileTool returns the contents of an existing file."""
    monkeypatch.chdir(tmp_path)
    file_path: Path = tmp_path / "sample.txt"
    file_path.write_text("hello hermes", encoding="utf-8")

    result = ReadFileTool().execute(ReadFileTool.Input(path="sample.txt"))

    assert result.success is True
    assert "hello hermes" in result.output


def test_read_file_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ReadFileTool returns exit_code 1 for a missing file."""
    monkeypatch.chdir(tmp_path)

    result = ReadFileTool().execute(ReadFileTool.Input(path="missing.txt"))

    assert result.success is False
    assert result.exit_code == 1


def test_write_file_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WriteFileTool creates a file and writes content to it."""
    monkeypatch.chdir(tmp_path)
    file_path: Path = tmp_path / "nested" / "sample.txt"

    result = WriteFileTool().execute(
        WriteFileTool.Input(path="nested/sample.txt", content="created")
    )

    assert result.success is True
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "created"


def test_write_file_append_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WriteFileTool appends content when mode is append."""
    monkeypatch.chdir(tmp_path)
    file_path: Path = tmp_path / "append.txt"
    WriteFileTool().execute(WriteFileTool.Input(path="append.txt", content="first"))

    result = WriteFileTool().execute(
        WriteFileTool.Input(path="append.txt", content="second", mode="append")
    )

    assert result.success is True
    assert file_path.read_text(encoding="utf-8") == "firstsecond"


def test_list_directory_shows_files_and_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ListDirectoryTool shows files and folders with the expected prefixes."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "folder").mkdir()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("bb", encoding="utf-8")

    result = ListDirectoryTool().execute(ListDirectoryTool.Input(path="."))

    assert result.success is True
    assert "[DIR]  folder" in result.output
    assert "[FILE] a.txt (1 bytes)" in result.output
    assert "[FILE] b.txt (2 bytes)" in result.output


def test_list_directory_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ListDirectoryTool returns success False for a nonexistent directory."""
    monkeypatch.chdir(tmp_path)

    result = ListDirectoryTool().execute(ListDirectoryTool.Input(path="missing"))

    assert result.success is False


# ── bash_exec tests ──────────────────────────────────────────────────


def test_bash_exec_runs_simple_command():
    tool = BashExecTool()
    result = tool.execute(BashExecTool.Input(command="echo hello_hermes"))
    assert result.success is True
    assert "hello_hermes" in result.output
    assert result.exit_code == 0


def test_bash_exec_captures_exit_code():
    tool = BashExecTool()
    result = tool.execute(BashExecTool.Input(command="exit 42", timeout_seconds=5))
    assert result.exit_code == 42
    assert result.success is False


def test_bash_exec_blocks_dangerous_command():
    tool = BashExecTool()
    result = tool.execute(BashExecTool.Input(command="rm -rf /"))
    assert result.success is False
    assert result.exit_code == 126
    assert "BLOCKED" in result.error


def test_bash_exec_captures_stderr():
    tool = BashExecTool()
    result = tool.execute(BashExecTool.Input(command="ls /nonexistent_path_xyz"))
    assert result.success is False
    assert result.exit_code != 0


def test_bash_exec_timeout():
    tool = BashExecTool()
    result = tool.execute(BashExecTool.Input(command="sleep 10", timeout_seconds=1))
    assert result.success is False
    assert result.exit_code == 124
    assert "timed out" in result.error.lower()


# ── run_python tests ─────────────────────────────────────────────────


def test_run_python_executes_file(tmp_path):
    # Create a real Python file that prints a unique string
    script = tmp_path / "test_script.py"
    script.write_text('print("HERMES_RUN_PYTHON_TEST_OK")\n')

    tool = RunPythonTool()
    result = tool.execute(RunPythonTool.Input(file_path=str(script)))
    assert result.success is True
    assert "HERMES_RUN_PYTHON_TEST_OK" in result.output
    assert result.exit_code == 0


def test_run_python_captures_script_error(tmp_path):
    script = tmp_path / "bad_script.py"
    script.write_text('raise ValueError("intentional test error")\n')

    tool = RunPythonTool()
    result = tool.execute(RunPythonTool.Input(file_path=str(script)))
    assert result.success is False
    assert result.exit_code != 0


def test_run_python_file_not_found():
    tool = RunPythonTool()
    result = tool.execute(RunPythonTool.Input(file_path="nonexistent_script.py"))
    assert result.success is False
    assert "not found" in result.error.lower()


# ── run_tests tests ──────────────────────────────────────────────────


def test_run_tests_on_passing_test(tmp_path):
    # Create a simple passing test file
    test_file = tmp_path / "test_simple.py"
    test_file.write_text("def test_always_passes():\n    assert 1 + 1 == 2\n")

    tool = RunTestsTool()
    result = tool.execute(RunTestsTool.Input(test_path=str(test_file)))
    assert result.success is True
    assert "passed" in result.output.lower()


def test_run_tests_on_failing_test(tmp_path):
    test_file = tmp_path / "test_failing.py"
    test_file.write_text("def test_always_fails():\n    assert 1 == 2\n")

    tool = RunTestsTool()
    result = tool.execute(RunTestsTool.Input(test_path=str(test_file)))
    assert result.success is False
    assert result.exit_code != 0
