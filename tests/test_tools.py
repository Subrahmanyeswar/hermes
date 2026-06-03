# tests/test_tools.py
# Test suite for tools/file_tools.py
# Run with: pytest tests/test_tools.py -v

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import git as gitpython

from tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool, AppendFileTool, CreateFolderTool, MoveFileTool, DeleteFileTool
from tools.git_tools import GitAddCommitTool, GitInitTool, GitPushTool
from tools.network_tools import WebFetchTool, WebSearchTool
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


# ── network tool tests ────────────────────────────────────────────────


def test_web_search_returns_formatted_results():
    """Mock the DuckDuckGo API response and verify formatting."""
    mock_response_data = {
        "AbstractText": "Python is a programming language.",
        "AbstractURL": "https://python.org",
        "RelatedTopics": [
            {
                "Text": "Python tutorial for beginners",
                "FirstURL": "https://docs.python.org/tutorial",
            },
            {
                "Text": "Python download page",
                "FirstURL": "https://python.org/downloads",
            },
        ],
    }
    mock_response = MagicMock()
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_response):
        tool = WebSearchTool()
        result = tool.execute(
            WebSearchTool.Input(query="Python programming", max_results=3)
        )

    assert result.success is True
    assert "Python" in result.output
    assert "https://python.org" in result.output
    assert result.exit_code == 0


def test_web_search_handles_timeout():
    with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
        tool = WebSearchTool()
        result = tool.execute(WebSearchTool.Input(query="test query"))
    assert result.success is False
    assert "timed out" in result.error.lower()


def test_web_search_handles_connection_error():
    with patch("httpx.get", side_effect=httpx.ConnectError("no connection")):
        tool = WebSearchTool()
        result = tool.execute(WebSearchTool.Input(query="test"))
    assert result.success is False
    assert "connect" in result.error.lower()


def test_web_fetch_returns_text_content():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = (
        "<html><body><h1>Hello World</h1><p>This is a test page.</p></body></html>"
    )
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_response):
        tool = WebFetchTool()
        result = tool.execute(WebFetchTool.Input(url="https://example.com"))

    assert result.success is True
    assert "Hello World" in result.output
    assert "<html>" not in result.output  # HTML tags should be stripped


def test_web_fetch_rejects_non_http_url():
    tool = WebFetchTool()
    result = tool.execute(WebFetchTool.Input(url="ftp://example.com/file.txt"))
    assert result.success is False
    assert "http" in result.error.lower()


def test_web_fetch_truncates_at_max_chars():
    long_content = "A" * 10000
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.text = long_content
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_response):
        tool = WebFetchTool()
        result = tool.execute(WebFetchTool.Input(url="https://example.com", max_chars=500))

    assert result.success is True
    assert len(result.output) <= 500


# ── git tool tests ────────────────────────────────────────────────────


def test_git_init_creates_repository(tmp_path):
    tool = GitInitTool()
    result = tool.execute(GitInitTool.Input(directory=str(tmp_path / "myrepo")))
    assert result.success is True
    assert "initialised" in result.output.lower() or "already exists" in result.output.lower()
    # Verify it's actually a git repo
    repo = gitpython.Repo(str(tmp_path / "myrepo"))
    assert repo.git_dir is not None


def test_git_init_on_existing_repo_returns_success(tmp_path):
    """Calling git_init twice should succeed both times."""
    tool = GitInitTool()
    tool.execute(GitInitTool.Input(directory=str(tmp_path)))
    result = tool.execute(GitInitTool.Input(directory=str(tmp_path)))
    assert result.success is True


def test_git_init_creates_gitignore(tmp_path):
    tool = GitInitTool()
    tool.execute(GitInitTool.Input(directory=str(tmp_path)))
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert "__pycache__" in gitignore.read_text()


def test_git_add_commit_creates_commit(tmp_path):
    # Set up: init repo and create a file
    gitpython.Repo.init(str(tmp_path))
    test_file = tmp_path / "hello.py"
    test_file.write_text('print("hello")\n')

    tool = GitAddCommitTool()
    result = tool.execute(
        GitAddCommitTool.Input(directory=str(tmp_path), message="Add hello.py")
    )
    assert result.success is True
    assert "hello.py" in result.output or "1 file" in result.output.lower()
    assert "SHA" in result.output  # should include short SHA


def test_git_add_commit_nothing_to_commit(tmp_path):
    """Clean working tree should return success with 'nothing to commit' message."""
    repo = gitpython.Repo.init(str(tmp_path))
    test_file = tmp_path / "file.py"
    test_file.write_text("x = 1\n")
    repo.index.add(["file.py"])
    repo.index.commit("initial commit")

    tool = GitAddCommitTool()
    result = tool.execute(
        GitAddCommitTool.Input(directory=str(tmp_path), message="nothing should happen")
    )
    assert result.success is True
    assert "nothing" in result.output.lower() or "clean" in result.output.lower()


def test_git_commit_fails_without_repo(tmp_path):
    """Committing in a non-repo directory should fail gracefully."""
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    tool = GitAddCommitTool()
    result = tool.execute(
        GitAddCommitTool.Input(directory=str(non_repo), message="this should fail")
    )
    assert result.success is False
    assert "git_init" in result.error.lower() or "repository" in result.error.lower()

# ── memory tool tests ─────────────────────────────────────────────────
from tools.memory_tools import SaveMemoryTool, ReadMemoryTool
from unittest.mock import patch
import pytest

def test_save_memory_tool_writes_fact():
    with patch("tools.memory_tools.write_fact", return_value=True) as mock_write:
        tool = SaveMemoryTool()
        result = tool.execute(SaveMemoryTool.Input(
            fact_type="FACT",
            content="Uses Flask 3.1 with SQLAlchemy",
            project="testproject"
        ))
    assert result.success is True
    assert mock_write.called
    assert "FACT" in result.output

def test_save_memory_tool_validates_max_length():
    tool = SaveMemoryTool()
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SaveMemoryTool.Input(fact_type="FACT", content="A" * 151)  # over 150 chars

def test_read_memory_tool_returns_content():
    with patch("tools.memory_tools.read_layer2_topic", return_value="# DB Schema\nTable: users"):
        tool = ReadMemoryTool()
        result = tool.execute(ReadMemoryTool.Input(topic_name="database_schema", project="myapp"))
    assert result.success is True
    assert "users" in result.output

def test_read_memory_tool_returns_failure_for_missing():
    with patch("tools.memory_tools.read_layer2_topic", return_value=None):
        tool = ReadMemoryTool()
        result = tool.execute(ReadMemoryTool.Input(topic_name="nonexistent", project="myapp"))
    assert result.success is False
    assert result.exit_code == 1


# ── File System tool additions tests ──────────────────────────────────

def test_append_file_creates_if_missing(tmp_path):
    tool = AppendFileTool()
    result = tool.execute(AppendFileTool.Input(path=str(tmp_path/"new.txt"), content="hello"))
    assert result.success and (tmp_path/"new.txt").read_text() == "hello"

def test_append_file_adds_to_existing(tmp_path):
    p = tmp_path/"log.txt"
    p.write_text("line1\n")
    tool = AppendFileTool()
    tool.execute(AppendFileTool.Input(path=str(p), content="line2\n"))
    assert p.read_text() == "line1\nline2\n"

def test_create_folder_creates_nested(tmp_path):
    result = CreateFolderTool().execute(CreateFolderTool.Input(path=str(tmp_path/"a/b/c")))
    assert result.success and (tmp_path/"a/b/c").is_dir()

def test_move_file_succeeds(tmp_path):
    src = tmp_path/"src.txt"; src.write_text("data")
    result = MoveFileTool().execute(MoveFileTool.Input(source=str(src), destination=str(tmp_path/"dst.txt")))
    assert result.success and (tmp_path/"dst.txt").exists() and not src.exists()

def test_delete_file_requires_confirm(tmp_path):
    p = tmp_path/"del.txt"; p.write_text("x")
    result = DeleteFileTool().execute(DeleteFileTool.Input(path=str(p), confirm=False))
    assert not result.success and p.exists()

def test_delete_file_succeeds_with_confirm(tmp_path):
    p = tmp_path/"del.txt"; p.write_text("x")
    result = DeleteFileTool().execute(DeleteFileTool.Input(path=str(p), confirm=True))
    assert result.success and not p.exists()


# ── Export tool tests (Week 17) ────────────────────────────────────────
from tools.export_tools import ExportZipTool, OpenInVSCodeTool

def test_export_zip_creates_valid_zip(tmp_path):
    """export_zip must create a real, openable ZIP file."""
    import zipfile

    # Create a project with some files
    proj = tmp_path / "myproject"
    proj.mkdir()
    (proj / "app.py").write_text('print("hello")\n')
    (proj / "requirements.txt").write_text("flask==3.0.0\n")
    sub = proj / "src"
    sub.mkdir()
    (sub / "models.py").write_text("# models\n")

    tool = ExportZipTool()
    result = tool.execute(ExportZipTool.Input(
        project_path=str(proj),
        output_name="test_export_week17",
    ))

    assert result.success is True, f"export_zip failed: {result.error}"
    assert result.exit_code == 0

    # Extract ZIP path from output
    zip_path = None
    for line in result.output.split("\n"):
        if line.startswith("Path:"):
            zip_path = line.split("Path:")[1].strip()
            break

    assert zip_path is not None, "ZIP path not in output"
    assert Path(zip_path).exists(), f"ZIP file not found at {zip_path}"

    # Verify it is a valid ZIP
    assert zipfile.is_zipfile(zip_path), "Created file is not a valid ZIP"

    # Verify contents
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert any("app.py" in n for n in names), f"app.py not in ZIP: {names}"

def test_export_zip_fails_for_nonexistent_path():
    tool = ExportZipTool()
    result = tool.execute(ExportZipTool.Input(
        project_path="/nonexistent/path/xyz",
    ))
    assert result.success is False
    assert result.exit_code == 1
    assert "not found" in result.error.lower()

def test_export_zip_fails_for_file_not_directory(tmp_path):
    """export_zip must reject a file path — only directories allowed."""
    f = tmp_path / "single_file.py"
    f.write_text("x = 1\n")
    tool = ExportZipTool()
    result = tool.execute(ExportZipTool.Input(project_path=str(f)))
    assert result.success is False
    assert "not a directory" in result.error.lower()

def test_open_in_vscode_fails_gracefully_when_code_not_found(monkeypatch):
    """open_in_vscode must return clean error when 'code' is not in PATH."""
    import subprocess as sp
    monkeypatch.setattr(
        sp, "Popen",
        lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("code not found"))
    )
    tool = OpenInVSCodeTool()
    result = tool.execute(OpenInVSCodeTool.Input(path="."))
    assert result.success is False
    assert result.exit_code == 127
    assert "VS Code" in result.error

def test_open_in_vscode_fails_for_nonexistent_path():
    tool = OpenInVSCodeTool()
    result = tool.execute(OpenInVSCodeTool.Input(path="/nonexistent/path/xyz"))
    assert result.success is False
    assert "does not exist" in result.error.lower()

def test_git_push_fails_without_github_token(monkeypatch):
    """git_push must return a clear error when GITHUB_TOKEN is not set."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from tools.git_tools import GitPushTool
    tool = GitPushTool()
    result = tool.execute(GitPushTool.Input(directory="."))
    assert result.success is False
    assert "GITHUB_TOKEN" in result.error

def test_git_push_fails_without_repo(tmp_path, monkeypatch):
    """git_push must fail cleanly when directory is not a git repo."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token_for_testing_only")
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    from tools.git_tools import GitPushTool
    tool = GitPushTool()
    result = tool.execute(GitPushTool.Input(directory=str(non_repo)))
    assert result.success is False
    assert "git_init" in result.error.lower() or "repository" in result.error.lower()

def test_git_push_token_never_in_error_message(monkeypatch, tmp_path):
    """The GITHUB_TOKEN value must never appear in any error output."""
    secret_token = "ghp_SUPER_SECRET_TOKEN_1234567890"
    monkeypatch.setenv("GITHUB_TOKEN", secret_token)
    from tools.git_tools import GitPushTool
    tool = GitPushTool()
    # Push to a non-repo — will fail before token is used in URL
    result = tool.execute(GitPushTool.Input(directory=str(tmp_path)))
    assert secret_token not in (result.error or "")
    assert secret_token not in (result.output or "")


# ── Vision tool tests (Week 17) ────────────────────────────────────────
from tools.vision_tools import ScreenshotToCodeTool

def test_screenshot_to_code_fails_for_missing_image():
    tool = ScreenshotToCodeTool()
    result = tool.execute(ScreenshotToCodeTool.Input(
        image_path="/nonexistent/screenshot.png"
    ))
    assert result.success is False
    assert "not found" in result.error.lower()
    assert result.exit_code == 1

def test_screenshot_to_code_fails_for_unsupported_format(tmp_path):
    """Unsupported image format must return clear error."""
    bad_file = tmp_path / "image.bmp"
    bad_file.write_bytes(b"BM fake bitmap data")
    tool = ScreenshotToCodeTool()
    result = tool.execute(ScreenshotToCodeTool.Input(
        image_path=str(bad_file)
    ))
    assert result.success is False
    assert "unsupported" in result.error.lower()

def test_screenshot_to_code_clean_code_output_strips_fences():
    """_clean_code_output must strip markdown fences."""
    tool = ScreenshotToCodeTool()
    raw = "```html\n<!DOCTYPE html>\n<html>\n<body>test</body>\n</html>\n```"
    cleaned = tool._clean_code_output(raw, "html")
    assert cleaned.startswith("<!DOCTYPE html>")
    assert "```" not in cleaned

def test_screenshot_to_code_clean_code_react_strips_fences():
    tool = ScreenshotToCodeTool()
    raw = "```jsx\nimport React from 'react';\nexport default function App() { return <div/>; }\n```"
    cleaned = tool._clean_code_output(raw, "react")
    assert "import React" in cleaned
    assert "```" not in cleaned

def test_screenshot_to_code_handles_ollama_connection_error(tmp_path):
    """Must return clean error when Ollama is not running."""
    # Create a real PNG file
    png_path = tmp_path / "test.png"
    # Minimal valid PNG (1x1 red pixel)
    import base64 as b64
    minimal_png = b64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )
    png_path.write_bytes(minimal_png)

    tool = ScreenshotToCodeTool()
    result = tool.execute(ScreenshotToCodeTool.Input(
        image_path=str(png_path),
        ollama_url="http://localhost:99999",  # Non-existent port
        output_file=str(tmp_path / "output.html"),
    ))
    assert result.success is False
    # Should be either connection error or timeout
    assert result.exit_code != 0
