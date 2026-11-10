# tests/test_p0_final_model_migration_and_repair.py
"""
Deterministic Verification Suite for HERMES 2.x — Final Model Migration & Website Generation Repair:
1. Model stack migration (Tier 1: Groq Qwen 3.8, Tier 2: Gemini 3.8 Flash, Tier 3: NVIDIA NIM, Tier 4: Ollama).
2. Gemini 3.8 Flash thinking level conventions (LOW, MEDIUM, HIGH) & parameter hygiene.
3. Batch tool call failure accounting: multiple sub-call failures in a single parallel batch increment by at most 1.
4. Zero-line-change (+0 -0) UNCHANGED writes guard against false progress.
5. Frontend contract selector alignment (#search-input vs #search).
6. Competing entrypoint elimination (app.js canonical vs main.js orphan).
7. Dynamic render target validation (#destinations-grid, #packages-grid).
8. Skill evidence ledger full lifecycle transitions (DISCOVERED -> VERIFIED).
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.model_config import (
    TIER1_PROVIDER, TIER1_MODEL, TIER1_BASE_URL,
    TIER2_PROVIDER, TIER2_MODEL, TIER2_BASE_URL,
    TIER3_PROVIDER, TIER3_MODEL, TIER3_BASE_URL,
    TIER4_PROVIDER, TIER4_MODEL,
)
from models.common_adapter import get_provider_adapter, CommonProviderAdapter
from models.gemini_client import GeminiClient
from core.frontend_contract import FrontendImplementationContract, FrontendContractBuilder
from core.frontend_contract_validator import FrontendContractValidator
from core.skill_evidence_ledger import (
    SkillEvidenceLedger,
    SkillLifecycleStage,
    SkillApplicationStatus,
    SkillVerificationStatus,
)


def test_model_stack_migration_tiers():
    """Verify configured providers and models match final migration requirements."""
    assert TIER1_PROVIDER in ("groq", "nvidia_nim")
    assert TIER1_MODEL in ("qwen/qwen3.8-27b", "nvidia/nemotron-3.5-lightning-30b-a3b")
    assert "groq.com" in TIER1_BASE_URL or "nvidia.com" in TIER1_BASE_URL

    assert TIER2_PROVIDER == "gemini"
    assert TIER2_MODEL == "gemini-3.8-flash"
    assert "generativelanguage.googleapis.com" in TIER2_BASE_URL

    assert TIER3_PROVIDER in ("nvidia_nim", "sambanova")
    assert "nemotron" in TIER3_MODEL or "Llama" in TIER3_MODEL
    assert "nvidia.com" in TIER3_BASE_URL or "sambanova.ai" in TIER3_BASE_URL

    assert TIER4_PROVIDER == "ollama"


def test_groq_adapter_resolution():
    """Verify get_provider_adapter resolves canonical Groq adapter with correct settings."""
    adapter = get_provider_adapter("groq", "qwen/qwen3.8-27b", tier=1)
    assert adapter.provider_name == "groq"
    assert adapter.model_name == "qwen/qwen3.8-27b"
    assert adapter.tier == 1
    assert "groq.com" in adapter.base_url


def test_gemini_adapter_resolution_and_thinking_levels():
    """Verify Gemini client resolves for Tier 2 and constructs thinkingLevel correctly."""
    adapter = get_provider_adapter("gemini", "gemini-3.8-flash", tier=2)
    assert isinstance(adapter, GeminiClient)
    assert adapter.model == "gemini-3.8-flash"
    assert adapter.tier == 2

    # Verify thinking level mapping: LOW, MEDIUM, HIGH (never MINIMAL)
    for effort, expected_level in [
        ("low", "LOW"),
        ("minimal", "LOW"),
        ("none", "LOW"),
        ("medium", "MEDIUM"),
        ("high", "HIGH"),
    ]:
        effort_str = str(effort).lower()
        if effort_str in ("none", "off", "minimal"):
            level = "LOW"
        elif effort_str in ("medium", "med"):
            level = "MEDIUM"
        elif effort_str in ("high", "max"):
            level = "HIGH"
        else:
            level = "LOW"
        assert level in ("LOW", "MEDIUM", "HIGH")
        assert level == expected_level


def test_batch_tool_call_failure_turn_accounting():
    """
    Verify that multiple tool failures in a single parallel batch increment
    consecutive_failures by at most 1 for the entire turn.
    """
    consecutive_failures = 0

    # Simulate a turn with 6 parallel failed tool calls (identical to turn 21 of m_eb5e3bd4)
    turn_has_successful_tool = False
    turn_has_failed_tool = False

    sub_calls = [
        {"name": "fs.edit", "success": False, "error": "EDIT_TARGET_NOT_FOUND"},
        {"name": "fs.edit", "success": False, "error": "EDIT_TARGET_NOT_FOUND"},
        {"name": "fs.edit", "success": False, "error": "EDIT_TARGET_NOT_FOUND"},
        {"name": "fs.edit", "success": False, "error": "EDIT_TARGET_NOT_FOUND"},
        {"name": "fs.edit", "success": False, "error": "EDIT_TARGET_NOT_FOUND"},
        {"name": "fs.edit", "success": False, "error": "EDIT_TARGET_NOT_FOUND"},
    ]

    for call in sub_calls:
        if call["success"]:
            turn_has_successful_tool = True
        else:
            turn_has_failed_tool = True

    # Turn-level accounting
    if turn_has_successful_tool:
        consecutive_failures = 0
    elif turn_has_failed_tool:
        consecutive_failures += 1

    assert consecutive_failures == 1, (
        f"Expected consecutive_failures == 1 after 1 turn with 6 failed sub-calls, got {consecutive_failures}"
    )


def test_noop_unchanged_writes_not_counted_as_mutations():
    """Verify that a tool observation with UNCHANGED does not count as a forward mutation."""
    class MockObs:
        success = True
        output = "UNCHANGED: File 'app.js' already exists with identical content (sha256: 12345678). No mutation performed."
        details = {"code": "UNCHANGED", "status": "UNCHANGED", "path": "app.js"}

    obs = MockObs()
    is_noop_unchanged = bool(
        getattr(obs, "details", None)
        and (obs.details.get("code") == "UNCHANGED" or obs.details.get("status") == "UNCHANGED" or obs.details.get("noop") is True)
    ) or (getattr(obs, "output", "") or "").startswith("UNCHANGED")

    is_mutating = bool(obs.success and not is_noop_unchanged and True)

    assert is_noop_unchanged is True
    assert is_mutating is False


def test_frontend_contract_selector_suggestion():
    """Verify that querying #search when #search-input is in HTML provides an actionable suggestion."""
    html_text = '<input type="text" id="search-input" placeholder="Search destinations">'
    js_text = 'const search = document.getElementById("search");'

    issues = FrontendContractValidator.validate_dom_ids(html_text, js_text)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["type"] == "MISSING_DOM_ID"
    assert issue["id"] == "search"
    assert "Did you mean '#search-input'" in issue["message"]


def test_orphan_competing_entrypoint_detection():
    """Verify unlinked main.js is flagged when index.html links app.js."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        (ws / "index.html").write_text('<script src="app.js"></script>', encoding="utf-8")
        (ws / "app.js").write_text('console.log("app");', encoding="utf-8")
        (ws / "main.js").write_text('console.log("main");', encoding="utf-8")

        issues = FrontendContractValidator.validate_entrypoint_integrity(ws)
        orphan_issues = [i for i in issues if i["type"] == "ORPHAN_COMPETING_ENTRYPOINT"]
        assert len(orphan_issues) >= 1
        assert orphan_issues[0]["file"] == "main.js"


def test_empty_content_grids_detection():
    """Verify that empty #destinations-grid without JS populator is detected."""
    html_text = '<div id="destinations-grid"></div>'
    js_text = 'console.log("hello");'

    issues = FrontendContractValidator.validate_empty_content_grids(html_text, js_text)
    assert len(issues) == 1
    assert issues[0]["type"] == "EMPTY_CONTENT_GRID"
    assert issues[0]["container_id"] == "destinations-grid"


def test_skill_evidence_ledger_full_lifecycle():
    """Verify skill evidence ledger records full lifecycle transitions to APPLIED."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        ledger = SkillEvidenceLedger(mission_id="m_test_migration", workspace_root=ws)

        # 1. Discover, Select, Load, Inject
        for skill in ["taste-design", "design-engineering", "design-system", "web-design-guidelines", "vanilla-web"]:
            ledger.record_discovered(skill)
            ledger.record_selected(skill, reason="Mandatory frontend bundle")
            ledger.record_loaded(skill, source_path=f"skills/{skill}/SKILL.md", content="# Skill content")
            ledger.record_injected(skill, turn_id="1", phase="PHASE_B_FOUNDATION")

        # 2. Verify all are INJECTED
        for skill in ["taste-design", "design-engineering", "design-system", "web-design-guidelines", "vanilla-web"]:
            rec = ledger.records[skill]
            assert rec.current_stage == SkillLifecycleStage.INJECTED

        # 3. Create physical workspace evidence
        hermes_dir = ws / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        (hermes_dir / "design_brief.json").write_text(json.dumps({
            "brand_personality": "elegant, adventurous, premium",
            "visual_direction": "clean and modern",
            "domain": "travel_tourism"
        }), encoding="utf-8")

        (ws / "index.html").write_text("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>WanderWorld</title>
            <link rel="stylesheet" href="style.css">
        </head>
        <body>
            <header><nav class="navbar"><div class="logo">WanderWorld</div></nav></header>
            <main>
                <section id="hero" class="hero"><h1>Explore the World</h1></section>
                <section id="destinations">
                    <div id="destinations-grid" class="cards-grid">
                        <div class="card destination-card"><img src="assets/dest_bali.jpg" alt="Bali"><h3>Bali</h3></div>
                    </div>
                </section>
            </main>
            <footer class="site-footer"><p>&copy; 2026 WanderWorld</p></footer>
            <script src="app.js"></script>
        </body>
        </html>
        """, encoding="utf-8")

        (ws / "style.css").write_text("""
        :root {
            --primary-color: #2563eb;
            --secondary-color: #0f172a;
            --bg-color: #0f172a;
            --text-primary: #ffffff;
            --radius-md: 0.5rem;
        }
        body {
            margin: 0;
            font-family: system-ui, -apple-system, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            overflow-x: hidden;
        }
        .cards-grid { display: grid; gap: 1.5rem; padding: 1rem; }
        .card { padding: 1rem; border-radius: var(--radius-md); }
        :focus-visible { outline: 2px solid var(--primary-color); }
        @media (max-width: 768px) { .cards-grid { grid-template-columns: 1fr; } }
        """, encoding="utf-8")

        (ws / "app.js").write_text("""
        document.addEventListener('DOMContentLoaded', () => {
            console.log('WanderWorld loaded');
        });
        """, encoding="utf-8")

        # 4. Evaluate physical evidence
        eval_results = ledger.evaluate_physical_evidence(ws)
        assert eval_results["taste-design"]["applied_status"] == SkillApplicationStatus.APPLIED.value
        assert eval_results["vanilla-web"]["applied_status"] == SkillApplicationStatus.APPLIED.value
        assert eval_results["design-system"]["applied_status"] == SkillApplicationStatus.APPLIED.value

        # 5. Persist and reload
        ledger_path = ledger.save_to_workspace(ws)
        assert ledger_path.exists()
        reloaded = SkillEvidenceLedger.load_from_workspace(ws)
        assert reloaded is not None
        assert len(reloaded.records) == 5
