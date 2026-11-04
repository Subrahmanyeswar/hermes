# tests/test_verified_feature_completion_and_contract_integrity_p0.py
"""
P0 Regression Test Suite:
Verified Feature Completion, Database Schema Evolution, Async DB Readiness,
Cross-File Contract Integrity, Preview Target Validation, and Turn-Budget Control.
Reproduces, investigates, and permanently fixes all failure modes observed in mission m_eb1d265a.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
from core.browser.acceptance import BrowserAcceptanceVerifier
from core.browser.manager import BrowserManager
from core.cross_file_contract import (
    CrossFileContractValidator,
    SEV_FAIL,
    SEV_PASS,
    SEV_WARNING,
)
from core.database_migrator import DatabaseMigrator
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    HermesRuntimeState,
    MissionState,
    MissionStatus,
    RequirementState,
    RequirementStatus,
)
from core.test_diagnostics import (
    TestFailureCategory,
    TestOutputParser,
)
from tools.platform.core_tools import ShellBashTool


# ==============================================================================
# TEST 1: FILE WRITES CANNOT INDEPENDENTLY COMPLETE FEATURE REQUIREMENTS
# ==============================================================================

def test_01_file_writes_do_not_verify_requirements():
    """
    Verify that file-write operations only transition tasks and requirements
    to IN_PROGRESS or IMPLEMENTED, but NEVER mark them COMPLETED or VERIFIED.
    """
    req = RequirementState(
        requirement_id="req_auth",
        goal_id="g1",
        title="B2B Authentication",
        description="Admin and user login functionality",
        status=RequirementStatus.NOT_STARTED,
    )

    # First write (e.g. index.html) transitions to IN_PROGRESS
    req.transition_status(RequirementStatus.IN_PROGRESS, reason="Artifact modified by write_file", actor="agent_loop")
    assert req.status == RequirementStatus.IN_PROGRESS
    assert req.status != RequirementStatus.VERIFIED

    # Second write (implementation code e.g. server.js) transitions to IMPLEMENTED
    req.transition_status(RequirementStatus.IMPLEMENTED, reason="Implementation code written by write_file", actor="agent_loop")
    assert req.status == RequirementStatus.IMPLEMENTED
    assert req.status != RequirementStatus.VERIFIED


# ==============================================================================
# TEST 2: REQUIREMENT COMPLETION REQUIRES MATCHING ACCEPTANCE EVIDENCE
# ==============================================================================

def test_02_requirement_completion_requires_acceptance_evidence():
    """
    Verify that GoalCompleteGuard and CompletionPolicy reject completion when
    requirements are merely IMPLEMENTED without passing acceptance evidence.
    """
    state = HermesRuntimeState.create_empty(mission_id="m_test_guard")
    req = RequirementState(
        requirement_id="req_dashboard",
        goal_id="g1",
        title="Interactive Dashboard",
        description="Dashboard statistics and charts",
        status=RequirementStatus.IMPLEMENTED,  # Implemented on disk, but NOT verified
    )
    state.requirements["req_dashboard"] = req

    can_complete, reason, issues = GoalCompleteGuard.evaluate(state=state, strict_requirements=True)
    assert can_complete is False
    assert any("req_dashboard" in iss for iss in issues)

    policy = CompletionPolicy()
    is_complete, pol_reason, pol_unmet = policy.evaluate_completion(
        mission_prompt="Build B2B Trade Platform with Interactive Dashboard",
        runtime_state=state,
        strict_requirements=True,
    )
    assert is_complete is False
    assert any("req_dashboard" in iss for iss in pol_unmet)


# ==============================================================================
# TEST 3: OLD SQLITE SCHEMAS DETECTED AND MIGRATED SAFELY
# ==============================================================================

def test_03_stale_sqlite_schema_detected_and_migrated_safely(tmp_path):
    """
    Verify DatabaseMigrator detects stale SQLite schemas on disk and applies
    safe, non-destructive ALTER TABLE migrations while preserving 100% of data.
    """
    db_file = tmp_path / "globaltrade.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            origin TEXT NOT NULL,
            image TEXT NOT NULL,
            price TEXT NOT NULL,
            moq TEXT NOT NULL,
            status TEXT NOT NULL
        );
    """)
    cursor.execute("""
        INSERT INTO products (id, name, type, origin, image, price, moq, status)
        VALUES (1, 'Basmati Rice', 'Export', 'India', '/img/rice.jpg', '$850/ton', '20 tons', 'Active');
    """)
    conn.commit()
    conn.close()

    backend_code = """
        const schema = `
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            classification TEXT NOT NULL,
            origin TEXT NOT NULL,
            image_url TEXT NOT NULL,
            indicative_price TEXT NOT NULL,
            min_order_quantity TEXT NOT NULL,
            availability TEXT NOT NULL
        );`;
    """

    actual = DatabaseMigrator.inspect_sqlite_schema(db_file)
    expected = DatabaseMigrator.extract_expected_schema_from_code(backend_code)
    discrepancies = DatabaseMigrator.detect_schema_discrepancies(actual, expected)

    assert len(discrepancies) > 0
    disc = discrepancies[0]
    assert disc["type"] == "STALE_SCHEMA_COLUMNS"
    assert "classification" in disc["missing_columns"]
    assert "availability" in disc["missing_columns"]
    assert disc["stale_synonyms"]["classification"] == "type"
    assert disc["stale_synonyms"]["availability"] == "status"

    report = DatabaseMigrator.apply_safe_schema_migration(db_file, expected)
    assert report.is_clean
    assert report.preserved_rows_count >= 1
    assert "products.classification" in report.added_columns
    assert "products.availability" in report.added_columns

    # Verify preserved data and migrated values
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM products WHERE id = 1;").fetchone()
    assert row["name"] == "Basmati Rice"
    assert row["classification"] == "Export"  # copied from 'type'
    assert row["availability"] == "Active"    # copied from 'status'
    assert row["indicative_price"] == "$850/ton"  # copied from 'price'
    conn.close()


# ==============================================================================
# TEST 4: ASYNC DB INITIALIZATION READINESS RACE DETECTED
# ==============================================================================

def test_04_async_db_initialization_readiness_race_detected(tmp_path):
    """
    Verify detection of asynchronous SQLite initialization race conditions
    where app.listen is invoked before the schema has completed creation.
    """
    racy_code = """
        const express = require('express');
        const sqlite3 = require('sqlite3').verbose();
        const app = express();
        const db = new sqlite3.Database('test.db', (err) => {
            initDb();
        });
        function initDb() {
            db.run("CREATE TABLE products (id INTEGER PRIMARY KEY);");
        }
        // Race condition: app.listen called synchronously outside initDb
        app.listen(3000);
        module.exports = { app, db };
    """

    is_safe, err_msg = DatabaseMigrator.verify_async_db_initialization(racy_code)
    assert not is_safe
    assert "ASYNC_DB_READINESS_RACE" in err_msg or "app.listen" in err_msg

    safe_code = """
        const express = require('express');
        const sqlite3 = require('sqlite3').verbose();
        const app = express();
        let db;
        function initDb() {
            return new Promise((resolve) => {
                db = new sqlite3.Database('test.db', () => {
                    db.run("CREATE TABLE products (id INTEGER PRIMARY KEY);", resolve);
                });
            });
        }
        initDb().then(() => {
            app.listen(3000);
        });
        module.exports = { app, initDb };
    """
    is_safe_2, _ = DatabaseMigrator.verify_async_db_initialization(safe_code)
    assert is_safe_2


# ==============================================================================
# TEST 5: FRONTEND AND BACKEND PRODUCT FIELD MISMATCH DETECTED
# ==============================================================================

def test_05_frontend_backend_product_field_mismatch_detected(tmp_path):
    """
    Verify CrossFileContractValidator flags discrepancies when backend and frontend
    use conflicting product attribute names (e.g. classification vs type).
    """
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "mismatch-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        const schema = `
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            classification TEXT NOT NULL,
            availability TEXT NOT NULL
        );`;
        app.get('/api/products', (req, res) => {
            res.json({ products: [{ id: 1, name: "Rice", classification: "Export", availability: "In Stock" }] });
        });
        module.exports = { app };
    """, encoding="utf-8")
    (ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="productGrid"></div>
        <script src="app.js"></script>
        </body></html>
    """, encoding="utf-8")
    (ws / "style.css").write_text("body { margin: 0; font-family: sans-serif; }\n" * 30, encoding="utf-8")
    (ws / "app.js").write_text("""
        async function render() {
            const res = await fetch('/api/products');
            const data = await res.json();
            const p = data.products[0];
            // Mismatch: accesses p.type and p.status instead of classification and availability
            document.getElementById('productGrid').innerHTML = `<span>${p.type} - ${p.status}</span>`;
        }
    """, encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    prop_discs = [d for d in report.discrepancies if d.type == "PRODUCT_PROPERTY_MISMATCH"]
    assert len(prop_discs) > 0
    assert any("classification" in d.mismatch or "availability" in d.mismatch for d in prop_discs)


# ==============================================================================
# TEST 6: CATEGORY VALUES AND CASING CONSISTENCY
# ==============================================================================

def test_06_category_casing_and_value_mismatch_detected(tmp_path):
    """
    Verify CrossFileContractValidator detects category casing discrepancies
    (e.g. 'Agricultural Products' in HTML vs 'Agricultural products' in DB seeds).
    """
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "cat-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        const seeds = [
            { id: 1, name: "Rice", category: "Agricultural products" },
            { id: 2, name: "Pepper", category: "Spices" }
        ];
        app.get('/api/products', (req, res) => res.json({ products: seeds }));
        module.exports = { app };
    """, encoding="utf-8")
    (ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <select id="categoryFilter">
            <option value="Agricultural Products">Agricultural Products</option>
            <option value="Spices">Spices</option>
        </select>
        <script src="app.js"></script>
        </body></html>
    """, encoding="utf-8")
    (ws / "style.css").write_text("body { margin: 0; }\n" * 30, encoding="utf-8")
    (ws / "app.js").write_text("// app", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    cat_discs = [d for d in report.discrepancies if d.type == "CATEGORY_VALUE_MISMATCH"]
    assert len(cat_discs) > 0
    assert "Agricultural Products" in cat_discs[0].mismatch


# ==============================================================================
# TEST 7: ENQUIRY TEST PAYLOADS MATCH BACKEND EXPECTATIONS
# ==============================================================================

def test_07_test_enquiry_payload_mismatch_detected(tmp_path):
    """
    Verify CrossFileContractValidator detects when Jest tests post enquiry
    payloads missing required fields (e.g. contact, country, direction).
    """
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "enq-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.use(express.json());
        app.post('/api/enquiries', (req, res) => {
            const { company, contact, country, direction } = req.body;
            if (!company || !contact || !country || !direction) {
                return res.status(400).json({ error: "Missing required enquiry fields" });
            }
            res.status(201).json({ success: true, reference: "GTC-ENQ-1001" });
        });
        module.exports = { app };
    """, encoding="utf-8")
    tests_dir = ws / "tests"
    tests_dir.mkdir()
    (tests_dir / "api.test.js").write_text("""
        const request = require('supertest');
        process.env.GLOBALTRADE_TEST_DB_PATH = ':memory:';
        const { app } = require('../server');
        test('create enquiry', async () => {
            // Defective payload missing direction and country
            const res = await request(app).post('/api/enquiries').send({
                company: "Acme Corp",
                contact: "Alice"
            });
            expect(res.status).toBe(201);
        });
    """, encoding="utf-8")
    (ws / "index.html").write_text("<!DOCTYPE html><html><body></body></html>", encoding="utf-8")
    (ws / "style.css").write_text("body { margin: 0; }\n" * 30, encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    enq_discs = [d for d in report.discrepancies if d.type == "TEST_PAYLOAD_MISMATCH"]
    assert len(enq_discs) > 0


# ==============================================================================
# TEST 8: TRACKING ROUTES, REFERENCES AND RESPONSE FIELDS MATCH
# ==============================================================================

def test_08_test_tracking_route_and_seed_mismatch_detected(tmp_path):
    """
    Verify CrossFileContractValidator detects when tests send requests to incorrect
    routes or query unseeded tracking references.
    """
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "track-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        const shipments = { "GT-SHP-1001": { status: "In Transit", origin: "Mumbai" } };
        app.get('/api/track/:ref', (req, res) => {
            const shp = shipments[req.params.ref];
            if (!shp) return res.status(404).json({ error: "Not found" });
            res.json(shp);
        });
        module.exports = { app };
    """, encoding="utf-8")
    tests_dir = ws / "tests"
    tests_dir.mkdir()
    (tests_dir / "api.test.js").write_text("""
        const request = require('supertest');
        process.env.GLOBALTRADE_TEST_DB_PATH = ':memory:';
        const { app } = require('../server');
        test('track shipment', async () => {
            // Mismatch: queries /api/shipments/ instead of /api/track/ and unseeded reference GT-SHP-9999
            const res = await request(app).get('/api/shipments/GT-SHP-9999');
            expect(res.status).toBe(200);
        });
    """, encoding="utf-8")
    (ws / "index.html").write_text("<!DOCTYPE html><html><body></body></html>", encoding="utf-8")
    (ws / "style.css").write_text("body { margin: 0; }\n" * 30, encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    route_discs = [d for d in report.discrepancies if d.type in ("TEST_ROUTE_MISMATCH", "TEST_SEED_REFERENCE_MISMATCH")]
    assert len(route_discs) > 0


# ==============================================================================
# TEST 9: ADMIN ROUTE AND AUTHENTICATION CONTRACTS MATCH
# ==============================================================================

def test_09_admin_auth_and_route_contract_mismatches_detected(tmp_path):
    """
    Verify CrossFileContractValidator detects authentication mechanism mismatches
    and admin update endpoint route parameter mismatches (:id vs :reference).
    """
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "admin-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        // Server requires Basic Auth header via checkAdmin
        function checkAdmin(req, res, next) {
            const auth = req.headers.authorization;
            if (!auth || !auth.startsWith('Basic ')) return res.status(401).send();
            next();
        }
        app.use('/api/admin', checkAdmin);
        // Expects :reference
        app.patch('/api/admin/enquiries/:reference/status', (req, res) => res.json({ success: true }));
        module.exports = { app };
    """, encoding="utf-8")
    (ws / "index.html").write_text("<!DOCTYPE html><html><body><script src='app.js'></script></body></html>", encoding="utf-8")
    (ws / "style.css").write_text("body { margin: 0; }\n" * 30, encoding="utf-8")
    (ws / "app.js").write_text("""
        async function adminLogin() {
            // Frontend sends JSON password body instead of Basic Auth header
            await fetch('/api/admin/login', {
                method: 'POST',
                body: JSON.stringify({ username: 'admin', password: 'secretpassword' })
            });
        }
        async function updateStatus(id) {
            // Frontend uses numeric id parameter instead of reference
            await fetch(`/api/admin/enquiries/${id}/status`, {
                method: 'PATCH',
                body: JSON.stringify({ status: 'Approved' })
            });
        }
    """, encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    auth_discs = [d for d in report.discrepancies if d.type in ("AUTH_MECHANISM_MISMATCH", "ADMIN_ROUTE_PARAM_MISMATCH")]
    assert len(auth_discs) > 0


# ==============================================================================
# TEST 10: JEST RELATIVE IMPORT CLASSIFIED AS IMPORT FAILURE
# ==============================================================================

def test_10_jest_relative_import_classified_as_import_failure():
    """
    Verify TestOutputParser classifies missing local relative imports (e.g. '../server')
    as TEST_IMPORT_FAILURE rather than misclassifying them as third-party DEPENDENCY_FAILURE.
    """
    raw_jest_output = """
    FAIL tests/api.test.js
      ● Test suite failed to run

        Cannot find module '../server' from 'tests/api.test.js'

          1 | const request = require('supertest');
        > 2 | const { app } = require('../server');
            |                 ^
          3 |

          at Resolver.resolveModule (node_modules/jest-resolve/build/resolver.js:324:11)
          at Object.require (tests/api.test.js:2:17)
    """

    evidence = TestOutputParser.parse(
        command="npm test",
        working_dir="/test",
        exit_code=1,
        stdout=raw_jest_output,
        stderr="",
    )
    assert evidence.primary_failure_category == TestFailureCategory.TEST_IMPORT_FAILURE
    assert evidence.primary_failure_category != TestFailureCategory.DEPENDENCY_FAILURE

    # In contrast, a genuine third-party missing package should be DEPENDENCY_FAILURE
    dep_output = """
    FAIL tests/api.test.js
      ● Test suite failed to run

        Cannot find module 'express' from 'server.js'
    """
    dep_evidence = TestOutputParser.parse(
        command="npm test",
        working_dir="/test",
        exit_code=1,
        stdout=dep_output,
        stderr="",
    )
    assert dep_evidence.primary_failure_category == TestFailureCategory.DEPENDENCY_FAILURE


# ==============================================================================
# TEST 11: INCORRECT PREVIEW TITLE FAILS QUALIFICATION
# ==============================================================================

@pytest.mark.asyncio
async def test_11_incorrect_preview_title_fails_qualification(tmp_path):
    """
    Verify BrowserManager.open_preview rejects preview with INCORRECT_PREVIEW_TARGET
    when the served page title does not match the generated workspace HTML title.
    """
    ws = tmp_path
    (ws / "index.html").write_text("""
        <!DOCTYPE html><html><head>
        <title>GlobalTrade Connect - B2B Platform</title>
        </head><body><h1>Platform</h1></body></html>
    """, encoding="utf-8")

    bm = BrowserManager()
    mock_server = MagicMock()
    mock_server.url = "http://127.0.0.1:56673"
    mock_server.port = 56673
    mock_server.workspace_dir = str(ws)

    bm.dev_servers = MagicMock()
    bm.dev_servers.get_active_server = MagicMock(return_value=mock_server)
    bm.dev_servers.start_static_server = AsyncMock(return_value=mock_server)
    bm.dev_servers.stop_stale_servers_not_matching = MagicMock()

    # Mock navigation returning a stale process page title ("Hello 2")
    nav_mock = MagicMock()
    nav_mock.success = True
    nav_mock.status = 200
    nav_mock.title = "Hello 2"
    nav_mock.error = None

    with patch.object(bm, "navigate", new_callable=AsyncMock, return_value=nav_mock):
        with patch.object(bm, "launch", new_callable=AsyncMock):
            bm.is_running = True
            result = await bm.open_preview(workspace_dir=ws)

            assert result["success"] is False
            assert "INCORRECT_PREVIEW_TARGET" in result["error"]
            assert "Hello 2" in result["error"]
            assert "GlobalTrade Connect" in result["error"]


# ==============================================================================
# TEST 12: BROWSER VERIFICATION TARGETS GENERATED APPLICATION
# ==============================================================================

@pytest.mark.asyncio
async def test_12_browser_verification_targets_generated_application(tmp_path):
    """
    Verify BrowserAcceptanceVerifier checks document.title against generated HTML
    and fails qualification when the page title belongs to a foreign or stale server.
    """
    ws = tmp_path
    (ws / "index.html").write_text("""
        <!DOCTYPE html><html><head>
        <title>GlobalTrade Connect - B2B Platform</title>
        </head><body><div id="app">Meaningful rendered application content exceeding 50 characters.</div></body></html>
    """, encoding="utf-8")
    (ws / "server.js").write_text("console.log('server');", encoding="utf-8")

    class MockWebSocket:
        def __init__(self):
            self._last_id = None
        async def send(self, msg):
            self._last_id = json.loads(msg).get("id")
        async def recv(self):
            if self._last_id == 10:
                return json.dumps({"id": 10, "result": {"result": {"value": "<div id='app'>Meaningful rendered application content exceeding 50 characters.</div>"}}})
            elif self._last_id == 11:
                # Returns stale foreign title instead of GlobalTrade Connect
                return json.dumps({"id": 11, "result": {"result": {"value": "Stale Foreign Application"}}})
            elif self._last_id == 12:
                return json.dumps({"id": 12, "result": {"result": {"value": []}}})
            elif self._last_id == 20:
                return json.dumps({"id": 20, "result": {"data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY44YAAAAASUVORK5CYII="}})
            return json.dumps({"id": self._last_id, "result": {}})
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch.object(BrowserAcceptanceVerifier, "find_browser_executable", return_value="dummy_chrome"):
        with patch.object(BrowserAcceptanceVerifier, "is_port_in_use", return_value=True):
            with patch("subprocess.Popen", return_value=mock_proc):
                with patch("urllib.request.urlopen") as mock_url:
                    mock_resp = MagicMock()
                    mock_resp.read.return_value = json.dumps([{"webSocketDebuggerUrl": "ws://127.0.0.1:9222/page"}]).encode("utf-8")
                    mock_url.return_value.__enter__.return_value = mock_resp
                    with patch("websockets.connect", return_value=MockWebSocket()):
                        res = await BrowserAcceptanceVerifier.verify_workspace(ws, preferred_port=3000)
                        assert not res.passed
                        assert any("INCORRECT_PREVIEW_TARGET" in iss for iss in res.issues)


# ==============================================================================
# TEST 13: RENDERED IMAGE QUALIFICATION
# ==============================================================================

@pytest.mark.asyncio
async def test_13_rendered_image_qualification(tmp_path):
    """
    Verify BrowserAcceptanceVerifier inspects rendered images and flags BROKEN_IMAGE_ASSETS
    when image tags finish loading with naturalWidth == 0.
    """
    ws = tmp_path
    (ws / "index.html").write_text("""
        <!DOCTYPE html><html><head><title>Trade App</title></head><body>
        <div id="app">Meaningful rendered application content exceeding 50 characters.
            <img src="/broken_asset.jpg" />
        </div>
        </body></html>
    """, encoding="utf-8")
    (ws / "server.js").write_text("console.log('server');", encoding="utf-8")

    class MockWebSocketWithBrokenImage:
        def __init__(self):
            self._last_id = None
        async def send(self, msg):
            self._last_id = json.loads(msg).get("id")
        async def recv(self):
            if self._last_id == 10:
                return json.dumps({"id": 10, "result": {"result": {"value": "<div id='app'>Meaningful rendered application content exceeding 50 characters.</div>"}}})
            elif self._last_id == 11:
                return json.dumps({"id": 11, "result": {"result": {"value": "Trade App"}}})
            elif self._last_id == 12:
                # Broken image element: complete=True, naturalWidth=0
                return json.dumps({"id": 12, "result": {"result": {"value": [{"src": "http://127.0.0.1:3000/broken_asset.jpg", "naturalWidth": 0, "complete": True}]}}})
            elif self._last_id == 20:
                return json.dumps({"id": 20, "result": {"data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY44YAAAAASUVORK5CYII="}})
            return json.dumps({"id": self._last_id, "result": {}})
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch.object(BrowserAcceptanceVerifier, "find_browser_executable", return_value="dummy_chrome"):
        with patch.object(BrowserAcceptanceVerifier, "is_port_in_use", return_value=True):
            with patch("subprocess.Popen", return_value=mock_proc):
                with patch("urllib.request.urlopen") as mock_url:
                    mock_resp = MagicMock()
                    mock_resp.read.return_value = json.dumps([{"webSocketDebuggerUrl": "ws://127.0.0.1:9222/page"}]).encode("utf-8")
                    mock_url.return_value.__enter__.return_value = mock_resp
                    with patch("websockets.connect", return_value=MockWebSocketWithBrokenImage()):
                        res = await BrowserAcceptanceVerifier.verify_workspace(ws, preferred_port=3000)
                        assert not res.passed
                        assert any("BROKEN_IMAGE_ASSETS" in iss for iss in res.issues)


# ==============================================================================
# TEST 14: CSS SELECTOR AND FRAMEWORK QUALIFICATION
# ==============================================================================

def test_14_css_selector_and_framework_qualification(tmp_path):
    """
    Verify CrossFileContractValidator detects missing CSS framework links
    and insufficient stylesheets (< 25 lines) missing responsive component styles.
    """
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "css-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("const express = require('express'); module.exports = { app: express() };", encoding="utf-8")
    # HTML uses bootstrap classes without bootstrap stylesheet
    (ws / "index.html").write_text("""
        <!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head><body>
        <div class="col-md-4 card-body">Item</div>
        </body></html>
    """, encoding="utf-8")
    # Insufficient stylesheet: only 3 lines
    (ws / "style.css").write_text("body { color: black; }\nh1 { font-size: 20px; }\n", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    types = [d.type for d in report.discrepancies]
    assert "MISSING_CSS_FRAMEWORK" in types
    assert "INSUFFICIENT_STYLESHEET" in types


# ==============================================================================
# TEST 15: REPEATED DEPENDENCY INSTALLATION IS PREVENTED
# ==============================================================================

def test_15_redundant_dependency_installation_prevented(tmp_path):
    """
    Verify ShellBashTool intercepts redundant npm install commands when the package
    is already listed in package.json and installed in node_modules, saving turns.
    """
    ws = tmp_path
    (ws / "package.json").write_text(json.dumps({
        "name": "test-pkg",
        "dependencies": {
            "cors": "^2.8.5"
        }
    }), encoding="utf-8")
    cors_dir = ws / "node_modules" / "cors"
    cors_dir.mkdir(parents=True)
    (cors_dir / "package.json").write_text('{"name": "cors", "version": "2.8.5"}', encoding="utf-8")

    tool = ShellBashTool()
    res = tool.execute({"command": "npm install cors", "working_dir": str(ws)})

    assert res.exit_code == 0
    assert "already declared in package.json and installed in node_modules" in res.output
    assert res.details.get("skipped_redundant_install") == "cors"


# ==============================================================================
# TEST 16: POSITIVE FIXTURE: CLEAN COHERENT PROJECT PASSES VALIDATOR
# ==============================================================================

def test_16_positive_coherent_workspace_passes_validation(tmp_path):
    """
    Verify that a fully coherent, well-architected full-stack workspace passes validation cleanly.
    """
    ws = tmp_path
    (ws / "package.json").write_text(json.dumps({
        "name": "globaltrade-connect",
        "version": "1.0.0",
        "main": "server.js",
        "scripts": {"test": "jest"},
        "dependencies": {"express": "^4.19.2", "sqlite3": "^5.1.7"},
        "devDependencies": {"jest": "^29.7.0", "supertest": "^7.0.0"}
    }), encoding="utf-8")

    (ws / "server.js").write_text("""
        const express = require('express');
        const path = require('path');
        const sqlite3 = require('sqlite3').verbose();
        const app = express();
        app.use(express.json());
        app.use(express.static(path.join(__dirname, 'public')));

        let db;
        function initDb() {
            return new Promise((resolve) => {
                db = new sqlite3.Database(':memory:', () => {
                    db.run(`
                        CREATE TABLE products (
                            id INTEGER PRIMARY KEY,
                            name TEXT NOT NULL,
                            category TEXT NOT NULL,
                            classification TEXT NOT NULL,
                            origin TEXT NOT NULL,
                            image_url TEXT NOT NULL,
                            indicative_price TEXT NOT NULL,
                            min_order_quantity TEXT NOT NULL,
                            availability TEXT NOT NULL
                        );
                    `, resolve);
                });
            });
        }

        app.get('/api/products', (req, res) => {
            res.json({
                products: [{
                    id: 1,
                    name: "Basmati Rice",
                    category: "Agricultural products",
                    classification: "Export",
                    origin: "India",
                    image_url: "/img/rice.jpg",
                    indicative_price: "$850/ton",
                    min_order_quantity: "20 tons",
                    availability: "In Stock"
                }]
            });
        });

        app.post('/api/enquiries', (req, res) => {
            const { company, contact, country, direction } = req.body;
            res.status(201).json({ success: true, reference: "GTC-ENQ-1001" });
        });

        app.get('/api/track/:ref', (req, res) => {
            res.json({ tracking_ref: req.params.ref, status: "In Transit", origin: "Mumbai", destination: "Dubai" });
        });

        app.post('/api/admin/login', (req, res) => {
            res.json({ success: true, token: "admin-jwt" });
        });

        app.get('/api/admin/stats', (req, res) => res.json({ enquiries: 1, shipments: 1 }));
        app.get('/api/admin/enquiries', (req, res) => res.json([]));
        app.get('/api/admin/shipments', (req, res) => res.json([]));
        app.patch('/api/admin/enquiries/:id/status', (req, res) => res.json({ success: true }));

        module.exports = { app, initDb };
    """, encoding="utf-8")

    pub_dir = ws / "public"
    pub_dir.mkdir()
    (pub_dir / "index.html").write_text("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>GlobalTrade Connect - B2B Marketplace</title>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
            <link rel="stylesheet" href="style.css">
        </head>
        <body>
            <header class="hero"><h1>GlobalTrade Connect</h1></header>
            <div class="container">
                <select id="categoryFilter">
                    <option value="Agricultural products">Agricultural products</option>
                </select>
                <div id="productGrid" class="product-grid"></div>
            </div>
            <script src="main.js"></script>
        </body>
        </html>
    """, encoding="utf-8")

    (pub_dir / "style.css").write_text("""
        :root {
            --primary: #0d6efd;
            --secondary: #6c757d;
            --success: #198754;
            --dark: #212529;
            --light: #f8f9fa;
        }
        body {
            font-family: system-ui, -apple-system, sans-serif;
            margin: 0;
            padding: 0;
            background-color: var(--light);
            color: var(--dark);
        }
        .hero {
            background: linear-gradient(135deg, #1a237e 0%, #0d47a1 100%);
            color: #ffffff;
            padding: 3rem 1.5rem;
            text-align: center;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem 1.5rem;
        }
        .product-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-top: 1.5rem;
        }
        .product-card {
            background: #ffffff;
            border-radius: 8px;
            border: 1px solid #dee2e6;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            transition: transform 0.2s ease;
        }
        .product-card:hover {
            transform: translateY(-4px);
        }
        .product-card img {
            width: 100%;
            height: 200px;
            object-fit: cover;
        }
        .product-card .card-body {
            padding: 1.25rem;
        }
        .badge-export {
            display: inline-block;
            background-color: var(--success);
            color: white;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.85rem;
        }
        .btn-enquiry {
            display: inline-block;
            background-color: var(--primary);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            text-decoration: none;
            margin-top: 0.5rem;
        }
        @media (max-width: 768px) {
            .hero { padding: 1.5rem 1rem; }
            .product-grid { grid-template-columns: 1fr; }
        }
    """, encoding="utf-8")

    (pub_dir / "main.js").write_text("""
        async function loadProducts() {
            const res = await fetch('/api/products');
            const data = await res.json();
            const grid = document.getElementById('productGrid');
            grid.innerHTML = (data.products || []).map(p => `
                <div class="product-card">
                    <img src="${p.image_url}" alt="${p.name}">
                    <div class="card-body">
                        <h5>${p.name}</h5>
                        <p>${p.classification} - ${p.origin}</p>
                        <p>${p.indicative_price} | MOQ: ${p.min_order_quantity}</p>
                        <span class="badge-export">${p.availability}</span>
                    </div>
                </div>
            `).join('');
        }
        window.addEventListener('DOMContentLoaded', loadProducts);
    """, encoding="utf-8")

    tests_dir = ws / "tests"
    tests_dir.mkdir()
    (tests_dir / "api.test.js").write_text("""
        const request = require('supertest');
        process.env.GLOBALTRADE_TEST_DB_PATH = ':memory:';
        const { app } = require('../server');

        describe('GlobalTrade Connect API', () => {
            test('GET /api/products returns products list', async () => {
                const res = await request(app).get('/api/products');
                expect(res.status).toBe(200);
                expect(res.body.products).toBeDefined();
            });

            test('POST /api/enquiries creates new trade enquiry', async () => {
                const res = await request(app).post('/api/enquiries').send({
                    company: "Gulf Importers Ltd",
                    contact: "Ahmed Al-Mansoor",
                    country: "UAE",
                    direction: "Import"
                });
                expect(res.status).toBe(201);
                expect(res.body.reference).toBe("GTC-ENQ-1001");
            });

            test('GET /api/track/:ref returns tracking details', async () => {
                const res = await request(app).get('/api/track/GTC-SHP-2025-001');
                expect(res.status).toBe(200);
            });
        });
    """, encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert report.valid
    assert report.severity in (SEV_PASS, SEV_WARNING)
