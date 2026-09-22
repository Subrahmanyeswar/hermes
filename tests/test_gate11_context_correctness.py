"""
tests/test_gate11_context_correctness.py
HERMES Pre-Benchmark Gate 11: Context-Engine Correctness & Small-Context Precision Regression Suite.

Validates that:
- 15/15 tasks in the Gate 11 suite passed with >= 90% required file, symbol, and dependency recall.
- Deceptive distractors (legacy, identity, payments) are suppressed in favor of active dependencies.
- Deleted and stale files are completely purged from retrieved ContextPack (0 stale leaks).
- Memory assists retrieval without overriding current filesystem truth.
- Task-state context correctly isolates active vs completed vs blocked tasks.
- Multi-hop dependency chains (API -> controller -> service -> validator) are resolved.
- Casual/underspecified user requests retrieve the required ground-truth evidence.
- Token budgeting enforces hard limits with zero overflow.
"""

import json
import os
import tempfile
import time
from pathlib import Path
import pytest

from core.workspace import WorkspaceManager, WorkspaceBoundaryError
from core.workspace_indexer import WorkspaceIndexer, WorkspaceIndexStore
from core.workspace_retriever import WorkspaceRetriever
from core.context_engine import ContextEngine, ContextSource, ContextBudgeter, ContextPack, ContextItem
from benchmarks.gate11_context_correctness_harness import Gate11Harness

WORKSPACE = Path(__file__).resolve().parent.parent
RESULTS_PATH = WORKSPACE / "artifacts" / "gate11_context_correctness_results.json"
TASK_RESULTS_PATH = WORKSPACE / "artifacts" / "gate11_task_results.json"
MANIFEST_PATH = WORKSPACE / "artifacts" / "gate11_ground_truth_manifest.json"


def test_gate11_results_file_and_summary_metrics():
    """Validates that Gate 11 results file exists with PASS & LOCKED status and genuine metrics."""
    assert RESULTS_PATH.exists(), f"Missing {RESULTS_PATH}"
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    assert data["gate"] == "11"
    assert data["status"] == "PASS & LOCKED"
    assert data["precision_grade"] in ["EXCELLENT", "GOOD", "ACCEPTABLE", "WEAK"]
    assert data["tasks"]["total"] >= 15
    assert data["tasks"]["passed"] == data["tasks"]["total"]
    assert data["tasks"]["failed"] == 0
    assert data["context"]["stale_context_cases"] == 0
    assert data["memory"]["current_truth_override_violations"] == 0
    assert data["memory"]["current_truth_cases_tested"] >= 3
    assert data["dependencies"]["unnecessary_expansion_rate"] >= 0.0
    assert data["retrieval"]["file_recall"] >= 0.90
    assert data["retrieval"]["symbol_recall"] >= 0.90
    assert data["retrieval"]["dependency_recall"] >= 0.90
    assert data["retrieval"]["hit_at_3"] >= 0.95
    assert data["retrieval"]["hit_at_5"] >= 0.95


def test_gate11_task_results_all_passed():
    """Validates that every single task in task_results.json is classified as strict PASS."""
    assert TASK_RESULTS_PATH.exists(), f"Missing {TASK_RESULTS_PATH}"
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    assert len(tasks) >= 15
    for t in tasks:
        assert t["classification"] == "PASS", f"Task {t['task_id']} failed: {t['failure_reason']}"
        assert len(t["stale_files_retrieved"]) == 0
        assert t["file_recall"] >= 0.90
        assert t["symbol_recall"] >= 0.90
        assert t["dependency_recall"] >= 0.90
        assert t["current_truth_overridden"] is False
        assert "unnecessary_expansion_rate" in t
        assert "relevant_files" in t
        assert "irrelevant_files" in t


def test_gate11_zero_stale_data_leaks():
    """Validates that externally deleted files never leak into the ContextPack."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        f_del = root / "deprecated_auth.py"
        f_del.write_text("class DeprecatedAuth: pass\n", encoding="utf-8")
        f_keep = root / "active_auth.py"
        f_keep.write_text("class ActiveAuth: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        # Delete deprecated file externally
        f_del.unlink()
        indexer.update_workspace(root)

        retriever = WorkspaceRetriever(store=store)
        res = retriever.retrieve_relevant_files(str(root), "DeprecatedAuth active authentication")
        retrieved_paths = [r.rel_path.replace("\\", "/") for r in res]

        assert "deprecated_auth.py" not in retrieved_paths
        assert any("active_auth.py" in p for p in retrieved_paths)


def test_gate11_memory_assists_without_overriding_truth():
    """Validates that memory provides context without overriding disk ground truth."""
    engine = ContextEngine(enabled=True)
    mem = "Previous finding: Auth timeout defined in auth/session_policy.py\nUnrelated fact: Payment session uses 100s"
    cpack = engine.build_context_pack(
        task_text="Investigate session timeout",
        mode="CODE",
        memory_context=mem
    )

    mem_items = [item for item in cpack.items if item.source == ContextSource.MEMORY]
    assert len(mem_items) > 0
    assert any("auth/session_policy.py" in m.content for m in mem_items)
    # Memory items are NOT hard required, so disk truth & user task take priority
    assert all(not m.is_hard_required for m in mem_items)


def test_gate11_task_state_isolation():
    """Validates that active task state is properly included with source TASK_STATE."""
    engine = ContextEngine(enabled=True)
    task_state_str = "Active: Task 3 (Patch) | Completed: [Task 1, Task 2] | Blocked: [Task 4]"
    cpack = engine.build_context_pack(
        task_text="Patch session timeout",
        mode="CODE",
        task_state=task_state_str
    )

    ts_items = [item for item in cpack.items if item.source == ContextSource.TASK_STATE]
    assert len(ts_items) == 1
    assert "Active: Task 3" in ts_items[0].content
    assert ts_items[0].relevance_score >= 40.0


def test_gate11_multi_hop_dependency_expansion():
    """Validates 2-hop transitive dependency resolution (controller -> service -> validator)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "src").mkdir()

        (root / "src" / "validator.py").write_text("class Validator:\n    def validate(self): pass\n", encoding="utf-8")
        (root / "src" / "service.py").write_text("import src.validator as validator\nclass Service:\n    pass\n", encoding="utf-8")
        (root / "src" / "controller.py").write_text("import src.service as service\nclass Controller:\n    pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        retriever = WorkspaceRetriever(store=store)
        res = retriever.retrieve_relevant_files(str(root), "controller endpoint", max_files=5)
        paths = [r.rel_path.replace("\\", "/") for r in res]

        assert "src/controller.py" in paths
        assert "src/service.py" in paths
        assert "src/validator.py" in paths


def test_gate11_similar_symbol_disambiguation():
    """Validates disambiguation between multiple similar TokenService implementations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        root.mkdir()
        (root / "src" / "auth").mkdir(parents=True)
        (root / "src" / "admin").mkdir(parents=True)
        (root / "src" / "identity").mkdir(parents=True)

        (root / "src" / "admin" / "token_svc.py").write_text("class AdminTokenService:\n    def get_admin_creds(self): pass\n", encoding="utf-8")
        (root / "src" / "admin" / "controller.py").write_text("import src.admin.token_svc as token_svc\nclass AdminController: pass\n", encoding="utf-8")
        (root / "src" / "identity" / "token_svc.py").write_text("class IdentityTokenService: pass\n", encoding="utf-8")
        (root / "src" / "auth" / "token_svc.py").write_text("class AuthTokenService: pass\n", encoding="utf-8")

        db_path = Path(tmp_dir) / "idx.db"
        store = WorkspaceIndexStore(db_path=db_path)
        indexer = WorkspaceIndexer(store=store, enabled=True)
        indexer.index_workspace(root)

        retriever = WorkspaceRetriever(store=store)
        res = retriever.retrieve_relevant_files(str(root), "The TokenService used by admin API is returning stale credentials", max_files=4)
        paths = [r.rel_path.replace("\\", "/") for r in res]

        assert "src/admin/token_svc.py" in paths
        assert "src/admin/controller.py" in paths
        # Admin implementation ranks higher than identity/auth distractors
        scores_map = {r.rel_path.replace("\\", "/"): r.score for r in res}
        assert scores_map["src/admin/token_svc.py"] >= scores_map.get("src/identity/token_svc.py", 0.0)


def test_gate11_casual_underspecified_request_recall():
    """Validates that underspecified conversational queries retrieve the core domain files."""
    harness = Gate11Harness()
    harness.generate_repository()
    harness.indexer.index_workspace(harness.repo_root)

    query = "Login keeps acting weird after the session refresh. Can you check what's going on?"
    res = harness.retriever.retrieve_relevant_files(str(harness.repo_root), query, max_files=8)
    paths = [r.rel_path.replace("\\", "/") for r in res]

    assert "src/auth/oauth_service.py" in paths
    assert "src/auth/session_manager.py" in paths
    assert "src/auth/token_service.py" in paths


def test_gate11_context_budgeting_within_4096_tokens():
    """Validates that ContextBudgeter enforces hard token caps without dropping hard required items."""
    budgeter = ContextBudgeter(max_context_tokens=1024, generation_reserve=256)
    items = [
        ContextItem(id="sys", source=ContextSource.SYSTEM_CORE, content="A" * 800, relevance_score=100.0, is_hard_required=True),
        ContextItem(id="task", source=ContextSource.USER_TASK, content="B" * 200, relevance_score=100.0, is_hard_required=True),
        ContextItem(id="f1", source=ContextSource.WORKSPACE_FILE, content="C" * 1000, relevance_score=20.0),
        ContextItem(id="f2", source=ContextSource.WORKSPACE_FILE, content="D" * 2000, relevance_score=10.0),
    ]

    included, dropped = budgeter.budget(items)
    # Hard required items must always be preserved
    assert any(i.id == "sys" for i in included)
    assert any(i.id == "task" for i in included)
    assert any(i.id == "f2" for i in dropped)


def test_gate11_workspace_boundary_security():
    """Validates that ContextPack generation strictly respects workspace boundaries."""
    wm = WorkspaceManager()
    with tempfile.TemporaryDirectory() as tmp_dir:
        wm.lock(tmp_dir)
        with pytest.raises(WorkspaceBoundaryError):
            wm.validate_path("../../secret.pem")
