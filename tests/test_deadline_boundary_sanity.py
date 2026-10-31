"""
HERMES Final Deadline-Boundary Sanity Check Test Suite.
Validates:
1. Deterministic boundary matrix: 120s, 30s, 25s, 24s, 15s, 5s, 0s remaining budget.
2. Insufficient remaining budget strictly blocks new model requests.
3. Effective request timeout never exceeds usable budget (preserves 10s verification reserve).
4. Consistency across all model-routing tiers (Tier 1, Tier 2, Tier 3).
5. Late responses cannot revive terminal or cancelled missions.
"""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.agent_loop.loop import (
    AgentLoop,
    FINAL_VERIFICATION_RESERVE_SECONDS,
    MIN_MODEL_REQUEST_TIMEOUT_SECONDS,
    calculate_effective_turn_timeout,
)
from core.agent_loop.types import AgentLoopConfig
from core.mission_planner import Mission
from core.runtime_state.events import EventType
from core.workspace import WorkspaceManager
from models.nvidia_client import NvidiaClient, NvidiaTimeoutError
from models.ollama_client import OllamaClient, OllamaTimeoutError
from core.orchestrator import Orchestrator


# ============================================================================
# 1. Deterministic Timeout Calculation Matrix
# ============================================================================
@pytest.mark.parametrize(
    "remaining_wall_time, expected_timeout, should_be_allowed",
    [
        (120.0, 110.0, True),    # 120 - 10 = 110s usable (min(360, 110) = 110s)
        (30.0, 20.0, True),       # 30 - 10 = 20s usable (min(360, 20) = 20s)
        (25.0, 15.0, True),       # 25 - 10 = 15s usable (exact boundary for 15s min request)
        (24.0, None, False),      # 24 < (15 + 10) -> Blocked
        (15.0, None, False),      # 15 < (15 + 10) -> Blocked
        (5.0, None, False),       # 5 < (15 + 10) -> Blocked
        (0.0, None, False),       # 0 <= 0 -> Blocked
        (-5.0, None, False),      # Negative -> Blocked
    ],
)
def test_calculate_effective_turn_timeout_deterministic_matrix(
    remaining_wall_time, expected_timeout, should_be_allowed
):
    """
    Verify calculate_effective_turn_timeout strictly enforces:
    - 10.0s final-verification reserve
    - 15.0s minimum model request timeout
    - Rejection when remaining budget < 25.0s
    - Clamping when remaining budget >= 25.0s
    """
    assert FINAL_VERIFICATION_RESERVE_SECONDS == 10.0
    assert MIN_MODEL_REQUEST_TIMEOUT_SECONDS == 15.0

    timeout = calculate_effective_turn_timeout(
        remaining_wall_time=remaining_wall_time,
        configured_timeout=360.0,
        reserve_seconds=10.0,
        min_model_timeout=15.0,
    )

    if should_be_allowed:
        assert timeout == expected_timeout
        # Timeout must NEVER exceed remaining usable budget
        assert timeout <= (remaining_wall_time - 10.0)
        # Timeout plus reserve must NEVER exceed total remaining wall time
        assert timeout + 10.0 <= remaining_wall_time
    else:
        assert timeout is None


# ============================================================================
# 2. Insufficient Remaining Budget Blocks New Model Call
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("remaining_sec", [24.0, 15.0, 5.0, 0.0])
async def test_insufficient_remaining_budget_blocks_model_call(tmp_path, remaining_sec):
    """Verify that when remaining budget is < 25s, AgentLoop halts without calling the model."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    mock_orch = MagicMock()
    mock_orch._generate_t1 = AsyncMock()

    loop = AgentLoop(orchestrator=mock_orch, workspace_manager=wm)
    # Configure max_wall_time_seconds directly to the remaining_sec limit
    loop.config.max_wall_time_seconds = remaining_sec

    mid = f"m_insufficient_{int(remaining_sec)}_{uuid.uuid4().hex[:6]}"
    mission = Mission(mission_id=mid, user_prompt="Build application")

    await loop.run(mission)

    # Model should NEVER have been invoked
    assert mock_orch._generate_t1.call_count == 0

    # Terminal state must be published with failure
    assert getattr(loop, "_terminal_event_published", False) is True


# ============================================================================
# 3. Sufficient Remaining Budget Clamps Request Timeout
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remaining_sec, expected_call_timeout",
    [
        (120.0, 110.0),
        (35.0, 25.0),
        (27.0, 17.0),
    ],
)
async def test_sufficient_remaining_budget_clamps_request_timeout(tmp_path, remaining_sec, expected_call_timeout):
    """Verify that AgentLoop passes clamped timeout_seconds to model generation."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    mock_orch = MagicMock()
    captured_kwargs = {}

    async def fake_generate_t1(**kwargs):
        captured_kwargs.update(kwargs)
        # Stop loop after first turn
        loop.abort_event.set()
        from models.provider import NormalizedModelResponse
        return NormalizedModelResponse(text="Plan created", tool_calls=[], success=True)

    mock_orch._generate_t1 = AsyncMock(side_effect=fake_generate_t1)

    loop = AgentLoop(orchestrator=mock_orch, workspace_manager=wm)
    loop.config.max_wall_time_seconds = remaining_sec

    mid = f"m_sufficient_{int(remaining_sec)}_{uuid.uuid4().hex[:6]}"
    mission = Mission(mission_id=mid, user_prompt="Build application")

    await loop.run(mission)

    assert mock_orch._generate_t1.call_count == 1
    passed_to = captured_kwargs.get("timeout_seconds")
    assert passed_to is not None
    # Tolerance of 0.5s for time.monotonic execution drift
    assert abs(passed_to - expected_call_timeout) < 0.5


# ============================================================================
# 4. Consistency Across Routing Tiers
# ============================================================================
@pytest.mark.asyncio
async def test_tier1_nvidia_client_respects_clamped_timeout():
    """Verify NvidiaClient enforces effective_timeout for both stream and non-stream."""
    client = NvidiaClient(api_key="test_key", timeout_seconds=360)

    # Effective timeout of 15s should be enforced over default 360s
    class SlowStreamResponse:
        status_code = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "ok"}}]}'
            await asyncio.sleep(0.1)

    mock_http = MagicMock()
    mock_http.stream.return_value = SlowStreamResponse()

    # If 1.0s elapsed > 0.05s effective timeout, raises TOTAL_GENERATION_TIMEOUT
    with pytest.raises(NvidiaTimeoutError) as exc_info:
        await client._generate_stream(
            client=mock_http,
            url="http://test",
            payload={},
            headers={},
            active_model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            prompt="test",
            system="",
            temperature=0.0,
            start_time=time.monotonic() - 1.0,
            effective_timeout=0.05,
        )
    assert exc_info.value.timeout_type == "TOTAL_GENERATION_TIMEOUT"


@pytest.mark.asyncio
async def test_tier2_and_tier3_ollama_client_receives_clamped_timeout():
    """Verify OllamaClient accepts and propagates timeout_seconds parameter."""
    client = OllamaClient(base_url="http://127.0.0.1:11434", timeout_seconds=360)

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=httpx.ReadTimeout("read timeout"))

    with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http

        with pytest.raises(OllamaTimeoutError):
            await client.generate(
                model="gpt-oss:120b-cloud",
                prompt="test",
                timeout_seconds=20,
            )

        # Verify client.post was called with httpx.Timeout(20.0)
        call_kwargs = mock_http.post.call_args[1]
        assert "timeout" in call_kwargs
        assert call_kwargs["timeout"].read == 20.0


# ============================================================================
# 5. Late Response Cannot Revive Terminal Mission
# ============================================================================
@pytest.mark.asyncio
async def test_late_response_cannot_revive_terminal_mission(tmp_path):
    """Verify that late model responses arriving after cancellation or terminal state are discarded."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    mock_orch = MagicMock()

    async def slow_generate_t1(**kwargs):
        # Trigger abort while generation is in flight
        loop.abort_event.set()
        await asyncio.sleep(0.05)
        from models.provider import NormalizedModelResponse
        return NormalizedModelResponse(
            text="Late response after cancellation",
            tool_calls=[{"id": "call_late", "name": "fs.write", "arguments": {"path": "revived.txt", "content": "revived"}}],
            success=True
        )

    mock_orch._generate_t1 = AsyncMock(side_effect=slow_generate_t1)

    loop = AgentLoop(orchestrator=mock_orch, workspace_manager=wm)
    mid = f"m_late_{uuid.uuid4().hex[:6]}"
    mission = Mission(mission_id=mid, user_prompt="Build application")

    await loop.run(mission)

    # Verify revived.txt was NEVER created on disk
    assert not (tmp_path / "revived.txt").exists()
    assert getattr(loop, "_terminal_event_published", False) is True
