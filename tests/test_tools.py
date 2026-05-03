# tests/test_tools.py
# Test suite for tools/file_tools.py
# Run with: pytest tests/test_tools.py -v

from pathlib import Path

import pytest

from tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool


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
