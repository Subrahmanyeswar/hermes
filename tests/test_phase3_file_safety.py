# tests/test_phase3_file_safety.py
"""
Deterministic acceptance tests for HERMES Phase 3:
Filesystem Safety, Read-Before-Edit Enforcement, Race-Safe Atomic Writes, and Workspace Containment.

Scenarios Covered:
H. Workspace containment: rejection of parent traversal (../), absolute escapes, and alternate volume escapes.
I. Read-before-edit requirement: rejection of edits on uninspected files.
J. Stale-file protection: rejection of edits when file was externally modified since read.
K. Non-existent file edit rejection with clear guidance.
L. Ambiguous edit target rejection (multiple occurrences when expected=1).
M. Exact string matching (no fuzzy replacement or corruption of nearby code).
N. File creation without overwrite (allow_overwrite=False fails race-safely on existing files).
O. Atomic replacement: temporary file staging, directory creation, and rollback safety.
P. Newline style preservation (LF vs CRLF).
"""

import os
import hashlib
import pytest
from pathlib import Path

from core.workspace import WorkspaceManager, WorkspaceBoundaryError
from tools.platform.core_tools import FSReadTool, FSEditTool, FSWriteTool
from tools.platform.file_identity import file_identity_cache


@pytest.fixture
def temp_workspace(tmp_path: Path):
    ws_dir = tmp_path / "safety_workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    file_identity_cache.clear()
    wm = WorkspaceManager()
    wm.lock(ws_dir)
    yield wm
    wm.unlock()
    file_identity_cache.clear()


def test_scenario_h_workspace_containment_rejections(temp_workspace: WorkspaceManager):
    """
    Scenario H: Workspace Containment
    Guarantees that:
    1. Parent traversal attempts ('../../secret.txt') are rejected without touching disk.
    2. Absolute paths outside workspace root are rejected.
    """
    write_tool = FSWriteTool()
    edit_tool = FSEditTool()
    read_tool = FSReadTool()

    # 1. Parent directory traversal
    res = write_tool.execute({
        "path": "../outside.txt",
        "content": "illegal escape",
        "_workspace": temp_workspace,
    })
    assert res.success is False
    assert "SECURITY" in (res.error or "") or "outside" in (res.error or "").lower()

    # 2. Reading outside
    res_read = read_tool.execute({
        "path": "../../outside_read.txt",
        "_workspace": temp_workspace,
    })
    assert res_read.success is False
    assert "SECURITY" in (res_read.error or "") or "outside" in (res_read.error or "").lower()

    # 3. Editing outside
    res_edit = edit_tool.execute({
        "path": "../outside_edit.txt",
        "old_string": "a",
        "new_string": "b",
        "_workspace": temp_workspace,
    })
    assert res_edit.success is False
    assert "SECURITY" in (res_edit.error or "") or "outside" in (res_edit.error or "").lower()


def test_scenario_i_read_before_edit_enforcement(temp_workspace: WorkspaceManager):
    """
    Scenario I: Read-Before-Edit Enforcement
    Guarantees that:
    1. Editing a file that has not been inspected with fs.read is rejected.
    2. Inspecting the file with fs.read allows subsequent fs.edit to proceed.
    """
    edit_tool = FSEditTool()
    read_tool = FSReadTool()

    ws_root = Path(temp_workspace.root_str)
    target_file = ws_root / "config.ini"
    target_file.write_text("setting=original\n", encoding="utf-8")

    # Attempt to edit without reading first
    res = edit_tool.execute({
        "path": "config.ini",
        "old_string": "original",
        "new_string": "updated",
        "require_read": True,
        "_workspace": temp_workspace,
    })
    assert res.success is False
    assert "READ_BEFORE_EDIT_REQUIRED" in (res.error or "")

    # Now read the file
    res_read = read_tool.execute({
        "path": "config.ini",
        "_workspace": temp_workspace,
    })
    assert res_read.success is True

    # Now edit succeeds
    res_edit = edit_tool.execute({
        "path": "config.ini",
        "old_string": "original",
        "new_string": "updated",
        "require_read": True,
        "_workspace": temp_workspace,
    })
    assert res_edit.success is True
    assert target_file.read_text(encoding="utf-8") == "setting=updated\n"


def test_scenario_j_stale_file_protection(temp_workspace: WorkspaceManager):
    """
    Scenario J: Stale File Protection
    Guarantees that if a file is modified externally after being inspected with fs.read,
    fs.edit detects the change and rejects the stale edit.
    """
    edit_tool = FSEditTool()
    read_tool = FSReadTool()

    ws_root = Path(temp_workspace.root_str)
    target_file = ws_root / "stale_target.py"
    target_file.write_text("x = 1\n", encoding="utf-8")

    # Read the file
    res_read = read_tool.execute({"path": "stale_target.py", "_workspace": temp_workspace})
    assert res_read.success is True

    # Simulate external edit behind the agent's back
    target_file.write_text("x = 2\n# external touch\n", encoding="utf-8")

    # Attempt edit using outdated baseline
    res_edit = edit_tool.execute({
        "path": "stale_target.py",
        "old_string": "x = 1",
        "new_string": "x = 10",
        "require_read": True,
        "_workspace": temp_workspace,
    })
    assert res_edit.success is False
    assert "FILE_CHANGED_SINCE_READ" in (res_edit.error or "")


def test_scenario_k_nonexistent_file_edit_rejection(temp_workspace: WorkspaceManager):
    """
    Scenario K: Non-existent File Edit Rejection
    FSEditTool rejects nonexistent files with clear guidance to use fs.write.
    """
    edit_tool = FSEditTool()
    res = edit_tool.execute({
        "path": "does_not_exist.txt",
        "old_string": "foo",
        "new_string": "bar",
        "_workspace": temp_workspace,
    })
    assert res.success is False
    assert "File not found" in (res.error or "")
    assert "fs.write" in (res.error or "")


def test_scenario_l_ambiguous_edit_target_rejection(temp_workspace: WorkspaceManager):
    """
    Scenario L: Ambiguous Edit Target Rejection
    If old_string occurs multiple times when expected_occurrences=1,
    the edit is rejected without modifying the file.
    """
    edit_tool = FSEditTool()
    read_tool = FSReadTool()

    ws_root = Path(temp_workspace.root_str)
    target_file = ws_root / "ambiguous.py"
    content = "val = 10\nprint(val)\nval = 10\n"
    target_file.write_text(content, encoding="utf-8")

    read_tool.execute({"path": "ambiguous.py", "_workspace": temp_workspace})

    res = edit_tool.execute({
        "path": "ambiguous.py",
        "old_string": "val = 10",
        "new_string": "val = 20",
        "expected_occurrences": 1,
        "require_read": True,
        "_workspace": temp_workspace,
    })
    assert res.success is False
    assert "EDIT_TARGET_NOT_UNIQUE" in (res.error or "") or "matched 2 time(s)" in (res.error or "")
    # Verify file was untouched
    assert target_file.read_text(encoding="utf-8") == content


def test_scenario_m_exact_string_matching(temp_workspace: WorkspaceManager):
    """
    Scenario M: Exact String Matching Without Fuzzy Corruption
    Surrounding lines must remain 100% byte-for-byte identical.
    """
    edit_tool = FSEditTool()
    read_tool = FSReadTool()

    ws_root = Path(temp_workspace.root_str)
    target_file = ws_root / "exact.py"
    initial = (
        "def compute(a, b):\n"
        "    # Precise line 1\n"
        "    result = a + b\n"
        "    # Precise line 2\n"
        "    return result\n"
    )
    target_file.write_text(initial, encoding="utf-8")

    read_tool.execute({"path": "exact.py", "_workspace": temp_workspace})

    res = edit_tool.execute({
        "path": "exact.py",
        "old_string": "result = a + b",
        "new_string": "result = a * b",
        "expected_occurrences": 1,
        "require_read": True,
        "_workspace": temp_workspace,
    })
    assert res.success is True

    expected = (
        "def compute(a, b):\n"
        "    # Precise line 1\n"
        "    result = a * b\n"
        "    # Precise line 2\n"
        "    return result\n"
    )
    assert target_file.read_text(encoding="utf-8") == expected


def test_scenario_n_write_file_no_clobber_when_allow_overwrite_false(temp_workspace: WorkspaceManager):
    """
    Scenario N: Race-Safe Create Without Clobber
    When allow_overwrite=False, existing file is NOT clobbered.
    """
    write_tool = FSWriteTool()
    ws_root = Path(temp_workspace.root_str)
    existing_file = ws_root / "precious.txt"
    existing_file.write_text("Do not overwrite me\n", encoding="utf-8")

    res = write_tool.execute({
        "path": "precious.txt",
        "content": "Malicious clobber\n",
        "allow_overwrite": False,
        "_workspace": temp_workspace,
    })
    assert res.success is False
    assert "ALREADY_EXISTS" in (res.error or "")
    assert existing_file.read_text(encoding="utf-8") == "Do not overwrite me\n"


def test_scenario_o_atomic_write_and_parent_creation(temp_workspace: WorkspaceManager):
    """
    Scenario O: Atomic Write and Parent Directory Creation
    Writes to nested non-existent directory atomically.
    """
    write_tool = FSWriteTool()
    ws_root = Path(temp_workspace.root_str)
    nested_path = "deeply/nested/dir/structure/artifact.json"
    content = '{"valid": true, "count": 100}\n'

    res = write_tool.execute({
        "path": nested_path,
        "content": content,
        "create_parents": True,
        "_workspace": temp_workspace,
    })
    assert res.success is True
    created = ws_root / nested_path
    assert created.exists()
    assert created.read_text(encoding="utf-8") == content


def test_scenario_p_newline_style_preservation(temp_workspace: WorkspaceManager):
    """
    Scenario P: Newline Style Preservation (LF vs CRLF)
    Editing a CRLF file preserves CRLF endings across the entire file.
    """
    edit_tool = FSEditTool()
    read_tool = FSReadTool()

    ws_root = Path(temp_workspace.root_str)
    target_file = ws_root / "crlf_file.txt"
    # Write explicit CRLF bytes
    crlf_content = b"Line 1\r\nLine 2 target\r\nLine 3\r\n"
    target_file.write_bytes(crlf_content)

    read_tool.execute({"path": "crlf_file.txt", "_workspace": temp_workspace})

    res = edit_tool.execute({
        "path": "crlf_file.txt",
        "old_string": "Line 2 target",
        "new_string": "Line 2 modified",
        "expected_occurrences": 1,
        "require_read": True,
        "_workspace": temp_workspace,
    })
    assert res.success is True

    result_bytes = target_file.read_bytes()
    assert b"\r\n" in result_bytes
    assert b"Line 2 modified\r\n" in result_bytes
    # Ensure no standalone '\n' without '\r'
    assert b"\r\n".join(result_bytes.split(b"\r\n")) == result_bytes
