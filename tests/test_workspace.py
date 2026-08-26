import pytest
import tempfile
from pathlib import Path
from core.workspace import WorkspaceManager, WorkspaceBoundaryError


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("class App:\n    def run(self): pass\n")
    (tmp_path / "src" / "models.py").write_text("class User:\n    def __init__(self): pass\n")
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_bytes(b"")
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    return wm


def test_lock_sets_workspace_root(ws, tmp_path):
    assert ws.workspace_root == tmp_path
    assert ws.is_locked is True


def test_index_ignores_pycache(ws):
    assert not any("__pycache__" in p for p in ws.index.files)


def test_index_finds_source_files(ws):
    assert "src\\app.py" in ws.index.files or "src/app.py" in ws.index.files
    assert "src\\models.py" in ws.index.files or "src/models.py" in ws.index.files
    assert "requirements.txt" in ws.index.files


def test_validate_path_allows_inside(ws, tmp_path):
    result = ws.validate_path("src/app.py")
    assert result == (tmp_path / "src" / "app.py").resolve()


def test_validate_path_blocks_traversal(ws):
    with pytest.raises(WorkspaceBoundaryError):
        ws.validate_path("../../etc/passwd")


def test_validate_path_blocks_absolute_escape(ws, tmp_path):
    with pytest.raises(WorkspaceBoundaryError):
        ws.validate_path("C:/Windows/System32/cmd.exe")


def test_is_path_safe_returns_tuple(ws):
    safe, reason = ws.is_path_safe("src/app.py")
    assert safe is True
    unsafe, reason = ws.is_path_safe("../../outside")
    assert unsafe is False
    assert "outside" in reason.lower() or "boundary" in reason.lower()


def test_get_skeleton_returns_string(ws):
    skeleton = ws.get_skeleton()
    assert isinstance(skeleton, str)
    assert "src" in skeleton
    assert "app.py" in skeleton
    assert "__pycache__" not in skeleton


def test_get_signatures_extracts_classes(ws):
    # Need to use the actual relative path as stored in the index
    # On Windows this will be "src\\app.py"
    rel_path = None
    for p in ws.index.files:
        if "app.py" in p:
            rel_path = p
            break
    assert rel_path is not None
    sigs = ws.get_signatures(rel_path)
    assert "class App:" in sigs
    assert "def run" in sigs


def test_get_file_content_reads_file(ws):
    rel_path = None
    for p in ws.index.files:
        if "app.py" in p:
            rel_path = p
            break
    assert rel_path is not None
    content = ws.get_file_content(rel_path)
    assert "class App" in content


def test_get_file_content_blocks_traversal(ws):
    content = ws.get_file_content("../../etc/passwd")
    assert "ERROR" in content


def test_framework_detection_python(ws):
    assert "Python" in ws.index.framework_detected or ws.index.framework_detected != "unknown"


def test_get_relevant_files_returns_list(ws):
    files = ws.get_relevant_files("create a user model")
    assert isinstance(files, list)


def test_lock_invalid_path_raises():
    wm = WorkspaceManager()
    with pytest.raises(ValueError):
        wm.lock("/nonexistent/path/xyz")


def test_workspace_summary_structure(ws):
    summary = ws.get_workspace_summary()
    assert "locked" in summary
    assert "root" in summary
    assert "framework" in summary
    assert summary["locked"] is True
