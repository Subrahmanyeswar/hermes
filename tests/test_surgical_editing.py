# tests/test_surgical_editing.py
"""
Comprehensive Test Suite for Prompt 6: Surgical Editing and Active Exploration.
Verifies line-addressable reads, exact surgical edits, stale-file detection,
CRLF/LF preservation, diff minimality, postcondition syntax checks, atomic writes,
bounded glob/grep, and workspace discovery.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import pytest

from core.workspace import WorkspaceManager
from tools.platform.catalog import tool_catalog
from tools.platform.executor import ToolExecutor
from tools.platform.core_tools import (
    FSReadTool,
    FSEditTool,
    FSWriteTool,
    SearchGlobTool,
    SearchGrepTool,
)
from tools.platform.file_identity import file_identity_cache, FileIdentity
from tools.platform.workspace_discovery import workspace_discovery, WorkspaceProfile
from tools.platform.errors import ToolErrorCode


# ─────────────────────────────────────────────────────────────────────────────
# 1. fs.read Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_fs_read_line_addressable_with_numbering(tmp_path):
    """fs.read returns 1-based line-numbered output with file header."""
    sample = tmp_path / "app.py"
    lines = [f"line_{i} = {i}" for i in range(1, 21)]
    sample.write_text("\n".join(lines), encoding="utf-8")

    tool = FSReadTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(sample),
        "start_line": 5,
        "end_line": 10,
    })

    assert res.success is True
    assert "Lines: 5-10 of 20" in res.output
    assert " 5 | line_5 = 5" in res.output
    assert "10 | line_10 = 10" in res.output
    assert "line_4" not in res.output
    assert "line_11" not in res.output


def test_fs_read_offset_and_limit_aliases(tmp_path):
    """fs.read supports offset and limit as aliases for start_line and max_lines."""
    sample = tmp_path / "test.txt"
    sample.write_text("\n".join(f"item_{i}" for i in range(1, 31)), encoding="utf-8")

    tool = FSReadTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(sample),
        "offset": 10,
        "limit": 5,
    })

    assert res.success is True
    assert "Lines: 10-14 of 30" in res.output
    assert "10 | item_10" in res.output
    assert "14 | item_14" in res.output
    assert "item_15" not in res.output


def test_fs_read_missing_file_with_suggestions(tmp_path):
    """fs.read provides real workspace suggestions when requested file does not exist."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    (tmp_path / "config.py").write_text("API_KEY = 'secret'")
    (tmp_path / "auth_service.py").write_text("def auth(): pass")

    tool = FSReadTool()
    res = tool.execute({
        "_workspace": wm,
        "path": "conf.py",
    })

    assert res.success is False
    assert "File not found" in res.error
    assert "config.py" in res.error
    assert res.details.get("code") == ToolErrorCode.FILE_NOT_FOUND.value


def test_fs_read_binary_file_rejection(tmp_path):
    """fs.read detects binary files with null bytes and rejects them cleanly."""
    bin_file = tmp_path / "image.png"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    tool = FSReadTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(bin_file),
    })

    assert res.success is False
    assert "Cannot read binary file" in res.error
    assert str(len(bin_file.read_bytes())) in res.error


def test_fs_read_large_file_default_policy(tmp_path):
    """fs.read defaults to first 200 lines with truncation banner on large files."""
    large_file = tmp_path / "big.log"
    large_file.write_text("\n".join(f"log entry {i}" for i in range(1, 800)), encoding="utf-8")

    tool = FSReadTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(large_file),
    })

    assert res.success is True
    assert "Lines: 1-200 of 799" in res.output
    assert "TRUNCATED" in res.output
    assert "offset=201" in res.output


def test_fs_read_detailed_format_reports_crlf_and_hash(tmp_path):
    """fs.read with response_format=detailed includes encoding, newline style, and hash."""
    crlf_file = tmp_path / "windows.txt"
    crlf_file.write_bytes(b"hello\r\nworld\r\n")

    tool = FSReadTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(crlf_file),
        "response_format": "detailed",
    })

    assert res.success is True
    assert "newline: CRLF" in res.output
    assert "sha256:" in res.output


# ─────────────────────────────────────────────────────────────────────────────
# 2. fs.edit Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_fs_edit_exact_one_match_success(tmp_path):
    """fs.edit replaces exact target and produces concise summary + diff."""
    f = tmp_path / "server.py"
    f.write_text("port = 8080\nhost = '0.0.0.0'\n", encoding="utf-8")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "port = 8080",
        "new_string": "port = 9000",
    })

    assert res.success is True
    assert "Replaced 1 occurrence(s)" in res.output
    assert f.read_text(encoding="utf-8") == "port = 9000\nhost = '0.0.0.0'\n"
    assert "-port = 8080" in res.output
    assert "+port = 9000" in res.output


def test_fs_edit_zero_matches_fails_safely(tmp_path):
    """fs.edit fails with EDIT_TARGET_NOT_FOUND when target is missing."""
    f = tmp_path / "config.py"
    original = "timeout = 30\n"
    f.write_text(original, encoding="utf-8")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "timeout = 100",
        "new_string": "timeout = 60",
    })

    assert res.success is False
    assert "EDIT_TARGET_NOT_FOUND" in res.error
    assert res.details.get("code") == ToolErrorCode.EDIT_TARGET_NOT_FOUND.value
    # Assert file unmodified
    assert f.read_text(encoding="utf-8") == original


def test_fs_edit_ambiguous_target_fails_with_match_line_numbers(tmp_path):
    """fs.edit fails with EDIT_TARGET_NOT_UNIQUE and lists all line numbers when ambiguous."""
    f = tmp_path / "dup.py"
    content = "val = 1\n# comment\nval = 1\n# another\nval = 1\n"
    f.write_text(content, encoding="utf-8")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "val = 1",
        "new_string": "val = 2",
        "expected_occurrences": 1,
    })

    assert res.success is False
    assert "EDIT_TARGET_NOT_UNIQUE" in res.error
    assert "line 1, line 3, line 5" in res.error
    assert res.details.get("matches_count") == 3
    assert res.details.get("matches_lines") == [1, 3, 5]
    # Verify file unmodified
    assert f.read_text(encoding="utf-8") == content


def test_fs_edit_replace_all_success(tmp_path):
    """fs.edit replaces all matches when replace_all=True is explicitly specified."""
    f = tmp_path / "multi.py"
    f.write_text("x = 10\ny = 10\nz = 10\n", encoding="utf-8")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "10",
        "new_string": "20",
        "replace_all": True,
    })

    assert res.success is True
    assert "Replaced 3 occurrence(s)" in res.output
    assert f.read_text(encoding="utf-8") == "x = 20\ny = 20\nz = 20\n"


def test_fs_edit_preserves_crlf_line_endings(tmp_path):
    """fs.edit preserves CRLF line endings on Windows / CRLF files."""
    f = tmp_path / "crlf_sample.py"
    f.write_bytes(b"def a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2\r\n")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "return 1",
        "new_string": "return 42",
    })

    assert res.success is True
    updated_bytes = f.read_bytes()
    assert b"\r\n" in updated_bytes
    # Ensure no lone LF was introduced
    raw_text = updated_bytes.decode("utf-8")
    assert raw_text.count("\r\n") == 5
    assert raw_text.replace("\r\n", "").count("\n") == 0



def test_fs_edit_minimality_regression(tmp_path):
    """2-line edit in a 100-line file only changes exactly the targeted lines."""
    f = tmp_path / "long_file.py"
    lines = [f"var_{i} = {i}" for i in range(1, 101)]
    lines[49] = "target_key = 'old_value'"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "target_key = 'old_value'",
        "new_string": "target_key = 'new_value'",
    })

    assert res.success is True
    assert "+1/-1 lines" in res.output

    updated_lines = f.read_text(encoding="utf-8").splitlines()
    assert len(updated_lines) == 100
    assert updated_lines[49] == "target_key = 'new_value'"
    for i in range(100):
        if i != 49:
            assert updated_lines[i] == lines[i]


def test_fs_edit_suspicious_large_diff_protection(tmp_path):
    """fs.edit blocks small target replacing entire file when allow_large_diff=False."""
    f = tmp_path / "big_rewrite.py"
    f.write_text("\n".join(f"line_{i} = {i}" for i in range(1, 100)) + "\n", encoding="utf-8")

    tool = FSEditTool()
    # Replacing single line with 250 lines without allow_large_diff
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "line_5 = 5",
        "new_string": "\n".join(f"new_line_{i} = {i}" for i in range(250)),
        "allow_large_diff": False,
    })

    assert res.success is False
    assert "EDIT_SUSPICIOUS_LARGE_DIFF" in res.error
    assert res.details.get("code") == ToolErrorCode.EDIT_SUSPICIOUS_LARGE_DIFF.value


def test_fs_edit_stale_file_protection(tmp_path):
    """fs.edit fails with EDIT_FILE_CHANGED if file was modified externally after being read."""
    f = tmp_path / "stale_target.py"
    f.write_text("counter = 0\n", encoding="utf-8")

    # 1. Read file to record identity in cache
    read_tool = FSReadTool()
    read_res = read_tool.execute({"_workspace": None, "path": str(f)})
    assert read_res.success is True

    # 2. External process modifies the file on disk
    f.write_text("counter = 999\n# external edit\n", encoding="utf-8")

    # 3. Edit using stale expectation
    edit_tool = FSEditTool()
    edit_res = edit_tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "counter = 0",
        "new_string": "counter = 1",
    })

    assert edit_res.success is False
    assert "EDIT_FILE_CHANGED" in edit_res.error
    assert edit_res.details.get("code") == ToolErrorCode.EDIT_FILE_CHANGED.value


def test_fs_edit_python_syntax_postcondition_rollback(tmp_path):
    """fs.edit rolls back file changes if edit introduces Python syntax error."""
    f = tmp_path / "valid.py"
    original_code = "def calculate():\n    return 42\n"
    f.write_text(original_code, encoding="utf-8")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "return 42",
        "new_string": "return (42 +",  # Syntax error: unclosed parenthesis
    })

    assert res.success is False
    assert "EDIT_POSTCONDITION_FAILED" in res.error
    assert "Python syntax error" in res.error
    # File must be restored to original valid syntax
    assert f.read_text(encoding="utf-8") == original_code


def test_fs_edit_json_syntax_postcondition_rollback(tmp_path):
    """fs.edit rolls back file changes if edit produces invalid JSON."""
    f = tmp_path / "data.json"
    original_json = '{\n  "version": 1\n}\n'
    f.write_text(original_json, encoding="utf-8")

    tool = FSEditTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": '"version": 1',
        "new_string": '"version": 1, trailing_comma:',  # Invalid JSON
    })

    assert res.success is False
    assert "EDIT_POSTCONDITION_FAILED" in res.error
    assert "JSON syntax error" in res.error
    assert f.read_text(encoding="utf-8") == original_json


# ─────────────────────────────────────────────────────────────────────────────
# 3. fs.write Safety Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_fs_write_creation_and_overwrite_protection(tmp_path):
    """fs.write requires allow_overwrite=True to overwrite existing file."""
    f = tmp_path / "immutable.txt"
    f.write_text("original content")

    tool = FSWriteTool()
    # Attempt overwrite with allow_overwrite=False
    res_blocked = tool.execute({
        "_workspace": None,
        "path": str(f),
        "content": "new content",
        "allow_overwrite": False,
    })
    assert res_blocked.success is False
    assert "FILE_EXISTS_OVERWRITE_REQUIRED" in res_blocked.error
    assert f.read_text() == "original content"

    # Attempt overwrite with allow_overwrite=True
    res_allowed = tool.execute({
        "_workspace": None,
        "path": str(f),
        "content": "new content",
        "allow_overwrite": True,
    })
    assert res_allowed.success is True
    assert f.read_text() == "new content"


# ─────────────────────────────────────────────────────────────────────────────
# 4. search.glob & search.grep Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_search_glob_filters_noise_directories(tmp_path):
    """search.glob ignores .git, node_modules, and __pycache__ folders."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("pass")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.py").write_text("pass")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hook.py").write_text("pass")

    tool = SearchGlobTool()
    res = tool.execute({
        "_workspace": None,
        "base_path": str(tmp_path),
        "pattern": "**/*.py",
    })

    assert res.success is True
    assert "src/main.py" in res.output or "src\\main.py" in res.output
    assert "node_modules" not in res.output
    assert ".git" not in res.output


def test_search_grep_line_addressable_and_context(tmp_path):
    """search.grep returns line numbers and context lines."""
    src = tmp_path / "logic.py"
    src.write_text(
        "def setup():\n"
        "    init_db()\n"
        "    EventBus.publish('init')\n"
        "    start_server()\n",
        encoding="utf-8",
    )

    tool = SearchGrepTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(src),
        "pattern": "EventBus.publish",
        "context_lines": 1,
    })

    assert res.success is True
    assert "3:" in res.output
    assert "EventBus.publish" in res.output
    assert "2:     init_db()" in res.output
    assert "4:     start_server()" in res.output


def test_search_grep_invalid_regex_returns_structured_error(tmp_path):
    """search.grep returns GREP_INVALID_PATTERN with guidance when regex is malformed."""
    tool = SearchGrepTool()
    res = tool.execute({
        "_workspace": None,
        "path": str(tmp_path),
        "pattern": "[unclosed bracket",
    })

    assert res.success is False
    assert "GREP_INVALID_PATTERN" in res.error
    assert res.details.get("code") == ToolErrorCode.GREP_INVALID_PATTERN.value


# ─────────────────────────────────────────────────────────────────────────────
# 5. Workspace Discovery Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_workspace_discovery_profile(tmp_path):
    """workspace_discovery detects manifests, source roots, test roots, and project types."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("pass")
    (tmp_path / "README.md").write_text("# Demo Project")

    profile = workspace_discovery.discover(tmp_path, force_refresh=True)

    assert "python" in profile.project_types
    assert "pyproject.toml" in profile.manifest_files
    assert "src" in profile.source_roots
    assert "tests" in profile.test_roots
    assert "README.md" in profile.important_files

    summary = profile.to_summary_text()
    assert "Project Type: python" in summary
    assert "Manifests: pyproject.toml" in summary


# ─────────────────────────────────────────────────────────────────────────────
# 6. Integration: Progressive Exploration to Surgical Edit
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_integration_explore_to_surgical_edit(tmp_path):
    """
    Simulates real agent loop workflow:
    Glob/Grep to find symbol -> Read targeted range -> Surgical edit -> Verify.
    """
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    # Setup realistic repo fixture
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    cfg_file = src_dir / "config.py"
    cfg_file.write_text(
        "# Server Configuration\n"
        "APP_ENV = 'production'\n"
        "API_TIMEOUT = 30\n"
        "MAX_RETRIES = 5\n"
        "LOG_LEVEL = 'INFO'\n",
        encoding="utf-8",
    )
    auth_file = src_dir / "auth.py"
    auth_file.write_text("def auth(): pass\n", encoding="utf-8")

    executor = ToolExecutor(mode="auto")

    # Step 1: Grep for API_TIMEOUT
    grep_res = await executor.execute(
        tool_name="search.grep",
        arguments={"pattern": "API_TIMEOUT"},
        workspace=wm,
    )
    assert grep_res.success is True
    assert "config.py:3:" in grep_res.observation_text

    # Step 2: Read targeted line range around line 3
    read_res = await executor.execute(
        tool_name="fs.read",
        arguments={"path": "src/config.py", "start_line": 2, "end_line": 4},
        workspace=wm,
    )
    assert read_res.success is True
    assert "3 | API_TIMEOUT = 30" in read_res.observation_text

    # Step 3: Surgical edit with exact string
    edit_res = await executor.execute(
        tool_name="fs.edit",
        arguments={
            "path": "src/config.py",
            "old_string": "API_TIMEOUT = 30",
            "new_string": "API_TIMEOUT = 60",
        },
        workspace=wm,
    )
    assert edit_res.success is True
    assert "Replaced 1 occurrence(s)" in edit_res.observation_text

    # Step 4: Verify resulting file content and ensure unrelated code is untouched
    updated_cfg = cfg_file.read_text(encoding="utf-8")
    assert "API_TIMEOUT = 60" in updated_cfg
    assert "APP_ENV = 'production'" in updated_cfg
    assert "MAX_RETRIES = 5" in updated_cfg
    assert "LOG_LEVEL = 'INFO'" in updated_cfg
    assert auth_file.read_text(encoding="utf-8") == "def auth(): pass\n"
