"""
Unit and Quality Tests for Phase 6.3 Task-Aware Reasoning & Generation Budget Manager.
Validates L0-L4 complexity classification, token budgets, truncation detection,
automatic single-step escalation, and rollback feature flag.
"""
import pytest
from core.reasoning_budget import ReasoningBudgetManager, ComplexityLevel, BudgetProfile


def test_classify_complexity_l0_direct():
    """Simple directory listing or read-only check must classify as L0_DIRECT."""
    mgr = ReasoningBudgetManager(enabled=True)
    level = mgr.classify_complexity(
        task_description="List all files in generated_projects",
        tools_needed=["list_directory"],
        permission_level="read_only",
        planner_complexity=0.2
    )
    assert level == ComplexityLevel.L0_DIRECT
    budget = mgr.get_budget(level)
    assert budget.num_predict == 768
    assert budget.timeout_seconds == 45


def test_classify_complexity_l1_simple():
    """Simple file creation must classify as L1_SIMPLE."""
    mgr = ReasoningBudgetManager(enabled=True)
    level = mgr.classify_complexity(
        task_description="Create a simple file helper.py with an add function",
        tools_needed=["write_file"],
        permission_level="write",
        planner_complexity=0.4
    )
    assert level == ComplexityLevel.L1_SIMPLE
    budget = mgr.get_budget(level)
    assert budget.num_predict == 1536
    assert budget.timeout_seconds == 75


def test_classify_complexity_l2_normal():
    """Standard coding task must classify as L2_NORMAL."""
    mgr = ReasoningBudgetManager(enabled=True)
    level = mgr.classify_complexity(
        task_description="Implement a UserAuthenticationService class with login and logout methods",
        tools_needed=["write_file"],
        permission_level="write",
        planner_complexity=0.55
    )
    assert level == ComplexityLevel.L2_NORMAL
    budget = mgr.get_budget(level)
    assert budget.num_predict == 2560
    assert budget.timeout_seconds == 120


def test_classify_complexity_l3_complex():
    """Multi-file refactoring or algorithmic tasks must classify as L3_COMPLEX."""
    mgr = ReasoningBudgetManager(enabled=True)
    level = mgr.classify_complexity(
        task_description="Refactor the multi-file router and verifier pipeline to optimize algorithm throughput",
        tools_needed=["read_file", "write_file", "git_diff"],
        permission_level="write",
        planner_complexity=0.75
    )
    assert level == ComplexityLevel.L3_COMPLEX
    budget = mgr.get_budget(level)
    assert budget.num_predict == 4096
    assert budget.timeout_seconds == 180


def test_classify_complexity_l4_very_complex():
    """Architecture redesign, security audits, or concurrency must classify as L4_VERY_COMPLEX."""
    mgr = ReasoningBudgetManager(enabled=True)
    level = mgr.classify_complexity(
        task_description="Perform system architecture redesign and fix distributed concurrency race conditions",
        tools_needed=["read_file", "write_file", "execute_command"],
        permission_level="write",
        planner_complexity=0.9
    )
    assert level == ComplexityLevel.L4_VERY_COMPLEX
    budget = mgr.get_budget(level)
    assert budget.num_predict == 8192
    assert budget.timeout_seconds == 240


def test_truncation_detection():
    """Detects output truncation when token limit is reached with unclosed think or JSON tags."""
    mgr = ReasoningBudgetManager(enabled=True)
    budget = mgr.get_budget(ComplexityLevel.L0_DIRECT)

    # Case 1: Unclosed <think> tag at limit -> Truncated
    truncated_raw_1 = "<think>I need to check the files in directory but"
    assert mgr.check_truncation(truncated_raw_1, output_tokens=760, budget=budget) is True

    # Case 2: Complete clean response -> Not truncated
    clean_raw = "<think>Done</think>```json\n{\"tool_name\": \"list_directory\", \"parameters\": {\"path\": \".\"}}\n```"
    assert mgr.check_truncation(clean_raw, output_tokens=400, budget=budget) is False

    # Case 3: Unclosed JSON at limit -> Truncated
    truncated_json = "<think>Done</think>```json\n{\"tool_name\": \"list_directory\", \"parameters\": {"
    assert mgr.check_truncation(truncated_json, output_tokens=765, budget=budget) is True


def test_budget_escalation():
    """Escalates complexity levels by exactly +1 tier without skipping."""
    mgr = ReasoningBudgetManager(enabled=True)
    assert mgr.escalate_budget(ComplexityLevel.L0_DIRECT) == ComplexityLevel.L1_SIMPLE
    assert mgr.escalate_budget(ComplexityLevel.L1_SIMPLE) == ComplexityLevel.L2_NORMAL
    assert mgr.escalate_budget(ComplexityLevel.L2_NORMAL) == ComplexityLevel.L3_COMPLEX
    assert mgr.escalate_budget(ComplexityLevel.L3_COMPLEX) == ComplexityLevel.L4_VERY_COMPLEX
    assert mgr.escalate_budget(ComplexityLevel.L4_VERY_COMPLEX) == ComplexityLevel.L4_VERY_COMPLEX


def test_feature_flag_rollback():
    """When ADAPTIVE_T1_BUDGET_ENABLED=False, get_budget returns unconstrained 8192 token limit."""
    mgr = ReasoningBudgetManager(enabled=False)
    budget = mgr.get_budget(ComplexityLevel.L0_DIRECT)
    assert budget.num_predict == 8192
    assert budget.timeout_seconds == 180
    assert mgr.check_truncation("<think>test", 760, budget) is False
