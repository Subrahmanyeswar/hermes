"""
Phase 7 Workspace Intelligence & Incremental Indexing Benchmark.
Measures:
1. Initial full indexing time (files, AST symbols, imports, SQLite storage)
2. Incremental update time on unchanged workspace (0ms bypass check)
3. Incremental update time on 1 modified file
4. Multi-signal retrieval latency and relevance accuracy
"""
import time
import json
import tempfile
from pathlib import Path

from core.workspace_indexer import WorkspaceIndexer, WorkspaceIndexStore
from core.workspace_retriever import WorkspaceRetriever

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase7"
PERF_DIR.mkdir(parents=True, exist_ok=True)

def create_benchmark_project(root: Path, file_count: int = 50):
    """Create a realistic synthetic software repository with 50 files."""
    for i in range(file_count):
        sub = root / f"module_{i % 5}"
        sub.mkdir(parents=True, exist_ok=True)
        if i == 0:
            (sub / "auth.py").write_text("from module_1.models import User\nclass AuthManager:\n    def authenticate(self, u, p): return True\n", encoding="utf-8")
        elif i == 1:
            (sub / "models.py").write_text("class User:\n    def __init__(self, name): self.name = name\n", encoding="utf-8")
        elif i == 2:
            (sub / "database.py").write_text("class DatabaseConnection:\n    def connect(self): pass\n", encoding="utf-8")
        elif i == 3:
            (sub / "test_auth.py").write_text("from module_0.auth import AuthManager\ndef test_auth(): assert AuthManager().authenticate('a', 'b')\n", encoding="utf-8")
        else:
            (sub / f"service_{i}.py").write_text(f"class Service{i}:\n    def execute(self): return {i}\n", encoding="utf-8")

def run_workspace_benchmark():
    print("================================================================")
    print(" PHASE 7 WORKSPACE INTELLIGENCE & INCREMENTAL BENCHMARK")
    print("================================================================")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir) / "bench_project"
        tmp_root.mkdir()
        create_benchmark_project(tmp_root, file_count=50)

        db_path = Path(tmp_dir) / "bench_index.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        retriever = WorkspaceRetriever(store=store)

        # 1. Initial Full Index
        print("\n[TEST 1] Initial Full Workspace Indexing (50 files)...")
        t0 = time.perf_counter()
        idx_res = indexer.index_workspace(tmp_root)
        dur_initial = (time.perf_counter() - t0) * 1000.0
        print(f"  -> Indexed {idx_res['files_indexed']} files in {dur_initial:.2f} ms")

        # 2. Incremental Update (Unchanged Workspace)
        print("\n[TEST 2] Incremental Check on Unchanged Workspace...")
        t0 = time.perf_counter()
        rep_unchanged = indexer.update_workspace(tmp_root)
        dur_unchanged = (time.perf_counter() - t0) * 1000.0
        print(f"  -> Unchanged Check: {rep_unchanged.files_unchanged} files unchanged in {dur_unchanged:.2f} ms")

        # 3. Incremental Update (1 Modified File)
        print("\n[TEST 3] Incremental Update (1 Modified File)...")
        (tmp_root / "module_0" / "auth.py").write_text("class AuthManager:\n    def authenticate_v2(self, u, p, t): return True\n", encoding="utf-8")
        t0 = time.perf_counter()
        rep_mod = indexer.update_workspace(tmp_root)
        dur_mod = (time.perf_counter() - t0) * 1000.0
        print(f"  -> Modified Update: +{rep_mod.files_added} ~{rep_mod.files_modified} in {dur_mod:.2f} ms")

        # 4. Multi-Signal Retrieval
        print("\n[TEST 4] Multi-Signal Query Retrieval ('Fix authentication login')...")
        t0 = time.perf_counter()
        retrieved = retriever.retrieve_relevant_files(
            workspace_root=str(tmp_root),
            query="Fix authentication login bug in auth",
            max_files=4
        )
        dur_ret = (time.perf_counter() - t0) * 1000.0
        print(f"  -> Retrieved {len(retrieved)} files in {dur_ret:.2f} ms:")
        for rf in retrieved:
            print(f"     * {rf.rel_path} (score={rf.score}) reasons={rf.reasons[:2]}")

        speedup = f"{(dur_initial / dur_unchanged):.1f}x" if dur_unchanged > 0 else "N/A"

        results = {
            "initial_full_indexing_ms": round(dur_initial, 2),
            "incremental_unchanged_check_ms": round(dur_unchanged, 2),
            "incremental_1_file_update_ms": round(dur_mod, 2),
            "retrieval_latency_ms": round(dur_ret, 2),
            "incremental_speedup": speedup,
            "retrieved_files": [rf.rel_path for rf in retrieved]
        }

        (PERF_DIR / "phase7_workspace_benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\n[OK] Saved results to {PERF_DIR / 'phase7_workspace_benchmark.json'}")

if __name__ == "__main__":
    run_workspace_benchmark()
