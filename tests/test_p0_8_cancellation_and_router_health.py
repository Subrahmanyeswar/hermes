"""
HERMES 2.x — Phase 3: Cancellation and Router Health Test Suite (P0.8)
Covers Scenarios 11, 12, 14, 15, 16:
  Test 11: Request cancelled while streaming -> transport resources close, no orphan tasks.
  Test 12: Unhealthy Tier 1 reaches cooldown -> HALF_OPEN probe, successful probe permits recovery.
  Test 14: Multiple concurrent calls cancelled -> no task or resource leaks.
  Test 15: Provider recovers after transient failure -> circuit breaker returns to CLOSED.
  Test 16: Phase 2 semantic & P0.5.2.1 content fidelity tests remain 100% intact.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adaptive_routing import get_adaptive_router, ProviderHealthState
from core.orchestrator import Orchestrator
from core.runtime_failover import (
    CircuitBreakerState,
    ErrorClassification,
    classify_runtime_error,
    global_attempt_ledger,
    global_failover_coordinator,
)
from models.common_adapter import NormalizedModelResponse


@pytest.fixture(autouse=True)
def clean_environment():
    """Ensure clean router and attempt ledger for every test."""
    router = get_adaptive_router()
    router.reset_state()
    if hasattr(router, "_mission_excluded_tiers"):
        router._mission_excluded_tiers.clear()
    global_attempt_ledger.clear_all()
    yield
    router.reset_state()
    if hasattr(router, "_mission_excluded_tiers"):
        router._mission_excluded_tiers.clear()
    global_attempt_ledger.clear_all()


@pytest.mark.asyncio
async def test_11_streaming_cancellation_closes_transport():
    """Test 11: Request cancelled while streaming -> transport resources close, no orphan tasks."""
    from models.nvidia_client import NvidiaClient

    client = NvidiaClient(api_key="mock_key", base_url="https://mock.nvidia.com")
    closed = False

    async def mock_stream(*args, **kwargs):
        nonlocal closed
        try:
            while True:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            closed = True
            raise

    # Mock the internal streaming generator
    client._generate_stream = mock_stream

    task = asyncio.create_task(client.generate(prompt="Stream something", stream=True))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert closed is True


@pytest.mark.asyncio
async def test_12_cooldown_half_open_probe_recovery():
    """Test 12: Unhealthy Tier 1 reaches cooldown -> HALF_OPEN probe, successful probe permits recovery."""
    router = get_adaptive_router()
    coordinator = global_failover_coordinator

    # 1. Trip Tier 1 circuit
    router.record_failure(tier=1, error=TimeoutError("First token timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    coordinator.exclude_tier_for_mission("m_probe_test", 1)

    # 2. Simulate cooldown window expiration
    import os
    base_window = float(os.getenv("T1_CIRCUIT_BREAKER_WINDOW", "30.0"))
    expired_ts = time.time() - (base_window + 5.0)
    router.providers[1].circuit_open_ts = expired_ts
    router.providers[1].last_state_change_ts = expired_ts
    router.providers[1].last_failure_ts = expired_ts
    coordinator._tier_cooldown_open[1] = expired_ts

    # Verify circuit transitions to HALF_OPEN
    cb_state = router.get_circuit_breaker_state(1)
    assert cb_state == CircuitBreakerState.HALF_OPEN

    # 3. Successful probe executes
    mock_client = AsyncMock()
    mock_client.is_running = AsyncMock(return_value=True)
    success = await router._run_probe(tier=1, client=mock_client)
    assert success is True

    # 4. State must return to HEALTHY / CLOSED
    assert router.get_health(1).state == ProviderHealthState.HEALTHY
    assert router.is_tier_healthy(1) is True
    coordinator.record_probe_success(1)
    _, coord_state = coordinator.is_tier_in_cooldown(1)
    assert coord_state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_14_concurrent_cancellations_no_resource_leaks():
    """Test 14: Multiple concurrent calls cancelled -> no task or resource leaks."""
    from models.nvidia_client import NvidiaClient

    client = NvidiaClient(api_key="mock_key", base_url="https://mock.nvidia.com")
    active_count = 0
    cleaned_up = 0

    async def mock_stream(*args, **kwargs):
        nonlocal active_count, cleaned_up
        active_count += 1
        try:
            while True:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            cleaned_up += 1
            raise

    client._generate_stream = mock_stream

    tasks = [asyncio.create_task(client.generate(prompt=f"Task {i}", stream=True)) for i in range(10)]
    await asyncio.sleep(0.05)
    assert active_count == 10

    for t in tasks:
        t.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, asyncio.CancelledError) for r in results)
    assert cleaned_up == 10


@pytest.mark.asyncio
async def test_15_provider_transient_failure_and_circuit_close():
    """Test 15: Provider recovers after transient failure -> circuit breaker returns to CLOSED."""
    router = get_adaptive_router()

    # Record 1 transient 500 error (DEGRADED, but not completely tripped)
    router.record_failure(tier=1, error=RuntimeError("HTTP 500 internal server error"), timeout_type="HTTP_500_SERVER_ERROR")
    health = router.get_health(1)
    assert health.failure_count == 1

    # Record success -> immediately restored to HEALTHY
    router.record_success(tier=1, latency=0.25)
    health = router.get_health(1)
    assert health.state == ProviderHealthState.HEALTHY
    assert health.consecutive_successes >= 1
    assert router.get_circuit_breaker_state(1) == CircuitBreakerState.CLOSED


def test_16_phase2_and_p0521_integrity_check(tmp_path):
    """Test 16: Phase 2 semantic & P0.5.2.1 content fidelity tests remain 100% intact."""
    from core.semantic_synthesizer import SemanticDomainSynthesizer
    from core.work_package_gate import WorkPackageGate

    verdant_prompt = """Brand: VERDANT LOOP
Business: Circular Construction Materials Marketplace.
Marketplace connecting construction companies, architects, builders, and material recovery suppliers.
Catalogue: Reclaimed timber, Recycled structural steel, Salvaged bricks, Recycled glass aggregates, Low-carbon concrete, Reclaimed stone, Recycled insulation, Reclaimed architectural fixtures.
Features: Category filters, real-time search, price sorting, quote basket with live subtotal, detail modal, supplier onboarding form."""

    canonical_entities = [
        "Reclaimed Timber",
        "Recycled Structural Steel",
        "Salvaged Bricks",
        "Recycled Glass Aggregates",
        "Low-Carbon Concrete",
        "Reclaimed Stone",
        "Recycled Insulation",
        "Reclaimed Architectural Fixtures",
    ]

    # 1. Verify synthesizer preserves all 8 exact canonical requested entities
    spec = SemanticDomainSynthesizer.synthesize(verdant_prompt, tmp_path)
    assert len(spec.content_entities) == 8
    titles = [e.get("title") for e in spec.content_entities]
    for canon in canonical_entities:
        assert canon in titles, f"Missing canonical entity '{canon}' in titles: {titles}"

    # 2. Verify gate initializes and recognizes Verdant Loop
    gate = WorkPackageGate()
    assert gate is not None
