# tests/test_persistence_journal.py
import pytest
from core.persistence.database import SQLiteDatabase
from core.persistence.journal import EventJournal
from core.persistence.models import SessionStatus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, TaskStatus


def test_journal_monotonic_append(tmp_path):
    db = SQLiteDatabase(tmp_path / "test.db")
    db.save_session("sess_j", "m_1", str(tmp_path), SessionStatus.RUNNING, 0.0, 0.0)
    journal = EventJournal(db)

    ev1 = HermesEvent(event_type=EventType.TASK_CREATED, payload={"task_id": "t1", "title": "Setup"})
    ev2 = HermesEvent(event_type=EventType.TASK_STARTED, payload={"task_id": "t1"})

    seq1 = journal.append("sess_j", ev1)
    seq2 = journal.append("sess_j", ev2)

    assert seq1 == 1
    assert seq2 == 2

    events = journal.get_events("sess_j")
    assert len(events) == 2
    assert events[0].sequence == 1
    assert events[1].sequence == 2
    assert events[0].event_type == EventType.TASK_CREATED


def test_journal_replay_without_tool_execution(tmp_path):
    db = SQLiteDatabase(tmp_path / "test.db")
    from core.persistence.models import SessionStatus
    db.save_session("sess_replay", "m_rep", str(tmp_path), SessionStatus.RUNNING, 0.0, 0.0)
    journal = EventJournal(db)

    journal.append("sess_replay", HermesEvent(event_type=EventType.TASK_CREATED, payload={"task_id": "t1", "title": "Build UI"}))
    journal.append("sess_replay", HermesEvent(event_type=EventType.TASK_STARTED, payload={"task_id": "t1"}))
    journal.append("sess_replay", HermesEvent(event_type=EventType.TASK_COMPLETED, payload={"task_id": "t1"}))

    initial_state = HermesRuntimeState.create_empty("m_rep", "sess_replay")
    final_state = journal.replay("sess_replay", initial_state)

    assert "t1" in final_state.tasks
    assert final_state.tasks["t1"].status == TaskStatus.COMPLETED
