# tests/test_phase5_hybrid_intelligence.py
"""
HERMES 2.x Phase 5 Regression Suite:
Unified LLM Intelligence, Genuine Provider Availability Registry,
Gemini/SambaNova/Ollama Failure Diagnosis & Recovery, Confidence-Aware Routing,
Strict Schema Validation, Separate Telemetry (TTFB vs Reasoning vs Usable TTFT),
and End-to-End FastAPI Runtime Mission Execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.adaptive_routing import AdaptiveRouter, ProviderHealthState
from core.domain_confidence import (
    DomainConfidenceCategory,
    DomainConfidenceClassifier,
    HybridExecutionMode,
)
from core.llm_semantic_planner import (
    LLMSynthesisBlockedError,
    LLMSemanticPlanner,
    validate_structured_semantic_spec,
)
from core.mission_spec import MissionSpecification
from core.provider_registry import (
    ProviderAvailabilityRegistry,
    ProviderAvailabilityState,
)
from core.universal_renderer import UniversalContentRenderer


# ── 1. Genuine Provider Availability Registry ──────────────────────────────────

def test_01_registry_never_equates_credentials_with_health():
    reg = ProviderAvailabilityRegistry()
    # Static config starts in CONFIGURED (even if keys exist in .env)
    for t in (1, 2, 3, 4):
        entry = reg.get(t)
        assert entry is not None
        assert entry.state == ProviderAvailabilityState.CONFIGURED
        assert entry.state != ProviderAvailabilityState.HEALTHY


# ── 2. Gemini 503 high-demand & /v1beta/models discovery ───────────────────────

@pytest.mark.asyncio
async def test_02_gemini_503_high_demand_bypasses_sleep_and_records_tier_int():
    from models.gemini_client import GeminiClient

    client = GeminiClient(api_key="AIzaFakeKey", model="gemini-3.8-flash", tier=2)

    mock_503 = MagicMock()
    mock_503.status_code = 503
    mock_503.text = json.dumps({
        "error": {
            "code": 503,
            "message": "This model is currently experiencing high demand.",
            "status": "UNAVAILABLE",
        }
    })
    mock_503.headers = {}

    router_mock = MagicMock()
    t0 = asyncio.get_running_loop().time()
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_503)), \
         patch("core.adaptive_routing.get_adaptive_router", return_value=router_mock):
        res = await client.generate(prompt="hello", timeout_seconds=10.0)
    elapsed = asyncio.get_running_loop().time() - t0

    assert res.success is False
    assert "503" in (res.error or "") or "high demand" in (res.error or "").lower()
    # Immediate exit without 1.5s-3.0s retry sleeps
    assert elapsed < 1.0
    # Tier passed to router.record_failure must be integer self.tier (2), not "gemini"
    assert router_mock.record_failure.called
    call_args = router_mock.record_failure.call_args
    tier_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("tier")
    assert isinstance(tier_arg, int)
    assert tier_arg == 2


@pytest.mark.asyncio
async def test_03_gemini_registry_probe_uses_models_discovery_for_503():
    reg = ProviderAvailabilityRegistry()

    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.text = '{"error": {"code": 503, "message": "This model is currently experiencing high demand."}}'

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}), \
         patch("models.gemini_client.GeminiClient.discover_models", new=AsyncMock(return_value=["gemini-3.8-flash", "gemini-3-flash-preview"])), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp_503)):
        entry = await reg.probe_tier(2, probe_inference=True, timeout=5.0)

    assert entry.state == ProviderAvailabilityState.DEGRADED
    assert entry.last_http_status == 503
    assert "gemini-3.8-flash" in entry.supported_models
    # Must NOT misclassify a live 503 model as INVALID_MODEL_ID / MODEL_UNAVAILABLE
    assert entry.state != ProviderAvailabilityState.MODEL_UNAVAILABLE


# ── 3. SambaNova HTTP 402 BILLING_BLOCKED ──────────────────────────────────────

def test_04_sambanova_402_billing_blocked_is_non_routable_zero_retries():
    reg = ProviderAvailabilityRegistry()
    entry = reg.record_outcome(
        3,
        success=False,
        status_code=402,
        error="HTTP 402 PAYMENT_METHOD_REQUIRED: balance_units=0",
    )
    assert entry.state == ProviderAvailabilityState.BILLING_BLOCKED
    assert entry.is_routable() is False
    assert 3 not in reg.get_routable_tiers()

    router = AdaptiveRouter()
    router.record_failure(tier=3, error="HTTP 402 Payment Required", timeout_type="BILLING_EXHAUSTED")
    assert router.providers[3].state == ProviderHealthState.BILLING_BLOCKED
    assert 3 not in router.get_eligible_tiers()


# ── 4. Ollama daemon down vs missing model diagnosis ───────────────────────────

@pytest.mark.asyncio
async def test_05_ollama_daemon_down_and_missing_model_diagnostics():
    reg = ProviderAvailabilityRegistry()

    # Case A: daemon unreachable
    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.ConnectError("Connection refused"))):
        entry_down = await reg.probe_tier(4, probe_inference=True, timeout=2.0)
    assert entry_down.state == ProviderAvailabilityState.DEGRADED
    assert "ollama serve" in (entry_down.corrective_action or "").lower()
    assert "ollama pull" in (entry_down.corrective_action or "").lower()

    # Case B: daemon reachable, other models present, configured llama3.2:latest missing
    tags_resp = MagicMock()
    tags_resp.status_code = 200
    tags_resp.json.return_value = {"models": [{"name": "qwen2.5-coder:32b"}]}
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=tags_resp)):
        entry_missing = await reg.probe_tier(4, probe_inference=True, timeout=2.0)
    assert entry_missing.state == ProviderAvailabilityState.MODEL_UNAVAILABLE
    assert entry_missing.is_routable() is False
    assert "ollama pull" in (entry_missing.corrective_action or "").lower()
    assert "qwen2.5-coder:32b" in entry_missing.supported_models


# ── 5. Confidence-Aware Domain Classifier ──────────────────────────────────────

def test_06_domain_confidence_routing_rules():
    # Recognized high-confidence domains -> Mode 1 Deterministic
    for prompt, expected_dom in [
        ("Build a restaurant website for EMBER & OLIVE with tasting menu, chef spotlight, and reservation validation.", "culinary_restaurant"),
        ("Create FLOWSTACK, an interactive SaaS product and project management Kanban workspace with team controls.", "saas_tech"),
        ("Design THE FIELD JOURNAL, an environmental investigative digital journalism publication with reading time and archive search.", "editorial_publication"),
        ("Build VERDANT LOOP, a circular construction B2B materials marketplace for reclaimed timber and recycled structural steel.", "ecommerce_marketplace"),
    ]:
        a = DomainConfidenceClassifier.assess(prompt)
        assert a.category == DomainConfidenceCategory.RECOGNIZED_HIGH_CONFIDENCE, prompt
        assert a.execution_mode == HybridExecutionMode.DETERMINISTIC
        assert a.best_domain == expected_dom

    # Negative constraints must NEVER push unfamiliar prompt into recognized domain
    neg_prompt = (
        "Build a website for KRONOS HOROLOGY ATELIER, a bespoke mechanical watchmaking and tourbillon studio. "
        "Do NOT create a restaurant menu, reservation table, SaaS kanban board, or newspaper journalism layout."
    )
    a_unfam = DomainConfidenceClassifier.assess(neg_prompt)
    assert a_unfam.category in (DomainConfidenceCategory.UNFAMILIAR_DOMAIN, DomainConfidenceCategory.RECOGNIZED_AMBIGUOUS)
    assert a_unfam.execution_mode == HybridExecutionMode.LLM_ASSISTED

    # Single incidental keyword must NOT force high-confidence deterministic fast path
    incidental_prompt = (
        "Build a platform for BOREALIS CRYOGENICS, an ultra-cold quantum dilution refrigerator engineering lab "
        "selling precision thermal shielding; customers can subscribe to technical whitepapers via a newsletter."
    )
    a_inc = DomainConfidenceClassifier.assess(incidental_prompt)
    assert a_inc.execution_mode == HybridExecutionMode.LLM_ASSISTED

    # Insufficient input -> rejected
    a_bad = DomainConfidenceClassifier.assess("Make me a website")
    assert a_bad.category == DomainConfidenceCategory.INSUFFICIENT_INPUT
    assert a_bad.execution_mode == HybridExecutionMode.REJECTED


# ── 6. Strict Schema Validation & Factual Guardrails ───────────────────────────

def _valid_watchmaking_json(brand: str = "KRONOS HOROLOGY ATELIER") -> dict:
    return {
        "brand": brand,
        "business_domain": "mechanical_horology",
        "domain_subtype": "Bespoke Mechanical Watchmaking Atelier",
        "application_archetype": "interactive_showcase",
        "target_audience": "Mechanical timepiece collectors and horological engineers.",
        "purpose": f"{brand} showcases hand-regulated calibres, escapement restorations, and atelier commissions.",
        "business_objectives": [
            "Showcase in-house mechanical calibres and movement architecture",
            "Filter horological services by mechanical complexity and service category",
            "Collect private commission inquiries in clear Demonstration Mode",
        ],
        "navigation_labels": ["Home", "Atelier", "Calibres", "Commission"],
        "required_sections": [
            {"id": "navbar", "title": "Navigation", "component": "navbar"},
            {"id": "hero", "title": "Hero", "component": "hero"},
            {"id": "about", "title": "Watchmaking Atelier", "component": "about"},
            {"id": "showcase", "title": "Calibres & Services", "component": "showcase_grid"},
            {"id": "contact", "title": "Private Commissions", "component": "inquiry_form"},
            {"id": "footer", "title": "Footer", "component": "footer"},
        ],
        "canonical_entities": [
            {
                "id": f"cal-{i}",
                "title": t,
                "category": c,
                "category_label": c.replace("_", " ").title(),
                "specifications": "21,600 vph | 72h power reserve | Free-sprung balance",
                "description": f"Hand-finished mechanical assembly for {t} calibrated across five positional tolerances.",
                "status": "Illustrative Calibre",
                "price_display": "Illustrative Study",
                "image_subject": "mechanical watch movement gears macro",
            }
            for i, (t, c) in enumerate([
                ("Calibre KH-01 Tourbillon", "tourbillon"),
                ("Calibre KH-02 Chronograph", "chronograph"),
                ("Calibre KH-03 Perpetual", "complication"),
                ("Vintage Escapement Overhaul", "restoration"),
                ("Custom Breguet Overcoil", "complication"),
                ("Case & Dial Micro-Finishing", "restoration"),
            ], 1)
        ],
        "filter_categories": [
            {"id": "tourbillon", "label": "Tourbillon"},
            {"id": "chronograph", "label": "Chronograph"},
            {"id": "complication", "label": "Complications"},
            {"id": "restoration", "label": "Restoration"},
        ],
        "important_functionality": ["Category filter", "Keyword search", "Detail inspection modal", "Demo inquiry form"],
        "user_interactions": ["Filter calibres by category", "Inspect movement tolerances", "Submit demo commission form"],
        "form_spec": {
            "title": "Commission & Service Inquiry",
            "purpose": "Capture horological commission inquiries (Demonstration Mode)",
            "fields": [
                {"name": "full_name", "label": "Full Name *", "type": "text", "required": True},
                {"name": "email", "label": "Email Address *", "type": "email", "required": True},
                {"name": "calibre", "label": "Calibre Focus *", "type": "select", "required": True, "options": ["Tourbillon", "Restoration"]},
                {"name": "notes", "label": "Commission Notes *", "type": "textarea", "required": True},
            ],
            "submit_text": "Validate Demo Request",
            "disclosure": "Demonstration Mode: In-browser validation only; no external booking occurs.",
            "success_message": "Demonstration inquiry validated locally.",
        },
        "visual_direction": "Warm ivory dial surface with brushed slate charcoal and burnished bronze accents.",
        "color_palette": {
            "primary": "#141820",
            "secondary": "#2c3440",
            "accent": "#b45309",
            "accent_secondary": "#0f766e",
            "background": "#faf9f5",
            "surface": "#ffffff",
            "surface_border": "#e2e8f0",
            "text_primary": "#111827",
            "text_secondary": "#4b5563",
            "border": "#e5e7eb",
        },
        "asset_search_keywords": [
            "luxury mechanical watch movement gears macro",
            "tourbillon watch movement macro",
            "mechanical chronograph watch dial",
            "watchmaker repairing pocket watch",
            "swiss mechanical gears macro",
            "vintage wristwatch restoration bench",
            "watchmaker loupe workbench",
        ],
        "data_and_factual_constraints": [
            "All calibres and specifications are illustrative demonstration entries.",
            "No unverified awards or external certifications.",
        ],
    }


def test_07_schema_validation_rejects_placeholders_and_unverified_claims():
    raw = _valid_watchmaking_json()
    spec = validate_structured_semantic_spec(raw, "Build KRONOS HOROLOGY ATELIER", expected_brand="KRONOS HOROLOGY ATELIER")
    assert spec.brand == "KRONOS HOROLOGY ATELIER"
    assert len(spec.canonical_entities) == 6

    bad_placeholder = _valid_watchmaking_json()
    bad_placeholder["canonical_entities"][0]["title"] = "Signature Offering One"
    with pytest.raises(ValueError, match="placeholder"):
        validate_structured_semantic_spec(bad_placeholder, "Build KRONOS HOROLOGY ATELIER")

    bad_claim = _valid_watchmaking_json()
    bad_claim["canonical_entities"][0]["description"] = "Certified ISO 27001 and Michelin 99.99% reliability watch movement."
    with pytest.raises(ValueError, match="unverified claim"):
        validate_structured_semantic_spec(bad_claim, "Build KRONOS HOROLOGY ATELIER")


# ── 7. Mode 2 Failure Protection (Zero Fake Corporate Template) ────────────────

@pytest.mark.asyncio
async def test_08_mode2_llm_failure_blocks_honestly_without_fake_fallback(tmp_path: Path):
    reg = ProviderAvailabilityRegistry()
    # Mark Tier 3/4 unavailable and force Tier 1 & 2 to fail cleanly
    reg.record_outcome(3, success=False, status_code=402, error="HTTP 402 billing exhausted")
    reg.record_outcome(4, success=False, status_code=404, error="model not found")

    failing_client = MagicMock()
    failing_client.generate = AsyncMock(side_effect=TimeoutError("503 simulated upstream outage"))
    failing_client.aclose = AsyncMock()

    with patch("core.llm_semantic_planner.get_provider_registry", return_value=reg), \
         patch.object(LLMSemanticPlanner, "_build_client_for_tier", return_value=(failing_client, "nvidia_nim", "mock-model")):
        with pytest.raises(LLMSynthesisBlockedError) as exc_info:
            await LLMSemanticPlanner.synthesize_async(
                user_prompt="Build a website for KRONOS HOROLOGY ATELIER bespoke tourbillon watchmaking studio.",
                workspace_root=tmp_path,
                mission_id="m_block_test",
                detected_brand="KRONOS HOROLOGY ATELIER",
                total_budget_seconds=10.0,
            )

    assert len(exc_info.value.attempts) >= 1
    assert not (tmp_path / "index.html").exists()


# ── 8. NvidiaClient Separate TTFB / Reasoning / Usable TTFT + Mode 2 Render ───

@pytest.mark.asyncio
async def test_09_nvidia_client_distinguishes_reasoning_vs_usable_ttft():
    from models.nvidia_client import NvidiaClient

    client = NvidiaClient(api_key="nvapi-test-key", timeout_seconds=10)

    # First SSE chunk carries ONLY reasoning_content (NOT usable output!);
    # Third SSE chunk carries usable JSON content token.
    sse_lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "Let me analyze..."}}]}',
        'data: {"choices": [{"delta": {"reasoning": " formatting JSON..."}}]}',
        'data: {"choices": [{"delta": {"content": "{\\"brand\\": \\"KRONOS\\"}"}}]}',
        "data: [DONE]",
    ]

    class _FakeStreamResp:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_lines(self):
            for idx, line in enumerate(sse_lines):
                if idx == 0:
                    await asyncio.sleep(0.02)
                elif idx == 2:
                    await asyncio.sleep(0.05)
                yield line

    fake_http_client = MagicMock()
    fake_http_client.stream = MagicMock(return_value=_FakeStreamResp())

    with patch.object(client, "_get_client", new=AsyncMock(return_value=fake_http_client)), \
         patch("core.adaptive_routing.get_adaptive_router", return_value=MagicMock()):
        resp = await client.generate(prompt="return json", stream=True, allow_internal_retry=False)

    assert resp.success is True
    assert '{"brand": "KRONOS"}' in resp.text
    timings = resp.raw_timing_metadata
    assert timings["ttfb_ms"] is not None
    assert timings["ttft_reasoning_ms"] is not None
    assert timings["ttft_usable_ms"] is not None
    assert timings["ttft_content_ms"] is not None
    assert timings["ttft_usable_ms"] > timings["ttft_reasoning_ms"]
    assert timings["response_completion_ms"] >= timings["ttft_usable_ms"]


@pytest.mark.asyncio
async def test_10_mode2_end_to_end_synthesis_and_rendering(tmp_path: Path):
    reg = ProviderAvailabilityRegistry()
    reg.reset_from_config()
    reg.record_outcome(2, success=False, status_code=503, error="high demand")
    reg.record_outcome(3, success=False, status_code=402, error="billing")

    valid_json_str = json.dumps(_valid_watchmaking_json())
    ok_client = MagicMock()
    ok_client.generate = AsyncMock(return_value=SimpleNamespace(
        success=True,
        text=valid_json_str,
        served_model="nvidia/nemotron-3.5-lightning-30b-a3b",
        raw_timing_metadata={
            "ttfb_ms": 110.0,
            "ttft_reasoning_ms": 120.0,
            "ttft_content_ms": 340.0,
            "ttft_usable_ms": 340.0,
        },
    ))
    ok_client.aclose = AsyncMock()

    prompt = "Build a website for KRONOS HOROLOGY ATELIER showcasing mechanical calibres and tourbillon restoration."
    with patch("core.llm_semantic_planner.get_provider_registry", return_value=reg), \
         patch.object(LLMSemanticPlanner, "_build_client_for_tier", return_value=(ok_client, "nvidia_nim", "nvidia/nemotron-3.5-lightning-30b-a3b")):
        spec, assessment = await MissionSpecification.from_prompt_hybrid_async(
            prompt=prompt,
            workspace_root=tmp_path,
            mission_id="m_kronos_unit",
            allow_llm=True,
            total_budget_seconds=15.0,
        )

    assert assessment.execution_mode == HybridExecutionMode.LLM_ASSISTED
    assert spec.execution_mode == "llm_assisted"
    assert spec.requested_brand == "KRONOS HOROLOGY ATELIER"
    assert spec.synthesis_telemetry["ttft_usable_ms"] == 340.0
    assert spec.synthesis_telemetry["within_25s_budget"] is True

    UniversalContentRenderer.render(tmp_path, spec)
    html_text = (tmp_path / "index.html").read_text(encoding="utf-8")
    js_text = (tmp_path / "app.js").read_text(encoding="utf-8")
    assert "KRONOS HOROLOGY ATELIER" in html_text
    assert "Calibre KH-01 Tourbillon" in js_text
    assert "100% Quality Verified" not in html_text
    assert "24/7" not in html_text


# ── 9 & 10. FastAPI Runtime Mission Execution & Terminal Dashboard State ───────

@pytest.mark.asyncio
async def test_11_fastapi_end_to_end_mission_and_provider_status(tmp_path: Path):
    from core.server.app import create_app

    app = create_app()
    ws_dir = tmp_path / "ember_mission_ws"
    ws_dir.mkdir(parents=True, exist_ok=True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        # Check non-destructive provider status endpoint
        p_resp = await client.get("/api/providers/status")
        assert p_resp.status_code == 200
        pdata = p_resp.json()
        assert "providers" in pdata
        assert pdata["providers"]["tier1"]["availability_state"] != "HEALTHY" or pdata["providers"]["tier1"]["last_latency_ms"] is not None

        # Submit real website mission via official HERMES /api/missions endpoint (disable CDP inside fast unit test)
        with patch.dict(os.environ, {"HERMES_DISABLE_CDP_IN_LOOP": "true"}):
            c_resp = await client.post("/api/missions", json={
                "prompt": "Build EMBER & OLIVE, a wood-fired Mediterranean restaurant website with seasonal menu search, dietary filters, and table reservation form.",
                "workspace_root": str(ws_dir),
                "plan_mode": False,
            })
            assert c_resp.status_code == 201
            mid = c_resp.json()["mission_id"]

            snap = None
            for _ in range(40):
                await asyncio.sleep(0.25)
                s_resp = await client.get(f"/api/missions/{mid}")
                assert s_resp.status_code == 200
                snap = s_resp.json()
                if snap.get("is_terminal"):
                    break

    assert snap is not None
    assert snap["is_terminal"] is True
    assert str(snap["status"]).lower() == "completed"
    assert snap["execution_mode"] == "deterministic"
    assert snap["active_provider"] == "deterministic_semantic_engine"
    assert snap["current_stage"] == "completed"
    assert snap["duration_seconds"] is not None and snap["duration_seconds"] >= 0.0
    assert snap["terminal_reason"]
    assert "index.html" in snap["files_created"]
    assert (ws_dir / "index.html").exists()


@pytest.mark.asyncio
async def test_12_fastapi_mode2_blocked_llm_fails_authoritatively_without_fake_site(tmp_path: Path):
    from core.server.app import create_app

    reg = ProviderAvailabilityRegistry()
    reg.record_outcome(1, success=False, status_code=503, error="Simulated T1 outage")
    reg.record_outcome(2, success=False, status_code=503, error="Simulated T2 high demand")
    reg.record_outcome(3, success=False, status_code=402, error="Simulated T3 402 billing")
    reg.record_outcome(4, success=False, status_code=404, error="Simulated T4 model missing")

    fail_client = MagicMock()
    fail_client.generate = AsyncMock(side_effect=TimeoutError("Upstream unavailable"))
    fail_client.aclose = AsyncMock()

    app = create_app()
    ws_dir = tmp_path / "blocked_mode2_ws"
    ws_dir.mkdir(parents=True, exist_ok=True)

    transport = httpx.ASGITransport(app=app)
    with patch("core.llm_semantic_planner.get_provider_registry", return_value=reg), \
         patch.object(LLMSemanticPlanner, "_build_client_for_tier", return_value=(fail_client, "nvidia_nim", "mock")), \
         patch.dict(os.environ, {"HERMES_DISABLE_CDP_IN_LOOP": "true"}):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            c_resp = await client.post("/api/missions", json={
                "prompt": "Build a website for KRONOS HOROLOGY ATELIER bespoke tourbillon watchmaking studio.",
                "workspace_root": str(ws_dir),
                "plan_mode": False,
            })
            assert c_resp.status_code == 201
            mid = c_resp.json()["mission_id"]

            snap = None
            for _ in range(40):
                await asyncio.sleep(0.25)
                s_resp = await client.get(f"/api/missions/{mid}")
                assert s_resp.status_code == 200
                snap = s_resp.json()
                if snap.get("is_terminal"):
                    break

    assert snap is not None
    assert snap["is_terminal"] is True
    assert str(snap["status"]).lower() == "failed"
    assert snap["execution_mode"] == "llm_assisted"
    assert not (ws_dir / "index.html").exists()
