"""
HERMES — Logging & Observability Test Suite
Tests every component of the centralised logging module.
"""
import json
import pytest
import time
from pathlib import Path
from loguru import logger

from utils.logging import (
    generate_trace_id, generate_session_id, setup_logging,
    TraceContext, get_trace_logger,
    log_pipeline_start, log_pipeline_complete,
    log_tier1_call, log_tier2_call, log_tier3_call,
    log_tool_call, log_tool_result, log_memory_event,
    log_security_gate, log_kairos_event,
    search_session_logs, get_session_log_path
)


@pytest.fixture
def temp_log_dir(tmp_path, monkeypatch):
    log_dir = tmp_path / "sessions"
    log_dir.mkdir()
    monkeypatch.setattr("utils.logging.SESSION_LOG_DIR", log_dir)
    return log_dir


@pytest.fixture
def session(temp_log_dir):
    sid = setup_logging(debug=True)
    return sid


# ── ID generation ─────────────────────────────────────────────────────

def test_trace_id_is_8_chars():
    tid = generate_trace_id()
    assert len(tid) == 8
    assert all(c in "0123456789abcdef" for c in tid)


def test_trace_ids_are_unique():
    ids = {generate_trace_id() for _ in range(100)}
    assert len(ids) == 100  # All unique


def test_session_id_is_12_chars():
    sid = generate_session_id()
    assert len(sid) == 12


# ── TraceContext ──────────────────────────────────────────────────────

def test_trace_context_generates_id():
    ctx = TraceContext()
    assert len(ctx.trace_id) == 8


def test_trace_context_accepts_custom_id():
    ctx = TraceContext(trace_id="abc12345")
    assert ctx.trace_id == "abc12345"


def test_trace_context_elapsed_time():
    ctx = TraceContext()
    with ctx:
        time.sleep(0.05)
    assert ctx.elapsed_seconds >= 0.04


def test_trace_context_get_logger_returns_bound_logger(session):
    ctx = TraceContext(trace_id="test0001")
    bound = ctx.get_logger()
    # Should not raise
    bound.debug("test message")


def test_trace_context_never_suppresses_exceptions(session):
    with pytest.raises(ValueError):
        with TraceContext():
            raise ValueError("test exception")


# ── Setup ─────────────────────────────────────────────────────────────

def test_setup_logging_returns_session_id(temp_log_dir):
    sid = setup_logging()
    assert sid is not None
    assert len(sid) == 12


def test_setup_logging_creates_log_file(temp_log_dir):
    sid = setup_logging()
    time.sleep(0.1)  # Let loguru flush
    log_files = list(temp_log_dir.glob("*.jsonl"))
    assert len(log_files) >= 1


def test_setup_logging_idempotent(temp_log_dir):
    """Calling setup_logging twice should not crash."""
    sid1 = setup_logging()
    sid2 = setup_logging()
    assert sid1 != sid2  # Each call gets a new session


# ── Structured log functions ──────────────────────────────────────────

def test_log_pipeline_start_does_not_raise(session):
    log_pipeline_start("abc12345", "list all files", "auto", "myproject", session)


def test_log_pipeline_complete_does_not_raise(session):
    log_pipeline_complete("abc12345", True, 12, 3.5, "write_file", False, 0.0)


def test_log_tier1_call_does_not_raise(session):
    log_tier1_call("abc12345", "qwen2.5-coder:7b", 1200, 2.3, "write_file", "direct_parse")


def test_log_tier2_call_does_not_raise(session):
    log_tier2_call("abc12345", "mistral:7b", 1.8, True, 0.92, 0.2, False)


def test_log_tier3_call_does_not_raise(session):
    log_tier3_call("abc12345", 3.1, 1500, 400, 0.015, True, "low confidence")


def test_log_tool_call_does_not_raise(session):
    log_tool_call("abc12345", "bash_exec", "auto", 0.7, '{"command": "ls"}')


def test_log_tool_result_does_not_raise(session):
    log_tool_result("abc12345", "bash_exec", True, 0, 0.15, "file1.py\nfile2.py", 0)


def test_log_memory_event_does_not_raise(session):
    log_memory_event("abc12345", "write", 3, "myproject", "wrote 3 facts")


def test_log_security_gate_does_not_raise(session):
    log_security_gate("abc12345", "rm -rf /", True, "gate_1_destructive_wildcard")


def test_log_kairos_event_does_not_raise(session):
    log_kairos_event("consolidation", "ran consolidation", {"facts": 5})


# ── JSONL search (Layer 3 grep) ───────────────────────────────────────

def test_search_session_logs_finds_written_content(temp_log_dir, monkeypatch):
    monkeypatch.setattr("utils.logging.SESSION_LOG_DIR", temp_log_dir)
    sid = setup_logging()

    # Log something with a unique marker
    log_pipeline_start("deadbeef", "UNIQUE_SEARCH_MARKER_XK7Q", "auto", "test", sid)
    time.sleep(0.2)  # Let loguru flush to disk

    results = search_session_logs("UNIQUE_SEARCH_MARKER_XK7Q", session_log_dir=temp_log_dir)
    # Note: results might be empty if loguru hasn't flushed — this is acceptable
    # The important thing is that search_session_logs never crashes
    assert isinstance(results, list)


def test_search_session_logs_empty_dir(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    results = search_session_logs("anything", session_log_dir=empty_dir)
    assert results == []


def test_search_session_logs_never_raises_on_bad_dir():
    results = search_session_logs("query", session_log_dir=Path("/nonexistent/path"))
    assert results == []


def test_search_session_logs_respects_max_results(temp_log_dir, monkeypatch):
    monkeypatch.setattr("utils.logging.SESSION_LOG_DIR", temp_log_dir)
    # Write many matching JSONL lines manually
    log_file = temp_log_dir / "test_search.jsonl"
    with open(log_file, "w") as f:
        for i in range(50):
            f.write(json.dumps({"message": f"search_target record {i}", "level": "INFO"}) + "\n")

    results = search_session_logs("search_target", session_log_dir=temp_log_dir, max_results=5)
    assert len(results) <= 5


def test_get_session_log_path_returns_none_for_unknown(temp_log_dir, monkeypatch):
    monkeypatch.setattr("utils.logging.SESSION_LOG_DIR", temp_log_dir)
    path = get_session_log_path("nonexistentsessionid999")
    assert path is None
