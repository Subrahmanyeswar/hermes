"""
Unit and Integration Tests for Phase 7 Workspace Intelligence & Incremental Indexing.
Tests SQLite persistence, AST symbol extraction, import mapping, incremental change detection,
multi-signal relevance retrieval, and test file pairing.
"""
import shutil
import tempfile
import time
from pathlib import Path
import pytest

from core.workspace_indexer import WorkspaceIndexer, WorkspaceIndexStore
from core.workspace_retriever import WorkspaceRetriever
from core.workspace import WorkspaceManager


@pytest.fixture
def sample_workspace(tmp_path):
    """Create a realistic temporary software project directory."""
    ws = tmp_path / "my_project"
    ws.mkdir()

    backend = ws / "backend"
    backend.mkdir()
    (backend / "database.py").write_text("class Database:\n    def connect(self): pass\n", encoding="utf-8")
    (backend / "models.py").write_text("from database import Database\nclass User:\n    def __init__(self, username): self.username = username\n", encoding="utf-8")
    (backend / "auth.py").write_text("from models import User\ndef authenticate(user, password):\n    return True\n", encoding="utf-8")

    tests = ws / "tests"
    tests.mkdir()
    (tests / "test_auth.py").write_text("from backend.auth import authenticate\ndef test_login(): assert authenticate('admin', '123')\n", encoding="utf-8")

    frontend = ws / "frontend"
    frontend.mkdir()
    (frontend / "App.jsx").write_text("import React from 'react';\nfunction App() { return <div>App</div>; }\nexport default App;\n", encoding="utf-8")

    return ws


def test_initial_workspace_indexing_and_sqlite_persistence(sample_workspace, tmp_path):
    """Full indexing must populate workspaces, files, symbols, and imports tables."""
    db_path = tmp_path / "test_ws_index.db"
    store = WorkspaceIndexStore(db_path=db_path)
    indexer = WorkspaceIndexer(store=store, enabled=True)

    res = indexer.index_workspace(sample_workspace)
    assert res["files_indexed"] == 5
    assert res["duration_ms"] > 0

    with store._get_conn() as conn:
        ws_row = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (str(sample_workspace),)).fetchone()
        assert ws_row is not None
        assert ws_row["file_count"] == 5

        files = conn.execute("SELECT rel_path, language FROM files WHERE workspace_id = ?", (str(sample_workspace),)).fetchall()
        assert len(files) == 5
        py_files = [f["rel_path"] for f in files if f["language"] == "Python"]
        assert "backend/auth.py" in py_files
        assert "backend/models.py" in py_files

        symbols = conn.execute("SELECT symbol_name, symbol_type FROM symbols WHERE workspace_id = ?", (str(sample_workspace),)).fetchall()
        sym_names = [s["symbol_name"] for s in symbols]
        assert "Database" in sym_names
        assert "User" in sym_names
        assert "authenticate" in sym_names


def test_incremental_update_unchanged_files_zero_parsing(sample_workspace, tmp_path):
    """Re-running update_workspace on unchanged files must report 100% unchanged."""
    db_path = tmp_path / "test_ws_index.db"
    store = WorkspaceIndexStore(db_path=db_path)
    indexer = WorkspaceIndexer(store=store, enabled=True)
    indexer.index_workspace(sample_workspace)

    report = indexer.update_workspace(sample_workspace)
    assert report.files_unchanged == 5
    assert report.files_added == 0
    assert report.files_modified == 0
    assert report.files_deleted == 0


def test_incremental_update_detects_added_modified_deleted(sample_workspace, tmp_path):
    """Adding, modifying, and deleting files must update SQLite incrementally."""
    db_path = tmp_path / "test_ws_index.db"
    store = WorkspaceIndexStore(db_path=db_path)
    indexer = WorkspaceIndexer(store=store, enabled=True)
    indexer.index_workspace(sample_workspace)

    # 1. Add new file
    (sample_workspace / "backend" / "api.py").write_text("def get_api_status(): return {'status': 'ok'}\n", encoding="utf-8")

    # 2. Modify existing file
    (sample_workspace / "backend" / "auth.py").write_text("def authenticate_v2(user, pwd, token): return True\n", encoding="utf-8")

    # 3. Delete file
    (sample_workspace / "frontend" / "App.jsx").unlink()

    report = indexer.update_workspace(sample_workspace)
    assert report.files_added == 1
    assert report.files_modified == 1
    assert report.files_deleted == 1
    assert report.files_unchanged == 3

    with store._get_conn() as conn:
        symbols = conn.execute("SELECT symbol_name FROM symbols WHERE workspace_id = ? AND rel_path = 'backend/auth.py'", (str(sample_workspace),)).fetchall()
        sym_names = [s["symbol_name"] for s in symbols]
        assert "authenticate_v2" in sym_names
        assert "authenticate" not in sym_names


def test_multi_signal_retrieval_query_ranking(sample_workspace, tmp_path):
    """Querying 'authentication' must rank auth.py and test_auth.py at top."""
    db_path = tmp_path / "test_ws_index.db"
    store = WorkspaceIndexStore(db_path=db_path)
    indexer = WorkspaceIndexer(store=store, enabled=True)
    indexer.index_workspace(sample_workspace)

    retriever = WorkspaceRetriever(store=store)
    results = retriever.retrieve_relevant_files(
        workspace_root=str(sample_workspace),
        query="Fix the authentication login issue in auth",
        max_files=3
    )

    retrieved_paths = [r.rel_path for r in results]
    assert "backend/auth.py" in retrieved_paths
    # test_auth.py should be paired and retrieved
    assert any("test_auth" in r for r in retrieved_paths)
    assert results[0].score > 5.0


def test_dependency_expansion_retrieval(sample_workspace, tmp_path):
    """Query matching auth.py expands to imported dependencies (models.py)."""
    db_path = tmp_path / "test_ws_index.db"
    store = WorkspaceIndexStore(db_path=db_path)
    indexer = WorkspaceIndexer(store=store, enabled=True)
    indexer.index_workspace(sample_workspace)

    retriever = WorkspaceRetriever(store=store)
    results = retriever.retrieve_relevant_files(
        workspace_root=str(sample_workspace),
        query="auth.py",
        max_files=4,
        expand_dependencies=True,
        include_tests=True
    )

    retrieved_paths = [r.rel_path for r in results]
    assert "backend/auth.py" in retrieved_paths
    # models.py should be pulled in via dependency expansion
    assert any("models.py" in p for p in retrieved_paths)


def test_workspace_manager_integration(sample_workspace):
    """WorkspaceManager must initialize indexer and provide context summary."""
    wm = WorkspaceManager()
    wm.lock(str(sample_workspace))
    assert wm.is_locked is True

    rel_files = wm.get_relevant_files("authentication", max_files=2)
    assert len(rel_files) > 0
    assert any("auth" in f for f in rel_files)
