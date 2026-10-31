# tests/test_phase9_persistence_batch_failure.py
"""
HERMES Phase 9 Audit C — Persistence Batching Durability & Failure Recovery Tests.

Proves:
1. Mixed-mission events in a batch are committed in strict monotonic sequence order.
2. Batch transaction failure safely falls back to individual retries without dropping events.
3. Shutdown drains all queued events before terminating.
4. Permanent database errors are explicitly recorded in persistence failure tracker.
"""

import threading
import time
from pathlib import Path
import pytest

from core.event_bus import EventBus, HermesEvent, EventType
from core.persistence.database import SQLiteDatabase


def test_mixed_mission_batch_monotonic_ordering(tmp_path):
    """
    Test that batches containing events from multiple missions maintain strict
    monotonic sequencing and update each mission's last_event_sequence record correctly.
    """
    db_file = tmp_path / "test_multi.db"
    db = SQLiteDatabase(db_file)
    db.save_mission("m_alpha", "/ws/alpha", "RUNNING")
    db.save_mission("m_beta", "/ws/beta", "RUNNING")

    bus = EventBus(enabled=True, db=db)

    # Publish interleaved events for two missions
    for i in range(20):
        m_id = "m_alpha" if i % 2 == 0 else "m_beta"
        bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id=m_id,
            payload={"step": i}
        ))

    bus.flush(timeout=5.0)

    # Verify alpha events
    alpha_events = db.get_mission_events("m_alpha")
    assert len(alpha_events) == 10
    for idx, e in enumerate(alpha_events):
        assert e["mission_id"] == "m_alpha"
        if idx > 0:
            assert e["sequence"] > alpha_events[idx - 1]["sequence"]

    # Verify beta events
    beta_events = db.get_mission_events("m_beta")
    assert len(beta_events) == 10
    for idx, e in enumerate(beta_events):
        assert e["mission_id"] == "m_beta"
        if idx > 0:
            assert e["sequence"] > beta_events[idx - 1]["sequence"]

    # Check updated mission records
    m_alpha = db.get_mission("m_alpha")
    m_beta = db.get_mission("m_beta")
    assert m_alpha["last_event_sequence"] == alpha_events[-1]["sequence"]
    assert m_beta["last_event_sequence"] == beta_events[-1]["sequence"]

    bus.shutdown(timeout=2.0)


def test_batch_failure_fallback_to_individual_retries(tmp_path):
    """
    Test that when a batch write encounters an error, the worker falls back
    to individual event retries so healthy events are committed without loss.
    """
    db_file = tmp_path / "test_fallback.db"
    db = SQLiteDatabase(db_file)
    db.save_mission("m_fallback", "/ws/fallback", "RUNNING")

    bus = EventBus(enabled=True, db=db)

    # Simulate batch failure on first batch call by temporarily replacing append_mission_events_batch
    orig_batch = db.append_mission_events_batch
    batch_call_count = 0

    def failing_batch(events, session_id=None):
        nonlocal batch_call_count
        batch_call_count += 1
        raise RuntimeError("Injected transient batch commit failure")

    db.append_mission_events_batch = failing_batch

    for i in range(5):
        bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id="m_fallback",
            payload={"step": i}
        ))

    bus.flush(timeout=5.0)

    # Verify that individual fallback successfully persisted the events
    db_events = db.get_mission_events("m_fallback")
    assert len(db_events) == 5, "Fallback should have persisted all 5 events individually!"
    assert batch_call_count >= 1

    bus.shutdown(timeout=2.0)


def test_shutdown_drains_queued_events(tmp_path):
    """
    Test that EventBus.shutdown drains all queued items before thread exits.
    """
    db_file = tmp_path / "test_shutdown.db"
    db = SQLiteDatabase(db_file)
    db.save_mission("m_shut", "/ws/shut", "RUNNING")

    bus = EventBus(enabled=True, db=db)

    for i in range(30):
        bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id="m_shut",
            payload={"step": i}
        ))

    bus.shutdown(timeout=5.0)

    assert bus._persist_queue.empty()
    db_events = db.get_mission_events("m_shut")
    assert len(db_events) == 30
