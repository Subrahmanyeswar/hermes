# tests/test_hermes_fullstack_gates.py
"""
Comprehensive Unit Tests for HERMES Full-Stack Contract, Responsibility,
and Pytest Failure Recovery Gates (Section 9.6).
"""

import ast
import json
import os
import tempfile
import textwrap
from pathlib import Path
import pytest

from core.responsibility_contract import (
    ResponsibilityContractEvaluator,
    ResponsibilityReport,
)
from core.cross_file_contract import (
    CrossFileContractValidator,
    CrossFileContractReport,
)
from core.pytest_recovery_engine import (
    PytestRecoveryEngine,
    FailureClass,
)
from core.code_completeness import (
    is_placeholder_js,
    validate_implementation_completeness,
)
from core.runtime_integration_gate import (
    RuntimeIntegrationGate,
)


def test_empty_javascript_stubs_rejected():
    """Verify that empty, truncated, or placeholder JS stubs are rejected."""
    stub_1 = "function loadData() { ... }"
    is_stub, reason = is_placeholder_js(stub_1)
    assert is_stub is True
    assert "placeholder stub" in reason.lower()

    stub_2 = "const fetchItems = () => { /* ... */ };"
    is_stub2, _ = is_placeholder_js(stub_2)
    assert is_stub2 is True

    stub_comments_only = "/* File header */\n// TODO: implement later\n"
    is_valid, err = validate_implementation_completeness(stub_comments_only, "app.js")
    assert is_valid is False
    assert "only comments" in err.lower()


def test_valid_frontend_source_accepted():
    """Verify that substantive, valid JS implementations pass completeness checks."""
    valid_js = textwrap.dedent("""
    async function loadApplications() {
        try {
            const resp = await fetch('/api/applications');
            const data = await resp.json();
            renderTable(data);
        } catch (err) {
            console.error('Failed to load applications:', err);
        }
    }

    function renderTable(items) {
        const tbody = document.getElementById('apps-table');
        tbody.innerHTML = '';
        items.forEach(it => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${it.role}</td>`;
            tbody.appendChild(tr);
        });
    }
    """).strip()
    is_stub, _ = is_placeholder_js(valid_js)
    assert is_stub is False

    is_valid, err = validate_implementation_completeness(valid_js, "app.js")
    assert is_valid is True
    assert err is None


def test_missing_html_elements_detected(tmp_path: Path):
    """Verify that DOM element lookups in JS without matching HTML elements are caught."""
    html = textwrap.dedent("""
    <!DOCTYPE html>
    <html><body>
        <div id="existing-container"></div>
    </body></html>
    """).strip()
    js = textwrap.dedent("""
    const el = document.getElementById('non-existent-button');
    el.addEventListener('click', () => {});
    """).strip()
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    (tmp_path / "app.js").write_text(js, encoding="utf-8")

    report: CrossFileContractReport = CrossFileContractValidator.validate_workspace(tmp_path)
    assert report.valid is False
    assert len(report.dom_id_mismatches) >= 1
    assert "non-existent-button" in report.dom_id_mismatches[0]


def test_api_route_mismatches_detected(tmp_path: Path):
    """Verify that frontend calls to unmapped backend endpoints are caught."""
    backend_py = textwrap.dedent("""
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}
    """).strip()
    frontend_js = textwrap.dedent("""
    async function loadStats() {
        const res = await api.get('/api/unmapped_metrics_endpoint');
        return res;
    }
    """).strip()
    (tmp_path / "main.py").write_text(backend_py, encoding="utf-8")
    (tmp_path / "app.js").write_text(frontend_js, encoding="utf-8")
    (tmp_path / "index.html").write_text("<html><body></body></html>", encoding="utf-8")

    report: CrossFileContractReport = CrossFileContractValidator.validate_workspace(tmp_path)
    assert report.valid is False
    assert len(report.endpoint_mismatches) >= 1
    assert "/api/unmapped_metrics_endpoint" in report.endpoint_mismatches[0]


def test_valid_api_routes_match(tmp_path: Path):
    """Verify that matching routes between frontend calls and FastAPI backend pass."""
    backend_py = textwrap.dedent("""
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/api/companies")
    def list_companies():
        return []

    @app.post("/api/companies")
    def create_company():
        return {}

    @app.put("/api/companies/{company_id}")
    def update_company(company_id: int):
        return {}
    """).strip()
    frontend_js = textwrap.dedent("""
    async function init() {
        const comps = await api.get('/api/companies');
        await api.post('/api/companies', { name: 'Acme' });
        const compId = 5;
        await api.put(`/api/companies/${compId}`, { name: 'Acme Corp' });
    }
    """).strip()
    (tmp_path / "main.py").write_text(backend_py, encoding="utf-8")
    (tmp_path / "app.js").write_text(frontend_js, encoding="utf-8")
    (tmp_path / "index.html").write_text("<html><body></body></html>", encoding="utf-8")

    report: CrossFileContractReport = CrossFileContractValidator.validate_workspace(tmp_path)
    assert report.valid is True
    assert len(report.endpoint_mismatches) == 0


def test_incorrect_static_mounts_detected(tmp_path: Path):
    """Verify that broken stylesheet and script links in HTML are caught."""
    html = textwrap.dedent("""
    <!DOCTYPE html>
    <html><head>
        <link rel="stylesheet" href="missing_theme.css">
    </head><body>
        <script src="missing_bundle.js"></script>
    </body></html>
    """).strip()
    (tmp_path / "index.html").write_text(html, encoding="utf-8")

    report: CrossFileContractReport = CrossFileContractValidator.validate_workspace(tmp_path)
    assert report.valid is False
    assert len(report.html_asset_mismatches) == 2
    assert any("missing_theme.css" in m for m in report.html_asset_mismatches)
    assert any("missing_bundle.js" in m for m in report.html_asset_mismatches)


def test_invalid_startup_commands_detected(tmp_path: Path):
    """Verify that package.json start script pointing to wrong entrypoint is caught."""
    pkg = {
        "name": "test-app",
        "scripts": {
            "start": "python main.py"
        }
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()", encoding="utf-8")
    (tmp_path / "index.html").write_text("<html><body></body></html>", encoding="utf-8")

    report: CrossFileContractReport = CrossFileContractValidator.validate_workspace(tmp_path)
    assert report.valid is False
    assert len(report.startup_mismatches) >= 1
    assert "main.py" in report.startup_mismatches[0]


def test_pytest_failure_parsing_and_classification(tmp_path: Path):
    """Verify that pytest failures are captured, classified, and mapped to targeted repairs."""
    engine = PytestRecoveryEngine(workspace_root=tmp_path)

    # 1. Test Contract Defect: 201 vs 200
    out_contract = "FAILED tests/test_app.py::test_create_item - assert 201 == 200\n"
    ev_contract = engine.parse_and_classify("pytest", exit_code=1, stdout=out_contract)
    assert len(ev_contract.failing_items) == 1
    item1 = ev_contract.failing_items[0]
    assert item1.failure_class == FailureClass.TEST_CONTRACT_DEFECT
    assert "201" in item1.suggested_repair

    # 2. Database check_same_thread Defect
    out_db = "FAILED tests/test_app.py::test_db_concurrency - sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.\n"
    ev_db = engine.parse_and_classify("pytest", exit_code=1, stdout=out_db)
    assert len(ev_db.failing_items) == 1
    item2 = ev_db.failing_items[0]
    assert item2.failure_class == FailureClass.DATABASE_OR_STATE_DEFECT
    assert "check_same_thread" in item2.suggested_repair


def test_pytest_recovery_repeated_identical_failure_detection(tmp_path: Path):
    """Verify that repeated identical failure without source changes triggers NO_PROGRESS."""
    engine = PytestRecoveryEngine(workspace_root=tmp_path, max_repairs_per_fingerprint=2)
    stdout_fail = "FAILED tests/test_app.py::test_repro - assert 5 == 10\n"

    # Attempt 1: Recorded
    rec1 = engine.parse_and_classify("pytest", 1, stdout_fail)
    assert rec1.is_no_progress is False

    # Attempt 2: Recorded
    rec2 = engine.parse_and_classify("pytest", 1, stdout_fail)
    assert rec2.is_no_progress is False

    # Attempt 3: Exceeds budget -> NO_PROGRESS triggered!
    rec3 = engine.parse_and_classify("pytest", 1, stdout_fail)
    assert rec3.is_no_progress is True


def test_pytest_recovery_transient_failure_ordering(tmp_path: Path):
    """Verify that pytest failure recovery produces structured execution order."""
    engine = PytestRecoveryEngine(workspace_root=tmp_path)
    stdout_fail = "FAILED tests/test_api.py::test_get_users - assert 404 == 200\n"
    rec = engine.parse_and_classify("pytest", 1, stdout_fail)

    assert len(rec.repair_order) == 4
    assert rec.repair_order[0] == "pytest tests/test_api.py::test_get_users -v"
    assert rec.repair_order[1] == "pytest tests/test_api.py -v"
    assert rec.repair_order[2] == "pytest tests/ -v"
    assert rec.repair_order[3] == "browser e2e verification"


def test_responsibility_contract_evaluation(tmp_path: Path):
    """Verify responsibility contract accurately evaluates all full-stack layers."""
    main_code = textwrap.dedent("""
    from fastapi import FastAPI
    from pydantic import BaseModel
    import sqlite3
    import uvicorn

    app = FastAPI()

    class Item(BaseModel):
        name: str

    def get_db():
        conn = sqlite3.connect(':memory:')
        try:
            yield conn
        finally:
            conn.close()

    @app.get('/api/items')
    def list_items():
        return []

    @app.get('/')
    def index():
        return 'OK'

    if __name__ == '__main__':
        uvicorn.run('main:app')
    """).strip()
    (tmp_path / "main.py").write_text(main_code, encoding="utf-8")

    html_code = textwrap.dedent("""
    <!DOCTYPE html>
    <html><body>
        <nav><a class="nav-item" data-page="home">Home</a></nav>
        <section class="page-view active">
            <form><input name="test"><button>Go</button></form>
            <div id="toast-container"></div>
        </section>
    </body></html>
    """).strip()
    (tmp_path / "index.html").write_text(html_code, encoding="utf-8")

    css_code = textwrap.dedent("""
    .btn { display: flex; }
    .page-view.active { display: block; }
    @media (max-width: 768px) { .btn { font-size: 0.8rem; } }
    """).strip()
    (tmp_path / "style.css").write_text(css_code, encoding="utf-8")

    js_code = textwrap.dedent("""
    async function load() {
        try {
            await fetch('/api/items');
            document.querySelectorAll('.nav-item').forEach(el => {
                el.addEventListener('click', () => navigateTo(el.dataset.page));
            });
        } catch(e) {
            console.error(e);
        }
    }
    """).strip()
    (tmp_path / "app.js").write_text(js_code, encoding="utf-8")

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_code = textwrap.dedent("""
    def test_one():
        assert 1 == 1

    def test_two():
        assert 2 == 2
    """).strip()
    (test_dir / "test_smoke.py").write_text(test_code, encoding="utf-8")

    report: ResponsibilityReport = ResponsibilityContractEvaluator.evaluate_workspace(tmp_path)
    assert report.valid is True
    assert report.workspace_type == "fullstack"
    assert len(report.unmet_responsibilities) == 0


def test_runtime_integration_gate_syntax_check(tmp_path: Path):
    """Verify runtime integration gate catches syntax errors early before booting server."""
    (tmp_path / "broken.py").write_text("def broken_syntax(:\n    pass", encoding="utf-8")
    gate = RuntimeIntegrationGate(workspace_root=tmp_path)
    rep = gate.execute_gate(test_port=8999)

    assert rep.passed is False
    assert "source_syntax_validation" in rep.failed_steps
