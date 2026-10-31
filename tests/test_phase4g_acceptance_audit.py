# tests/test_phase4g_acceptance_audit.py
"""
HERMES Phase 4G — Independent Acceptance Audit & Generalization Test Suite.
Validates:
1. Target artifact existence and non-zero size across all 3 workspaces (simple, medium, complex).
2. Zero 404 linked external assets (all referenced stylesheets and scripts physically exist).
3. DOM selector coherence: JavaScript selectors match HTML elements across all 3 applications.
4. Complexity classification accuracy on reference gold set (>= 90% accuracy).
5. Medium mission architectural milestone decomposition (not collapsing to 1 task).
6. Trivial mission atomic planning (exactly 1 task, zero overhead).
7. Conflict-key serialization on identical write targets.
8. Safe disjoint parallel task dispatch.
9. Hard verification barrier holding until implementation completion.
10. Target artifact integrity gate preventing false mission success.
11. Path traversal security protection.
12. Checkpoint SHA-256 integrity and recovery.
13. Browser CDP functional mutation evidence verification.
14. Visual responsive reflow (0px horizontal overflow across viewports).
15. No unresolved placeholders or TODO stubs across all generated code.
"""

import json
import os
import re
import uuid
import pytest
from pathlib import Path

from core.mission_planner import (
    MissionPlanner,
    Mission,
    MissionTask,
    TaskPriority,
    TaskState,
    MissionComplexity,
    classify_mission_complexity,
)
from core.quality_verifier import QualityVerifier, PLACEHOLDER_PATTERNS
from core.workspace import WorkspaceManager, WorkspaceBoundaryError
from core.checkpoints.engine import CheckpointEngine
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import CheckpointReason, CheckpointTrigger, SessionStatus
from core.runtime_state.models import HermesRuntimeState


REPO_ROOT = Path(__file__).resolve().parent.parent

# Resolve workspace directories (prioritize sibling directories where Phase 4F ran)
def resolve_ws(name: str) -> Path:
    sibling = REPO_ROOT.parent / name
    if sibling.exists():
        return sibling
    local = REPO_ROOT / name
    return local

SIMPLE_WS = resolve_ws("hermes_phase4f_simple")
MEDIUM_WS = resolve_ws("hermes_phase4f_medium")
COMPLEX_WS = resolve_ws("hermes_phase4f_complex")
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "phase4g"


# ── Test 1: Artifact Existence & Non-Zero Size ──────────────────────────────

def test_target_artifact_existence_and_non_zero_size():
    """All required artifacts across all 3 workspaces must physically exist and be non-empty."""
    workspaces = [
        (SIMPLE_WS, ["index.html", "css/styles.css", "js/app.js"]),
        (MEDIUM_WS, ["index.html", "css/styles.css", "js/app.js"]),
        (COMPLEX_WS, ["index.html", "css/styles.css", "js/app.js", "data/projects.json"]),
    ]

    for ws, expected_files in workspaces:
        assert ws.exists(), f"Workspace directory does not exist: {ws}"
        for rel_path in expected_files:
            file_path = ws / rel_path
            assert file_path.exists(), f"Missing required file {rel_path} in {ws.name}"
            size = file_path.stat().st_size
            assert size >= 200, f"File {rel_path} in {ws.name} is suspiciously small: {size} bytes"


# ── Test 2: Zero 404 Linked External Assets ─────────────────────────────────

def test_zero_404_linked_external_assets():
    """Every stylesheet and script linked in index.html must exist on disk."""
    for ws in [SIMPLE_WS, MEDIUM_WS, COMPLEX_WS]:
        html_file = ws / "index.html"
        assert html_file.exists()
        content = html_file.read_text(encoding="utf-8")

        # Check stylesheets
        css_matches = re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']', content, re.IGNORECASE)
        css_matches += re.findall(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\']', content, re.IGNORECASE)

        for href in css_matches:
            if href.startswith(("http://", "https://", "//")):
                continue
            css_path = ws / href
            assert css_path.exists(), f"Linked CSS {href} in {ws.name} does not exist on disk (404 error)!"

        # Check scripts
        js_matches = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE)
        for src in js_matches:
            if src.startswith(("http://", "https://", "//")):
                continue
            js_path = ws / src
            assert js_path.exists(), f"Linked script {src} in {ws.name} does not exist on disk (404 error)!"


# ── Test 3: DOM Selector Coherence ──────────────────────────────────────────

def test_dom_selector_coherence():
    """JavaScript DOM queries must match element IDs and classes present in index.html."""
    for ws in [SIMPLE_WS, MEDIUM_WS, COMPLEX_WS]:
        html_file = ws / "index.html"
        js_file = ws / "js" / "app.js"
        if not js_file.exists():
            continue

        html_text = html_file.read_text(encoding="utf-8")
        js_text = js_file.read_text(encoding="utf-8")

        # Extract getElementById calls
        id_calls = re.findall(r'getElementById\(["\']([^"\']+)["\']\)', js_text)
        id_queries = re.findall(r'querySelector\(["\']#([^"\'\s,\.\[\]:]+)["\']\)', js_text)
        all_queried_ids = set(id_calls + id_queries)

        missing_ids = []
        for elem_id in all_queried_ids:
            if f'id="{elem_id}"' not in html_text and f"id='{elem_id}'" not in html_text:
                missing_ids.append(elem_id)

        assert len(missing_ids) == 0, f"In {ws.name}, JS queries DOM IDs missing from HTML: {missing_ids}"


# ── Test 4: Complexity Classification Accuracy ──────────────────────────────

def test_complexity_classification_accuracy():
    """Complexity classification on reference prompts must achieve >= 90% accuracy."""
    gold_file = ARTIFACTS_DIR / "complexity_gold_labels.json"
    assert gold_file.exists(), f"Missing gold labels file: {gold_file}"

    with open(gold_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    correct = 0
    total = len(cases)
    for case in cases:
        pred = classify_mission_complexity(case["prompt"])
        expected = case.get("expected_complexity") or case.get("expected")
        if pred.value.upper() == expected.upper():
            correct += 1

    accuracy = (correct / total) * 100.0
    assert accuracy >= 90.0, f"Classification accuracy {accuracy:.1f}% is below 90% threshold ({correct}/{total})"


# ── Test 5: Medium Mission Architectural Decomposition ───────────────────────

def test_medium_mission_architectural_milestone_decomposition():
    """Medium complexity missions must decompose into structured architectural milestones."""
    planner = MissionPlanner()
    prompts = [
        "Build a Flask REST API with SQLite database, models, and routes for managing books",
        "Create a FastAPI CRUD backend with database models, endpoints, and validation for user accounts",
        "Build a Python service with SQLite database storage, transaction models, and query handlers",
    ]

    for prompt in prompts:
        mission = planner.plan(prompt)
        assert mission.complexity == MissionComplexity.MEDIUM
        assert len(mission.tasks) >= 4, f"Medium mission '{prompt[:30]}' collapsed into too few tasks: {len(mission.tasks)}"
        titles = " ".join([t.title.lower() for t in mission.tasks])
        assert any(term in titles for term in ["model", "database", "data", "schema", "api", "route", "service"])


# ── Test 6: Trivial Mission Atomic Planning ─────────────────────────────────

def test_trivial_mission_atomic_planning():
    """Trivial missions must be planned as a compressed atomic unit (at most 2 tasks: impl + verify)."""
    planner = MissionPlanner()
    trivial_prompts = [
        "Create hello.py printing hello world",
        "Write a python script fib.py to compute the first 10 fibonacci numbers",
        "Create a simple helper script ping.py",
    ]

    for prompt in trivial_prompts:
        mission = planner.plan(prompt)
        assert mission.complexity == MissionComplexity.TRIVIAL
        assert len(mission.tasks) <= 2, f"Trivial prompt generated too many tasks: {len(mission.tasks)} for: {prompt}"
        assert mission.tasks[0].task_id in mission.tasks[-1].depends_on or len(mission.tasks) == 1


# ── Test 7: Conflict-Key Serialization on Identical Targets ─────────────────

def test_conflict_key_serialization_on_identical_targets():
    """Tasks with overlapping write targets must never execute in parallel."""
    t1 = MissionTask(
        task_id="task_css_part1",
        title="Write base CSS",
        target_paths=["css/styles.css"],
        write_dependencies=["css/styles.css"],
        state=TaskState.PENDING,
    )
    t2 = MissionTask(
        task_id="task_css_part2",
        title="Write dark mode CSS",
        target_paths=["css/styles.css"],
        write_dependencies=["css/styles.css"],
        state=TaskState.PENDING,
    )
    mission = Mission(tasks=[t1, t2], execution_order=["task_css_part1", "task_css_part2"])

    batch = mission.get_executable_batch(max_concurrent=4)
    assert len(batch) == 1, f"Conflicting tasks scheduled in parallel! Batch size: {len(batch)}"
    assert batch[0].task_id == "task_css_part1"


# ── Test 8: Safe Disjoint Parallel Task Dispatch ─────────────────────────────

def test_safe_disjoint_parallel_task_dispatch():
    """Tasks with disjoint write dependencies must be dispatched concurrently."""
    t_html = MissionTask(
        task_id="t_html",
        title="HTML Layout",
        target_paths=["index.html"],
        write_dependencies=["index.html"],
        state=TaskState.COMPLETED,
    )
    t_css = MissionTask(
        task_id="t_css",
        title="CSS Styling",
        target_paths=["css/styles.css"],
        write_dependencies=["css/styles.css"],
        depends_on=["t_html"],
        state=TaskState.PENDING,
    )
    t_js = MissionTask(
        task_id="t_js",
        title="JS Interactions",
        target_paths=["js/app.js"],
        write_dependencies=["js/app.js"],
        depends_on=["t_html"],
        state=TaskState.PENDING,
    )

    mission = Mission(tasks=[t_html, t_css, t_js], execution_order=["t_html", "t_css", "t_js"])
    batch = mission.get_executable_batch(max_concurrent=4)

    batch_ids = [t.task_id for t in batch]
    assert "t_css" in batch_ids and "t_js" in batch_ids
    assert len(batch) == 2, f"Expected 2 parallel tasks, got {len(batch)}"


# ── Test 9: Hard Verification Barrier Preservation ──────────────────────────

def test_hard_verification_barrier_preservation():
    """Verification task must hold until all implementation dependencies are completed."""
    t1 = MissionTask(task_id="t1", target_paths=["index.html"], write_dependencies=["index.html"], state=TaskState.COMPLETED)
    t2 = MissionTask(task_id="t2", target_paths=["css/styles.css"], write_dependencies=["css/styles.css"], depends_on=["t1"], state=TaskState.RUNNING)
    t3 = MissionTask(task_id="t3", target_paths=["js/app.js"], write_dependencies=["js/app.js"], depends_on=["t1"], state=TaskState.PENDING)
    t_verify = MissionTask(
        task_id="t_verify",
        title="Verify and validate application functionality",
        target_paths=["index.html", "css/styles.css", "js/app.js"],
        depends_on=["t1", "t2", "t3"],
        state=TaskState.PENDING,
    )

    mission = Mission(tasks=[t1, t2, t3, t_verify], execution_order=["t1", "t2", "t3", "t_verify"])
    batch = mission.get_executable_batch(max_concurrent=4)

    batch_ids = [t.task_id for t in batch]
    assert "t_verify" not in batch_ids, "Verification task released before implementation completed!"
    assert "t3" in batch_ids


# ── Test 10: Target Artifact Integrity Gate ─────────────────────────────────

def test_target_artifact_integrity_gate(tmp_path):
    """QualityVerifier must reject tasks whose declared files do not physically exist on disk."""
    ws_dir = tmp_path / "mock_workspace"
    ws_dir.mkdir()
    # Create HTML that references a missing stylesheet
    (ws_dir / "index.html").write_text('<!DOCTYPE html><html><head><link rel="stylesheet" href="css/missing.css"></head><body><h1>Test</h1></body></html>', encoding="utf-8")

    verifier = QualityVerifier()
    # css/missing.css does not exist on disk — must fail scoped verification
    result = verifier.verify_task_scoped(
        task_id="t_val",
        task_title="Verify and validate application",
        task_description="Validate linked assets",
        task_index=6,
        total_tasks=6,
        project_root=str(ws_dir),
    )
    assert result.needs_improvement, "Integrity gate allowed verification to pass when linked asset was missing from disk!"


# ── Test 11: Path Traversal Security Protection ─────────────────────────────

def test_path_traversal_security_protection(tmp_path):
    """Path traversal outside workspace root must be strictly blocked with WorkspaceBoundaryError."""
    ws_dir = tmp_path / "sandbox"
    ws_dir.mkdir()
    wm = WorkspaceManager()
    wm.lock(str(ws_dir))

    with pytest.raises(WorkspaceBoundaryError):
        wm.validate_path("../../outside.txt")

    with pytest.raises(WorkspaceBoundaryError):
        wm.validate_path("../../../secret.env")


# ── Test 12: Checkpoint SHA-256 Integrity & Tamper Detection ────────────────

def test_checkpoint_sha256_integrity_and_recovery(tmp_path):
    """Checkpoints must store SHA-256 hashes and reject tampered state."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "main.py").write_text("print('secure')", encoding="utf-8")

    hermes_dir = tmp_path / ".hermes"
    db = SQLiteDatabase(hermes_dir / "audit.db")
    db.save_session("sess_audit", "m_audit", str(ws), SessionStatus.RUNNING, 0.0, 0.0)
    blob_store = BlobStore(hermes_dir)

    engine = CheckpointEngine(
        base_dir=hermes_dir,
        workspace_root=ws,
        db=db,
        blob_store=blob_store,
    )

    state = HermesRuntimeState.create_empty("m_audit", "sess_audit")
    chk = engine.create_checkpoint(
        session_id="sess_audit",
        mission_id="m_audit",
        runtime_state=state,
        reason=CheckpointReason.MANUAL,
        trigger=CheckpointTrigger.USER,
    )

    # Initial integrity check passes
    assert engine.verify_checkpoint_integrity(chk.checkpoint_id) is True

    # Tamper with stored blob
    file_blob_id = chk.workspace.files["main.py"].blob_id
    blob_file = blob_store._blob_path(file_blob_id)
    with open(blob_file, "wb") as f:
        f.write(b"tampered content")

    # Integrity verification must catch corruption
    assert engine.verify_checkpoint_integrity(chk.checkpoint_id) is False


# ── Test 13: Browser CDP Functional Evidence Verification ───────────────────

def test_browser_cdp_functional_evidence_verification():
    """Live CDP functional testing artifact must confirm passing status and zero console errors."""
    evidence_file = ARTIFACTS_DIR / "browser_functional_evidence.json"
    assert evidence_file.exists(), f"Missing browser evidence file: {evidence_file}"

    with open(evidence_file, "r", encoding="utf-8") as f:
        evidence = json.load(f)

    for app_key in ["simple", "medium", "complex"]:
        assert app_key in evidence, f"Missing {app_key} in browser evidence"
        data = evidence[app_key]
        assert data.get("overall_success") is True, f"{app_key} functional test failed: {data}"
        assert len(data.get("console_errors", [])) == 0, f"{app_key} had console errors: {data.get('console_errors')}"
        flows = data.get("flows", {})
        assert any(v is True for k, v in flows.items() if "verified" in k), f"{app_key} had no verified flows"


# ── Test 14: Visual Responsive Reflow Verification ──────────────────────────

def test_visual_responsive_reflow_verification():
    """Visual evidence artifact must verify 0px horizontal overflow across all viewports."""
    evidence_file = ARTIFACTS_DIR / "visual_quality_evidence.json"
    assert evidence_file.exists(), f"Missing visual evidence file: {evidence_file}"

    with open(evidence_file, "r", encoding="utf-8") as f:
        evidence = json.load(f)

    for app_key in ["simple", "medium", "complex"]:
        assert app_key in evidence, f"Missing {app_key} in visual evidence"
        viewports = evidence[app_key]["viewports"]
        for vp_name in ["desktop", "tablet", "mobile"]:
            assert vp_name in viewports, f"Missing viewport {vp_name} in {app_key}"
            vp_data = viewports[vp_name]
            assert vp_data["overflow_px"] == 0, f"Horizontal overflow in {app_key} {vp_name}: {vp_data['overflow_px']}px"
            assert vp_data["responsive_pass"] is True
            screenshot_path = Path(vp_data["screenshot_path"])
            assert screenshot_path.exists(), f"Screenshot not found: {screenshot_path}"


# ── Test 15: No Unresolved Placeholders or TODO Stubs ───────────────────────

def test_no_unresolved_placeholders_or_todo_stubs():
    """All code across simple, medium, and complex workspaces must have zero TODOs or stubs."""
    for ws in [SIMPLE_WS, MEDIUM_WS, COMPLEX_WS]:
        for root, _, files in os.walk(ws):
            for file_name in files:
                if not file_name.endswith((".html", ".css", ".js", ".py")):
                    continue
                file_path = Path(root) / file_name
                content = file_path.read_text(encoding="utf-8")
                for pat in PLACEHOLDER_PATTERNS:
                    match = re.search(pat, content, re.IGNORECASE)
                    assert match is None, f"Unresolved placeholder '{match.group(0)}' found in {file_path.relative_to(REPO_ROOT.parent)}"
