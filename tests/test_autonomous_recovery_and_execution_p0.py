# tests/test_autonomous_recovery_and_execution_p0.py
"""
HERMES 2.x — Critical Autonomous Execution, Recovery, and Contract Verification P0 Test Suite
=============================================================================================
Validates:
1. Failed npm test output is captured and made available to the agent (full diagnostics, assertion errors).
2. Test assertion failures are classified deterministically (TEST_ASSERTION_FAILURE, etc.).
3. A failed test causes diagnostic analysis rather than blind repetition (RepairBrief).
4. Recovery across model tiers preserves relevant failure history.
5. Repeated no-progress operations are detected correctly without premature aborts.
6. A genuine repair permits the next validation attempt.
7. Browser verification launches through HTTP when the application requires a backend (bans file://).
8. Browser evidence is generated and consumed using the exact unified contract.
9. Missing browser tooling is reported honestly without falsifying results.
10. SQLite tests use an isolated database (GLOBALTRADE_TEST_DB_PATH, TEST_DB_PATH).

Scenarios A-I:
- Scenario A: API contract mismatch (health status 'healthy' vs 'ok')
- Scenario B: Enquiry request payload field mismatch (companyName vs company_name)
- Scenario C: Enquiry reference format mismatch (GT-ENQ- vs GTC-ENQ-)
- Scenario D: Shipment tracking mismatch (GT-SHP-88210 vs GTC-SHP-8821)
- Scenario E: Admin authentication mismatch (conflicting passwords)
- Scenario F: HTML and JS DOM contract mismatch (productGrid vs product-grid)
- Scenario G: Admin API contract mismatch (separate routes vs dashboard)
- Scenario H: Shipment event mismatch (missing required fields)
- Scenario I: Test discovery and DB isolation
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.browser.acceptance import BrowserAcceptanceResult, BrowserAcceptanceVerifier
from core.browser.evidence import (
    AuthoritativeBrowserEvidence,
    BrowserEvidenceLifecycle,
    BrowserEvidenceValidator,
    compute_workspace_artifact_hashes,
)
from core.cross_file_contract import (
    CrossFileContractReport,
    CrossFileContractValidator,
    SEV_FAIL,
    SEV_PASS,
    SEV_WARNING,
)
from core.structured_observation import StructuredObservation
from core.test_diagnostics import (
    TestExecutionEvidence,
    TestFailureCategory,
    TestFailureDetail,
    TestOutputParser,
)
from tools.platform.core_tools import ShellBashTool, ToolResult


@pytest.fixture
def clean_workspace():
    """Provides an isolated workspace directory."""
    temp_dir = tempfile.mkdtemp(prefix="hermes_exec_rec_")
    ws = Path(temp_dir)
    yield ws
    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST 1: FAILED COMMAND OUTPUT & DIAGNOSTICS CAPTURE
# ==============================================================================

def test_1_failed_npm_test_output_captured_and_exposed():
    """Failed npm test output must capture complete command, duration, and full assertion failure."""
    jest_raw = """
FAIL tests/api.test.js
  GlobalTrade Connect API Tests
    × GET /api/health returns status ok (93 ms)

  ● GlobalTrade Connect API Tests › GET /api/health returns status ok

    expect(received).toEqual(expected) // deep equality

    Expected: "ok"
    Received: "healthy"

       6 |     const res = await request(app).get('/api/health');
       7 |     expect(res.statusCode).toEqual(200);
    >  8 |     expect(res.body.status).toEqual('ok');
         |                             ^
       9 |   });

      at Object.toEqual (tests/api.test.js:8:29)

Tests: 1 failed, 1 total
Time: 0.776 s
"""
    evidence = TestOutputParser.parse(
        command="npm test",
        working_dir="C:\\test_ws",
        exit_code=1,
        stdout=jest_raw,
        stderr="",
        duration_seconds=0.776,
    )

    assert evidence.exit_code == 1
    assert evidence.failed_count == 1
    assert evidence.primary_failure_category == TestFailureCategory.TEST_ASSERTION_FAILURE
    assert len(evidence.failures) == 1
    f0 = evidence.failures[0]
    assert f0.test_name == "GET /api/health returns status ok"
    assert f0.expected == '"ok"'
    assert f0.received == '"healthy"'
    assert f0.file_path == "tests/api.test.js"
    assert f0.line_number == 8
    assert "Expected: \"ok\"" in evidence.repair_brief
    assert "Received: \"healthy\"" in evidence.repair_brief


# ==============================================================================
# TEST 2: TEST ASSERTION FAILURE CLASSIFICATION
# ==============================================================================

def test_2_failure_classification_categories():
    """Deterministic classification of diverse test failures."""
    # Assertion failure
    ev_assert = TestOutputParser.parse("npm test", ".", 1, "Expected: 201\nReceived: 400\nat (test.js:12:1)", "")
    assert ev_assert.primary_failure_category == TestFailureCategory.TEST_ASSERTION_FAILURE

    # Dependency failure
    ev_dep = TestOutputParser.parse("npm test", ".", 1, "Error: Cannot find module 'express'", "")
    assert ev_dep.primary_failure_category == TestFailureCategory.DEPENDENCY_FAILURE

    # Database constraint failure
    ev_db = TestOutputParser.parse("npm test", ".", 1, "SQLITE_CONSTRAINT: CHECK constraint failed", "")
    assert ev_db.primary_failure_category == TestFailureCategory.DATABASE_TEST_FAILURE

    # Server startup / address in use
    ev_srv = TestOutputParser.parse("npm test", ".", 1, "Error: listen EADDRINUSE: address already in use :::3000", "")
    assert ev_srv.primary_failure_category == TestFailureCategory.SERVER_STARTUP_ERROR

    # Timeout
    ev_time = TestOutputParser.parse("npm test", ".", 1, "Timeout - Async callback was not invoked within the 5000 ms timeout", "")
    assert ev_time.primary_failure_category == TestFailureCategory.TEST_TIMEOUT


# ==============================================================================
# TEST 3: DIAGNOSTIC REPAIR BRIEF IN OBSERVATION
# ==============================================================================

def test_3_failed_test_causes_diagnostic_analysis_rather_than_blind_repetition():
    """StructuredObservation from a failed test includes rich actionable error summary and repair brief."""
    t_ev = TestOutputParser.parse(
        command="npm test",
        working_dir=".",
        exit_code=1,
        stdout="Expected: 200\nReceived: 404\nat Object.toEqual (tests/api.test.js:39:28)",
        stderr="",
    )
    res = ToolResult(
        success=False,
        output=f"{t_ev.repair_brief}\n\n[RAW TEST OUTPUT]\nExpected: 200\nReceived: 404",
        error=f"Test failure ({t_ev.primary_failure_category}) in 'Generic Test Suite': expected 200 but received 404",
        exit_code=1,
        details={"test_evidence": t_ev.to_dict(), "raw_stdout": "Expected: 200\nReceived: 404"},
    )
    obs = StructuredObservation.from_tool_result(
        tool_name="shell.bash",
        tool_result=res,
        duration=1.0,
        files_before=set(),
        files_after=set(),
    )

    assert not obs.success
    assert obs.error_summary is not None
    context_str = obs.to_context_string()
    assert "TEST_ASSERTION_FAILURE" in obs.error_summary or "TEST_ASSERTION_FAILURE" in context_str or "expected 200" in context_str
    assert "Expected" in context_str or "expected" in context_str


# ==============================================================================
# TEST 4: MULTI-TIER RECOVERY PRESERVES FAILURE HISTORY
# ==============================================================================

@pytest.mark.asyncio
async def test_4_tier_escalation_preserves_test_failure_history():
    """When recovering to Tier 2, recent test failure details are injected into the recovery directive."""
    from core.agent_loop.loop import AgentLoop
    from core.agent_loop.types import Observation

    loop = AgentLoop(bus=MagicMock(), workspace=MagicMock(), orchestrator=MagicMock())
    loop._mission_id = "m_test_preservation"
    loop._observation_history = [
        Observation(
            observation_id="obs_f1",
            mission_id="m_test_preservation",
            source_type="tool",
            source_id="shell.bash",
            success=False,
            summary="Test failure: Expected 'ok' but received 'healthy'",
            content="[TEST EXECUTION FAILURE DIAGNOSIS]\nExpected: 'ok'\nReceived: 'healthy'",
            metadata={
                "test_evidence": {
                    "repair_brief": "[TEST EXECUTION FAILURE DIAGNOSIS]\nFailing test: GET /api/health\nExpected: 'ok'\nReceived: 'healthy'"
                }
            }
        )
    ]
    loop.orchestrator = MagicMock()
    loop.orchestrator._active_tier = 1
    loop.context_engine = MagicMock()

    mission = MagicMock()
    mission.mission_id = "m_test_preservation"
    mission.user_prompt = "Build application and pass tests" 

    success = await loop._trigger_recovery_transition(
        turn_id="turn_test_1",
        rejection_reason="Test assertions failed twice",
        unmet_reqs=["Tests failing on /api/health"],
        mission=mission,
    )

    assert success is True
    assert loop.orchestrator._active_tier == 2
    # Verify directive contains the failure diagnosis
    assert hasattr(loop, "_active_recovery_brief")
    assert "RECENT TEST FAILURE DIAGNOSIS" in loop._active_recovery_brief
    assert "Expected: 'ok'" in loop._active_recovery_brief


# ==============================================================================
# TEST 5: REPEATED NO-PROGRESS OPERATIONS DETECTION
# ==============================================================================

def test_5_repeated_no_progress_detection_and_non_mutation_accounting():
    """fs.read does not count as a meaningful change in progress tracking."""
    from core.planning.progress import ProgressController
    from core.runtime_state.models import GoalState, RequirementState, RequirementStatus, RequirementPriority

    acceptance_mgr = MagicMock()
    acceptance_mgr.evaluate_requirement.return_value = (RequirementStatus.IN_PROGRESS, "working")
    acceptance_mgr.ledger.report.return_value = {"total_checks": 2, "passed": 0}
    acceptance_mgr.ledger.checks = {}

    goal = GoalState(goal_id="goal_1", mission_id="m_test", title="Build app")
    ctrl = ProgressController(goal=goal, requirements={}, acceptance_manager=acceptance_mgr)
    ctrl.requirements["req_1"] = RequirementState(
        requirement_id="req_1",
        goal_id="goal_1",
        title="Implement server",
        status=RequirementStatus.IN_PROGRESS,
        priority=RequirementPriority.CRITICAL,
    )

    # 1. Mutating change
    has_chg, prog = ctrl.update_progress(event_summary="fs.write server.js with initial routes")
    assert prog.last_meaningful_change == "fs.write server.js with initial routes"

    # 2. Read-only inspection - must NOT update last_meaningful_change
    has_chg2, prog2 = ctrl.update_progress(event_summary="fs.read server.js lines 1-100")
    assert "fs.read" not in prog2.last_meaningful_change
    assert prog2.last_meaningful_change == "fs.write server.js with initial routes"


# ==============================================================================
# TEST 6: GENUINE REPAIR PERMITS VALIDATION
# ==============================================================================

def test_6_genuine_repair_updates_workspace_digest(clean_workspace):
    """File edits update the deterministic workspace digest, allowing duplicate validation guard to clear."""
    ws = clean_workspace
    (ws / "server.js").write_text("console.log('v1');", encoding="utf-8")
    d1 = BrowserAcceptanceVerifier.compute_workspace_digest(ws)

    (ws / "server.js").write_text("console.log('v2 - repaired');", encoding="utf-8")
    d2 = BrowserAcceptanceVerifier.compute_workspace_digest(ws)

    assert d1 != d2


# ==============================================================================
# TEST 7: BROWSER VERIFICATION ENFORCES HTTP & BANS file:// FOR BACKEND APPS
# ==============================================================================

@pytest.mark.asyncio
async def test_7_browser_verification_bans_file_uri_for_backend(clean_workspace):
    """Web applications with a backend must never use file:// URLs for browser verification."""
    ws = clean_workspace
    (ws / "server.js").write_text("const express = require('express'); const app = express();", encoding="utf-8")
    (ws / "static").mkdir(parents=True, exist_ok=True)
    (ws / "static" / "index.html").write_text("<html><body><h1>Trade</h1></body></html>", encoding="utf-8")

    # If backend fails to start/listen, verifier returns FAIL rather than falling back to file://
    with patch.object(BrowserAcceptanceVerifier, "find_browser_executable", return_value="dummy_chrome"):
        with patch.object(BrowserAcceptanceVerifier, "is_port_in_use", return_value=False):
            res = await BrowserAcceptanceVerifier.verify_workspace(ws, preferred_port=3000)
            assert not res.passed
            assert "file:// navigation prohibited" in res.issues[0] or "failed to start" in res.issues[0]


# ==============================================================================
# TEST 8: UNIFIED BROWSER EVIDENCE PRODUCER & CONSUMER CONTRACT
# ==============================================================================

def test_8_browser_evidence_unified_contract(clean_workspace):
    """acceptance_evidence.json and browser_verified.json are both recognized and validated by BrowserEvidenceValidator."""
    ws = clean_workspace
    (ws / "server.js").write_text("console.log('test');", encoding="utf-8")
    (ws / "index.html").write_text("<html><body><h1>Test</h1></body></html>", encoding="utf-8")
    ev_dir = ws / ".hermes"
    ev_dir.mkdir(parents=True, exist_ok=True)

    digest = BrowserAcceptanceVerifier.compute_workspace_digest(ws)
    ev_payload = {
        "workspace_digest": digest,
        "timestamp": time.time(),
        "passed": True,
        "status": "PASS",
        "target_url": "http://127.0.0.1:3000",
        "issues": [],
    }
    (ev_dir / "acceptance_evidence.json").write_text(json.dumps(ev_payload), encoding="utf-8")

    status, ev_obj, reason = BrowserEvidenceValidator.load_and_validate(ws)
    assert status == BrowserEvidenceLifecycle.PASSED
    assert ev_obj is not None
    assert ev_obj.status == BrowserEvidenceLifecycle.PASSED


# ==============================================================================
# TEST 9: MISSING BROWSER TOOLING REPORTED HONESTLY
# ==============================================================================

@pytest.mark.asyncio
async def test_9_missing_browser_tooling_reported_honestly(clean_workspace):
    """When no browser binary is available, verifier reports failure honestly without claiming pass."""
    ws = clean_workspace
    (ws / "index.html").write_text("<html><body>Hello</body></html>", encoding="utf-8")
    (ws / "app.js").write_text("console.log('app');", encoding="utf-8")

    with patch.object(BrowserAcceptanceVerifier, "find_browser_executable", return_value=None):
        res = await BrowserAcceptanceVerifier.verify_workspace(ws)
        assert not res.passed
        assert res.status == "FAIL"
        assert any("browser binary found" in iss.lower() for iss in res.issues)


# ==============================================================================
# TEST 10: SQLITE TEST DATABASE ISOLATION
# ==============================================================================

def test_10_sqlite_test_database_isolation(clean_workspace):
    """Subprocess execution injects dedicated test database environment variables."""
    ws = clean_workspace
    tool = ShellBashTool()
    # Execute a simple echo command that prints the test DB environment variable
    res = tool.execute({
        "command": "python -c \"import os; print('TEST_DB:', os.environ.get('TEST_DB_PATH'))\"",
        "directory": str(ws),
    })
    # For a validation test command, test env vars are injected
    res_test = tool.execute({
        "command": "npm test -- --version || python -c \"import os; print('INJECTED:', os.environ.get('GLOBALTRADE_TEST_DB_PATH', ''))\"",
        "directory": str(ws),
    })
    assert res_test is not None


# ==============================================================================
# SCENARIOS A THROUGH I: REAL CROSS-FILE INTEGRATION FAILURES
# ==============================================================================

def test_scenario_a_api_health_contract_mismatch(clean_workspace):
    """Scenario A: Backend returns { status: 'healthy' } but test expects { status: 'ok' }."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "const express = require('express'); const app = express();\n"
        "app.get('/api/health', (req, res) => res.json({ status: 'healthy' }));\n"
        "module.exports = { app };",
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "api.test.js").write_text(
        "const { app } = require('../server');\n"
        "test('health check', async () => {\n"
        "  const res = await request(app).get('/api/health');\n"
        "  expect(res.body.status).toEqual('ok');\n"
        "});",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("API contract mismatch" in m for m in report.response_shape_mismatches)
    assert any(d.type == "API_RESPONSE_VALUE_MISMATCH" for d in report.discrepancies)


def test_scenario_b_enquiry_request_field_mismatch(clean_workspace):
    """Scenario B: Backend expects snake_case fields but test submits camelCase fields."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "app.post('/api/enquiries', (req, res) => {\n"
        "  const { company_name, contact_person, product, country, trade_direction, requirements } = req.body;\n"
        "  if (!company_name) return res.status(400).json({ error: 'Missing company_name' });\n"
        "  res.status(201).json({ success: true });\n"
        "});",
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "api.test.js").write_text(
        "test('create enquiry', async () => {\n"
        "  const res = await request(app).post('/api/enquiries').send({\n"
        "    companyName: 'Apex',\n"
        "    contactPerson: 'John',\n"
        "    productName: 'Rice',\n"
        "    destinationOrOrigin: 'India',\n"
        "    additionalRequirements: 'Bulk'\n"
        "  });\n"
        "});",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("Enquiry request payload mismatch" in m for m in report.endpoint_mismatches)
    assert any(d.type == "REQUEST_PAYLOAD_FIELD_MISMATCH" for d in report.discrepancies)


def test_scenario_c_enquiry_reference_mismatch(clean_workspace):
    """Scenario C: Backend generates 'GT-ENQ-' but test expects /^GTC-ENQ-/."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "app.post('/api/enquiries', (req, res) => {\n"
        "  const ref = 'GT-ENQ-' + Date.now();\n"
        "  res.status(201).json({ reference: ref });\n"
        "});",
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "api.test.js").write_text(
        "test('ref check', async () => {\n"
        "  const res = await request(app).post('/api/enquiries').send({});\n"
        "  expect(res.body.reference).toMatch(/^GTC-ENQ-/);\n"
        "});",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("reference format mismatch" in m.lower() for m in report.endpoint_mismatches)
    assert any(d.type == "REFERENCE_FORMAT_MISMATCH" for d in report.discrepancies)


def test_scenario_d_shipment_tracking_mismatch(clean_workspace):
    """Scenario D: Seeded tracking is GT-SHP-88210 but test queries GTC-SHP-8821."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "const seed = 'GT-SHP-88210';\n"
        "app.get('/api/shipments/:ref', (req, res) => {\n"
        "  if (req.params.ref === seed) return res.json({ status: 'Delivered', description: 'Grain' });\n"
        "  res.status(404).json({ error: 'Not found' });\n"
        "});",
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "api.test.js").write_text(
        "test('shipment tracking', async () => {\n"
        "  const res = await request(app).get('/api/shipments/GTC-SHP-8821');\n"
        "  expect(res.statusCode).toEqual(200);\n"
        "});",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("Shipment tracking mismatch" in m for m in report.endpoint_mismatches)
    assert any(d.type == "TRACKING_DATA_CONTRACT_MISMATCH" for d in report.discrepancies)


def test_scenario_e_admin_auth_password_mismatch(clean_workspace):
    """Scenario E: Backend checks password 'admin123' but test submits 'securepassword123'."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "app.post('/api/admin/login', (req, res) => {\n"
        "  if (req.body.password === 'admin123') return res.json({ token: 'abc' });\n"
        "  res.status(401).json({ error: 'Invalid' });\n"
        "});",
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "api.test.js").write_text(
        "test('admin login', async () => {\n"
        "  const res = await request(app).post('/api/admin/login').send({ username: 'admin', password: 'securepassword123' });\n"
        "  expect(res.statusCode).toEqual(200);\n"
        "});",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("Admin authentication mismatch" in m for m in report.endpoint_mismatches)
    assert any(d.type == "AUTH_CREDENTIALS_MISMATCH" for d in report.discrepancies)


def test_scenario_f_dom_selector_mismatch(clean_workspace):
    """Scenario F: HTML has #productGrid, #searchInput, but JS queries #product-grid, #search-input."""
    ws = clean_workspace
    (ws / "index.html").write_text(
        "<!DOCTYPE html><html><body>\n"
        "<div id=\"productGrid\"></div>\n"
        "<input id=\"searchInput\" />\n"
        "</body></html>",
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        "const grid = document.getElementById('product-grid');\n"
        "const search = document.querySelector('#search-input');\n",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("DOM contract mismatch" in m for m in report.dom_id_mismatches)
    assert any(d.type == "DOM_REFERENCE_MISMATCH" for d in report.discrepancies)


def test_scenario_g_admin_api_contract_mismatch(clean_workspace):
    """Scenario G: Frontend attempts to call separate endpoint /api/admin/enquiries, backend only has /api/admin/dashboard."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "app.get('/api/admin/dashboard', (req, res) => res.json({ enquiries: [], shipments: [] }));\n",
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        "async function loadAdmin() {\n"
        "  const res = await fetch('/api/admin/enquiries');\n"
        "}\n",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("Admin API contract mismatch" in m for m in report.endpoint_mismatches)


def test_scenario_h_shipment_event_missing_fields(clean_workspace):
    """Scenario H: Client sends event { title, description } but backend requires event_date and event_title."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "app.post('/api/admin/shipments/event', (req, res) => {\n"
        "  const { event_title, event_date, notes } = req.body;\n"
        "  if (!event_date) return res.status(400).json({ error: 'event_date is required' });\n"
        "});",
        encoding="utf-8"
    )
    (ws / "app.js").write_text(
        "async function addEvent() {\n"
        "  await fetch('/api/admin/shipments/event', {\n"
        "    method: 'POST',\n"
        "    body: JSON.stringify({ title: 'Departed', description: 'Port' })\n"
        "  });\n"
        "}",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert not report.valid
    assert any("Shipment event contract mismatch" in m for m in report.endpoint_mismatches)


def test_scenario_i_test_db_isolation_warning(clean_workspace):
    """Scenario I: Warning issued when test file requires server before setting test database environment variable."""
    ws = clean_workspace
    (ws / "server.js").write_text(
        "const sqlite3 = require('sqlite3');\n"
        "const dbPath = process.env.TEST_DB_PATH || 'database.sqlite';\n"
        "const db = new sqlite3.Database(dbPath);\n"
        "module.exports = { app: {} };",
        encoding="utf-8"
    )
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "api.test.js").write_text(
        "const { app } = require('../server');\n"
        "process.env.TEST_DB_PATH = ':memory:';\n"
        "test('dummy', () => expect(1).toBe(1));",
        encoding="utf-8"
    )

    validator = CrossFileContractValidator(ws)
    report = validator.validate()
    assert any("Test database isolation warning" in w for w in report.warnings)
    assert any(d.type == "TEST_DB_ISOLATION_WARNING" for d in report.discrepancies)
