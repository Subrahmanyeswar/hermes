"""
tests/test_gate10_workspace_correctness.py
HERMES Pre-Benchmark Gate 10: Workspace Correctness & Incremental Indexing Regression Suite.

Validates that:
- Initial workspace discovery and AST symbol parsing are accurate.
- External filesystem changes (modify, add, delete, rename, touch) are incrementally detected.
- Deleted and renamed files are purged from active index and retrieval.
- AST symbols and import dependencies refresh immediately.
- Context packs and retrieval queries receive strictly fresh information (zero stale data).
- Incremental updates do NOT trigger full semantic rescans.
- Workspace index state persists across restart and recovers from cold-start.
- Index corruption (C1 truncated header, C2 corrupted table schema, C3 missing DB) is safely detected and recovered.
"""

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
import pytest

from core.workspace import WorkspaceManager, WorkspaceBoundaryError
from core.workspace_indexer import WorkspaceIndexer, WorkspaceIndexStore
from core.workspace_retriever import WorkspaceRetriever
from core.context_engine import context_engine

WORKSPACE = Path(__file__).resolve().parent.parent
RESULTS_PATH = WORKSPACE / "artifacts" / "gate10_workspace_correctness_results.json"
CORRUPTION_RESULTS_PATH = WORKSPACE / "artifacts" / "gate10_corruption_recovery_results.json"


def test_gate10_results_file_and_summary_metrics():
    """Validates that Gate 10 results file exists with PASS & LOCKED status."""
    assert RESULTS_PATH.exists(), f"Missing {RESULTS_PATH}"
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    
    assert data["gate"] == "10"
    assert data["status"] == "PASS & LOCKED"
    assert data["filesystem_index_consistency"] is True
    assert data["initial_indexing"]["correct"] is True
    assert data["incremental_indexing"]["full_rescan_triggered"] is False
    assert data["retrieval"]["fresh_results"] is True
    assert data["retrieval"]["stale_results_detected"] == 0
    assert data["corruption_recovery"]["status"] == "VERIFIED"
    assert data["corruption_recovery"]["scenarios_passed"] == 3
    assert data["regression"]["passed"] == 16
    assert data["regression"]["failed"] == 0


def test_gate10_corruption_results_file():
    """Validates that dedicated corruption recovery results file exists and all 3 scenarios passed."""
    assert CORRUPTION_RESULTS_PATH.exists(), f"Missing {CORRUPTION_RESULTS_PATH}"
    data = json.loads(CORRUPTION_RESULTS_PATH.read_text(encoding="utf-8"))
    
    assert data["status"] == "VERIFIED"
    assert data["scenarios_tested"] == 3
    assert data["scenarios_passed"] == 3
    for sc in data["scenarios"]:
        assert sc["corruption_injected"] is True
        assert sc["corruption_detected"] is True
        assert sc["crash"] is False
        assert sc["recovery_completed"] is True
        assert sc["retrieval_correct"] is True


def test_initial_index_correctness():
    """Verify clean full indexing maps files, AST symbols, and imports correctly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "src").mkdir()
        
        f1 = root / "src" / "math_ops.py"
        f1.write_text("class MathOps:\n    def add(self, a, b):\n        return a + b\n", encoding="utf-8")
        
        f2 = root / "src" / "service.py"
        f2.write_text("from src.math_ops import MathOps\nclass CalcService:\n    def run(self): return 10\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        
        rep = indexer.index_workspace(root)
        assert rep["files_indexed"] == 2
        
        with store._get_conn() as conn:
            symbols = [r["symbol_name"] for r in conn.execute("SELECT symbol_name FROM symbols").fetchall()]
            assert "MathOps" in symbols
            assert "MathOps.add" in symbols
            assert "CalcService" in symbols
            
            imports = [r["imported_module"] for r in conn.execute("SELECT imported_module FROM imports").fetchall()]
            assert "src.math_ops" in imports


def test_external_modify_detected():
    """Verify that external modification is detected and updates AST symbols."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        f = root / "worker.py"
        f.write_text("def worker_v1(): return 1\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # External modify
        f.write_text("def worker_v2(): return 2\n", encoding="utf-8")
        rep = indexer.update_workspace(root)
        
        assert rep.files_modified == 1
        assert rep.files_unchanged == 0
        assert rep.asts_rebuilt == 1
        
        with store._get_conn() as conn:
            symbols = [r["symbol_name"] for r in conn.execute("SELECT symbol_name FROM symbols").fetchall()]
            assert "worker_v2" in symbols
            assert "worker_v1" not in symbols


def test_new_file_detected():
    """Verify that externally created files are discovered and indexed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "base.py").write_text("class Base: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # External create
        (root / "new_feature.py").write_text("class NewFeature:\n    def execute(self): pass\n", encoding="utf-8")
        rep = indexer.update_workspace(root)
        
        assert rep.files_added == 1
        assert rep.files_unchanged == 1
        
        with store._get_conn() as conn:
            symbols = [r["symbol_name"] for r in conn.execute("SELECT symbol_name FROM symbols WHERE rel_path = 'new_feature.py'").fetchall()]
            assert "NewFeature" in symbols


def test_deleted_file_removed():
    """Verify that externally deleted files are completely purged from the index."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        f_del = root / "deprecated.py"
        f_del.write_text("class DeprecatedService: pass\n", encoding="utf-8")
        (root / "keep.py").write_text("class KeepService: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # External delete
        f_del.unlink()
        rep = indexer.update_workspace(root)
        
        assert rep.files_deleted == 1
        assert rep.files_unchanged == 1
        
        with store._get_conn() as conn:
            row = conn.execute("SELECT * FROM files WHERE rel_path = 'deprecated.py'").fetchone()
            assert row is None
            syms = conn.execute("SELECT * FROM symbols WHERE rel_path = 'deprecated.py'").fetchall()
            assert len(syms) == 0


def test_rename_detected():
    """Verify that file rename removes old path and indexes new path without duplicate state."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        f_old = root / "old_name.py"
        f_old.write_text("class RenamedClass: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # External rename
        f_old.unlink()
        (root / "new_name.py").write_text("class RenamedClass: pass\n", encoding="utf-8")
        rep = indexer.update_workspace(root)
        
        assert rep.files_deleted == 1
        assert rep.files_added == 1
        
        with store._get_conn() as conn:
            assert conn.execute("SELECT * FROM files WHERE rel_path = 'old_name.py'").fetchone() is None
            assert conn.execute("SELECT * FROM files WHERE rel_path = 'new_name.py'").fetchone() is not None


def test_symbol_refresh():
    """Verify that symbol changes replace old symbols in the index."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        f = root / "auth.py"
        f.write_text("class UserManager: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # Symbol update
        f.write_text("class AccountManager: pass\n", encoding="utf-8")
        indexer.update_workspace(root)
        
        retriever = WorkspaceRetriever(store=store)
        res_new = retriever.retrieve_relevant_files(str(root), "AccountManager")
        assert len(res_new) > 0 and "AccountManager" in res_new[0].symbols
        assert "UserManager" not in res_new[0].symbols


def test_dependency_refresh():
    """Verify that import updates refresh the dependency metadata."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "utils.py").write_text("def helper_a(): pass\ndef helper_b(): pass\n", encoding="utf-8")
        f_serv = root / "service.py"
        f_serv.write_text("from utils import helper_a\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # Update import
        f_serv.write_text("from utils import helper_b\n", encoding="utf-8")
        indexer.update_workspace(root)
        
        with store._get_conn() as conn:
            imps = [r["imported_symbol"] for r in conn.execute("SELECT imported_symbol FROM imports WHERE rel_path = 'service.py'").fetchall()]
            assert "helper_b" in imps
            assert "helper_a" not in imps


def test_retrieval_freshness():
    """Verify that query retrieval returns the latest modified file and symbol rankings."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        f = root / "billing.py"
        f.write_text("class InvoiceCalculator:\n    def calculate_v1(self): return 100\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        retriever = WorkspaceRetriever(store=store)
        
        indexer.index_workspace(root)

        # Update
        f.write_text("class InvoiceCalculator:\n    def calculate_v2(self): return 200\n", encoding="utf-8")
        indexer.update_workspace(root)

        res = retriever.retrieve_relevant_files(str(root), "calculate_v2 InvoiceCalculator")
        assert len(res) > 0
        assert res[0].rel_path == "billing.py"
        assert "InvoiceCalculator.calculate_v2" in res[0].symbols


def test_no_stale_deleted_file():
    """Verify that a deleted file cannot be retrieved."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        f_legacy = root / "legacy_auth.py"
        f_legacy.write_text("class LegacyAuthEngine: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        retriever = WorkspaceRetriever(store=store)
        indexer.index_workspace(root)

        f_legacy.unlink()
        indexer.update_workspace(root)

        res = retriever.retrieve_relevant_files(str(root), "LegacyAuthEngine")
        assert len(res) == 0 or not any(r.rel_path == "legacy_auth.py" for r in res)


def test_incremental_not_full_semantic_rescan():
    """Verify that updating 1 file in a 50-file workspace reindexes only 1 file semantically."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        for i in range(50):
            (root / f"mod_{i}.py").write_text(f"class Mod{i}: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # Modify only 1 file
        (root / "mod_25.py").write_text("class Mod25_Modified: pass\n", encoding="utf-8")
        
        rep = indexer.update_workspace(root)
        assert rep.files_modified == 1
        assert rep.files_unchanged == 49
        assert rep.asts_rebuilt == 1


def test_restart_then_incremental_update():
    """Verify that an indexer restarted with existing DB detects changes incrementally."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "f1.py").write_text("class F1: pass\n", encoding="utf-8")
        (root / "f2.py").write_text("class F2: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store1 = WorkspaceIndexStore(db_path=db_path)
        indexer1 = WorkspaceIndexer(store=store1, enabled=True)
        indexer1.index_workspace(root)

        # Shutdown indexer1, start indexer2 on same DB
        store2 = WorkspaceIndexStore(db_path=db_path)
        indexer2 = WorkspaceIndexer(store=store2, enabled=True)

        # Modify f1
        (root / "f1.py").write_text("class F1_Restarted: pass\n", encoding="utf-8")
        rep = indexer2.update_workspace(root)
        
        assert rep.files_modified == 1
        assert rep.files_unchanged == 1
        assert rep.asts_rebuilt == 1


def test_corruption_recovery_c1_truncated_database():
    """Scenario C1: Truncated / garbage DB header detects corruption and rebuilds cleanly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "main.py").write_text("class AppMain:\n    def run(self): return 1\n", encoding="utf-8")
        
        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)
        
        # Corrupt DB file
        with open(db_path, "wb") as f:
            f.write(b"GARBAGE_HEADER_BYTES_NOT_A_SQLITE_DATABASE" + b"\x00" * 100)
            
        store_rec = WorkspaceIndexStore(db_path=db_path)
        indexer_rec = WorkspaceIndexer(store=store_rec, enabled=True)
        rep = indexer_rec.update_workspace(root)
        
        assert rep.files_discovered == 1
        retriever = WorkspaceRetriever(store=store_rec)
        res = retriever.retrieve_relevant_files(str(root), "AppMain")
        assert len(res) > 0 and res[0].rel_path == "main.py"
        assert "AppMain" in res[0].symbols


def test_corruption_recovery_c2_corrupted_table():
    """Scenario C2: Broken schema / dropped tables triggers safe rebuild without crash."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "core.py").write_text("class CoreModule: pass\n", encoding="utf-8")
        
        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)
        
        # Drop table and create broken structure with explicit connection closure
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("DROP TABLE files")
            conn.execute("CREATE TABLE files (broken_id TEXT)")
            conn.commit()
        finally:
            conn.close()
            
        store_rec = WorkspaceIndexStore(db_path=db_path)
        indexer_rec = WorkspaceIndexer(store=store_rec, enabled=True)
        rep = indexer_rec.update_workspace(root)
        
        assert rep.files_discovered == 1
        retriever = WorkspaceRetriever(store=store_rec)
        res = retriever.retrieve_relevant_files(str(root), "CoreModule")
        assert len(res) > 0 and res[0].rel_path == "core.py"


def test_corruption_recovery_c3_missing_database():
    """Scenario C3: Deleted index DB file automatically recreates clean index."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "service.py").write_text("class WebService: pass\n", encoding="utf-8")
        
        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)
        
        # Delete DB file
        db_path.unlink()
        
        store_rec = WorkspaceIndexStore(db_path=db_path)
        indexer_rec = WorkspaceIndexer(store=store_rec, enabled=True)
        rep = indexer_rec.update_workspace(root)
        
        assert rep.files_discovered == 1
        retriever = WorkspaceRetriever(store=store_rec)
        res = retriever.retrieve_relevant_files(str(root), "WebService")
        assert len(res) > 0 and res[0].rel_path == "service.py"
