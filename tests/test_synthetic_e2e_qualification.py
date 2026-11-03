# tests/test_synthetic_e2e_qualification.py
"""
Synthetic End-to-End Pipeline Integration Test for HERMES 2.x (Phase H).
Verifies the complete autonomous application generation lifecycle:
  1. Natural-language requirement intake.
  2. Project layout detection and contract compilation.
  3. Staged artifact generation and node syntax validation.
  4. Atomic artifact promotion.
  5. Cross-file contract verification.
  6. Detection of deliberately introduced synthetic inconsistency.
  7. Targeted defect repair and contract convergence.
  8. Application execution and API verification via FastAPI TestClient.
  9. Authoritative mission state reconciliation.
  10. Immutable evidence and provenance manifest generation.
"""

import json
import os
import sqlite3
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from core.project_contract import ProjectContract, CanonicalPathResolver
from core.js_syntax_validator import (
    validate_javascript_detailed,
    promote_staged_javascript,
    compute_file_sha256,
    CLASS_VALIDATION_SUCCESS,
)
from core.cross_file_contract import (
    CrossFileContractValidator,
    SEV_PASS,
    SEV_FAIL,
)
from core.mission_state import MissionStateManager
from core.evidence.provenance import (
    MissionProvenanceManifest,
    ProvenanceClassification,
)


def test_synthetic_autonomous_generation_e2e_lifecycle(tmp_path: Path):
    """Demonstrates complete autonomous engineering pipeline in an isolated workspace."""
    ws = tmp_path
    mission_id = "m_synthetic_e2e_7788"
    requirement_prompt = (
        "Build TaskForge: a fullstack task tracking application called TaskForge with "
        "FastAPI backend in main.py, SQLite database in taskforge.db, and modern responsive frontend "
        "in static/index.html, static/style.css, and static/app.js."
    )

    # --------------------------------------------------------------------------
    # Step 1: Plan & Compile Canonical Project Contract (Phases B1, B2)
    # --------------------------------------------------------------------------
    contract = ProjectContract.create_or_load(ws, mission_id=mission_id, prompt=requirement_prompt)
    assert contract.project_layout == "static"
    assert contract.canonical_html == "static/index.html"
    assert contract.canonical_css == "static/style.css"
    assert contract.canonical_js == "static/app.js"
    assert contract.canonical_backend == "main.py"
    contract_hash_1 = contract.contract_hash
    assert len(contract_hash_1) >= 8

    # Define contract interfaces
    contract.api_endpoints = [
        {"path": "/api/health", "method": "GET"},
        {"path": "/api/tasks", "method": "GET"},
        {"path": "/api/tasks", "method": "POST"},
    ]
    contract.database_tables = {
        "tasks": ["id", "title", "status", "created_at"]
    }
    contract.required_ids = ["task-form", "task-input", "task-list", "task-count"]
    contract.save_to_workspace(ws)
    contract_hash = contract.contract_hash

    # --------------------------------------------------------------------------
    # Step 2: Generate Staged JavaScript (Phase A1)
    # --------------------------------------------------------------------------
    static_dir = ws / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    
    staged_js = static_dir / "app.pending.js"
    staged_js_content = """// TaskForge Client Application
const CONTRACT_HASH = "{contract_hash}";

async function fetchTasks() {
    try {
        const response = await fetch('/api/tasks');
        const tasks = await response.json();
        renderTasks(tasks);
    } catch (e) {
        console.error("Failed fetching tasks:", e);
    }
}

function renderTasks(tasks) {
    const list = document.getElementById('task-list');
    const count = document.getElementById('task-count');
    if (count) count.innerText = tasks.length;
    if (!list) return;
    list.innerHTML = '';
    tasks.forEach(t => {
        const item = document.createElement('div');
        item.className = 'task-item';
        item.innerText = t.title;
        list.appendChild(item);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('task-form');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const input = document.getElementById('task-input');
            if (!input || !input.value.trim()) return;
            await fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: input.value.trim() })
            });
            input.value = '';
            fetchTasks();
        });
    }
    fetchTasks();
});
""".replace("{contract_hash}", contract_hash)

    staged_js.write_text(staged_js_content, encoding="utf-8")
    staged_sha = compute_file_sha256(staged_js)

    # --------------------------------------------------------------------------
    # Step 3: Validate Staged JavaScript (Phase A)
    # --------------------------------------------------------------------------
    val_res = validate_javascript_detailed(staged_js, workspace_root=ws, canonical_target=static_dir / "app.js")
    assert val_res.is_valid is True
    assert val_res.error_class == CLASS_VALIDATION_SUCCESS
    assert val_res.exit_code == 0
    assert val_res.input_sha256 == staged_sha

    # --------------------------------------------------------------------------
    # Step 4: Promote Validated Artifact (Phase A6)
    # --------------------------------------------------------------------------
    target_js = static_dir / "app.js"
    prom_ok, prom_msg = promote_staged_javascript(staged_js, target_js, workspace_root=ws, expected_sha256=staged_sha)
    assert prom_ok is True
    assert target_js.exists()
    assert not staged_js.exists()

    # --------------------------------------------------------------------------
    # Step 5: Generate Remaining Artifacts (HTML, CSS, Backend, DB)
    # --------------------------------------------------------------------------
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>TaskForge</title>
    <link rel="stylesheet" href="style.css">
    <script src="app.js"></script>
</head>
<body>
    <header class="app-header">
        <h1>TaskForge</h1>
        <span id="task-count">0</span>
    </header>
    <main>
        <form id="task-form">
            <input type="text" id="task-input" placeholder="New task..." required>
            <button type="submit">Add Task</button>
        </form>
        <div id="task-list"></div>
    </main>
</body>
</html>
"""
    (static_dir / "index.html").write_text(html_content, encoding="utf-8")

    css_content = """:root {
    --primary: #2563eb;
    --bg: #f8fafc;
    --text: #0f172a;
}
body {
    background-color: var(--bg);
    color: var(--text);
    font-family: sans-serif;
    margin: 0;
    padding: 20px;
}
.app-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid var(--primary);
}
.task-item {
    padding: 10px;
    background: var(--card-bg, #ffffff);
    margin-top: 8px;
    border-radius: 4px;
}
"""
    (static_dir / "style.css").write_text(css_content, encoding="utf-8")

    # SQLite Database
    db_path = ws / "taskforge.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE tasks ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  title TEXT NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'pending',"
        "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");"
    )
    conn.execute("INSERT INTO tasks (title, status) VALUES ('Initial Qualification Task', 'completed');")
    conn.commit()
    conn.close()

    # Backend FastAPI main.py
    backend_content = """from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
from pathlib import Path

app = FastAPI(title="TaskForge")
DB_PATH = Path(__file__).parent / "taskforge.db"
STATIC_DIR = Path(__file__).parent / "static"

class TaskCreate(BaseModel):
    title: str

def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "taskforge"}

@app.get("/api/tasks")
def list_tasks():
    conn = get_db()
    rows = conn.execute("SELECT id, title, status FROM tasks").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/tasks")
def create_task(task: TaskCreate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO tasks (title) VALUES (?)", (task.title,))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "title": task.title, "status": "pending"}

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
"""
    (ws / "main.py").write_text(backend_content, encoding="utf-8")

    # --------------------------------------------------------------------------
    # Step 6: Initial Cross-File Contract Verification (Phase C)
    # --------------------------------------------------------------------------
    rep = CrossFileContractValidator.validate_workspace(ws)
    assert rep.valid is True
    assert rep.severity == SEV_PASS
    assert len(rep.endpoint_mismatches) == 0
    assert len(rep.dom_id_mismatches) == 0

    # --------------------------------------------------------------------------
    # Step 7: Introduce Deliberate Synthetic Inconsistency (Phase H Step 9)
    # --------------------------------------------------------------------------
    broken_js = target_js.read_text(encoding="utf-8").replace(
        "async function fetchTasks() {",
        "async function fetchTasks() {\n    await fetch('/api/unsupported_metric'); // DELIBERATE DEFECT"
    )
    target_js.write_text(broken_js, encoding="utf-8")

    # Gate detects the planted inconsistency
    rep_defect = CrossFileContractValidator.validate_workspace(ws)
    assert rep_defect.valid is False
    assert rep_defect.severity == SEV_FAIL
    assert any("unsupported_metric" in m for m in rep_defect.endpoint_mismatches)

    # --------------------------------------------------------------------------
    # Step 8: Targeted Repair of Identified Inconsistency (Phase H Step 10)
    # --------------------------------------------------------------------------
    repaired_backend = backend_content.replace(
        '@app.get("/api/health")',
        '@app.get("/api/unsupported_metric")\ndef metric(): return {"metric": 42}\n\n@app.get("/api/health")'
    )
    (ws / "main.py").write_text(repaired_backend, encoding="utf-8")

    # Cross-file contract re-evaluation: must now pass
    rep_repaired = CrossFileContractValidator.validate_workspace(ws)
    assert rep_repaired.valid is True
    assert rep_repaired.severity == SEV_PASS

    # --------------------------------------------------------------------------
    # Step 9: Runtime API Verification via TestClient (Phase H Steps 12-13)
    # --------------------------------------------------------------------------
    # Import app dynamically from the temporary workspace
    import importlib.util
    spec = importlib.util.spec_from_file_location("main_synthetic", ws / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = TestClient(module.app)

    # Health check
    h_res = client.get("/api/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "healthy"

    # Tasks list check
    t_res = client.get("/api/tasks")
    assert t_res.status_code == 200
    tasks_data = t_res.json()
    assert len(tasks_data) >= 1
    assert tasks_data[0]["title"] == "Initial Qualification Task"

    # Task creation check
    post_res = client.post("/api/tasks", json={"title": "Autonomous Verification Passed"})
    assert post_res.status_code == 200
    assert post_res.json()["title"] == "Autonomous Verification Passed"

    # --------------------------------------------------------------------------
    # Step 10: Reconcile Authoritative Mission State (Phase D)
    # --------------------------------------------------------------------------
    state = MissionStateManager.reconcile_state(ws, mission_id=mission_id, contract=contract)
    assert state.contract_validation_status == SEV_PASS
    assert len(state.unmet_requirements) == 0
    assert len(state.final_artifact_paths) >= 4
    assert state.single_next_action == "VERIFY_RUNTIME_APPLICATION"

    # --------------------------------------------------------------------------
    # Step 11: Machine-Readable Provenance Manifest (Phase E4)
    # --------------------------------------------------------------------------
    journal = [
        {"target_path": "static/index.html", "content_sha256": compute_file_sha256(static_dir / "index.html"), "event_type": "ARTIFACT_WRITE"},
        {"target_path": "static/style.css", "content_sha256": compute_file_sha256(static_dir / "style.css"), "event_type": "ARTIFACT_WRITE"},
        {"target_path": "static/app.js", "content_sha256": compute_file_sha256(static_dir / "app.js"), "event_type": "ARTIFACT_PROMOTION"},
        {"target_path": "main.py", "content_sha256": compute_file_sha256(ws / "main.py"), "event_type": "ARTIFACT_WRITE"},
    ]
    manifest = MissionProvenanceManifest.generate(ws, mission_id=mission_id, hermes_write_journal=journal)
    assert manifest.artifacts["static/index.html"].classification == ProvenanceClassification.HERMES_GENERATED
    assert manifest.artifacts["static/style.css"].classification == ProvenanceClassification.HERMES_GENERATED
    assert manifest.artifacts["static/app.js"].classification == ProvenanceClassification.HERMES_GENERATED
    assert manifest.artifacts["main.py"].classification == ProvenanceClassification.HERMES_GENERATED
    assert manifest.artifacts["taskforge.db"].classification == ProvenanceClassification.RUNTIME_GENERATED
