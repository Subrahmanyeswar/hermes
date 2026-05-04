import pytest
from pathlib import Path
from memory.session_logger import SessionLogger, SessionEvent

@pytest.fixture
def logger_instance(tmp_path, monkeypatch):
    monkeypatch.setattr("memory.session_logger.SESSION_LOG_DIR", tmp_path / "sessions")
    return SessionLogger(session_id="test001")

def test_session_logger_creates_log_file(logger_instance, tmp_path):
    logger_instance.log_user_input("build a flask app")
    log_files = list((tmp_path / "sessions").glob("*.jsonl"))
    assert len(log_files) == 1

def test_log_user_input_writes_correct_event(logger_instance, tmp_path):
    logger_instance.log_user_input("create a python script")
    events = logger_instance.get_recent_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "user_input"
    assert events[0]["prompt"] == "create a python script"

def test_log_tool_result_is_retrievable(logger_instance):
    logger_instance.log_tool_call("write_file", {"path": "app.py"}, "auto")
    logger_instance.log_tool_result("write_file", True, 0, "Written 500 chars", 0.05)
    
    tool_results = logger_instance.get_recent_events(event_type="tool_result")
    assert len(tool_results) == 1
    assert tool_results[0]["tool_name"] == "write_file"
    assert tool_results[0]["exit_code"] == 0

def test_multiple_events_are_ordered(logger_instance):
    logger_instance.log_user_input("task 1")
    logger_instance.log_user_input("task 2")
    logger_instance.log_user_input("task 3")
    
    events = logger_instance.get_recent_events(limit=10)
    assert len(events) == 3
    assert events[-1]["prompt"] == "task 3"

def test_get_recent_events_respects_limit(logger_instance):
    for i in range(10):
        logger_instance.log_user_input(f"task {i}")
    
    events = logger_instance.get_recent_events(limit=3)
    assert len(events) == 3

def test_get_recent_events_empty_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("memory.session_logger.SESSION_LOG_DIR", tmp_path / "sessions")
    logger = SessionLogger(session_id="brand_new")
    # No events written yet
    events = logger.get_recent_events()
    assert events == []

def test_session_logger_never_raises_on_write_error(logger_instance, monkeypatch):
    """Logger should log warning but never raise if write fails."""
    def bad_open(*args, **kwargs):
        raise PermissionError("disk full")
    monkeypatch.setattr("builtins.open", bad_open)
    # Should not raise — should silently handle
    try:
        logger_instance.log_user_input("this should not crash")
    except Exception as e:
        pytest.fail(f"SessionLogger raised an exception: {e}")
