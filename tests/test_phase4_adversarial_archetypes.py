"""
Phase 4 Adversarial Qualification Tests:
- Benchmark A: Restaurant Reservation Website (EMBER & OLIVE)
- Benchmark B: B2B SaaS Project Management & Kanban Dashboard (FLOWSTACK)
- Benchmark C: Digital Editorial & Journalism Publication (THE FIELD JOURNAL)
- Runtime Error Classification (HTTP 402 & Missing Model 404)
- Non-Website Prompt Isolation (WebsiteMvpGate)
"""

import json
import re
from pathlib import Path

from core.agent_loop.mvp_gate import WebsiteMvpGate
from core.design_intelligence import DesignBriefGenerator, detect_brand_name
from core.foundation_scaffolder import seed_initial_foundation_files
from core.frontend_contract import FrontendContractBuilder
from core.mission_spec import MissionSpecification
from core.runtime_failover import ErrorClassification, classify_runtime_error
from core.universal_renderer import UniversalContentRenderer
from models.common_adapter import classify_provider_error


PROMPT_EMBER = (
    "Build a premium modern restaurant reservation website for EMBER & OLIVE. "
    "Include editorial food photography, restaurant identity and chef introduction, "
    "menu categories and dish cards, menu search and category filters, "
    "reservation form with date, time and party-size selection, reservation validation, "
    "and location and opening-hours sections. "
    "Clearly label demonstration/sample data and ensure the reservation form discloses demonstration mode."
)

PROMPT_FLOWSTACK = (
    "Create a professional B2B project-management SaaS product website for FLOWSTACK. "
    "Include product landing page, interactive Kanban workspace with draggable task cards, "
    "project status and progress metrics, team management interface, "
    "pricing comparison with interactive monthly/annual billing switcher, and product demonstration section. "
    "Clearly label sample workspace/demo billing data and disclose demonstration mode."
)

PROMPT_JOURNAL = (
    "Build a premium digital editorial and journalism publication website for THE FIELD JOURNAL "
    "focused on science, technology, environment and innovation. "
    "Include editorial homepage, featured stories, article categories, search, article detail views, "
    "editorial author information, reading-time indicators, related stories, and newsletter subscription validation. "
    "Label sample editorial profiles and disclose newsletter demonstration mode."
)


def test_p4_failover_error_classification_402_and_missing_model():
    # HTTP 402 from SambaNova (balance_units: 0 / PAYMENT_METHOD_REQUIRED) must fail fast non-transiently
    err_cls, is_transient, _ = classify_runtime_error(
        response_text="HTTP 402 Payment Required: balance_units: 0 PAYMENT_METHOD_REQUIRED",
        status_code=402,
    )
    assert err_cls == ErrorClassification.AUTHENTICATION_ERROR
    assert is_transient is False

    # Ollama missing model must classify as invalid model config, non-transient
    err_cls2, is_transient2, _ = classify_runtime_error(
        response_text="HTTP 404: model 'llama3.2:latest' not found",
        status_code=404,
    )
    assert err_cls2 == ErrorClassification.INVALID_MODEL_CONFIGURATION
    assert is_transient2 is False

    # Common adapter HTTP 402 classification must also mark non-transient
    info_402 = classify_provider_error(status_code=402, response_body="balance_units: 0")
    assert info_402.is_transient is False
    assert info_402.is_quota_exhausted or info_402.is_unauthorized


def test_p4_non_website_prompt_isolation(tmp_path: Path):
    py_prompt = "Create hello.py that prints Hello World from CLI and exit."
    assert WebsiteMvpGate.is_website_mission(py_prompt, tmp_path) is False
    assert WebsiteMvpGate.is_website_mission(PROMPT_EMBER, tmp_path) is True
    assert WebsiteMvpGate.is_website_mission(PROMPT_FLOWSTACK, tmp_path) is True
    assert WebsiteMvpGate.is_website_mission(PROMPT_JOURNAL, tmp_path) is True


def test_p4_brand_domain_archetype_extraction():
    assert detect_brand_name(PROMPT_EMBER) == "EMBER & OLIVE"
    assert DesignBriefGenerator.detect_domain(PROMPT_EMBER) == "culinary_restaurant"
    assert DesignBriefGenerator.detect_archetype(PROMPT_EMBER) == "culinary_restaurant"

    assert detect_brand_name(PROMPT_FLOWSTACK) == "FLOWSTACK"
    assert DesignBriefGenerator.detect_domain(PROMPT_FLOWSTACK) == "saas_tech"
    assert DesignBriefGenerator.detect_archetype(PROMPT_FLOWSTACK) == "saas_product"

    assert detect_brand_name(PROMPT_JOURNAL) == "THE FIELD JOURNAL"
    assert DesignBriefGenerator.detect_domain(PROMPT_JOURNAL) == "editorial_publication"
    assert DesignBriefGenerator.detect_archetype(PROMPT_JOURNAL) == "editorial_publication"


def test_p4_ember_olive_restaurant_generation_and_honesty(tmp_path: Path):
    ws = tmp_path / "ember"
    ws.mkdir()
    spec = MissionSpecification.from_prompt(PROMPT_EMBER, ws)
    spec.persist(ws)
    brief = DesignBriefGenerator.generate_brief(PROMPT_EMBER, spec.business_domain)
    brief.persist_artifacts(ws)
    contract = FrontendContractBuilder.build_initial_contract(PROMPT_EMBER, "p4-ember", design_brief=brief)
    (ws / ".hermes" / "frontend_contract.json").write_text(json.dumps(contract.to_dict(), indent=2), encoding="utf-8")
    seed_initial_foundation_files(ws, prompt=PROMPT_EMBER)
    UniversalContentRenderer.render(ws, spec)

    html = (ws / "index.html").read_text(encoding="utf-8")
    js = (ws / "app.js").read_text(encoding="utf-8")
    html_lower = html.lower()

    assert "EMBER & OLIVE" in html
    for leak in ("saffron", "wanderworld", "verdant loop", "northstar", "skytrace", "sparkfield"):
        assert not re.search(rf"\b{re.escape(leak)}\b", html_lower), f"Unexpected leak: {leak}"

    assert 'id="about"' in html
    assert 'id="menu"' in html
    assert 'id="location-hours"' in html
    assert 'id="inquiry-form"' in html
    assert 'type="date"' in html
    assert 'name="reservation_time"' in html
    assert 'name="party_size"' in html
    assert "Demonstration Mode" in html
    assert "please select today or a future date" in js.lower()
    for fake in ("michelin", "yelp", "google reviews", "4.9 stars"):
        assert fake not in html_lower


def test_p4_flowstack_saas_kanban_team_billing_and_no_fake_compliance(tmp_path: Path):
    ws = tmp_path / "flowstack"
    ws.mkdir()
    spec = MissionSpecification.from_prompt(PROMPT_FLOWSTACK, ws)
    spec.persist(ws)
    brief = DesignBriefGenerator.generate_brief(PROMPT_FLOWSTACK, spec.business_domain)
    brief.persist_artifacts(ws)
    contract = FrontendContractBuilder.build_initial_contract(PROMPT_FLOWSTACK, "p4-flowstack", design_brief=brief)
    (ws / ".hermes" / "frontend_contract.json").write_text(json.dumps(contract.to_dict(), indent=2), encoding="utf-8")
    seed_initial_foundation_files(ws, prompt=PROMPT_FLOWSTACK)
    UniversalContentRenderer.render(ws, spec)

    html = (ws / "index.html").read_text(encoding="utf-8")
    js = (ws / "app.js").read_text(encoding="utf-8")
    combined_lower = (html + "\n" + js).lower()

    assert "FLOWSTACK" in html
    assert 'id="demo-preview"' in html
    assert 'id="view-kanban"' in html
    assert 'draggable="true"' in html
    assert 'id="add-task-btn"' in html
    assert 'id="kanban-progress-bar"' in html
    assert 'id="team-management"' in html
    assert 'id="add-member-btn"' in html
    assert 'id="billing-toggle"' in html
    assert 'data-monthly="$29"' in html and 'data-annual="$23"' in html
    assert 'data-monthly="$79"' in html and 'data-annual="$63"' in html
    assert 'data-monthly="$199"' in html and 'data-annual="$159"' in html
    assert "plan comparison" in combined_lower
    assert "capability (illustrative comparison)" in combined_lower
    assert "recomputeKanbanStats" in js
    assert "addMemberBtn" in js

    for fake_claim in ("soc2", "hipaa", "iso 27001", "iso27001", "99.99%"):
        assert fake_claim not in combined_lower, f"Forbidden unverified claim leaked: {fake_claim}"


def test_p4_field_journal_editorial_features_and_honesty(tmp_path: Path):
    ws = tmp_path / "journal"
    ws.mkdir()
    spec = MissionSpecification.from_prompt(PROMPT_JOURNAL, ws)
    spec.persist(ws)
    brief = DesignBriefGenerator.generate_brief(PROMPT_JOURNAL, spec.business_domain)
    brief.persist_artifacts(ws)
    contract = FrontendContractBuilder.build_initial_contract(PROMPT_JOURNAL, "p4-journal", design_brief=brief)
    (ws / ".hermes" / "frontend_contract.json").write_text(json.dumps(contract.to_dict(), indent=2), encoding="utf-8")
    seed_initial_foundation_files(ws, prompt=PROMPT_JOURNAL)
    UniversalContentRenderer.render(ws, spec)

    html = (ws / "index.html").read_text(encoding="utf-8")
    js = (ws / "app.js").read_text(encoding="utf-8")
    combined_lower = (html + "\n" + js).lower()

    assert "THE FIELD JOURNAL" in html
    assert 'id="featured-story"' in html
    assert 'id="btn-read-featured"' in html
    assert 'id="contributors"' in html
    assert 'id="articles"' in html
    for cat in ("science", "technology", "environment", "innovation"):
        assert cat in combined_lower
    assert "min read" in combined_lower
    assert "btn-related-story" in js
    assert "full_body" in js
    assert "sample" in combined_lower
    assert "demonstration" in combined_lower
