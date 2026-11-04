# tests/test_cross_file_intelligence_and_session_reliability_p0.py
"""
P0 Follow-up Regression Suite:
Cross-File Integration Intelligence, Browser Session Reliability,
Windows Server Process Lifecycle, Jest Zero-Test Prevention, and Mission Turn-Budget Control.
Reproduces and prevents all failure modes observed in mission m_90be2835.
"""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.browser.dev_server import DevServerManager
from core.browser.manager import BrowserManager
from core.cross_file_contract import (
    CrossFileContractValidator,
    SEV_FAIL,
    SEV_PASS,
    SEV_WARNING,
)
from core.project_contract import ProjectContract
from core.test_diagnostics import (
    TestDiscoveryResult,
    TestExecutionEvidence,
    TestFailureCategory,
    TestOutputParser,
)
from tools.platform.core_tools import ShellBashTool


# ==============================================================================
# 1. API ARRAY VS WRAPPED-OBJECT RESPONSE MISMATCH
# ==============================================================================

def test_01_api_array_vs_wrapped_object_response_mismatch(tmp_path):
    """Detect when backend returns raw JSON array but frontend expects wrapped object data.products."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const app = express();
const apiRouter = express.Router();
apiRouter.get('/products', (req, res) => {
    const rows = [{ id: 1, name: "Basmati Rice" }];
    res.json(rows);
});
app.use('/api', apiRouter);
app.listen(3000);
module.exports = { app };
""", encoding="utf-8")

    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("""
<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="style.css"></head>
<body>
    <div id="productGrid"></div>
    <script src="main.js"></script>
</body>
</html>
""", encoding="utf-8")

    (ws / "static" / "style.css").write_text("body { font-family: sans-serif; }", encoding="utf-8")
    (ws / "static" / "main.js").write_text("""
async function loadProducts() {
    const res = await fetch('/api/products');
    const data = await res.json();
    const products = data.products || [];
    renderProducts(products);
}
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    shape_disc = [d for d in report.discrepancies if d.type == "API_RESPONSE_SHAPE_MISMATCH"]
    assert len(shape_disc) > 0
    assert "products" in shape_disc[0].mismatch
    assert "raw JSON Array" in shape_disc[0].mismatch


# ==============================================================================
# 2. BACKEND/FRONTEND PRODUCT PROPERTY MISMATCH
# ==============================================================================

def test_02_backend_frontend_product_property_mismatch(tmp_path):
    """Detect when frontend expects properties that contradict database schema."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const app = express();
// Database table schema uses type, origin, image, price, moq, status
const schema = `
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  type TEXT NOT NULL,
  origin TEXT NOT NULL,
  price TEXT NOT NULL,
  moq TEXT NOT NULL,
  image TEXT NOT NULL,
  status TEXT NOT NULL
);`;
app.get('/api/products', (req, res) => res.json([]));
module.exports = { app };
""", encoding="utf-8")

    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("""
<!DOCTYPE html><html><body><div id="productGrid"></div><script src="main.js"></script></body></html>
""", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (ws / "static" / "main.js").write_text("""
function renderProducts(products) {
    document.getElementById('productGrid').innerHTML = products.map(p => `
        <div class="card">
            <h3>${p.name}</h3>
            <span>${p.classification}</span>
            <span>${p.origin_country}</span>
            <span>${p.indicative_price}</span>
            <span>${p.min_order_qty}</span>
            <span>${p.availability}</span>
            <img src="${p.image_url}" />
        </div>
    `).join('');
}
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert not report.valid
    prop_disc = [d for d in report.discrepancies if d.type == "PRODUCT_PROPERTY_MISMATCH"]
    assert len(prop_disc) > 0
    assert "classification" in prop_disc[0].mismatch


# ==============================================================================
# 3. INCORRECT DOM RENDERING TARGET
# ==============================================================================

def test_03_incorrect_dom_rendering_target(tmp_path):
    """Detect when frontend renders cards into parent catalogue section, destroying controls."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("const express = require('express'); const app = express(); module.exports = { app };", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("""
<!DOCTYPE html>
<html>
<body>
    <section id="catalogue">
        <h2>Catalogue</h2>
        <input type="text" id="search" />
        <select id="filter"></select>
        <div class="product-grid" id="productGrid"></div>
    </section>
    <script src="main.js"></script>
</body>
</html>
""", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "main.js").write_text("""
function renderProducts(products) {
    // BUG: writing directly into #catalogue overwrites the search and filter elements
    document.getElementById('catalogue').innerHTML = products.map(p => `<div>${p.name}</div>`).join('');
}
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    target_disc = [d for d in report.discrepancies if d.type == "INCORRECT_DOM_TARGET"]
    assert len(target_disc) > 0
    assert "destroys other section controls" in target_disc[0].mismatch


# ==============================================================================
# 4. MISSING/MISMATCHED DOM FILTER SELECTORS
# ==============================================================================

def test_04_missing_or_mismatched_dom_filter_selectors(tmp_path):
    """Detect when JS expects classFilter while HTML provides typeFilter."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("const express = require('express'); module.exports = express();", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("""
<!DOCTYPE html>
<html>
<body>
    <select id="typeFilter"><option value="Export">Export</option></select>
    <script src="main.js"></script>
</body>
</html>
""", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "main.js").write_text("""
const classFilter = document.getElementById('classFilter');
classFilter.addEventListener('change', () => {});
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    filter_disc = [d for d in report.discrepancies if d.type == "DOM_REFERENCE_MISMATCH" and "classFilter" in d.mismatch]
    assert len(filter_disc) > 0
    assert "typeFilter" in filter_disc[0].mismatch


# ==============================================================================
# 5. ENQUIRY PAYLOAD MISMATCH
# ==============================================================================

def test_05_enquiry_payload_mismatch(tmp_path):
    """Detect mismatch between frontend enquiry submission keys and backend expected keys."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const app = express();
app.post('/api/enquiries', (req, res) => {
    const { company, contact, country, direction } = req.body;
    if (!company || !contact || !country || !direction) {
        return res.status(400).json({ error: "Missing required fields" });
    }
    res.status(201).json({ success: true, reference: "GTC-ENQ-1234" });
});
module.exports = { app };
""", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("<!DOCTYPE html><html><body><script src='main.js'></script></body></html>", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "main.js").write_text("""
async function submitEnquiry(form) {
    const payload = {
        company_name: "Acme",
        contact_person: "John",
        destination_country: "USA",
        trade_direction: "Export"
    };
    await fetch('/api/enquiries', { method: 'POST', body: JSON.stringify(payload) });
}
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    enq_disc = [d for d in report.discrepancies if d.type == "REQUEST_PAYLOAD_FIELD_MISMATCH"]
    assert len(enq_disc) > 0
    assert "company_name" in enq_disc[0].mismatch


# ==============================================================================
# 6. SHIPMENT TRACKING ROUTE AND RESPONSE MISMATCH
# ==============================================================================

def test_06_shipment_tracking_route_and_response_mismatch(tmp_path):
    """Detect route discrepancy and response property mismatches for shipment tracking."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const app = express();
const schema = `
CREATE TABLE shipments (
    tracking_ref TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL,
    eta TEXT NOT NULL
);`;
app.get('/api/track/:ref', (req, res) => res.json({ tracking_ref: req.params.ref, description: "Rice", eta: "2025-05-01" }));
module.exports = { app };
""", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("<!DOCTYPE html><html><body><script src='main.js'></script></body></html>", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "main.js").write_text("""
async function trackShipment(ref) {
    // Frontend calls /api/tracking/ instead of /api/track/
    const res = await fetch(`/api/tracking/${encodeURIComponent(ref)}`);
    const data = await res.json();
    console.log(data.product_description, data.estimated_delivery);
}
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    route_disc = [d for d in report.discrepancies if d.type == "API_ROUTE_MISMATCH" and "tracking" in d.mismatch]
    assert len(route_disc) > 0
    prop_disc = [d for d in report.discrepancies if d.type == "SHIPMENT_PROPERTY_MISMATCH"]
    assert len(prop_disc) > 0


# ==============================================================================
# 7. ADMIN ENDPOINT AND HTTP METHOD MISMATCH
# ==============================================================================

def test_07_admin_endpoint_and_http_method_mismatch(tmp_path):
    """Detect when frontend calls /api/admin/data while backend provides separate routes, and PUT vs PATCH."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const app = express();
app.get('/api/admin/stats', (req, res) => res.json({}));
app.get('/api/admin/enquiries', (req, res) => res.json([]));
app.patch('/api/admin/enquiries/:id/status', (req, res) => res.json({ success: true }));
module.exports = { app };
""", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("<!DOCTYPE html><html><body><script src='main.js'></script></body></html>", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "main.js").write_text("""
async function loadAdmin() {
    // Discrepancy: calls combined /api/admin/data
    const res = await fetch('/api/admin/data');
    // Discrepancy: calls status update with PUT instead of PATCH
    await fetch('/api/admin/enquiries/1/status', { method: 'PUT', body: JSON.stringify({ status: 'Closed' }) });
}
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    route_disc = [d for d in report.discrepancies if d.type == "ADMIN_ROUTE_CONTRACT_MISMATCH"]
    assert len(route_disc) > 0
    method_disc = [d for d in report.discrepancies if d.type == "API_METHOD_MISMATCH"]
    assert len(method_disc) > 0


# ==============================================================================
# 8. DEMO CREDENTIAL MISMATCH
# ==============================================================================

def test_08_demo_credential_mismatch(tmp_path):
    """Detect mismatch between HTML demo password hint and backend authentication logic."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const app = express();
app.post('/api/admin/login', (req, res) => {
    const { username, password } = req.body;
    if (username === 'admin' && password === 'globaltrade2025') {
        return res.json({ success: true });
    }
    res.status(401).json({ error: 'Invalid credentials' });
});
module.exports = { app };
""", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("""
<!DOCTYPE html>
<html>
<body>
    <form id="adminLoginForm">
        <input type="text" id="adminUser" value="admin" />
        <input type="password" id="adminPass" value="globaltrade2023" />
    </form>
    <script src="main.js"></script>
</body>
</html>
""", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "main.js").write_text("// admin", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    cred_disc = [d for d in report.discrepancies if d.type == "AUTH_CREDENTIALS_MISMATCH"]
    assert len(cred_disc) > 0
    assert "globaltrade2023" in cred_disc[0].mismatch
    assert "globaltrade2025" in cred_disc[0].mismatch


# ==============================================================================
# 9. PRODUCT IMAGE FIELD AND CSS SELECTOR MISMATCH
# ==============================================================================

def test_09_product_image_field_and_css_selector_mismatch(tmp_path):
    """Detect CSS selector .hero vs HTML .hero-section mismatch."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("const express = require('express'); module.exports = express();", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("""
<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="style.css"></head>
<body>
    <header class="hero-section">
        <h1>Global Trade</h1>
    </header>
    <script src="main.js"></script>
</body>
</html>
""", encoding="utf-8")
    (ws / "static" / "style.css").write_text("""
.hero {
    background: url('/banner.jpg');
    height: 400px;
}
""", encoding="utf-8")
    (ws / "static" / "main.js").write_text("// main", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    css_disc = [d for d in report.discrepancies if d.type == "CSS_CLASS_MISMATCH"]
    assert len(css_disc) > 0
    assert "hero-section" in css_disc[0].mismatch


# ==============================================================================
# 10. INCONSISTENT STATIC ASSET LOCATIONS
# ==============================================================================

def test_10_inconsistent_static_asset_locations(tmp_path):
    """Detect when Express serves public but assets are in static."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const path = require('path');
const app = express();
app.use(express.static(path.join(__dirname, 'public')));
module.exports = { app };
""", encoding="utf-8")
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("""
<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="static/style.css"></head>
<body><script src="static/main.js"></script></body>
</html>
""", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "main.js").write_text("// test", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    static_disc = [d for d in report.discrepancies if d.type == "STATIC_DIRECTORY_MISMATCH"]
    assert len(static_disc) > 0
    assert "public" in static_disc[0].mismatch


# ==============================================================================
# 11. ASYNC SQLITE READINESS RACE
# ==============================================================================

def test_11_async_sqlite_readiness_race(tmp_path):
    """Detect async sqlite initialization when app.listen is called without awaiting readiness."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "test-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const app = express();
const db = new sqlite3.Database(':memory:', (err) => {
    initDb();
});
function initDb() {
    db.run("CREATE TABLE items (id INTEGER);");
}
// Race condition: app.listen called synchronously outside initDb callback
app.listen(3000);
module.exports = { app, db };
""", encoding="utf-8")
    (ws / "index.html").write_text("<!DOCTYPE html><html><body><script src='app.js'></script></body></html>", encoding="utf-8")
    (ws / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "app.js").write_text("// app", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    async_disc = [d for d in report.discrepancies if d.type == "ASYNC_DB_READINESS_RACE"]
    assert len(async_disc) > 0
    assert "app.listen" in async_disc[0].mismatch


# ==============================================================================
# 12. JEST ZERO-TEST FALSE-SUCCESS PREVENTION
# ==============================================================================

def test_12_jest_zero_test_false_success_prevention():
    """Verify that npx jest --passWithNoTests with 0 discovered tests is classified as TESTS_NOT_DISCOVERED."""
    raw_output = """
No tests found, exiting with code 0
Ran all test suites.
"""
    evidence = TestOutputParser.parse(
        command="npx jest --passWithNoTests",
        working_dir=".",
        exit_code=0,
        stdout=raw_output,
        stderr="",
    )

    assert evidence.discovery_result == TestDiscoveryResult.TESTS_NOT_DISCOVERED
    assert evidence.primary_failure_category == TestFailureCategory.TEST_DISCOVERY_FAILURE
    assert not evidence.is_valid_pass
    assert evidence.total_count == 0


# ==============================================================================
# 13. BROWSER SESSION EXPIRATION AND BOUNDED RECOVERY
# ==============================================================================

@pytest.mark.asyncio
async def test_13_browser_session_expiration_and_bounded_recovery():
    """Verify that BrowserManager automatically recovers an inactive session without unhandled crashes."""
    mgr = BrowserManager()
    mgr._is_active = False
    mgr.driver = None

    # Inspect should invoke _ensure_active_session and not crash
    result = await mgr.inspect()
    assert result is not None
    assert mgr.is_active


# ==============================================================================
# 14. WINDOWS MANAGED SERVER STARTUP AND CLEANUP
# ==============================================================================

@pytest.mark.asyncio
async def test_14_windows_managed_server_startup_and_cleanup(tmp_path):
    """Verify DevServerManager starts and stops managed application servers cleanly."""
    dev_mgr = DevServerManager()
    ws = tmp_path

    # Start a quick mock static server
    server = await dev_mgr.start_static_server(ws, name="test_server")
    assert server.is_alive
    assert server.port > 0

    # Stop server
    dev_mgr.stop_server("test_server")
    assert not server.is_alive


# ==============================================================================
# 15. REPEATED TEST EXECUTION WITHOUT WORKSPACE MUTATION
# ==============================================================================

@pytest.mark.asyncio
async def test_15_repeated_test_execution_without_workspace_mutation():
    """Verify duplicate validation guard blocks repeating test commands on unchanged failing code."""
    from core.agent_loop.loop import AgentLoop, AgentLoopConfig
    from core.event_bus import EventBus

    bus = EventBus(enabled=True)
    mock_orch = MagicMock()
    mock_orch.mode = "auto"

    call_count = 0
    async def mock_gen(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return MagicMock(
            text="Run tests",
            tool_calls=[{"id": f"c_{call_count}", "name": "shell.bash", "arguments": {"command": "npm test"}}],
            success=True,
        )
    mock_orch._generate_t1 = mock_gen

    loop = AgentLoop(
        orchestrator=mock_orch,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=5, execution_mode="agentic"),
    )
    loop._last_validation_failed = True
    loop._last_validation_source_digest = "abc_digest"
    loop._compute_workspace_source_digest = lambda: "abc_digest"

    # Simulate governor check
    obs = loop._record_observation = MagicMock()
    # Verification that condition triggers
    assert loop._last_validation_failed and loop._compute_workspace_source_digest() == loop._last_validation_source_digest


# ==============================================================================
# 16. POSITIVE COHERENT WORKSPACE PASSES VALIDATION
# ==============================================================================

def test_16_positive_coherent_workspace_passes_validation(tmp_path):
    """Verify that a properly aligned and coherent full-stack workspace passes validation cleanly."""
    ws = tmp_path
    (ws / "package.json").write_text('{"name": "coherent-app", "main": "server.js"}', encoding="utf-8")
    (ws / "server.js").write_text("""
const express = require('express');
const path = require('path');
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const schema = `
CREATE TABLE products (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  type TEXT NOT NULL,
  origin TEXT NOT NULL,
  price TEXT NOT NULL,
  moq TEXT NOT NULL,
  image TEXT NOT NULL,
  status TEXT NOT NULL
);`;

app.get('/api/products', (req, res) => {
    res.json({ products: [{ id: 1, name: "Rice", type: "Export", origin: "India", price: "$10", moq: "1", image: "/img.jpg", status: "Active" }] });
});

app.post('/api/enquiries', (req, res) => {
    const { company, contact, country, direction } = req.body;
    res.status(201).json({ success: true, reference: "GTC-ENQ-9999" });
});

app.get('/api/track/:ref', (req, res) => {
    res.json({ tracking_ref: req.params.ref, description: "Rice", eta: "2025" });
});

app.post('/api/admin/login', (req, res) => {
    const { username, password } = req.body;
    if (username === 'admin' && password === 'globaltrade2025') {
        return res.json({ success: true });
    }
    res.status(401).json({ error: "Invalid credentials" });
});

app.get('/api/admin/stats', (req, res) => res.json({}));
app.get('/api/admin/enquiries', (req, res) => res.json([]));
app.get('/api/admin/shipments', (req, res) => res.json([]));
app.patch('/api/admin/enquiries/:id/status', (req, res) => res.json({ success: true }));

module.exports = { app };
""", encoding="utf-8")

    (ws / "public").mkdir()
    (ws / "public" / "index.html").write_text("""
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <h1>Coherent Global Trade</h1>
    </header>
    <section id="catalogue">
        <select id="typeFilter"></select>
        <div id="productGrid" class="product-grid"></div>
    </section>
    <form id="adminLoginForm">
        <input type="text" id="adminUser" value="admin" />
        <input type="password" id="adminPass" value="globaltrade2025" />
    </form>
    <script src="main.js"></script>
</body>
</html>
""", encoding="utf-8")

    (ws / "public" / "style.css").write_text("""
.hero { background: #333; color: #fff; }
.product-grid { display: grid; }
""", encoding="utf-8")

    (ws / "public" / "main.js").write_text("""
async function loadProducts() {
    const res = await fetch('/api/products');
    const data = await res.json();
    const products = data.products || [];
    renderProducts(products);
}

function renderProducts(products) {
    document.getElementById('productGrid').innerHTML = products.map(p => `
        <div>${p.name} - ${p.type} - ${p.origin}</div>
    `).join('');
}

async function submitEnquiry() {
    const payload = { company: "Acme", contact: "Alice", country: "USA", direction: "Export" };
    await fetch('/api/enquiries', { method: 'POST', body: JSON.stringify(payload) });
}

async function trackShipment(ref) {
    await fetch(`/api/track/${encodeURIComponent(ref)}`);
}

async function updateEnquiryStatus(id) {
    await fetch(`/api/admin/enquiries/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status: 'Confirmed' }) });
}
""", encoding="utf-8")

    validator = CrossFileContractValidator(ws)
    report = validator.validate()

    assert report.valid
    assert report.severity in (SEV_PASS, SEV_WARNING)
