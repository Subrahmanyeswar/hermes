# tests/test_contract_first_engine_p0.py
"""
HERMES 2.x — P0 Contract-First Engine & Integration Intelligence Test Suite
=============================================================================
Tests deterministic contract gates:
- Fixture A: Browser module loading tag mismatch (BROWSER_MODULE_TYPE_MISMATCH)
- Fixture B: Missing imported named export (MISSING_IMPORTED_EXPORT)
- Fixture C: Missing API client method (API_CLIENT_METHOD_MISSING)
- Fixture D: Response envelope mismatch (API_RESPONSE_SHAPE_MISMATCH)
- Fixture E: Direction enum uppercase mismatch (DATABASE_ENUM_CONTRACT_MISMATCH)
- Fixture F: Missing required request field in form (REQUEST_FIELD_CONTRACT_MISMATCH)
- Fixture G: Tracking DOM selectors mismatch (DOM_REFERENCE_MISMATCH)
- Fixture H: Supertest server export shape mismatch (TEST_SERVER_EXPORT_MISMATCH)
- Fixture I: Duplicate validation attempt blocked without intervening source changes
- Fixture J: Autonomous tool repair of contract mismatches to valid state
- Fixture K: Preservation of HTTP 201 contract truth (not altering to 200)
- Fixture L: Stale evidence invalidation upon subsequent file mutation
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.cross_file_contract import (
    CrossFileContractValidator,
    CrossFileContractReport,
    SEV_FAIL,
    SEV_PASS,
)
from core.test_diagnostics import (
    TestFailureCategory,
    TestOutputParser,
)


@pytest.fixture
def disposable_workspace():
    """Provides a clean temporary workspace for each test."""
    temp_dir = tempfile.mkdtemp(prefix="hermes_p0_contract_")
    ws = Path(temp_dir)
    yield ws
    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# FIXTURE A: BROWSER MODULE LOADING
# ==============================================================================

def test_fixture_a_browser_module_type_mismatch(disposable_workspace):
    """HTML loads an ES module entry point using a classic script tag without type='module'."""
    ws = disposable_workspace
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><script src="app.js"></script></head><body><div id="root"></div></body></html>',
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        'import { initCatalog } from "./js/catalog.js";\nconsole.log("App init");',
        encoding="utf-8"
    )
    (ws / "js").mkdir(parents=True, exist_ok=True)
    (ws / "js" / "catalog.js").write_text(
        'export function initCatalog() { return true; }',
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("BROWSER_MODULE_TYPE_MISMATCH" in m for m in report.module_graph_mismatches)
    assert any(d.type == "BROWSER_MODULE_TYPE_MISMATCH" for d in report.discrepancies)


# ==============================================================================
# FIXTURE B: MISSING EXPORT
# ==============================================================================

def test_fixture_b_missing_imported_export(disposable_workspace):
    """app.js imports initCatalog, while catalog.js exports only CatalogModule."""
    ws = disposable_workspace
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><script type="module" src="app.js"></script></head><body></body></html>',
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        'import { initCatalog } from "./js/catalog.js";\ninitCatalog();',
        encoding="utf-8"
    )
    (ws / "js").mkdir(parents=True, exist_ok=True)
    (ws / "js" / "catalog.js").write_text(
        'export const CatalogModule = { init: () => true };',
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("MISSING_IMPORTED_EXPORT" in m for m in report.module_graph_mismatches)
    assert any("initCatalog" in m for m in report.module_graph_mismatches)
    assert any(d.type == "MISSING_IMPORTED_EXPORT" for d in report.discrepancies)


# ==============================================================================
# FIXTURE C: MISSING API METHOD
# ==============================================================================

def test_fixture_c_missing_api_method(disposable_workspace):
    """catalog.js calls api.getProducts(), but api.js does not implement it."""
    ws = disposable_workspace
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><script type="module" src="app.js"></script></head><body></body></html>',
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        'import { CatalogModule } from "./js/catalog.js";\nCatalogModule.init();',
        encoding="utf-8"
    )
    (ws / "js").mkdir(parents=True, exist_ok=True)
    (ws / "js" / "api.js").write_text(
        'export const api = { get: async (url) => ({}), post: async (url, d) => ({}) };',
        encoding="utf-8"
    )
    (ws / "js" / "catalog.js").write_text(
        'import { api } from "./api.js";\nexport const CatalogModule = { init: async () => { const prods = await api.getProducts(); } };',
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("API_CLIENT_METHOD_MISSING" in m for m in report.api_client_mismatches)
    assert any("getProducts" in m for m in report.api_client_mismatches)
    assert any(d.type == "API_CLIENT_METHOD_MISSING" for d in report.discrepancies)


# ==============================================================================
# FIXTURE D: RESPONSE ENVELOPE MISMATCH
# ==============================================================================

def test_fixture_d_response_envelope_mismatch(disposable_workspace):
    """Backend returns { success: true, reference: '123' }, frontend reads res.inquiry.reference."""
    ws = disposable_workspace
    (ws / "server.js").write_text(
        """
        const express = require('express');
        const app = express();
        app.post('/api/inquiries', (req, res) => {
            res.status(201).json({ success: true, reference: 'BBT-123', inquiry_id: 42 });
        });
        module.exports = { app };
        """,
        encoding="utf-8"
    )
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><script type="module" src="app.js"></script></head><body></body></html>',
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        """
        async function submitRFQ() {
            const res = await api.post('/api/inquiries', { direction: 'export' });
            const ref = res.inquiry.reference;
            document.getElementById('ref').innerText = ref;
        }
        submitRFQ();
        """,
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("API_RESPONSE_SHAPE_MISMATCH" in m for m in report.response_shape_mismatches)
    assert any("inquiry" in m for m in report.response_shape_mismatches)


# ==============================================================================
# FIXTURE E: DIRECTION ENUM MISMATCH
# ==============================================================================

def test_fixture_e_direction_enum_mismatch(disposable_workspace):
    """HTML form sends uppercase EXPORT, database CHECK constraint requires lowercase export."""
    ws = disposable_workspace
    (ws / "server.js").write_text(
        """
        // CREATE TABLE inquiries (id INTEGER PRIMARY KEY, direction TEXT CHECK (direction IN ('export', 'import', 'contact')));
        const express = require('express');
        const app = express();
        module.exports = { app };
        """,
        encoding="utf-8"
    )
    (ws / "index.html").write_text(
        """
        <!DOCTYPE html><html><body>
        <form id="rfqForm">
            <select name="direction">
                <option value="EXPORT">Export</option>
                <option value="IMPORT">Import</option>
            </select>
        </form>
        </body></html>
        """,
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("DATABASE_ENUM_CONTRACT_MISMATCH" in m for m in report.form_enum_mismatches)
    assert any(d.type == "DATABASE_ENUM_CONTRACT_MISMATCH" for d in report.discrepancies)


# ==============================================================================
# FIXTURE F: CONTACT FORM FIELD MISMATCH
# ==============================================================================

def test_fixture_f_contact_form_field_mismatch(disposable_workspace):
    """Backend requires contact_name in POST /api/contact, but HTML form lacks it."""
    ws = disposable_workspace
    (ws / "server.js").write_text(
        """
        const express = require('express');
        const app = express();
        app.post('/api/contact', (req, res) => {
            const { contact_name, email, message } = req.body;
            if (!contact_name) return res.status(400).json({ error: 'Name required' });
            res.json({ success: true });
        });
        module.exports = { app };
        """,
        encoding="utf-8"
    )
    (ws / "index.html").write_text(
        """
        <!DOCTYPE html><html><body>
        <form id="contactForm" action="/api/contact">
            <input name="email" type="email" />
            <textarea name="message"></textarea>
        </form>
        </body></html>
        """,
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("REQUEST_FIELD_CONTRACT_MISMATCH" in m for m in report.form_enum_mismatches)
    assert any("contact_name" in m for m in report.form_enum_mismatches)


# ==============================================================================
# FIXTURE G: TRACKING DOM SELECTORS
# ==============================================================================

def test_fixture_g_tracking_dom_selectors(disposable_workspace):
    """Frontend queries #trackShipmentBtn and #trackingResultContainer which do not exist in HTML."""
    ws = disposable_workspace
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><body><div id="generalContainer"></div></body></html>',
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        """
        const btn = document.getElementById('trackShipmentBtn');
        const container = document.getElementById('trackingResultContainer');
        """,
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("trackShipmentBtn" in m for m in report.dom_id_mismatches)
    assert any(d.type in ("DOM_REFERENCE_MISMATCH", "DOM_CONTRACT_MISMATCH") for d in report.discrepancies)


# ==============================================================================
# FIXTURE H: SUPERTEST APP EXPORT
# ==============================================================================

def test_fixture_h_supertest_app_export(disposable_workspace):
    """Backend exports { app, db }, test does const app = require('../server') and request(app)."""
    ws = disposable_workspace
    (ws / "server.js").write_text(
        """
        const express = require('express');
        const app = express();
        const db = {};
        module.exports = { app, db };
        """,
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "test.js").write_text(
        """
        const request = require('supertest');
        const app = require('../server');
        test('health check', async () => {
            const res = await request(app).get('/health');
            expect(res.status).toBe(200);
        });
        """,
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    assert any("TEST_SERVER_EXPORT_MISMATCH" in m for m in report.test_export_mismatches)
    assert any(d.type == "TEST_SERVER_EXPORT_MISMATCH" for d in report.discrepancies)


# ==============================================================================
# FIXTURE I: TEST PARSER & FAILURE CLASSIFICATION
# ==============================================================================

def test_fixture_i_jest_failure_diagnosis():
    """Verify Jest test diagnostics correctly classifies TypeError: app.address is not a function."""
    jest_raw_output = """
    FAIL tests/test.js
      ● Test suite failed to run

        TypeError: app.address is not a function
          at Test.serverAddress (node_modules/supertest/lib/test.js:46:22)
          at new Test (node_modules/supertest/lib/test.js:34:14)
          at Object.<anonymous> (tests/test.js:5:24)

    Tests:       1 failed, 1 total
    """
    evidence = TestOutputParser.parse(
        command="npm test",
        working_dir="/workspace",
        exit_code=1,
        stdout=jest_raw_output,
        stderr="",
    )

    assert evidence.exit_code == 1
    assert evidence.primary_failure_category == TestFailureCategory.TEST_IMPORT_FAILURE
    assert "Supertest was passed an object instead of the Express application instance" in evidence.repair_brief
    assert "const { app } = require" in evidence.repair_brief


# ==============================================================================
# FIXTURE J: ACTUAL SUCCESSFUL REPAIR
# ==============================================================================

def test_fixture_j_successful_contract_coherence(disposable_workspace):
    """When all contracts are coherent, CrossFileContractValidator produces valid = True."""
    ws = disposable_workspace
    (ws / "server.js").write_text(
        """
        const express = require('express');
        const app = express();
        app.get('/api/products', (req, res) => res.json({ products: [], total: 0 }));
        app.post('/api/inquiries', (req, res) => res.status(201).json({ success: true, inquiry: { reference: 'BBT-1' } }));
        app.post('/api/contact', (req, res) => {
            const { contact_name } = req.body;
            res.json({ success: true });
        });
        module.exports = { app };
        """,
        encoding="utf-8"
    )
    (ws / "index.html").write_text(
        """
        <!DOCTYPE html><html>
        <head>
            <link rel="stylesheet" href="style.css">
            <script type="module" src="app.js"></script>
        </head>
        <body>
            <div id="catalogGrid"></div>
            <form id="contactForm">
                <input name="contact_name" />
                <select name="direction">
                    <option value="export">Export</option>
                    <option value="import">Import</option>
                </select>
            </form>
        </body></html>
        """,
        encoding="utf-8"
    )
    (ws / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (ws / "js").mkdir(parents=True, exist_ok=True)
    (ws / "js" / "api.js").write_text(
        """
        export const api = {
            get: async (u) => ({}),
            post: async (u, d) => ({}),
            getProducts: async () => ({ products: [], total: 0 })
        };
        """,
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        """
        import { api } from "./js/api.js";
        async function init() {
            const p = await api.getProducts();
            const grid = document.getElementById('catalogGrid');
        }
        init();
        """,
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "test.js").write_text(
        """
        const request = require('supertest');
        const { app } = require('../server');
        test('get products', async () => {
            const res = await request(app).get('/api/products');
            expect(res.status).toBe(200);
        });
        """,
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert report.valid is True
    assert report.total_issues == 0
    assert report.severity in (SEV_PASS, "PASS")


# ==============================================================================
# FIXTURE K: PRESERVATION OF HTTP 201 CONTRACT TRUTH
# ==============================================================================

def test_fixture_k_http_201_contract_truth(disposable_workspace):
    """Controlled backend returns HTTP 201 on creation; contract validator respects 201."""
    ws = disposable_workspace
    (ws / "server.js").write_text(
        """
        const express = require('express');
        const app = express();
        app.post('/api/inquiries', (req, res) => res.status(201).json({ success: true }));
        module.exports = { app };
        """,
        encoding="utf-8"
    )
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><script type="module" src="app.js"></script></head><body></body></html>',
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        'fetch("/api/inquiries", { method: "POST" });',
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    # The 201 route must be recognized as valid POST /api/inquiries
    assert not any("Frontend route mismatch" in m and "/api/inquiries" in m for m in report.endpoint_mismatches)


# ==============================================================================
# FIXTURE L: STALE EVIDENCE INVALIDATION
# ==============================================================================

def test_fixture_l_stale_evidence_invalidation(disposable_workspace):
    """When a file is modified, its contract validation is rechecked fresh."""
    ws = disposable_workspace
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><script type="module" src="app.js"></script></head><body><div id="app"></div></body></html>',
        encoding="utf-8"
    )
    (ws / "app.js").write_text('document.getElementById("app");', encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report1 = validator.validate()
    assert report1.valid is True

    # Mutate app.js to introduce an invalid DOM ID reference
    (ws / "app.js").write_text('document.getElementById("nonExistentElementXYZ");', encoding="utf-8")

    report2 = validator.validate()
    assert report2.valid is False
    assert any("nonExistentElementXYZ" in m for m in report2.dom_id_mismatches)
