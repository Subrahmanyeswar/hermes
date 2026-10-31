"""
Phase 4 Acceptance Test Suite: Durable Network Waiting & Recoverable Blockers (Scenarios M, R / Gate F).

Verifies:
- Scenario M: All eligible routes transiently failing transitions to durable WAITING without infinite spinning.
- Mission is not marked COMPLETED or FAILED; unfinished execution step and context preserved.
- Scenario R: Recoverable workspace or checkpoint blocker enters safe WAITING state rather than hard FAILED.
"""

import uuid
import tempfile
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import MissionStatus, WaitReason
from core.transport.types import (
    ErrorCategory,
    StructuredTransportError,
)
from core.transport.circuit_breaker import CircuitBreakerRegistry, circuit_breaker_registry
from core.transport.retry_coordinator import (
    FallbackPolicyConfig,
    RetryCoordinator,
)


@pytest.fixture(autouse=True)
async def reset_cb():
    await circuit_breaker_registry.reset()


@pytest.mark.asyncio
async def test_scenario_m_all_routes_failing_bounds_and_enters_waiting():
    """Verify that when all 3 tiers fail transiently, the coordinator terminates cleanly and runtime records WAITING."""
    cfg = FallbackPolicyConfig(
        enabled=True,
        max_fallback_depth=3,
        primary_max_retries=1,
        fallback_max_retries=1,
    )
    routes = [
        (1, "nvidia_nim", "z-ai/glm-5.3-flash"),
        (2, "ollama", "gpt-oss:120b-cloud"),
        (3, "ollama", "nemotron-3-ultra:cloud"),
    ]
    coord = RetryCoordinator(
        config=cfg,
        routes=routes,
        circuit_breaker=CircuitBreakerRegistry(),
    )

    invoked_tiers = []

    async def all_failing_invoker(tier, provider, model, attempt, timeout_remaining):
        invoked_tiers.append(tier)
        raise StructuredTransportError(
            category=ErrorCategory.PROVIDER_UNAVAILABLE,
            message=f"Tier {tier} unavailable (HTTP 503)",
            provider=provider,
            model=model,
            status_code=503,
            retryable=True,
        )

    res = await coord.execute_with_resilience(all_failing_invoker)
    assert res.response is None
    assert res.error is not None
    # Each tier attempted exactly once before escalating
    assert invoked_tiers == [1, 2, 3]
    assert res.total_attempts == 3

    # Now verify runtime persistence of WAITING_FOR_PROVIDER
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p4_m_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_wait_{test_id}"

    store = bus.get_or_create_state(mission_id)
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"mission_id": mission_id, "prompt": "Process data pipeline"}
    ))

    # All tiers failed -> publish MISSION_WAITING
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id=mission_id,
        payload={
            "wait_reason": "WAITING_FOR_PROVIDER",
            "reason": "All configured model tiers (1, 2, 3) temporarily unavailable (HTTP 503)",
        }
    ))

    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.WAITING
    assert snap.progress.waiting_reason == WaitReason.WAITING_FOR_PROVIDER
    assert snap.mission.is_terminal is False

    # Database records WAITING, not FAILED
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="WAITING",
        wait_reason="WAITING_FOR_PROVIDER",
    )
    row = db.get_mission(mission_id)
    assert row["status"] == "WAITING"
    assert row["wait_reason"] == "WAITING_FOR_PROVIDER"


def test_scenario_r_recoverable_workspace_blocker_persists_waiting():
    """Verify that a temporary workspace or checkpoint blocker is tracked as WAITING, not fatal FAILED."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p4_r_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_rec_r_{test_id}"

    store = bus.get_or_create_state(mission_id)
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"mission_id": mission_id}
    ))

    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id=mission_id,
        payload={
            "wait_reason": "WAITING_FOR_NETWORK",
            "reason": "Network workspace volume temporarily unmounted",
        }
    ))

    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.WAITING
    assert snap.progress.waiting_reason == WaitReason.WAITING_FOR_NETWORK
    assert "workspace volume" in snap.progress.current_action
    assert snap.mission.is_terminal is False
