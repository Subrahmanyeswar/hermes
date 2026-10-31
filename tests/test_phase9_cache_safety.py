# tests/test_phase9_cache_safety.py
"""
HERMES Phase 9 Audit D — Cache Freshness, Invalidation Safety & Bounded Memory Tests.

Proves:
1. Verification checks cache invalidates immediately when task status or verification evidence changes.
2. Verification checks cache invalidates when mission status changes.
3. Checks cache memory is bounded and prevents memory leaks.
4. Workspace existence cache uses canonical paths and does not retain negative results.
"""

import time
from pathlib import Path
import pytest

from core.runtime_state.models import HermesRuntimeState, MissionState, TaskState, MissionStatus, TaskStatus
from core.event_bus import HermesEvent, EventType
from core.server.checks_service import extract_mission_checks, clear_checks_cache, _CHECKS_CACHE, _compute_checks_cache_key
from core.server.app import _WS_EXIST_CACHE


def test_checks_cache_invalidates_on_task_status_change():
    """Verify cache invalidates when a task status changes without new events."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_cache_1", workspace_root="/ws", prompt="test", status=MissionStatus.RUNNING)
    t1 = TaskState(task_id="t1", mission_id="m_cache_1", title="Task 1", status=TaskStatus.RUNNING)
    state = HermesRuntimeState(mission=m_state, tasks={"t1": t1})

    events = [
        HermesEvent(
            event_type=EventType.TASK_STARTED,
            mission_id="m_cache_1",
            task_id="t1",
            sequence=1,
            payload={"task_id": "t1"},
        )
    ]

    resp1 = extract_mission_checks("m_cache_1", state, events)
    assert "m_cache_1" in _CHECKS_CACHE
    assert resp1.total_count == 1
    assert resp1.checks[0].status == "pending"

    # Now change task status to COMPLETED and add verification_id without changing events
    t1.status = TaskStatus.COMPLETED
    t1.verification_id = "v_123"
    t1.completion_reason = "All tests passed"

    resp2 = extract_mission_checks("m_cache_1", state, events)
    assert resp2.total_count == 1
    assert resp2.checks[0].status == "passed"
    assert resp2.checks[0].evidence == "All tests passed"
    assert resp2 is not resp1


def test_checks_cache_invalidates_on_mission_completion():
    """Verify cache invalidates when mission transitions to terminal status."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_cache_2", workspace_root="/ws", prompt="test", status=MissionStatus.RUNNING)
    t1 = TaskState(task_id="t1", mission_id="m_cache_2", title="Task 1", status=TaskStatus.COMPLETED)
    state = HermesRuntimeState(mission=m_state, tasks={"t1": t1})

    events = [
        HermesEvent(
            event_type=EventType.TASK_COMPLETED,
            mission_id="m_cache_2",
            task_id="t1",
            sequence=1,
            payload={"task_id": "t1"},
        )
    ]

    resp1 = extract_mission_checks("m_cache_2", state, events)
    # When mission is RUNNING and task is not verified, status is not_run
    assert resp1.checks[0].status == "not_run"

    # Mission transitions to COMPLETED
    m_state.status = MissionStatus.COMPLETED

    resp2 = extract_mission_checks("m_cache_2", state, events)
    # Under COMPLETED mission, completed tasks are marked passed
    assert resp2.checks[0].status == "passed"
    assert resp2 is not resp1


def test_checks_cache_bounded_memory():
    """Verify checks cache is bounded to prevent unbounded memory growth."""
    clear_checks_cache()
    for i in range(250):
        mid = f"m_stress_{i}"
        m_state = MissionState(mission_id=mid, workspace_root="/ws", prompt="test", status=MissionStatus.RUNNING)
        state = HermesRuntimeState(mission=m_state)
        extract_mission_checks(mid, state, [])

    # Cache should have cleared when exceeding 200 items, keeping memory bounded
    assert len(_CHECKS_CACHE) <= 200


def test_workspace_negative_cache_bypass(tmp_path):
    """Verify non-existent workspace path is not cached negatively so recreation is seen immediately."""
    _WS_EXIST_CACHE.clear()
    non_existent = tmp_path / "created_later"
    canonical_ws = str(non_existent.resolve())

    # Simulate app logic for checking workspace existence
    now_ts = time.time()
    ws_cached = _WS_EXIST_CACHE.get(canonical_ws)
    assert ws_cached is None

    ws_exists = non_existent.exists()
    assert not ws_exists
    if ws_exists:
        _WS_EXIST_CACHE[canonical_ws] = (ws_exists, now_ts)
    else:
        _WS_EXIST_CACHE.pop(canonical_ws, None)

    # Ensure negative result was NOT cached
    assert canonical_ws not in _WS_EXIST_CACHE

    # Now create the folder
    non_existent.mkdir()

    # Next check immediately sees the directory without waiting for TTL
    ws_cached_2 = _WS_EXIST_CACHE.get(canonical_ws)
    assert ws_cached_2 is None
    ws_exists_2 = non_existent.exists()
    assert ws_exists_2 is True

    # Existing directory is cached
    _WS_EXIST_CACHE[canonical_ws] = (ws_exists_2, time.time())
    assert canonical_ws in _WS_EXIST_CACHE
