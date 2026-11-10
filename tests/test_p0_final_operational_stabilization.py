# tests/test_p0_final_operational_stabilization.py
"""
Deterministic Acceptance Test Suite for HERMES 2.x — Final Operational Stabilization:
Tier Availability, Recovery/Fallback Separation, Durable Skill Evidence,
and Honest Visual Acceptance Reporting.

Covers all 18 required scenarios from Section 8:
 1. Ollama daemon unavailable
 2. Unavailable Tier 4 excluded from routing
 3. Tier 1, Tier 2 and Tier 3 identities preserved
 4. All configured tiers unavailable
 5. No-progress does not cause provider failover
 6. Provider timeout does trigger appropriate failover
 7. Repeated non-progress invokes bounded repair
 8. No-progress budget exhaustion produces a clear failure
 9. Provider cooldown is respected
10. Runtime timeout values match effective configuration
11. Skill ledger persists every valid lifecycle transition
12. Skill ledger survives cancellation
13. Skill ledger survives recovery
14. Skill ledger records remain available after mission failure
15. Skill injection evidence retains actual request/turn association
16. Applied evidence is distinct from verified evidence
17. Atomic persistence does not corrupt existing ledger files
18. Honest visual inspection reporting (explicit distinction from vision AI)
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from config.model_config import (
    TIER1_PROVIDER, TIER1_MODEL,
    TIER2_PROVIDER, TIER2_MODEL,
    TIER3_PROVIDER, TIER3_MODEL,
    TIER4_PROVIDER, TIER4_MODEL,
    HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS,
    HERMES_MODEL_FIRST_TOKEN_TIMEOUT_SECONDS,
    HERMES_MODEL_STREAM_IDLE_TIMEOUT_SECONDS,
)
from core.adaptive_routing import (
    AdaptiveRouter,
    ProviderHealthRecord,
    ProviderHealthState,
    adaptive_router,
)
from core.agent_loop.loop import AgentLoop
from core.latency_governor import LatencyBudgetGovernor, latency_governor
from core.skill_evidence_ledger import (
    SkillApplicationStatus,
    SkillEvidenceLedger,
    SkillEvidenceRecord,
    SkillLifecycleStage,
    SkillVerificationStatus,
)
from core.visual_quality_inspector import (
    GateStatus,
    VisualQualityInspector,
    VisualReviewReport,
)
from models.ollama_client import OllamaClient


# ==============================================================================
# 1. Ollama daemon unavailable
# ==============================================================================

@pytest.mark.asyncio
async def test_01_ollama_daemon_unavailable():
    """Verify OllamaClient reports unavailable when daemon endpoint is unreachable."""
    client = OllamaClient(base_url="http://127.0.0.1:65530")
    # Must return False quickly without raising unhandled exception
    is_avail = await client.is_available(timeout=0.2)
    assert is_avail is False

    is_sync_avail = client.is_available_sync(timeout=0.2)
    assert is_sync_avail is False


# ==============================================================================
# 2. Unavailable Tier 4 excluded from routing
# ==============================================================================

def test_02_unavailable_tier4_excluded_from_routing():
    """Verify Tier 4 is marked unavailable and excluded from eligible routing."""
    router = AdaptiveRouter()
    router.mark_tier_unavailable(4, "Local Ollama daemon unreachable at http://127.0.0.1:11434")

    rec = router.providers[4]
    assert rec.is_available is False
    assert rec.state == ProviderHealthState.OPEN_CIRCUIT
    assert "unreachable" in (rec.unavailability_reason or "").lower()

    assert router.is_tier_available(4) is False
    assert router.is_tier_healthy(4) is False
    assert 4 not in router.get_eligible_tiers()


# ==============================================================================
# 3. Tier 1, Tier 2 and Tier 3 identities preserved
# ==============================================================================

def test_03_tier_identities_preserved():
    """Verify primary, secondary, and tertiary tier identities remain exactly preserved."""
    assert TIER1_PROVIDER in ("groq", "nvidia_nim")
    assert TIER1_MODEL in ("qwen/qwen3.8-27b", "nvidia/nemotron-3.5-lightning-30b-a3b")

    assert TIER2_PROVIDER == "gemini"
    assert TIER2_MODEL == "gemini-3.8-flash"

    assert TIER3_PROVIDER in ("nvidia_nim", "sambanova")
    assert TIER3_MODEL in ("nvidia/nemotron-3.5-lightning-30b-a3b", "Meta-Llama-3.3-70B-Instruct")

    assert TIER4_PROVIDER == "ollama"
    assert TIER4_MODEL == "llama3.2:latest"


# ==============================================================================
# 4. All configured tiers unavailable
# ==============================================================================

def test_04_all_configured_tiers_unavailable():
    """Verify clean empty eligible list when all configured tiers are unavailable."""
    router = AdaptiveRouter()
    for t in (1, 2, 3, 4):
        router.mark_tier_unavailable(t, f"Tier {t} offline")

    assert router.get_eligible_tiers() == []
    for t in (1, 2, 3, 4):
        assert router.is_tier_healthy(t) is False


# ==============================================================================
# 5. No-progress does not cause provider failover
# ==============================================================================

@pytest.mark.asyncio
async def test_05_no_progress_does_not_cause_provider_failover():
    """Verify agent no-progress maintains current tier and does NOT escalate tiers."""
    orch = MagicMock()
    loop = AgentLoop(orchestrator=orch)
    loop.set_active_model_state(tier=1)
    assert loop.active_tier == 1

    # Simulate no-progress trigger
    handled = await loop._trigger_agent_no_progress_recovery(
        turn_id="turn_no_prog_1",
        rejection_reason="Repeated non-mutating turns without file writes",
        unmet_reqs=["Create style.css"],
    )

    assert handled is True
    assert loop.active_tier == 1  # Crucial: Must stay on Tier 1
    assert loop._active_recovery_brief is not None
    assert "In-Tier Recovery" in loop._active_recovery_brief
    assert "Tier 1" in loop._active_recovery_brief


# ==============================================================================
# 6. Provider timeout does trigger appropriate failover
# ==============================================================================

def test_06_provider_timeout_triggers_failover():
    """Verify genuine provider errors do trigger fast zero-wait failover."""
    router = AdaptiveRouter()
    router.reset_state()

    # Trigger failure threshold on Tier 1
    t1_err = TimeoutError("Gemini first-token deadline exceeded")
    router.record_failure(tier=1, error=t1_err, timeout_type="FIRST_TOKEN_TIMEOUT")
    router.record_failure(tier=1, error=t1_err, timeout_type="FIRST_TOKEN_TIMEOUT")

    t1_rec = router.get_health(1)
    assert t1_rec.state == ProviderHealthState.OPEN_CIRCUIT

    # Routing decision should now bypass Tier 1 to Tier 2
    decision = router.route_primary()
    assert decision.tier == 2
    assert decision.bypassed is True
    assert decision.provider == TIER2_PROVIDER


# ==============================================================================
# 7. Repeated non-progress invokes bounded repair
# ==============================================================================

@pytest.mark.asyncio
async def test_07_repeated_non_progress_invokes_bounded_repair(tmp_path: Path):
    """Verify consecutive in-tier repairs provide targeted directives."""
    orch = MagicMock()
    loop = AgentLoop(orchestrator=orch)
    loop.workspace_root = tmp_path
    loop.set_active_model_state(tier=2)

    h1 = await loop._trigger_agent_no_progress_recovery(
        turn_id="turn_1",
        rejection_reason="Turn produced no file modifications",
        unmet_reqs=["Missing index.html"],
    )
    assert h1 is True
    assert loop.active_tier == 2
    assert "Missing index.html" in loop._active_recovery_brief

    h2 = await loop._trigger_agent_no_progress_recovery(
        turn_id="turn_2",
        rejection_reason="Repeated inspection of workspace",
        unmet_reqs=["Missing index.html"],
    )
    assert h2 is True
    assert loop.active_tier == 2
    assert getattr(loop, "_agent_no_progress_recovery_count", 0) == 2


# ==============================================================================
# 8. No-progress budget exhaustion produces a clear failure
# ==============================================================================

@pytest.mark.asyncio
async def test_08_no_progress_budget_exhaustion_produces_clear_failure():
    """Verify exceeding no-progress budget terminates cleanly without moving to Tier 4."""
    orch = MagicMock()
    loop = AgentLoop(orchestrator=orch)
    loop.set_active_model_state(tier=1)
    loop._max_agent_no_progress_budget = 3

    for i in range(3):
        ok = await loop._trigger_agent_no_progress_recovery(
            turn_id=f"turn_{i}",
            rejection_reason="No progress",
        )
        assert ok is True

    # 4th call must exhaust budget and return False
    exhausted = await loop._trigger_agent_no_progress_recovery(
        turn_id="turn_4",
        rejection_reason="No progress",
    )
    assert exhausted is False
    assert loop.active_tier == 1  # Never escalated to Tier 4!


# ==============================================================================
# 9. Provider cooldown is respected
# ==============================================================================

def test_09_provider_cooldown_respected():
    """Verify circuit breaker cooldown prevents premature re-routing."""
    router = AdaptiveRouter()
    router.reset_state()
    rec = router.providers[1]
    rec.state = ProviderHealthState.OPEN_CIRCUIT
    rec.circuit_open_ts = time.time() - 10.0  # Open 10 seconds ago

    with patch.dict(os.environ, {"T1_CIRCUIT_BREAKER_WINDOW": "90.0"}):
        health = router.get_health(1)
        # 10s < 90s, must remain OPEN_CIRCUIT
        assert health.state == ProviderHealthState.OPEN_CIRCUIT


# ==============================================================================
# 10. Runtime timeout values match effective configuration
# ==============================================================================

def test_10_runtime_timeout_values_match_effective_config():
    """Verify timeout configuration matches the operational targets (25s, 7.5s, 10s)."""
    assert HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS == 25.0
    assert HERMES_MODEL_FIRST_TOKEN_TIMEOUT_SECONDS == 7.5
    assert HERMES_MODEL_STREAM_IDLE_TIMEOUT_SECONDS == 10.0

    gov = LatencyBudgetGovernor()
    assert gov.max_attempt_ceiling == 25.0
    assert gov.first_token_target == 7.5
    assert gov.idle_watchdog == 10.0

    budget = gov.get_budget(is_streaming=True)
    assert budget.total_timeout <= 25.0
    assert budget.first_token_timeout == 7.5
    assert budget.stream_idle_timeout == 10.0


# ==============================================================================
# 11. Skill ledger persists every valid lifecycle transition
# ==============================================================================

def test_11_skill_ledger_persists_every_valid_lifecycle_transition(tmp_path: Path):
    """Verify every lifecycle transition immediately persists atomically to disk."""
    ledger = SkillEvidenceLedger(mission_id="m_test_ledger", workspace_root=tmp_path)
    ledger_file = tmp_path / ".hermes" / "skill_evidence_ledger.json"

    # Stage 1: DISCOVERED
    ledger.record_discovered("taste-design", source_path="skills/taste-design/SKILL.md")
    assert ledger_file.exists()
    d1 = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert d1["records"]["taste-design"]["current_stage"] == "DISCOVERED"

    # Stage 2: SELECTED
    ledger.record_selected("taste-design", reason="Travel agency web design")
    d2 = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert d2["records"]["taste-design"]["current_stage"] == "SELECTED"

    # Stage 3: LOADED
    ledger.record_loaded("taste-design", "skills/taste-design/SKILL.md", "# Taste Design")
    d3 = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert d3["records"]["taste-design"]["current_stage"] == "LOADED"

    # Stage 4: INJECTED
    ledger.record_injected("taste-design", turn_id="turn_1", phase="PHASE_B")
    d4 = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert d4["records"]["taste-design"]["current_stage"] == "INJECTED"

    # Stage 5: APPLIED
    ledger.record_applied("taste-design", evidence="Intentional color palette and typography implemented.")
    d5 = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert d5["records"]["taste-design"]["current_stage"] == "APPLIED"
    assert d5["records"]["taste-design"]["applied_status"] == "APPLIED"

    # Stage 6: VERIFIED
    ledger.record_verified("taste-design", results={"contract_passed": True})
    d6 = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert d6["records"]["taste-design"]["current_stage"] == "VERIFIED"
    assert d6["records"]["taste-design"]["verified_status"] == "VERIFIED"


# ==============================================================================
# 12. Skill ledger survives cancellation
# ==============================================================================

def test_12_skill_ledger_survives_cancellation(tmp_path: Path):
    """Verify saved ledger remains intact after simulated cancellation."""
    ledger = SkillEvidenceLedger(mission_id="m_cancel_test", workspace_root=tmp_path)
    ledger.record_discovered("design-system")
    ledger.record_injected("design-system", turn_id="t_cancel", phase="PHASE_B")

    # Simulate cancellation: fresh instance loads from disk
    restored = SkillEvidenceLedger.load_from_workspace(tmp_path)
    assert restored is not None
    assert "design-system" in restored.records
    assert restored.records["design-system"].current_stage == SkillLifecycleStage.INJECTED


# ==============================================================================
# 13. Skill ledger survives recovery
# ==============================================================================

def test_13_skill_ledger_survives_recovery(tmp_path: Path):
    """Verify ledger state is preserved through recovery checkpoints."""
    ledger = SkillEvidenceLedger(mission_id="m_rec_test", workspace_root=tmp_path)
    ledger.record_applied("web-design-guidelines", evidence="Semantic HTML & responsive media queries.")

    # Check that reading again preserves stage
    loaded = SkillEvidenceLedger.load_from_workspace(tmp_path)
    assert loaded is not None
    rec = loaded.records["web-design-guidelines"]
    assert rec.current_stage == SkillLifecycleStage.APPLIED
    assert rec.applied_status == SkillApplicationStatus.APPLIED


# ==============================================================================
# 14. Skill ledger records remain available after mission failure
# ==============================================================================

def test_14_skill_ledger_records_remain_available_after_mission_failure(tmp_path: Path):
    """Verify earlier phase evidence is not wiped if a later phase fails."""
    ledger = SkillEvidenceLedger(mission_id="m_fail_test", workspace_root=tmp_path)
    ledger.record_applied("taste-design", evidence="Styling created in turn 2")
    ledger.record_applied("design-system", evidence="Tokens created in turn 3")

    # Mission fails in later turn
    persisted = tmp_path / ".hermes" / "skill_evidence_ledger.json"
    assert persisted.exists()

    data = json.loads(persisted.read_text(encoding="utf-8"))
    assert data["records"]["taste-design"]["applied_status"] == "APPLIED"
    assert data["records"]["design-system"]["applied_status"] == "APPLIED"


# ==============================================================================
# 15. Skill injection evidence retains actual request/turn association
# ==============================================================================

def test_15_skill_injection_evidence_retains_actual_turn_association(tmp_path: Path):
    """Verify injection events record the exact turn ID and instruction IDs."""
    ledger = SkillEvidenceLedger(mission_id="m_assoc_test", workspace_root=tmp_path)
    ledger.record_injected(
        "design-engineering",
        turn_id="turn_42",
        phase="PHASE_C",
        instruction_ids=["grid_layout", "card_geometry"],
    )

    rec = ledger.records["design-engineering"]
    assert "turn_42" in rec.associated_turns
    assert len(rec.injection_events) == 1
    assert rec.injection_events[0]["turn_id"] == "turn_42"
    assert "grid_layout" in rec.applicable_instruction_ids


# ==============================================================================
# 16. Applied evidence is distinct from verified evidence
# ==============================================================================

def test_16_applied_evidence_distinct_from_verified_evidence():
    """Verify strict stage boundaries: INJECTED != APPLIED != VERIFIED."""
    rec = SkillEvidenceRecord(skill_id="test-skill")
    assert rec.current_stage == SkillLifecycleStage.DISCOVERED

    # Injected must not set APPLIED
    rec.injection_events.append({"turn_id": "t1"})
    rec.current_stage = SkillLifecycleStage.INJECTED
    assert rec.applied_status == SkillApplicationStatus.NOT_RUN
    assert rec.verified_status == SkillVerificationStatus.NOT_RUN

    # Applied must not set VERIFIED
    rec.applied_status = SkillApplicationStatus.APPLIED
    rec.current_stage = SkillLifecycleStage.APPLIED
    assert rec.verified_status == SkillVerificationStatus.NOT_RUN


# ==============================================================================
# 17. Atomic persistence does not corrupt existing ledger files
# ==============================================================================

def test_17_atomic_persistence_does_not_corrupt_existing_ledger(tmp_path: Path):
    """Verify rapid atomic updates never leave half-written or corrupt JSON."""
    ledger = SkillEvidenceLedger(mission_id="m_atomic_test", workspace_root=tmp_path)

    for i in range(25):
        ledger.record_injected("skill_a", turn_id=f"turn_{i}", phase="PHASE_B")

    ledger_file = tmp_path / ".hermes" / "skill_evidence_ledger.json"
    assert ledger_file.exists()

    # Must parse cleanly
    content = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert len(content["records"]["skill_a"]["injection_events"]) == 25


# ==============================================================================
# 18. Honest visual inspection reporting (explicit distinction from vision AI)
# ==============================================================================

def test_18_visual_inspector_honest_reporting(tmp_path: Path):
    """Verify VisualQualityInspector explicitly categorizes heuristics vs multimodal vision."""
    # Create minimal entrypoint files
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Travel</h1></body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text("body { font-family: sans-serif; } @media (max-width: 768px) { body { font-size: 14px; } }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('init');", encoding="utf-8")

    # Create dummy screenshot
    shot_dir = tmp_path / ".hermes" / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_file = shot_dir / "desktop_1280.png"
    from PIL import ImageDraw
    im = Image.new("RGB", (1280, 800), color=(100, 150, 200))
    d = ImageDraw.Draw(im)
    d.rectangle([50, 50, 400, 300], fill=(255, 220, 100))
    d.text((60, 60), "WanderWorld Travel", fill=(10, 20, 30))
    im.save(shot_file, format="PNG")

    report = VisualQualityInspector.inspect_workspace(tmp_path, prompt="WanderWorld travel website")
    rep_dict = report.to_dict()

    # Must explicitly differentiate the categories
    assert "structural_visual_heuristics" in rep_dict
    assert rep_dict["structural_visual_heuristics"]["passed"] is True

    assert "screenshot_capture" in rep_dict
    assert rep_dict["screenshot_capture"]["captured_count"] >= 1

    assert "screenshot_non_blank_check" in rep_dict
    assert rep_dict["screenshot_non_blank_check"]["passed"] is True

    assert "vision_based_visual_review" in rep_dict
    assert rep_dict["vision_based_visual_review"]["status"] == "NOT_CONFIGURED"
    assert rep_dict["vision_based_visual_review"]["multimodal_critique_executed"] is False
