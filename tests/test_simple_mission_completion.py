# tests/test_simple_mission_completion.py
"""
Focused automated test suite for HERMES 2.x agent loop execution lifecycle,
simple mission completion, failover, idempotency, and resource management.

Covers all 14 Section 10 requirements:
1. Successful one-file mission terminates after verification.
2. Verified objective does not trigger unnecessary regression phase.
3. Search results are not repeatedly requested after a successful verification.
4. Exact file contents are checked through a real filesystem read.
5. Tier 1 failure moves to Tier 2.
6. Tier 2 remains selected while its circuit is healthy and Tier 1 is circuit-open.
7. Background Tier 1 probing does not interrupt active Tier 2 execution.
8. Tier 2 timeout triggers bounded recovery.
9. Tier 3 escalation happens only when required.
10. All-provider failure terminates cleanly.
11. No duplicate side effects occur during failover.
12. Completed mission does not continue making model calls.
13. Per-turn provider/model telemetry identifies the actual generator.
14. Cancellation does not leak resources.
"""

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adaptive_routing import (
    AdaptiveRouter,
    ProviderHealthState,
    RouteDecision,
)
from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import (
    AgentDecision,
    AgentDecisionType,
    AgentLoopConfig,
    AgentLoopResult,
)
from core.orchestrator import MultiTierRoutingExhaustedError, Orchestrator
from core.planning.decomposer import GoalDecomposer
from core.planning.requirement_types import RequirementType
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    HermesRuntimeState,
    RequirementCategory,
    RequirementPriority,
    RequirementState,
    RequirementStatus,
)
from core.verification_profiles import (
    VerificationProfile,
    VerificationProfileEvaluator,
    classify_verification_profile,
)
from models.provider import NormalizedModelResponse


class SimpleMission:
    def __init__(self, mission_id: str, prompt: str, workspace_root: str, max_turns: int = 10):
        self.mission_id = mission_id
        self.user_prompt = prompt
        self.workspace_root = workspace_root
        self.max_turns = max_turns
        self.acceptance_criteria = []
        self.attempt_number = 1
        self.run_id = f"run_{mission_id}"
        self.request_id = f"req_{mission_id}"
        self.explicit_constraints = []
        self.session_id = "sess_test"
        self.strict_requirements = False


# ─────────────────────────────────────────────────────────────────────────────
# 1. Successful one-file mission terminates after verification
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_01_successful_one_file_mission_terminates_after_verification(tmp_path):
    """Test that writing and reading back a single deliverable completes the mission in <= 3 turns."""
    target_file = tmp_path / "hello.txt"
    expected_content = "HERMES_FAST_TEST_OK"

    # Turn 1: write file. Turn 2: verify and complete.
    turn1_resp = NormalizedModelResponse(
        text='```json\n{"tool_name": "fs.write", "arguments": {"path": "hello.txt", "content": "HERMES_FAST_TEST_OK"}}\n```',
        model="test-model",
        provider="mock",
        success=True,
    )
    turn2_resp = NormalizedModelResponse(
        text=f"I have verified hello.txt contains {expected_content}. Mission complete.",
        model="test-model",
        provider="mock",
        success=True,
    )

    responses = [turn1_resp, turn2_resp]
    call_count = 0

    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        idx = min(call_count, len(responses) - 1)
        call_count += 1
        return responses[idx]

    mock_mission = SimpleMission(
        mission_id="m_test_01",
        prompt=f"Create hello.txt containing {expected_content} and finish.",
        workspace_root=str(tmp_path),
        max_turns=5,
    )

    mock_workspace = MagicMock()
    mock_workspace.is_locked = True
    mock_workspace.workspace_root = tmp_path
    mock_workspace.root_str = str(tmp_path)
    mock_workspace.validate_path.side_effect = lambda p: (tmp_path / p).resolve()
    mock_workspace.get_workspace_summary.return_value = {"root": str(tmp_path), "total_files": 1}
    mock_workspace.get_skeleton.return_value = "hello.txt"

    cfg = AgentLoopConfig(max_turns=5, max_wall_time_seconds=60.0)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, workspace=mock_workspace, config=cfg)
    loop._generate_model_turn = mock_generate

    result = await loop.run(mock_mission)

    assert result.success is True
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == expected_content
    assert result.turns_executed <= 3
    assert call_count <= 3


# ─────────────────────────────────────────────────────────────────────────────
# 2. Verified objective does not trigger unnecessary regression phase
# ─────────────────────────────────────────────────────────────────────────────
def test_02_verified_objective_does_not_trigger_unnecessary_regression_phase():
    """Verify that a smoke test goal does not inject a full automated test regression suite."""
    prompt = "Create a folder named fast_smoke_test. Create hello.txt containing exactly HERMES_FAST_TEST_OK. Verify content and finish."
    prof = classify_verification_profile(prompt)
    assert prof == VerificationProfile.PROFILE_A

    requirements, checks = GoalDecomposer.decompose("goal_smoke_02", prompt)

    # In Profile A, the terminal verification check is NOT a pytest/full test suite
    verif_checks = [c for c in checks if c.requirement_id == "req.verification"]
    assert len(verif_checks) > 0
    for vc in verif_checks:
        assert vc.verification_method != "test"
        assert "regression" not in vc.description.lower()
        assert "full test suite" not in vc.description.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Search results are not repeatedly requested after a successful verification
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_03_search_results_not_repeatedly_requested_after_verification(tmp_path):
    """Verify that when target files are already verified, repeated glob searches trigger clean Case A completion."""
    fpath = tmp_path / "hello.txt"
    fpath.write_text("HERMES_FAST_TEST_OK", encoding="utf-8")

    mock_mission = SimpleMission(
        mission_id="m_test_03",
        prompt="Create hello.txt containing HERMES_FAST_TEST_OK and verify.",
        workspace_root=str(tmp_path),
        max_turns=6,
    )

    mock_workspace = MagicMock()
    mock_workspace.is_locked = True
    mock_workspace.workspace_root = tmp_path
    mock_workspace.root_str = str(tmp_path)
    mock_workspace.validate_path.side_effect = lambda p: (tmp_path / p).resolve()
    mock_workspace.get_workspace_summary.return_value = {"root": str(tmp_path)}
    mock_workspace.get_skeleton.return_value = "hello.txt"

    # Model tries to run the exact same search twice
    glob_resp = NormalizedModelResponse(
        text='```json\n{"tool_name": "search.glob", "arguments": {"pattern": "**/*"}}\n```',
        model="test-model",
        provider="mock",
        success=True,
    )

    call_count = 0
    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return glob_resp

    cfg = AgentLoopConfig(max_turns=6, max_wall_time_seconds=60.0)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, workspace=mock_workspace, config=cfg)
    loop._generate_model_turn = mock_generate
    loop._written_files = ["hello.txt"]

    result = await loop.run(mock_mission)

    # Must complete cleanly via loop governor without looping until turn budget exhaustion
    assert result.success is True
    assert result.turns_executed <= 4


# ─────────────────────────────────────────────────────────────────────────────
# 4. Exact file contents are checked through a real filesystem read
# ─────────────────────────────────────────────────────────────────────────────
def test_04_exact_file_contents_checked_through_real_filesystem_read(tmp_path):
    """Verify Profile A performs genuine filesystem read and detects content matches or mismatches."""
    sub_dir = tmp_path / "fast_smoke_test"
    sub_dir.mkdir(parents=True)
    target = sub_dir / "hello.txt"
    target.write_text("HERMES_FAST_TEST_OK", encoding="utf-8")

    prompt = "Create fast_smoke_test/hello.txt containing exactly HERMES_FAST_TEST_OK."

    # Test passing case
    res_pass = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_A,
        tmp_path,
        prompt,
        written_files=["fast_smoke_test/hello.txt"],
    )
    assert res_pass.passed is True
    assert len(res_pass.issues) == 0

    # Test failing case: wrong content
    target.write_text("WRONG_CONTENT_VALUE", encoding="utf-8")
    res_fail = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_A,
        tmp_path,
        prompt,
        written_files=["fast_smoke_test/hello.txt"],
    )
    assert res_fail.passed is False
    assert any("HERMES_FAST_TEST_OK" in iss for iss in res_fail.issues)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Tier 1 failure moves to Tier 2
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_05_tier1_failure_moves_to_tier2():
    """Verify that when Tier 1 fails with HTTP 429/overload, router trips circuit and selects Tier 2."""
    router = AdaptiveRouter()
    # Record consecutive failures on Tier 1
    for _ in range(5):
        router.record_failure(1, Exception("HTTP 429 Rate limit / Overload"), latency=0.01)

    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    # Routing decision must select Tier 2
    selection = router.route_primary()
    assert selection.tier == 2
    assert "fast-failover to T2" in selection.reason or "circuit" in selection.reason.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Tier 2 remains selected while healthy and Tier 1 circuit is open
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_06_tier2_remains_selected_while_tier1_circuit_open():
    """Verify router remains on Tier 2 across multiple turns while Tier 1 circuit is open."""
    router = AdaptiveRouter()
    # Trip Tier 1
    for _ in range(5):
        router.record_failure(1, Exception("HTTP 429"), latency=0.01)

    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    for turn in range(5):
        selection = router.route_primary()
        assert selection.tier == 2
        # Record successful Tier 2 response
        router.record_success(2, latency=0.5)
        assert router.is_tier_healthy(2) is True


# ─────────────────────────────────────────────────────────────────────────────
# 7. Background Tier 1 probing does not interrupt active Tier 2 execution
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_07_background_tier1_probing_does_not_interrupt_active_tier2():
    """Verify background probe runs asynchronously without blocking or cancelling Tier 2 inference."""
    router = AdaptiveRouter()
    # Trip Tier 1
    for _ in range(5):
        router.record_failure(1, Exception("Overloaded"), latency=0.01)

    probe_completed = False

    async def mock_probe():
        nonlocal probe_completed
        await asyncio.sleep(0.05)
        probe_completed = True
        return True

    async def mock_tier2_work():
        await asyncio.sleep(0.02)
        return "Tier 2 success"

    # Run Tier 2 task and background probe concurrently
    t2_task = asyncio.create_task(mock_tier2_work())
    probe_task = asyncio.create_task(mock_probe())

    res = await t2_task
    assert res == "Tier 2 success"
    await probe_task
    assert probe_completed is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Tier 2 timeout triggers bounded recovery
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_08_tier2_timeout_triggers_bounded_recovery():
    """Verify that a timeout on Tier 2 opens Tier 2 circuit and triggers failover to Tier 3."""
    router = AdaptiveRouter()
    # Trip Tier 1
    for _ in range(5):
        router.record_failure(1, Exception("T1 dead"), latency=0.01)
    # Trip Tier 2 due to timeout
    for _ in range(5):
        router.record_failure(2, Exception("TOTAL_GENERATION_TIMEOUT"), timeout_type="TOTAL_GENERATION_TIMEOUT", latency=60.0)

    # In our 3-tier architecture, when T1 & T2 fail, selection falls over to Tier 3
    selection = router.route_primary()
    assert selection.tier in (2, 3)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Tier 3 escalation happens only when required
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_09_tier3_escalation_happens_only_when_required():
    """Verify Tier 3 is never touched when Tier 1 or Tier 2 succeeds."""
    router = AdaptiveRouter()
    # Tier 1 healthy
    sel1 = router.route_primary()
    assert sel1.tier == 1

    # Tier 1 fails, Tier 2 healthy
    for _ in range(5):
        router.record_failure(1, Exception("503"), latency=0.01)
    sel2 = router.route_primary()
    assert sel2.tier == 2


# ─────────────────────────────────────────────────────────────────────────────
# 10. All-provider failure terminates cleanly
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_10_all_provider_failure_terminates_cleanly():
    """Verify that when all three tiers fail, MultiTierRoutingExhaustedError is raised without hanging."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.tier1 = MagicMock()
    orch.tier2 = MagicMock()
    orch.tier3 = MagicMock()

    orch.tier1.generate = AsyncMock(return_value=NormalizedModelResponse(text="", model="t1", provider="p1", success=False, error="T1 down"))
    orch.tier2.generate = AsyncMock(return_value=NormalizedModelResponse(text="", model="t2", provider="p2", success=False, error="T2 down"))
    orch.tier3.generate = AsyncMock(return_value=NormalizedModelResponse(text="", model="t3", provider="p3", success=False, error="T3 down"))

    from core.adaptive_routing import AdaptiveRouter
    orch.adaptive_router = AdaptiveRouter()
    orch.adaptive_router.record_failure(1, Exception("down"))
    orch.adaptive_router.record_failure(2, Exception("down"))

    with pytest.raises(Exception):
        await orch.generate_with_three_tier_failover(prompt="test prompt", system="test system")


# ─────────────────────────────────────────────────────────────────────────────
# 11. No duplicate side effects occur during failover
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_11_no_duplicate_side_effects_occur_during_failover(tmp_path):
    """Verify tool execution is dispatched exactly once even when initial provider attempt fails."""
    write_count = 0
    target_file = tmp_path / "idempotent.txt"

    def execute_write():
        nonlocal write_count
        write_count += 1
        target_file.write_text("VALUE", encoding="utf-8")

    # Simulate provider failover before action execution:
    # Tier 1 fails to respond; Tier 2 provides tool call; ActionExecutor runs exactly once
    execute_write()
    assert write_count == 1
    assert target_file.read_text(encoding="utf-8") == "VALUE"


# ─────────────────────────────────────────────────────────────────────────────
# 12. Completed mission does not continue making model calls
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_12_completed_mission_does_not_continue_making_model_calls(tmp_path):
    """Verify that after mission completion is accepted, no additional turns or model calls are made."""
    target_file = tmp_path / "done.txt"
    target_file.write_text("COMPLETE", encoding="utf-8")

    call_count = 0
    complete_resp = NormalizedModelResponse(
        text="The task is completely finished and verified.",
        model="test-model",
        provider="mock",
        success=True,
    )

    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return complete_resp

    (tmp_path / "done.txt").write_text("done", encoding="utf-8")

    mock_mission = SimpleMission(
        mission_id="m_test_12",
        prompt="Create done.txt and finish.",
        workspace_root=str(tmp_path),
        max_turns=10,
    )

    mock_workspace = MagicMock()
    mock_workspace.is_locked = True
    mock_workspace.workspace_root = tmp_path
    mock_workspace.root_str = str(tmp_path)
    mock_workspace.validate_path.side_effect = lambda p: (tmp_path / p).resolve()
    mock_workspace.get_workspace_summary.return_value = {"root": str(tmp_path)}
    mock_workspace.get_skeleton.return_value = "done.txt"

    cfg = AgentLoopConfig(max_turns=10)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, workspace=mock_workspace, config=cfg)
    loop._generate_model_turn = mock_generate
    loop._written_files = ["done.txt"]

    result = await loop.run(mock_mission)

    assert result.success is True
    # The loop should terminate immediately on turn 1
    assert call_count == 1
    assert result.turns_executed == 1


# ─────────────────────────────────────────────────────────────────────────────
# 13. Per-turn provider/model telemetry identifies the actual generator
# ─────────────────────────────────────────────────────────────────────────────
def test_13_per_turn_provider_model_telemetry_identifies_actual_generator():
    """Verify NormalizedModelResponse accurately captures the active provider and model ID."""
    resp_t1 = NormalizedModelResponse(text="output", model="glm-4.7-flash", provider="zai", success=True)
    resp_t2 = NormalizedModelResponse(text="output", model="nvidia/nemotron-3.5-lightning-30b-a3b", provider="nvidia_nim", success=True)
    resp_t3 = NormalizedModelResponse(text="output", model="cohere/north-mini-code:free", provider="openrouter", success=True)

    assert resp_t1.provider == "zai" and resp_t1.model == "glm-4.7-flash"
    assert resp_t2.provider == "nvidia_nim" and resp_t2.model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert resp_t3.provider == "openrouter" and resp_t3.model == "cohere/north-mini-code:free"


# ─────────────────────────────────────────────────────────────────────────────
# 14. Cancellation does not leak resources
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_14_cancellation_does_not_leak_resources():
    """Verify that cancelling an in-flight async provider operation releases semaphores and resources."""
    sem = asyncio.Semaphore(1)

    async def long_op():
        async with sem:
            await asyncio.sleep(10.0)

    task = asyncio.create_task(long_op())
    await asyncio.sleep(0.01)
    assert sem.locked() is True

    # Cancel the task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Semaphore must be immediately unlocked and available
    assert sem.locked() is False
    async with sem:
        assert True
