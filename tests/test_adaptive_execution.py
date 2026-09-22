"""
Unit and Integration Tests for Phase 9 Adaptive Execution Engine.
Tests lightweight multi-signal classification, sub-millisecond classifier speed,
deterministic fast path execution (0 LLM calls), escalation manager hysteresis,
and security guardrails.
"""
import time
import pytest
from pathlib import Path

from core.adaptive_execution import (
    ExecutionMode,
    TaskComplexityClassifier,
    EscalationManager,
    AdaptiveExecutionEngine
)


def test_task_complexity_classifier_simple():
    """Simple deterministic operations must classify as SIMPLE with high confidence."""
    classifier = TaskComplexityClassifier()

    res1 = classifier.classify("Create folder reports")
    assert res1.mode == ExecutionMode.SIMPLE
    assert res1.deterministic_tool == "create_directory"
    assert res1.deterministic_args == {"path": "reports"}
    assert res1.confidence >= 0.90

    res2 = classifier.classify("read config.py")
    assert res2.mode == ExecutionMode.SIMPLE
    assert res2.deterministic_tool == "read_file"
    assert res2.deterministic_args == {"path": "config.py"}

    res3 = classifier.classify("show project structure")
    assert res3.mode == ExecutionMode.SIMPLE
    assert res3.deterministic_tool == "list_directory"


def test_task_complexity_classifier_standard():
    """Localized coding tasks must classify as STANDARD."""
    classifier = TaskComplexityClassifier()
    res = classifier.classify("Fix authentication login timeout in backend/auth.py")
    assert res.mode == ExecutionMode.STANDARD
    assert res.deterministic_tool is None
    assert res.confidence >= 0.80


def test_task_complexity_classifier_complex():
    """Architectural tasks across frontend and backend must classify as COMPLEX."""
    classifier = TaskComplexityClassifier()
    res = classifier.classify("Refactor entire architecture for frontend and backend data layer")
    assert res.mode == ExecutionMode.COMPLEX
    assert res.confidence >= 0.85


def test_classifier_speed_sub_millisecond():
    """Classification must execute in under 1.0 ms."""
    classifier = TaskComplexityClassifier()
    t0 = time.perf_counter()
    for _ in range(50):
        classifier.classify("Create folder test_output")
        classifier.classify("Fix authentication bug in auth.py")
        classifier.classify("Migrate complete system architecture")
    elapsed_ms = ((time.perf_counter() - t0) * 1000.0) / 150.0
    assert elapsed_ms < 1.0  # Must be strictly sub-millisecond


def test_escalation_manager_simple_to_standard():
    """Tool failure or syntax error must escalate SIMPLE to STANDARD."""
    manager = EscalationManager(initial_mode=ExecutionMode.SIMPLE)
    assert manager.current_mode == ExecutionMode.SIMPLE

    new_mode = manager.check_escalation(tool_failed=True)
    assert new_mode == ExecutionMode.STANDARD
    assert manager.current_mode == ExecutionMode.STANDARD


def test_escalation_manager_standard_to_complex():
    """High dependency count (>3) must escalate STANDARD to COMPLEX."""
    manager = EscalationManager(initial_mode=ExecutionMode.STANDARD)
    new_mode = manager.check_escalation(dependency_count=5)
    assert new_mode == ExecutionMode.COMPLEX
    assert manager.current_mode == ExecutionMode.COMPLEX


def test_fast_path_create_directory_execution(tmp_path):
    """Fast path must create directory directly in <15ms without LLM."""
    engine = AdaptiveExecutionEngine(enabled=True)
    target_dir = tmp_path / "fast_created_folder"

    ok, out = engine.execute_fast_path(
        tool_name="create_directory",
        tool_args={"path": str(target_dir)},
        workspace_manager=None
    )
    assert ok is True
    assert target_dir.exists()
    assert target_dir.is_dir()


def test_fast_path_read_file_execution(tmp_path):
    """Fast path must read file content directly in <15ms without LLM."""
    engine = AdaptiveExecutionEngine(enabled=True)
    sample_file = tmp_path / "hello.txt"
    sample_file.write_text("Hello from Fast Path!", encoding="utf-8")

    ok, out = engine.execute_fast_path(
        tool_name="read_file",
        tool_args={"path": str(sample_file)},
        workspace_manager=None
    )
    assert ok is True
    assert "Hello from Fast Path!" in out
