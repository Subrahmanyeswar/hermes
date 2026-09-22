"""
Unit and Integration Tests for Phase 6.4 Model Switching & Foreground Residency Optimization.
Validates single-model VRAM management, warm model reuse, foreground priority locking,
switch tracking, and rollback feature flag.
"""
import pytest
import asyncio
from core.model_residency_manager import ModelResidencyManager, ModelLifecycleState
from config.model_config import TIER1_MODEL, TIER2_MODEL, T1_KEEP_ALIVE, T2_KEEP_ALIVE


@pytest.mark.asyncio
async def test_first_model_acquire_and_release():
    """First acquire of T1 must set active model, track switch, and release cleanly to RESIDENT."""
    mgr = ModelResidencyManager(enabled=True)
    ka = await mgr.acquire_model(TIER1_MODEL, is_foreground=True)
    assert ka == T1_KEEP_ALIVE
    assert mgr.active_model == TIER1_MODEL
    assert mgr.total_switches == 1
    assert mgr.switches_avoided == 0

    state = mgr.get_state()
    assert state["active_model"] == TIER1_MODEL
    assert state["state"] == "IN_USE"

    mgr.release_model(TIER1_MODEL, is_foreground=True)
    state_after = mgr.get_state()
    assert state_after["state"] == "RESIDENT"
    assert state_after["foreground_in_progress"] is False


@pytest.mark.asyncio
async def test_warm_model_reuse_zero_switches():
    """Re-acquiring the active model must avoid switch penalty and increment switches_avoided."""
    mgr = ModelResidencyManager(enabled=True)
    await mgr.acquire_model(TIER1_MODEL, is_foreground=True)
    mgr.release_model(TIER1_MODEL, is_foreground=True)

    # Acquire again (warm reuse)
    ka2 = await mgr.acquire_model(TIER1_MODEL, is_foreground=True)
    assert ka2 == T1_KEEP_ALIVE
    assert mgr.total_switches == 1  # No new switch!
    assert mgr.switches_avoided == 1  # Avoided!
    mgr.release_model(TIER1_MODEL, is_foreground=True)


@pytest.mark.asyncio
async def test_model_switch_tracking():
    """Switching between T1 and T2 must track switch count and model state."""
    mgr = ModelResidencyManager(enabled=True)
    await mgr.acquire_model(TIER1_MODEL, is_foreground=True)
    mgr.release_model(TIER1_MODEL, is_foreground=True)

    # Switch to T2
    ka_t2 = await mgr.acquire_model(TIER2_MODEL, is_foreground=True)
    assert ka_t2 == T2_KEEP_ALIVE
    assert mgr.active_model == TIER2_MODEL
    assert mgr.total_switches == 2
    mgr.release_model(TIER2_MODEL, is_foreground=True)

    # Switch back to T1
    ka_t1 = await mgr.acquire_model(TIER1_MODEL, is_foreground=True)
    assert ka_t1 == T1_KEEP_ALIVE
    assert mgr.active_model == TIER1_MODEL
    assert mgr.total_switches == 3
    mgr.release_model(TIER1_MODEL, is_foreground=True)


@pytest.mark.asyncio
async def test_foreground_priority_guard():
    """Background acquire of T1 must yield while foreground is actively executing with T2."""
    mgr = ModelResidencyManager(enabled=True)
    # Foreground holds T2
    await mgr.acquire_model(TIER2_MODEL, is_foreground=True)

    bg_started = False
    bg_finished = False

    async def bg_worker():
        nonlocal bg_started, bg_finished
        bg_started = True
        await mgr.acquire_model(TIER1_MODEL, is_foreground=False)
        bg_finished = True
        mgr.release_model(TIER1_MODEL, is_foreground=False)

    task = asyncio.create_task(bg_worker())
    await asyncio.sleep(0.05)
    assert bg_started is True
    # Foreground is still active, background should not immediately take over
    mgr.release_model(TIER2_MODEL, is_foreground=True)
    await task
    assert bg_finished is True


@pytest.mark.asyncio
async def test_concurrent_acquisition_lock():
    """Concurrent tasks requesting T1 must be handled safely without race conditions."""
    mgr = ModelResidencyManager(enabled=True)

    async def worker():
        await mgr.acquire_model(TIER1_MODEL, is_foreground=True)
        await asyncio.sleep(0.01)
        mgr.release_model(TIER1_MODEL, is_foreground=True)

    await asyncio.gather(worker(), worker(), worker())
    assert mgr.total_switches == 1
    assert mgr.switches_avoided == 2


@pytest.mark.asyncio
async def test_feature_flag_rollback():
    """When OPTIMIZED_MODEL_RESIDENCY_ENABLED=False, returns standard fallback keep-alive."""
    mgr = ModelResidencyManager(enabled=False)
    ka = await mgr.acquire_model(TIER1_MODEL, is_foreground=True)
    assert ka == "300s"
    assert mgr.total_switches == 0
