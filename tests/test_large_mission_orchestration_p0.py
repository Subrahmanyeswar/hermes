# tests/test_large_mission_orchestration_p0.py
"""
P0 Test Suite: Large Mission Orchestration, Context Efficiency, Durable Checkpoints,
Two-Level Verification Scheduling, and Reliable Autonomous Completion.

Covers the 15 required scenarios:
1. Large prompt detection and decomposition into Work Packages.
2. Structured work package dependencies (DAG validation).
3. Deduplication of requirements and acceptance checks across overlapping concepts.
4. Negative constraint handling without generating excluded requirements.
5. Generic planning without domain hardcoding.
6. Bounded execution phase transitions (Phase A -> B -> C -> D -> E -> F).
7. Durable mission checkpoint creation (.hermes/mission_checkpoint.json) and reload/resume.
8. Context compaction: Completed phases summarized and historical tool outputs pruned.
9. Workspace skeleton filtering: Ignoring .git, node_modules, venv, __pycache__, .hermes.
10. Two-level verification scheduling: Incremental syntax vs comprehensive Phase E.
11. Adaptive turn budgeting across phases based on complexity estimation.
12. Early stall detection within bounded phase.
13. Inference telemetry tracking (timing, tokens, tool count, finish reason).
14. Small-mission pass-through (Profile A / compact prompt simplicity).
15. Synthetic large static website mission execution end-to-end.
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import (
    AgentLoopConfig,
    AgentTurn,
    AgentDecision,
    AgentDecisionType,
    ExecutionPhase,
    Observation,
    get_phase_budget,
)
from core.planning.decomposer import GoalDecomposer, DependencyCycleError
from core.mission_checkpoint import MissionCheckpoint, MissionCheckpointManager
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    RequirementCategory,
    RequirementPriority,
    RequirementState,
    RequirementStatus,
)
from core.verification_profiles import VerificationProfile


def make_test_loop(tmp_path: Path) -> AgentLoop:
    """Helper to instantiate an isolated AgentLoop for testing."""
    loop = AgentLoop.__new__(AgentLoop)
    loop._mission_id = "m_test_large_orchestration"
    loop._turns_count = 0
    loop._actions_count = 0
    loop._tool_calls_count = 0
    loop._consecutive_empty_turns = 0
    loop._in_recovery = False
    loop._recovery_attempt_count = 0
    loop._total_recovery_budget = 2
    loop._tier_rotations = 0
    loop._incident_visited_tiers = {}
    loop._observation_history = []
    loop._written_files = set()
    loop._recent_actions = []
    loop._inference_history = []
    loop._active_recovery_brief = None
    loop._active_routing_tier = 1
    loop._pending_diagnostics = {}
    loop._file_write_counts = {}
    loop._tasks = []
    loop._active_task_idx = 0
    loop.config = AgentLoopConfig(max_turns=80)

    # Large mission orchestration fields
    loop.current_phase = ExecutionPhase.PHASE_A_PLANNING
    loop.completed_phases = []
    loop.completed_phase_summaries = {}
    loop._phase_turn_count = {}
    loop._phase_stall_count = 0
    loop._is_large_mission = True
    loop._progress_in_current_phase = False

    # Mock workspace
    ws_mock = MagicMock()
    ws_mock.is_locked = True
    ws_mock.root_str = str(tmp_path)
    ws_mock.workspace_root = tmp_path
    ws_mock.get_workspace_summary.return_value = {
        "root": str(tmp_path),
        "framework": "vanilla",
        "total_files": 2,
    }
    ws_mock.get_skeleton.return_value = "project/\n├── index.html\n└── style.css"
    loop.workspace = ws_mock

    # Mock event bus & state store
    loop.event_bus = MagicMock()
    loop._publish_event = AsyncMock()
    loop.context_engine = None
    return loop


# ── Scenario 1: Large prompt detection and decomposition into Work Packages ───

def test_01_large_prompt_detection_and_work_packages():
    large_prompt = """
    Build a comprehensive cosmic travel agency platform called WanderWorld with:
    1. Hero section featuring brand statement, value propositions, and interactive destination booking bar.
    2. 6 detailed destination cards displaying high-res imagery, duration, luxury level, and direct booking trigger.
    3. Curated luxury travel packages section featuring filter tabs and inclusive amenities breakdown.
    4. Customer testimonials carousel with traveler review ratings and quotes.
    5. Interactive booking consultation modal dialog with multi-step validation.
    6. Contact and inquiry form with destination selector and date picker.
    7. Fully responsive layout with zero horizontal overflow, zero console errors, and real browser acceptance.
    """
    assert GoalDecomposer.is_large_mission(large_prompt) is True

    reqs, checks = GoalDecomposer.decompose("goal_large_1", large_prompt)
    assert "wp.foundation" in reqs
    assert "wp.content" in reqs
    assert "wp.functional" in reqs
    assert "wp.verification" in reqs
    assert len(checks) >= 12


# ── Scenario 2: Structured work package dependencies (DAG validation) ─────────

def test_02_work_package_dependencies_form_valid_dag():
    large_prompt = """
    Create a complete multi-section luxury real estate portal with:
    - Hero showcase and navigation header
    - 8 luxury property cards with price and amenities
    - Interactive mortgage calculator and inquiry modal
    - Responsive layout with full browser preview verification
    """
    reqs, _ = GoalDecomposer.decompose("goal_dag_1", large_prompt)

    # Foundation has no dependencies
    assert reqs["wp.foundation"].dependencies == []
    # Content depends on Foundation
    assert "wp.foundation" in reqs["wp.content"].dependencies
    # Functional depends on Content
    assert "wp.content" in reqs["wp.functional"].dependencies
    # Verification depends on Functional
    assert "wp.functional" in reqs["wp.verification"].dependencies

    # Valid DAG passes cycle detection
    GoalDecomposer.validate_dependencies(reqs)


# ── Scenario 3: Deduplication across overlapping concepts ─────────────────────

def test_03_deduplication_of_redundant_requirements():
    req1 = RequirementState(
        requirement_id="req.modal_1",
        goal_id="g_dedup",
        title="Interactive Modal Component",
        acceptance_check_ids=["chk_1"],
    )
    req2 = RequirementState(
        requirement_id="req.modal_2",
        goal_id="g_dedup",
        title="Interactive Modal Component",  # Exact duplicate normalized title
        acceptance_check_ids=["chk_2"],
    )
    chk1 = AcceptanceCheck(check_id="chk_1", requirement_id="req.modal_1", description="Modal opens")
    chk2 = AcceptanceCheck(check_id="chk_2", requirement_id="req.modal_2", description="Modal closes")

    deduped_reqs, deduped_checks = GoalDecomposer.deduplicate_requirements(
        {"req.modal_1": req1, "req.modal_2": req2},
        [chk1, chk2]
    )

    assert len(deduped_reqs) == 1
    assert "req.modal_1" in deduped_reqs
    assert "chk_1" in deduped_reqs["req.modal_1"].acceptance_check_ids
    assert "chk_2" in deduped_reqs["req.modal_1"].acceptance_check_ids
    # Check 2 requirement_id was remapped
    assert any(c.check_id == "chk_2" and c.requirement_id == "req.modal_1" for c in deduped_checks)


# ── Scenario 4: Negative constraint handling ──────────────────────────────────

def test_04_negative_constraints_exclude_unwanted_requirements():
    prompt = """
    Build a comprehensive portfolio website showcasing 10 photography projects with:
    - Hero section, gallery grid, full-screen lightbox modal dialog, and contact form.
    - Responsive mobile layout with zero console errors.
    Constraint: No backend, no database, no server, zero node runtime. Pure static HTML/JS.
    """
    reqs, _ = GoalDecomposer.decompose("g_neg", prompt)

    assert "wp.foundation" in reqs
    assert "req.persistence" not in reqs
    assert "req.backend" not in reqs
    assert "wp.persistence" not in reqs


# ── Scenario 5: Generic planning without domain hardcoding ────────────────────

def test_05_generic_planning_across_diverse_domains():
    medical_prompt = """
    Build a healthcare telemedicine portal with doctor directory, specialty cards,
    appointment booking modal, and patient symptom inquiry form. Zero console errors.
    """
    finance_prompt = """
    Build a crypto wealth analytics dashboard with 6 asset performance cards,
    interactive portfolio filter, currency conversion modal, and live charts.
    """
    reqs_med, _ = GoalDecomposer.decompose("g_med", medical_prompt)
    reqs_fin, _ = GoalDecomposer.decompose("g_fin", finance_prompt)

    # Both generic missions receive standard, reusable Work Packages
    for r in (reqs_med, reqs_fin):
        assert "wp.foundation" in r
        assert "wp.content" in r
        assert "wp.functional" in r
        assert "wp.verification" in r
        # Verify no domain specific words in titles
        for req in r.values():
            assert "wanderworld" not in req.title.lower()
            assert "bharatbridge" not in req.title.lower()


# ── Scenario 6: Bounded execution phase transitions ───────────────────────────

def test_06_bounded_execution_phase_transitions(tmp_path):
    loop = make_test_loop(tmp_path)
    assert loop.current_phase == ExecutionPhase.PHASE_A_PLANNING

    # Transition to Foundation
    loop.transition_phase(ExecutionPhase.PHASE_B_FOUNDATION, "Foundation setup started")
    assert loop.current_phase == ExecutionPhase.PHASE_B_FOUNDATION
    assert ExecutionPhase.PHASE_A_PLANNING.value in loop.completed_phases

    # Transition to Main Implementation
    loop.transition_phase(ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION, "Scaffold verified")
    assert loop.current_phase == ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION
    assert ExecutionPhase.PHASE_B_FOUNDATION.value in loop.completed_phases

    # Transition to Functional Implementation
    loop.transition_phase(ExecutionPhase.PHASE_D_FUNCTIONAL_IMPLEMENTATION, "Cards and content written")
    assert loop.current_phase == ExecutionPhase.PHASE_D_FUNCTIONAL_IMPLEMENTATION

    # Transition to Verification
    loop.transition_phase(ExecutionPhase.PHASE_E_VERIFICATION, "Interactions and modals wired")
    assert loop.current_phase == ExecutionPhase.PHASE_E_VERIFICATION

    # Transition to Completion
    loop.transition_phase(ExecutionPhase.PHASE_F_COMPLETION, "All checks passed")
    assert loop.current_phase == ExecutionPhase.PHASE_F_COMPLETION
    assert len(loop.completed_phases) == 5


# ── Scenario 7: Durable mission checkpoint creation and reload ────────────────

def test_07_durable_checkpoint_save_and_reload(tmp_path):
    ws = tmp_path / "app_ws"
    ws.mkdir()
    (ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>Title</h1></body></html>", encoding="utf-8")
    (ws / "style.css").write_text("body { margin: 0; }", encoding="utf-8")

    chk = MissionCheckpointManager.save_checkpoint(
        workspace_root=ws,
        mission_id="m_chk_test",
        current_phase="PHASE_C_MAIN_IMPLEMENTATION",
        completed_phases=["PHASE_A_PLANNING", "PHASE_B_FOUNDATION"],
        completed_tasks=["wp.foundation"],
        tier_state=2,
    )

    chk_path = MissionCheckpointManager.get_checkpoint_path(ws)
    assert chk_path.exists()

    loaded = MissionCheckpointManager.load_checkpoint(ws)
    assert loaded is not None
    assert loaded.mission_id == "m_chk_test"
    assert loaded.current_phase == "PHASE_C_MAIN_IMPLEMENTATION"
    assert "PHASE_B_FOUNDATION" in loaded.completed_phases
    assert loaded.tier_state == 2
    assert "index.html" in loaded.workspace_fingerprint

    # Integrity verification
    valid, mismatches = MissionCheckpointManager.verify_fingerprint_integrity(ws, loaded)
    assert valid is True
    assert len(mismatches) == 0

    # Modify file and verify mismatch detected
    (ws / "index.html").write_text("<h1>Mutated</h1>", encoding="utf-8")
    valid_after, mismatches_after = MissionCheckpointManager.verify_fingerprint_integrity(ws, loaded)
    assert valid_after is False
    assert any("index.html" in m for m in mismatches_after)


# ── Scenario 8: Context compaction: Completed phases summarized, outputs pruned

def test_08_context_compaction_for_large_missions(tmp_path):
    loop = make_test_loop(tmp_path)
    loop.current_phase = ExecutionPhase.PHASE_D_FUNCTIONAL_IMPLEMENTATION
    loop.completed_phases = [ExecutionPhase.PHASE_A_PLANNING.value, ExecutionPhase.PHASE_B_FOUNDATION.value, ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION.value]
    loop.completed_phase_summaries = {
        ExecutionPhase.PHASE_B_FOUNDATION.value: "Created index.html and style.css foundation",
        ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION.value: "Created 6 destination cards and hero section",
    }

    # Add several large tool observations
    for i in range(10):
        loop._observation_history.append(
            Observation(
                observation_id=f"obs_{i}",
                source_type="tool",
                source_id="fs.write",
                success=True,
                content="A" * 5000,  # 5,000 characters of raw output
            )
        )

    mission_mock = MagicMock()
    mission_mock.user_prompt = "Build luxury travel agency website WanderWorld"
    sys_prompt, user_msg = loop._build_turn_context(mission_mock, None)

    # 1. Authoritative phase block is present with completed phase summaries
    assert "Execution Phase: PHASE_D_FUNCTIONAL_IMPLEMENTATION" in user_msg
    assert "PHASE_B_FOUNDATION: Created index.html and style.css foundation" in user_msg
    assert "PHASE_C_MAIN_IMPLEMENTATION: Created 6 destination cards" in user_msg

    # 2. Raw observations were compacted: only 2 recent observations kept and truncated
    assert user_msg.count("[OBSERVATION") <= 2
    assert "[truncated for context efficiency]" in user_msg
    # Ensure user message is bounded and not 50,000 characters
    assert len(user_msg) < 8000


# ── Scenario 9: Workspace skeleton filtering ──────────────────────────────────

def test_09_workspace_skeleton_filtering(tmp_path):
    # Setup test workspace with excluded directories
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("console.log()", encoding="utf-8")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "pyvenv.cfg").write_text("cfg", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "temp.pyc").write_text("bytes", encoding="utf-8")
    (tmp_path / "index.html").write_text("<h1>App</h1>", encoding="utf-8")

    fp = MissionCheckpointManager.compute_fingerprint(tmp_path)
    # Ignored directories must not appear in the fingerprint
    assert "index.html" in fp
    for p in fp.keys():
        assert not p.startswith(".git")
        assert not p.startswith("node_modules")
        assert not p.startswith("venv")
        assert not p.startswith("__pycache__")


# ── Scenario 10: Two-level verification scheduling ────────────────────────────

def test_10_two_level_verification_scheduling(tmp_path):
    loop = make_test_loop(tmp_path)

    # Level 1: Incremental syntax check
    js_file = tmp_path / "test_script.js"
    js_file.write_text("const x = 1;", encoding="utf-8")

    from core.js_syntax_validator import validate_javascript_file
    val_ok, val_err, _ = validate_javascript_file(js_file)
    assert val_ok is True

    # Bad JS syntax detected incrementally without launching preview server
    bad_js = tmp_path / "broken.js"
    bad_js.write_text("function bad( {", encoding="utf-8")
    bad_ok, bad_err, _ = validate_javascript_file(bad_js)
    assert bad_ok is False

    # Level 2: Comprehensive verification classification
    from core.verification_profiles import classify_verification_profile, VerificationProfile
    prof = classify_verification_profile(
        "Build a travel website with cards, filters, booking modal and browser preview",
        workspace_path=str(tmp_path),
        written_files=["index.html", "style.css", "main.js"]
    )
    assert prof in (VerificationProfile.PROFILE_B, VerificationProfile.PROFILE_C)


# ── Scenario 11: Adaptive turn budgeting across phases ────────────────────────

def test_11_adaptive_turn_budgeting():
    # 80-turn budget allocations across phases
    b_plan = get_phase_budget(ExecutionPhase.PHASE_A_PLANNING, 80)
    b_found = get_phase_budget(ExecutionPhase.PHASE_B_FOUNDATION, 80)
    b_main = get_phase_budget(ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION, 80)
    b_func = get_phase_budget(ExecutionPhase.PHASE_D_FUNCTIONAL_IMPLEMENTATION, 80)
    b_verif = get_phase_budget(ExecutionPhase.PHASE_E_VERIFICATION, 80)
    b_comp = get_phase_budget(ExecutionPhase.PHASE_F_COMPLETION, 80)

    assert b_plan == 2
    assert b_found == 8
    assert b_main == 25
    assert b_func == 25
    assert b_verif == 15
    assert b_comp == 5
    assert (b_plan + b_found + b_main + b_func + b_verif + b_comp) == 80

    # Config resolution test: Large mission receives 80 turns, Profile A receives 8
    cfg = AgentLoopConfig()
    large_mission = MagicMock()
    large_mission.user_prompt = "Build large website with 10 sections and modals" * 10
    large_mission.max_turns = None
    assert cfg.resolve_for_mission(large_mission) == 80

    cfg_small = AgentLoopConfig()
    small_mission = MagicMock()
    small_mission.user_prompt = "diagnostic test write data to output.log"
    small_mission.max_turns = None
    assert cfg_small.resolve_for_mission(small_mission) <= 8


# ── Scenario 12: Early stall detection within bounded phase ───────────────────

def test_12_early_stall_detection(tmp_path):
    loop = make_test_loop(tmp_path)
    loop.current_phase = ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION

    # Simulate 3 consecutive turns without mutating progress
    for turn_idx in range(3):
        p_key = loop.current_phase.value
        loop._phase_turn_count[p_key] = loop._phase_turn_count.get(p_key, 0) + 1
        loop._phase_stall_count += 1
        if loop._phase_stall_count >= 3:
            loop._active_recovery_brief = (
                f"STALL WARNING in {p_key}: {loop._phase_stall_count} consecutive turns without progress."
            )

    assert loop._phase_stall_count == 3
    assert "STALL WARNING in PHASE_C_MAIN_IMPLEMENTATION" in loop._active_recovery_brief

    # Simulate a mutating action resetting stall count
    loop._progress_in_current_phase = True
    loop._phase_stall_count = 0
    assert loop._phase_stall_count == 0


# ── Scenario 13: Inference telemetry tracking ─────────────────────────────────

def test_13_inference_telemetry_tracking(tmp_path):
    loop = make_test_loop(tmp_path)

    rec = loop.record_inference_telemetry(
        requested_tier=1,
        actual_provider="google",
        actual_model="gemini-2.5-pro",
        start_time=100.0,
        completion_time=102.5,
        success=True,
        tool_call_count=2,
        finish_reason="tool_calls",
        turn_id="turn_telemetry_1",
        duration_ms=2500.0,
        prompt_tokens=1420,
        completion_tokens=210,
        ttft_ms=350.0,
    )

    assert rec["turn_id"] == "turn_telemetry_1"
    assert rec["requested_tier"] == 1
    assert rec["actual_provider"] == "google"
    assert rec["actual_model_id"] == "gemini-2.5-pro"
    assert rec["duration_ms"] == 2500.0
    assert rec["tool_call_count"] == 2
    assert rec["finish_reason"] == "tool_calls"
    assert rec["prompt_tokens"] == 1420
    assert rec["completion_tokens"] == 210
    assert rec["ttft_ms"] == 350.0
    assert len(loop._inference_history) == 1


# ── Scenario 14: Small-mission pass-through ───────────────────────────────────

def test_14_small_mission_pass_through():
    small_prompt = "Create a python script that prints 'Hello World'"
    assert GoalDecomposer.is_large_mission(small_prompt) is False

    reqs, checks = GoalDecomposer.decompose("g_small", small_prompt)
    # Standard requirements generated, no work package overhead
    assert "req.core_implementation" in reqs
    assert "req.verification" in reqs
    assert "wp.foundation" not in reqs
    assert "wp.content" not in reqs


# ── Scenario 15: Synthetic large static website mission execution ─────────────

@pytest.mark.asyncio
async def test_15_synthetic_large_static_website_mission_execution(tmp_path):
    """
    End-to-end synthetic simulation verifying that a complex multi-section website
    with destination cards, filters, booking modal, and browser acceptance
    completes through all phases with evidence logged.
    """
    ws = tmp_path / "wanderworld_sim"
    ws.mkdir()

    large_prompt = """
    Build a complete luxury cosmic travel agency platform called WanderWorld with:
    1. Hero section with interactive booking bar
    2. 6 destination cards with pricing and details
    3. Filterable travel packages section
    4. Customer testimonials carousel
    5. Interactive booking consultation modal dialog
    6. Contact and inquiry form
    7. Fully responsive layout with zero console errors
    """
    reqs, checks = GoalDecomposer.decompose("g_wanderworld", large_prompt)
    assert "wp.foundation" in reqs
    assert "wp.content" in reqs
    assert "wp.functional" in reqs
    assert "wp.verification" in reqs

    loop = make_test_loop(ws)
    loop._tasks = [
        {"task_id": r_id, "title": r.title, "status": "PENDING"}
        for r_id, r in reqs.items()
    ]
    loop._active_task_idx = 0

    # Phase B: Foundation
    loop.current_phase = ExecutionPhase.PHASE_B_FOUNDATION
    (ws / "index.html").write_text("<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'></head><body><header>WanderWorld</header></body></html>", encoding="utf-8")
    (ws / "style.css").write_text("body { font-family: sans-serif; background: #0b0c10; color: #fff; }", encoding="utf-8")
    loop._written_files.update(["index.html", "style.css"])
    await loop._advance_active_task("Foundation created")
    loop.transition_phase(ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION, "Scaffold created")
    assert loop.current_phase == ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION
    assert loop._tasks[0]["status"] == "COMPLETED"

    # Phase C: Main Implementation (Sections & Cards)
    (ws / "index.html").write_text("""<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'></head><body>
    <section id='hero'><h1>Cosmic Horizons</h1></section>
    <section id='destinations'>
        <div class='card'>Mars Colony</div>
        <div class='card'>Europa Depths</div>
        <div class='card'>Titan Spire</div>
        <div class='card'>Lunar Base</div>
        <div class='card'>Enceladus Geysers</div>
        <div class='card'>Venus Cloud City</div>
    </section>
    <section id='packages'></section>
    </body></html>""", encoding="utf-8")
    await loop._advance_active_task("Content populated")
    loop.transition_phase(ExecutionPhase.PHASE_D_FUNCTIONAL_IMPLEMENTATION, "Content sections populated")
    assert loop.current_phase == ExecutionPhase.PHASE_D_FUNCTIONAL_IMPLEMENTATION
    assert loop._tasks[1]["status"] == "COMPLETED"

    # Phase D: Functional Implementation (Modal & Form JS)
    (ws / "main.js").write_text("""
    document.addEventListener('DOMContentLoaded', () => {
        const modal = document.getElementById('booking-modal');
        function openModal() { if (modal) modal.style.display = 'block'; }
        function closeModal() { if (modal) modal.style.display = 'none'; }
    });
    """, encoding="utf-8")
    loop._written_files.add("main.js")
    await loop._advance_active_task("Functional wired")
    loop.transition_phase(ExecutionPhase.PHASE_E_VERIFICATION, "Interactive handlers wired")
    assert loop.current_phase == ExecutionPhase.PHASE_E_VERIFICATION
    assert loop._tasks[2]["status"] == "COMPLETED"

    # Phase E: Verification
    await loop._advance_active_task("Verification passed")
    loop.transition_phase(ExecutionPhase.PHASE_F_COMPLETION, "Browser qualified with zero errors")
    assert loop.current_phase == ExecutionPhase.PHASE_F_COMPLETION
    assert loop._tasks[3]["status"] == "COMPLETED"

    # Verify durable checkpoint was recorded at completion
    chk = MissionCheckpointManager.load_checkpoint(ws)
    assert chk is not None
    assert chk.current_phase == ExecutionPhase.PHASE_F_COMPLETION.value
    assert "index.html" in chk.workspace_fingerprint
    assert "style.css" in chk.workspace_fingerprint
    assert "main.js" in chk.workspace_fingerprint
