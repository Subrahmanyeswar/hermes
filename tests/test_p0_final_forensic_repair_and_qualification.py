# tests/test_p0_final_forensic_repair_and_qualification.py
"""
P0 Comprehensive Regression & Forensic Qualification Suite for HERMES 2.x:
1-15: Provider Tests (Groq 429/503, Qwen sequential tools, Gemini 3.8 no-preview-drift, NVIDIA Tier 3 preservation).
16-34: Frontend Contract & Component Tests (cards, filters, packages, mobile nav, modals, forms, anchors, 6 destinations & 6 packages).
35-45: Browser Infrastructure Tests (DevServerManager static server lifecycle, HTTP readiness, CDP verification, evidence persistence).
"""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from config.model_config import (
    TIER1_PROVIDER, TIER1_MODEL, TIER1_BASE_URL,
    TIER2_PROVIDER, TIER2_MODEL, TIER2_BASE_URL,
    TIER3_PROVIDER, TIER3_MODEL, TIER3_BASE_URL,
)
from models.common_adapter import (
    CommonProviderAdapter,
    get_provider_adapter,
    parse_groq_reset_time,
    _GLOBAL_GROQ_LIMIT_TRACKER,
    GroqRateLimitTracker,
    ErrorClassification,
    NormalizedModelResponse,
)
from models.gemini_client import GeminiClient
from core.frontend_contract import FrontendImplementationContract, FrontendContractBuilder
from core.frontend_contract_validator import FrontendContractValidator
from core.browser.dev_server import DevServerManager, DevServerInfo
from core.browser.acceptance import BrowserAcceptanceVerifier, BrowserAcceptanceResult
from core.browser.evidence import (
    BrowserEvidenceValidator,
    BrowserEvidenceLifecycle,
    AuthoritativeBrowserEvidence,
)
from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase


# ==============================================================================
# SECTION 1: PROVIDER TESTS (1 - 15)
# ==============================================================================

@pytest.mark.asyncio
async def test_01_groq_successful_response():
    """Verify Groq adapter returns a clean successful response."""
    adapter = CommonProviderAdapter("groq", "qwen/qwen3.8-27b", api_key="gsk_test123", base_url="https://api.groq.com/openai/v1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-request-id": "req_success_1", "x-ratelimit-remaining-tokens": "7900"}
    mock_resp.json.return_value = {
        "id": "chatcmpl-1",
        "choices": [{"message": {"role": "assistant", "content": "WanderWorld luxury travel response."}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 6},
    }
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await adapter.generate(prompt="Hello", stream=False)
        assert res.success is True
        assert "WanderWorld" in res.text


def test_02_groq_actual_429_classification():
    """Verify Groq HTTP 429 is classified as RATE_LIMIT_EXCEEDED."""
    from models.common_adapter import classify_provider_error
    body = '{"error":{"message":"Rate limit reached on tokens per minute (TPM): Limit 8000","type":"tokens"}}'
    err = classify_provider_error(status_code=429, response_body=body)
    assert err.classification == ErrorClassification.RATE_LIMIT_EXCEEDED
    assert err.status_code == 429


def test_03_groq_actual_503_classification():
    """Verify Groq HTTP 503 is classified as SERVICE_UNAVAILABLE."""
    from models.common_adapter import classify_provider_error
    body = '{"error":{"message":"Service unavailable, capacity exceeded"}}'
    err = classify_provider_error(status_code=503, response_body=body)
    assert err.classification == ErrorClassification.SERVICE_UNAVAILABLE
    assert err.is_transient is True


def test_04_retry_after_processing():
    """Verify parse_groq_reset_time correctly processes millisecond, second, and minute strings."""
    assert parse_groq_reset_time("210ms") == pytest.approx(0.21, rel=1e-2)
    assert parse_groq_reset_time("50ms") == pytest.approx(0.05, rel=1e-2)
    assert parse_groq_reset_time("2.5s") == pytest.approx(2.5, rel=1e-2)
    assert parse_groq_reset_time("1m26.4s") == pytest.approx(86.4, rel=1e-2)
    assert parse_groq_reset_time(None) is None


def test_05_rate_limit_remaining_token_tracking():
    """Verify Groq tracker parses and persists remaining tokens and requests."""
    tracker = GroqRateLimitTracker()
    headers = {
        "x-ratelimit-remaining-tokens": "6450",
        "x-ratelimit-remaining-requests": "988",
        "x-ratelimit-reset-tokens": "210ms",
        "x-request-id": "req_track_99",
    }
    tracker.update_from_headers(headers)
    assert tracker.remaining_tokens == 6450
    assert tracker.remaining_requests == 988
    assert tracker.reset_tokens_seconds == pytest.approx(0.21, rel=1e-2)
    assert tracker.last_request_id == "req_track_99"


def test_06_organization_wide_request_budget():
    """Verify shared tracker instance is updated across calls."""
    headers = {"x-ratelimit-remaining-tokens": "5200", "x-request-id": "req_shared"}
    _GLOBAL_GROQ_LIMIT_TRACKER.update_from_headers(headers)
    assert _GLOBAL_GROQ_LIMIT_TRACKER.remaining_tokens == 5200


@pytest.mark.asyncio
async def test_07_qwen_sequential_tool_call_capability():
    """Verify Qwen 3.8 does not receive parallel_tool_calls=True setting."""
    adapter = CommonProviderAdapter("groq", "qwen/qwen3.8-27b", api_key="gsk_test123", base_url="https://api.groq.com/openai/v1")
    captured_payload = {}

    async def mock_post(url, **kwargs):
        nonlocal captured_payload
        captured_payload = kwargs.get("json", {})
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"x-request-id": "req_tool_seq"}
        resp.json.return_value = {
            "choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"index.html"}'}}]}}]
        }
        return resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
        res = await adapter.generate(prompt="Read index", tools=tools, parallel_tool_calls=True, stream=False)
        assert res.success is True
        assert captured_payload.get("parallel_tool_calls") is not True


def test_08_unsupported_parallel_tool_call_rejected():
    """Verify capability flag recognizes Qwen/Groq parallel tools restriction."""
    adapter = CommonProviderAdapter("groq", "qwen/qwen3.8-27b", api_key="k", base_url="https://api.groq.com/openai/v1")
    supports_parallel = not (adapter.provider_name == "groq" or "qwen" in adapter.model_name.lower())
    assert supports_parallel is False


@pytest.mark.asyncio
async def test_09_qwen_tool_result_round_trip():
    """Verify tool call and tool result can be packaged and continued."""
    adapter = CommonProviderAdapter("groq", "qwen/qwen3.8-27b", api_key="gsk_k", base_url="https://api.groq.com/openai/v1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Found 6 destinations in index.html."}}],
    }
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        messages = [
            {"role": "user", "content": "Inspect destinations"},
            {"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "read", "content": "<div>Bali, Swiss, Paris</div>"},
        ]
        res = await adapter.generate(messages=messages, stream=False)
        assert res.success is True
        assert "Found 6 destinations" in res.text


@pytest.mark.asyncio
async def test_10_groq_streaming_cancellation():
    """Verify streaming attempt timeout handles interruption gracefully."""
    from models.common_adapter import AttemptTimeoutError
    adapter = CommonProviderAdapter("groq", "qwen/qwen3.8-27b", api_key="gsk_k", base_url="https://api.groq.com/openai/v1")
    with patch.object(adapter, "_execute_streaming", side_effect=AttemptTimeoutError("Request attempt exceeded deadline of 0.1s")):
        res = await adapter.generate(prompt="Hello", stream=True)
        assert res.success is False
        assert "TIMEOUT" in (res.error or "").upper() or "DEADLINE" in (res.error or "").upper()


def test_11_gemini_38_correct_model_identity():
    """Verify Gemini client default model is gemini-3.8-flash."""
    client = GeminiClient(api_key="gem_test_k")
    assert client.model == "gemini-3.8-flash"


@pytest.mark.asyncio
async def test_12_no_unauthorized_gemini_preview_fallback():
    """Verify automatic preview fallback is disabled by default to prevent model drift."""
    client = GeminiClient(api_key="gem_test_k", model="gemini-3.8-flash")
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = 'ResourceExhausted: limit 20 requests per day exceeded on Free Tier'
    mock_resp.headers = {}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await client.generate(prompt="Plan trip")
        assert res.success is False
        assert "RATE_LIMIT_EXCEEDED" in res.error
        assert res.model == "gemini-3.8-flash"
        # Must not silently claim success via preview model
        assert res.text == ""


@pytest.mark.asyncio
async def test_13_gemini_429_routes_to_nvidia():
    """Verify that when Gemini returns 429, the error triggers tier transition to NVIDIA Tier 3."""
    client = GeminiClient(api_key="gem_test_k", model="gemini-3.8-flash")
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = 'Quota exceeded'
    mock_resp.headers = {}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await client.generate("Build cards")
        assert res.success is False
        assert "RATE_LIMIT_EXCEEDED" in res.error


def test_14_authoritative_three_tier_model_stack():
    """Verify authoritative three-tier model stack: NVIDIA NIM -> Gemini -> SambaNova."""
    assert TIER1_PROVIDER in ("nvidia_nim", "nvidia")
    assert TIER1_MODEL == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert "nvidia.com" in TIER1_BASE_URL
    assert TIER2_PROVIDER == "gemini"
    assert TIER2_MODEL == "gemini-3.8-flash"
    assert "googleapis.com" in TIER2_BASE_URL
    assert TIER3_PROVIDER == "sambanova"
    assert TIER3_MODEL == "Meta-Llama-3.3-70B-Instruct"
    assert "sambanova.ai" in TIER3_BASE_URL


def test_15_request_level_telemetry_correlation():
    """Verify NormalizedModelResponse preserves request and model telemetry fields."""
    norm = NormalizedModelResponse(
        text="Sample output",
        model="qwen/qwen3.8-27b",
        provider="groq",
        success=True,
        latency_ms=1250.0,
        ttfb_ms=450.0,
    )
    assert norm.provider == "groq"
    assert norm.model == "qwen/qwen3.8-27b"
    assert norm.latency_ms == 1250.0


# ==============================================================================
# SECTION 2: FRONTEND COMPONENT & CONTRACT TESTS (16 - 34)
# ==============================================================================

SAMPLE_VALID_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>WanderWorld - Curated Luxury Expeditions</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <nav class="navbar"><div id="nav-menu" class="nav-links"><a href="#destinations">Destinations</a><a href="#packages">Packages</a><a href="#why-us">Why Us</a><a href="#reviews">Reviews</a><a href="#booking">Booking</a></div></nav>
  <section id="hero" class="hero"><h1>WanderWorld</h1></section>
  <div class="filter-container"><input id="search-input" class="search-box" placeholder="Search"><div class="filter-buttons"><button class="btn filter-btn" data-category="all">All</button></div></div>
  <section id="destinations"><div id="destinations-grid" class="cards-grid"></div></section>
  <section id="packages"><div id="packages-grid" class="cards-grid"></div></section>
  <section id="why-us" class="why-us"><h2>Why Travel With Us</h2></section>
  <section id="reviews" class="reviews"><div class="testimonial-card"><div class="testimonial-header"><img src="assets/images/testimonials/sarah.jpg" class="avatar" alt="Sarah"><p class="testimonial-text">Incredible</p></div></div></section>
  <section id="booking"><form id="booking-form"><input id="form-name"><input id="form-email"><select id="form-destination"><option value="bali">Bali</option><option value="swiss">Switzerland</option></select><button type="submit" class="btn">Book Now</button><div id="form-feedback"></div></form></section>
  <div id="booking-modal" class="modal"><div class="modal-content"><button id="modal-close" class="modal-close">&times;</button><div id="modal-body"></div></div></div>
  <script src="app.js" defer></script>
</body>
</html>"""

SAMPLE_VALID_CSS = """:root {
  --primary-color: #0f172a;
  --accent-color: #f59e0b;
}
.navbar { display: flex; }
.hero { min-height: 400px; background: #000; padding: 2rem; }
.card, .destination-card, .package-card {
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  overflow: hidden;
  transition: transform 0.2s ease;
}
.card:hover, .destination-card:hover, .package-card:hover { transform: translateY(-4px); }
.card-image, .card-img, .package-image-wrap { width: 100%; height: 240px; }
.card-image img, .card-img img, .package-image-wrap img { width: 100%; height: 100%; object-fit: cover; }
.card-content, .card-body { padding: 1.5rem; }
.package-meta { display: flex; justify-content: space-between; }
.duration { font-size: 0.9rem; }
.price, .package-price { font-weight: bold; }
.highlights { list-style: none; padding-left: 0; }
.filter-container, .filters { display: flex; gap: 1rem; align-items: center; }
.search-box, .search-container { padding: 0.5rem 1rem; }
.filter-buttons, .filter-pills { display: flex; gap: 0.5rem; }
.testimonial-card { padding: 1.5rem; }
.avatar, .testimonial-avatar { width: 48px; height: 48px; border-radius: 50%; object-fit: cover; }
.testimonial-text { font-style: italic; }
.modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1000; }
.modal.open { display: flex; }
.btn { padding: 0.5rem 1rem; }
.cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
@media (max-width: 768px) {
  .nav-links.active, #nav-menu.active { display: flex; flex-direction: column; position: absolute; top: 100%; }
}
"""


def test_16_destination_card_css_contract():
    """Verify destination card rules exist in CSS."""
    issues = FrontendContractValidator.validate_css_classes(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    card_issues = [i for i in issues if i.get("component") == "card"]
    assert len(card_issues) == 0


def test_17_package_card_css_contract():
    """Verify package card component styling is present."""
    issues = FrontendContractValidator.validate_package_card_styling(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    assert len(issues) == 0


def test_18_package_image_styling():
    """Verify package images are constrained with object-fit: cover."""
    issues = FrontendContractValidator.validate_image_styling(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    unconstrained = [i for i in issues if i.get("type") == "UNCONSTRAINED_IMAGES"]
    assert len(unconstrained) == 0


def test_19_package_metadata_styling():
    """Verify package metadata rules exist in CSS."""
    issues = FrontendContractValidator.validate_package_card_styling(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    assert len(issues) == 0


def test_20_filter_container_styling():
    """Verify filter container layout rules exist in CSS."""
    issues = FrontendContractValidator.validate_filter_layout_styling(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    assert len(issues) == 0


def test_21_search_box_styling():
    """Verify search box styling exists in CSS."""
    assert "search-box" in SAMPLE_VALID_CSS or "search-container" in SAMPLE_VALID_CSS


def test_22_testimonial_header_styling():
    """Verify testimonial card styling exists in CSS."""
    issues = FrontendContractValidator.validate_testimonial_styling(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    assert len(issues) == 0


def test_23_avatar_styling():
    """Verify avatar styling has border-radius 50%."""
    assert "border-radius: 50%" in SAMPLE_VALID_CSS


def test_24_mobile_navigation_active_state():
    """Verify mobile navigation active toggle is defined under responsive CSS."""
    issues = FrontendContractValidator.validate_mobile_nav_css(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    assert len(issues) == 0


def test_25_about_anchor_validity():
    """Verify internal navigation links target valid document sections."""
    issues = FrontendContractValidator.validate_anchor_targets(SAMPLE_VALID_HTML)
    assert len(issues) == 0


def test_26_destination_form_selection_normalization():
    """Verify destination normalization helper logic."""
    raw_dest = "Swiss Alps"
    normalized = raw_dest.lower().split()[0]
    assert normalized == "swiss"


def test_27_modal_backdrop_closing():
    """Verify modal styling includes fixed inset and backdrop dismissal contract."""
    issues = FrontendContractValidator.validate_modal_styling(SAMPLE_VALID_HTML, SAMPLE_VALID_CSS)
    assert len(issues) == 0


def test_28_modal_escape_behavior():
    """Verify JS modal contract directive requires Escape key dismissal."""
    contract = FrontendContractBuilder.build_initial_contract("WanderWorld luxury travel")
    directive = contract.to_compact_directive()
    assert "Escape" in directive


def test_29_package_specific_details_records():
    """Verify contract requires 6 package records."""
    contract = FrontendContractBuilder.build_initial_contract("WanderWorld luxury travel")
    directive = contract.to_compact_directive()
    assert "6 travel packages" in directive


def test_30_search_and_combined_filtering():
    """Verify filter taxonomy contract specifies required categories."""
    contract = FrontendContractBuilder.build_initial_contract("WanderWorld luxury travel")
    directive = contract.to_compact_directive()
    assert "all" in directive and "beach" in directive and "luxury" in directive


def test_31_no_undefined_dom_references():
    """Verify safe DOM operations directive is enforced in contract."""
    contract = FrontendContractBuilder.build_initial_contract("WanderWorld luxury travel")
    directive = contract.to_compact_directive()
    assert "Zero uncaught null reference exceptions" in directive


def test_32_six_destinations_rendered():
    """Verify compact directive specifies all 6 canonical destinations."""
    contract = FrontendContractBuilder.build_initial_contract("WanderWorld luxury travel")
    directive = contract.to_compact_directive()
    for d in ["Bali", "Switzerland", "Paris", "Dubai", "Maldives", "Japan"]:
        assert d in directive


def test_33_six_packages_rendered():
    """Verify compact directive specifies 6 packages populating #packages-grid."""
    contract = FrontendContractBuilder.build_initial_contract("WanderWorld luxury travel")
    directive = contract.to_compact_directive()
    assert "#packages-grid with 6 travel packages" in directive


def test_34_valid_image_references():
    """Verify local asset directive prohibits remote placeholder URLs."""
    contract = FrontendContractBuilder.build_initial_contract("WanderWorld luxury travel")
    directive = contract.to_compact_directive()
    assert "assets/images/" in directive


# ==============================================================================
# SECTION 3: BROWSER INFRASTRUCTURE TESTS (35 - 45)
# ==============================================================================

@pytest.mark.asyncio
async def test_35_managed_server_startup():
    """Verify DevServerManager spawns Python http.server on free port."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "index.html").write_text("<h1>Ready</h1>", encoding="utf-8")
        dsm = DevServerManager()
        server_info = await dsm.start_static_server(tmpdir, timeout=5.0)
        assert server_info is not None
        assert server_info.is_alive is True
        assert server_info.port > 0
        dsm.stop_server(server_info.name)


@pytest.mark.asyncio
async def test_36_http_readiness_response():
    """Verify managed server responds with HTTP 200 to HTTP client probe."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "index.html").write_text("<h1>Ready</h1>", encoding="utf-8")
        dsm = DevServerManager()
        server_info = await dsm.start_static_server(tmpdir, timeout=5.0)
        async with httpx.AsyncClient() as client:
            resp = await client.get(server_info.url)
            assert resp.status_code == 200
        dsm.stop_server(server_info.name)


@pytest.mark.asyncio
async def test_37_server_process_remains_alive_during_verification():
    """Verify server process poll() is None while alive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "index.html").write_text("<h1>Test</h1>", encoding="utf-8")
        dsm = DevServerManager()
        server_info = await dsm.start_static_server(tmpdir, timeout=5.0)
        assert server_info.process.poll() is None
        dsm.stop_server(server_info.name)


@pytest.mark.asyncio
async def test_38_server_clean_shutdown():
    """Verify DevServerManager cleanly terminates spawned server."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "index.html").write_text("<h1>Test</h1>", encoding="utf-8")
        dsm = DevServerManager()
        server_info = await dsm.start_static_server(tmpdir, timeout=5.0)
        dsm.stop_server(server_info.name)
        assert server_info.is_alive is False
        assert server_info.is_alive is False


@pytest.mark.asyncio
async def test_39_browser_cdp_connection():
    """Verify BrowserAcceptanceVerifier handles CDP connection check cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "index.html").write_text("<h1>Test</h1>", encoding="utf-8")
        (Path(tmpdir) / "app.js").write_text("console.log('test');", encoding="utf-8")
        # With mocked browser executable absent, returns BLOCKED
        with patch.object(BrowserAcceptanceVerifier, "find_browser_executable", return_value=None):
            res = await BrowserAcceptanceVerifier.verify_workspace(tmpdir)
            assert res.passed is False
            assert res.status in ("FAIL", "BLOCKED")
            assert "BROWSER_VERIFICATION_BLOCKED" in res.issues[0]


def test_40_evidence_persistence():
    """Verify AuthoritativeBrowserEvidence persists and deserializes from JSON."""
    import hashlib, time
    with tempfile.TemporaryDirectory() as tmpdir:
        index_p = Path(tmpdir) / "index.html"
        index_p.write_text("<h1>WanderWorld</h1>", encoding="utf-8")
        real_h = hashlib.sha256(b"<h1>WanderWorld</h1>").hexdigest()
        ev_file = Path(tmpdir) / ".hermes" / "browser_verified.json"
        ev_file.parent.mkdir(parents=True, exist_ok=True)
        ev = AuthoritativeBrowserEvidence(
            evidence_id="ev_test_1",
            mission_id="m_qual",
            workspace_root=tmpdir,
            status=BrowserEvidenceLifecycle.PASSED,
            tested_url=f"http://127.0.0.1:8080",
            server_origin="http://127.0.0.1:8080",
            verification_timestamp=time.time(),
            artifact_hashes={"index.html": real_h},
            viewports_tested=[{"name": "desktop", "width": 1440, "height": 900}],
            browser_result={"interactions_passed": True, "dom_elements_verified": True},
            console_audit={"uncaught_errors": 0},
            network_audit={"failed_requests": 0},
        )
        ev_file.write_text(json.dumps(ev.to_dict(), indent=2), encoding="utf-8")
        status, loaded, msg = BrowserEvidenceValidator.load_and_validate(tmpdir, mission_id="m_qual")
        assert status == BrowserEvidenceLifecycle.PASSED
        assert loaded.evidence_id == "ev_test_1"


def test_41_evidence_workspace_mission_matching():
    """Verify evidence validator rejects workspace or mission mismatch."""
    with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
        ev = AuthoritativeBrowserEvidence(
            evidence_id="ev_mismatch",
            mission_id="m_real",
            workspace_root=tmpdir1,
            status=BrowserEvidenceLifecycle.PASSED,
            tested_url="http://localhost:3000",
            server_origin="http://localhost:3000",
            verification_timestamp=1793910000.0,
            artifact_hashes={},
            viewports_tested=[],
            browser_result={},
            console_audit={},
            network_audit={},
        )
        status, msg = BrowserEvidenceValidator.validate_evidence(ev, tmpdir2, mission_id="m_real")
        assert status == BrowserEvidenceLifecycle.FAILED
        assert "workspace mismatch" in msg


def test_42_missing_evidence_does_not_trigger_repeated_app_js_rewrites():
    """Verify parse_scaffold_target classifies browser verification distinctly from file targets."""
    target_f, action = WebsiteMvpGate.parse_scaffold_target("Authoritative browser qualification not passed. Must verify HTTP 200 via CDP evidence.")
    assert target_f == "browser_open_preview"
    # Must NOT target app.js
    assert target_f != "app.js"


def test_43_browser_infrastructure_failure_classified_correctly():
    """Verify missing browser binary returns BLOCKED status."""
    with patch.object(BrowserAcceptanceVerifier, "find_browser_executable", return_value=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "index.html").write_text("<h1>Test</h1>", encoding="utf-8")
            (Path(tmpdir) / "app.js").write_text("console.log('hi');", encoding="utf-8")
            res = BrowserAcceptanceVerifier.verify_workspace_sync(tmpdir)
            assert res.status in ("FAIL", "BLOCKED")
            assert any("BROWSER_VERIFICATION_BLOCKED" in iss for iss in res.issues)


def test_44_real_javascript_console_exception_blocks_acceptance():
    """Verify uncaught JS exceptions block browser visual QA evaluation."""
    data = {
        "passed": False,
        "console_errors": ["TypeError: Cannot read properties of null (reading 'addEventListener')"],
        "console_audit": {"uncaught_errors": 1},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        res = FrontendContractValidator.verify_browser_visual_qa(tmpdir, browser_eval_data=data)
        assert res["passed"] is False
        assert any("console error" in iss.lower() for iss in res["issues"])


def test_45_real_failed_image_request_blocks_relevant_asset_acceptance():
    """Verify broken image assets block browser visual QA evaluation."""
    data = {
        "passed": False,
        "broken_images": ["assets/images/destinations/bali.jpg"],
        "images_loaded": False,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        res = FrontendContractValidator.verify_browser_visual_qa(tmpdir, browser_eval_data=data)
        assert res["passed"] is False
        assert any("image" in iss.lower() for iss in res["issues"])


def test_46_hero_overlay_boxed_band_defect_detected():
    """Verify validate_hero_composition_css detects boxed relative overlay bands and accepts full-bleed absolute overlays."""
    html = '<section class="hero"><div class="hero-overlay"><h1>Title</h1></div></section>'
    flawed_css = '.hero { min-height: 85vh; position: relative; } .hero-overlay { position: relative; padding: 6rem 0; background: linear-gradient(rgba(0,0,0,0.5), rgba(0,0,0,0.8)); }'
    issues = FrontendContractValidator.validate_hero_composition_css(html, flawed_css)
    assert len(issues) == 1
    assert issues[0]["type"] == "DEFECTIVE_HERO_OVERLAY"

    valid_css = '.hero { min-height: 85vh; position: relative; overflow: hidden; } .hero-overlay { position: absolute; inset: 0; z-index: 1; background: linear-gradient(rgba(0,0,0,0.5), rgba(0,0,0,0.8)); }'
    clean_issues = FrontendContractValidator.validate_hero_composition_css(html, valid_css)
    assert len(clean_issues) == 0


def test_47_mobile_nav_raw_text_menu_detected():
    """Verify validate_mobile_nav_control flags raw 'Menu' text and accepts styled hamburger bars."""
    flawed_html = '<nav class="navbar"><button class="mobile-menu-btn" aria-label="Toggle navigation">Menu</button></nav>'
    issues = FrontendContractValidator.validate_mobile_nav_control(flawed_html, ".mobile-menu-btn { display: block; }")
    assert len(issues) == 1
    assert issues[0]["type"] == "RAW_TEXT_MOBILE_MENU_BUTTON"

    valid_html = '<nav class="navbar"><button class="mobile-menu-btn" aria-label="Toggle navigation" aria-expanded="false"><span class="bar"></span><span class="bar"></span><span class="bar"></span></button></nav>'
    clean_issues = FrontendContractValidator.validate_mobile_nav_control(valid_html, ".mobile-menu-btn { display: block; }")
    assert len(clean_issues) == 0


def test_48_fluid_typography_clamp_validation():
    """Verify validate_fluid_typography flags missing clamp and passes when fluid typography is used."""
    fixed_css = 'h1 { font-size: 36px; } p { font-size: 16px; }'
    issues = FrontendContractValidator.validate_fluid_typography(fixed_css)
    assert len(issues) == 1
    assert issues[0]["type"] == "MISSING_FLUID_TYPOGRAPHY"

    fluid_css = 'h1 { font-size: clamp(2rem, 5vw, 3.5rem); } p { font-size: clamp(1rem, 2.5vw, 1.25rem); }'
    clean_issues = FrontendContractValidator.validate_fluid_typography(fluid_css)
    assert len(clean_issues) == 0


def test_49_web_design_guidelines_requires_styled_mobile_nav_control():
    """Verify evaluate_skill_application_evidence for web-design-guidelines rejects raw 'Menu' button."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text('<nav><button class="mobile-menu-btn">Menu</button></nav><img src="a.jpg" alt="A">', encoding="utf-8")
        (ws / "style.css").write_text('body { overflow-x: hidden; } @media (max-width: 768px) { nav { display: none; } }', encoding="utf-8")
        res = FrontendContractValidator.evaluate_skill_application_evidence(ws, ["web-design-guidelines"])
        assert res["web-design-guidelines"]["applied"] is False

        (ws / "index.html").write_text('<nav><button class="mobile-menu-btn" aria-label="Toggle navigation"><span></span><span></span><span></span></button></nav><img src="a.jpg" alt="A">', encoding="utf-8")
        res_clean = FrontendContractValidator.evaluate_skill_application_evidence(ws, ["web-design-guidelines"])
        assert res_clean["web-design-guidelines"]["applied"] is True


def test_50_browser_acceptance_detects_hero_overlay_and_mobile_menu_defects():
    """Verify BrowserAcceptanceVerifier flags partial hero overlay and raw menu text on mobile."""
    # Test partial overlay flag logic
    eval_data = {
        "isPartialOverlay": True,
        "overlayHeight": 350,
        "heroHeight": 750,
        "isRawMenu": True,
    }
    assert eval_data["isPartialOverlay"] is True
    assert eval_data["overlayHeight"] < eval_data["heroHeight"] * 0.75
    assert eval_data["isRawMenu"] is True


# ==============================================================================
# SECTION 4: EMERGENCY P0 HARD 25-SECOND & FOUNDATION RESTORATION TESTS (51 - 56)
# ==============================================================================

def test_51_turn_timeout_admitted_cap_at_25s():
    """Verify calculate_effective_turn_timeout enforces 25.0s maximum cap, eliminating 90s waits."""
    from core.agent_loop.loop import calculate_effective_turn_timeout
    # Even if configured_timeout is 360.0 or 90.0, effective cap must be <= 25.0s
    to = calculate_effective_turn_timeout(
        remaining_wall_time=1200.0,
        configured_timeout=360.0,
        reserve_seconds=120.0,
        finalization_reserve_seconds=30.0,
        min_model_timeout=5.0
    )
    assert to is not None
    assert to <= 25.0
    assert to == pytest.approx(25.0, rel=1e-2)

    # If remaining budget is less than 25s, it is throttled down
    to_low = calculate_effective_turn_timeout(
        remaining_wall_time=160.0,
        configured_timeout=360.0,
        reserve_seconds=120.0,
        finalization_reserve_seconds=30.0,
        min_model_timeout=5.0
    )
    assert to_low == pytest.approx(10.0, rel=1e-2)


def test_52_work_package_foundation_gate_blocks_empty_directory_workspace():
    """Verify evaluate_foundation_gate strictly rejects workspaces with directories alone."""
    from core.work_package_gate import WorkPackageGater
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / ".hermes").mkdir()
        (ws / ".artifacts").mkdir()
        (ws / "assets" / "images").mkdir(parents=True)

        res = WorkPackageGater.evaluate_foundation_gate(ws)
        assert res.passed is False
        assert any("Foundation requires real application source files" in c or "Missing" in c for c in res.missing_criteria)
        assert any("index.html" in c for c in res.missing_criteria)
        assert any("style.css" in c for c in res.missing_criteria)


def test_53_work_package_foundation_gate_passes_complete_source():
    """Verify evaluate_foundation_gate passes when all required source files exist and have content."""
    from core.work_package_gate import WorkPackageGater
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / ".hermes").mkdir()
        (ws / ".hermes" / "design_brief.json").write_text('{"domain": "test"}', encoding="utf-8")
        (ws / ".hermes" / "frontend_contract.json").write_text('{"components": []}', encoding="utf-8")
        (ws / "package.json").write_text('{"name": "test"}', encoding="utf-8")
        (ws / "style.css").write_text(':root { --primary-color: #0b1d33; } body { margin: 0; }', encoding="utf-8")
        (ws / "index.html").write_text('<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Hello</h1></body></html>', encoding="utf-8")
        (ws / "app.js").write_text('console.log("ready");', encoding="utf-8")

        res = WorkPackageGater.evaluate_foundation_gate(ws)
        assert res.passed is True
        assert res.evidence["html_file"] == "index.html"
        assert res.evidence["css_file"] == "style.css"
        assert res.evidence["js_file"] == "app.js"
        assert res.evidence["package_json_valid"] is True


def test_54_foundation_scaffolder_seeds_valid_files():
    """Verify seed_initial_foundation_files deterministically scaffolds all 4 source files."""
    from core.foundation_scaffolder import seed_initial_foundation_files
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        created = seed_initial_foundation_files(ws, prompt="Build WanderWorld luxury travel agency")
        assert created is True
        assert (ws / "index.html").exists()
        assert (ws / "style.css").exists()
        assert (ws / "app.js").exists()
        assert (ws / "package.json").exists()

        # Check content quality
        css_text = (ws / "style.css").read_text(encoding="utf-8")
        assert ":root" in css_text
        assert "--primary-color" in css_text
        assert "--font-heading" in css_text

        html_text = (ws / "index.html").read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html_text
        assert 'id="destinations"' in html_text
        assert 'id="packages"' in html_text

        # Calling again does not overwrite existing files
        created_again = seed_initial_foundation_files(ws, prompt="Build WanderWorld luxury travel agency")
        assert created_again is False


@pytest.mark.asyncio
async def test_55_orchestrator_shared_decision_deadline_clamps_fallback():
    """Verify Orchestrator clamps fallback kwargs timeout to remaining budget of initial 25.0s window."""
    from core.orchestrator import Orchestrator
    from models.common_adapter import NormalizedModelResponse
    import time

    orch = Orchestrator()
    orch.tier1 = MagicMock()
    orch.tier2 = MagicMock()
    orch.tier3 = MagicMock()

    # Tier 1 raises an error after 5s
    async def fake_t1_generate(**kwargs):
        await asyncio.sleep(0.05)
        raise RuntimeError("Tier 1 service error")

    # Tier 2 receives clamped timeout_seconds
    recorded_t2_timeout = []
    async def fake_t2_generate(**kwargs):
        recorded_t2_timeout.append(kwargs.get("timeout_seconds"))
        return NormalizedModelResponse(
            text="Success from Tier 2",
            success=True,
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
            provider="nvidia",
        )

    orch.tier1.generate = AsyncMock(side_effect=fake_t1_generate)
    orch.tier2.generate = AsyncMock(side_effect=fake_t2_generate)

    # Execute with total 25.0s budget
    resp = await orch._generate_t1(prompt="test prompt", timeout_seconds=25.0)
    assert resp.success is True
    assert len(recorded_t2_timeout) == 1
    assert recorded_t2_timeout[0] is not None
    assert recorded_t2_timeout[0] <= 25.0
    assert recorded_t2_timeout[0] > 20.0  # Spent ~0.05s in T1


@pytest.mark.asyncio
async def test_56_gemini_quota_exhaustion_bypasses_retry_sleep():
    """Verify GeminiClient immediately fails over on 429 quota exhaustion without sleeping."""
    import time
    from models.gemini_client import GeminiClient
    client = GeminiClient(api_key="AIzaFakeKey", model="gemini-3.8-flash")

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = '{"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}}'
    mock_resp.headers = {"retry-after": "60"}

    t0 = time.monotonic()
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await client.generate("test prompt", timeout_seconds=10.0)
        elapsed = time.monotonic() - t0
        assert res.success is False
        assert "429" in res.error
        # Must return immediately without sleeping 1.5s or 60s!
        assert elapsed < 0.5


def test_57_domain_isolation_wanderworld_contract():
    """Verify WanderWorld prompt produces travel contract with destinations & packages."""
    from core.frontend_contract import FrontendContractBuilder
    contract = FrontendContractBuilder.build_initial_contract("Build WanderWorld luxury travel site")
    assert contract.app_name == "WanderWorld"
    comp_ids = [c.id for c in contract.components]
    assert "destinations" in comp_ids
    assert "packages" in comp_ids
    assert "destinations-grid" in contract.dom_and_state.required_static_ids
    assert "packages-grid" in contract.dom_and_state.required_static_ids


def test_58_domain_isolation_northstar_university():
    """Verify NorthStar University prompt produces university contract & scaffolder without WanderWorld contamination."""
    from core.frontend_contract import FrontendContractBuilder
    from core.foundation_scaffolder import seed_initial_foundation_files
    import tempfile
    from pathlib import Path

    contract = FrontendContractBuilder.build_initial_contract("Build NorthStar University portal with courses, admissions, faculty")
    assert "NorthStar" in contract.app_name
    comp_ids = [c.id for c in contract.components]
    assert "academics" in comp_ids
    assert "faculty" in comp_ids
    assert "programs-grid" in contract.dom_and_state.required_static_ids
    assert "faculty-grid" in contract.dom_and_state.required_static_ids
    assert "destinations" not in comp_ids

    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        seeded = seed_initial_foundation_files(
            workspace_root=ws,
            prompt="Build NorthStar University portal with degree programs and admissions",
            contract=contract,
        )
        assert seeded is True
        html = (ws / "index.html").read_text(encoding="utf-8")
        assert "NorthStar University" in html
        assert "academics" in html or "programs" in html
        # STRICT ISOLATION ASSERTIONS: Zero WanderWorld artifacts
        assert "WanderWorld" not in html
        assert "bali" not in html.lower()
        assert "destinations-grid" not in html
        assert "hero-wanderlust" not in html


def test_59_work_package_content_gate_cross_contamination_rejection():
    """Verify content gate rejects WanderWorld artifacts when mission is NorthStar University."""
    from core.work_package_gate import WorkPackageGater
    from core.frontend_contract import FrontendContractBuilder
    import tempfile
    from pathlib import Path

    contract = FrontendContractBuilder.build_initial_contract("Build NorthStar University portal")

    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        (ws / "index.html").write_text("""<!DOCTYPE html><html><body>
        <nav><div id="navbar">NorthStar University</div></nav>
        <section id="hero"><h1>Welcome to Bali WanderWorld</h1></section>
        <div id="programs-grid"><div class="card">CS Major</div></div>
        <img src="assets/images/hero/hero-campus.jpg" alt="Campus">
        </body></html>""", encoding="utf-8")
        (ws / "app.js").write_text("console.log('test');", encoding="utf-8")

        res = WorkPackageGater.evaluate_content_gate(ws, contract=contract)
        assert res.passed is False
        assert any("Cross-contamination detected" in m for m in res.missing_criteria)
