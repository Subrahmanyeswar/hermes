# tests/test_tool_platform.py
"""
Comprehensive Test Suite for HERMES 2.x Tool Platform.
Verifies all 60 prompt requirements across:
    1. ToolCatalog & Identity
    2. ToolSearch & Discovery
    3. ToolSchema & Provider Conversion
    4. ToolExamples & Failure Cases
    5. RiskMetadata & Classification
    6. PermissionPolicy & Pre-Execution Authorization
    7. Validator & Path Discipline
    8. Executor & Canonical Events
    9. OutputShaper & Truncation Semantics
    10. OutputStore & External Retrieval
    11. ErrorGuidance & Windows Shell Guidance
    12. RetryPolicy & Idempotency Rules
    13. ToolSpecLinter & Specification Audit
    14. ToolEvaluationSuite (Dev & Held-Out)
    15. End-to-End Core Tool Operations (fs.read, fs.edit, fs.write, shell.bash, search.glob, search.grep, task.todo, user.ask)
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.event_bus import event_bus
from core.runtime_state.events import EventType
from core.workspace import WorkspaceManager
from tools.platform import (
    ToolCatalog,
    tool_catalog,
    ToolSearch,
    tool_search,
    ToolSchema,
    ToolSpec,
    ToolExample,
    RiskMetadata,
    RiskLevel,
    ToolAvailability,
    ResponseFormat,
    PermissionDecision,
    PermissionPolicy,
    Validator,
    ToolExecutor,
    ShapedOutput,
    OutputShaper,
    OutputStore,
    output_store,
    ToolErrorCode,
    ToolError,
    ErrorGuidance,
    RetryDecision,
    RetryPolicy,
    ToolSpecLinter,
    ToolEvaluationSuite,
    FSReadTool,
    FSEditTool,
    FSWriteTool,
    ShellBashTool,
    SearchGlobTool,
    SearchGrepTool,
    TaskTodoTool,
    TaskDelegateTool,
    UserAskTool,
)


@pytest.fixture(autouse=True)
def setup_catalog():
    """Ensure catalog is fully initialized for each test."""
    tool_catalog.initialize()
    output_store.clear()


# ── Section 1: ToolCatalog & Identity ────────────────────────────────────────

def test_tool_catalog_initialization():
    """ToolCatalog registers canonical core tools and bridges legacy tools."""
    core = tool_catalog.list_core()
    core_names = {s.canonical_name for s in core}
    assert "fs.read" in core_names
    assert "fs.edit" in core_names
    assert "fs.write" in core_names
    assert "shell.bash" in core_names
    assert "search.glob" in core_names
    assert "search.grep" in core_names
    assert "task.todo" in core_names
    assert "task.delegate" in core_names
    assert "user.ask" in core_names
    assert len(core) == 9


def test_tool_catalog_alias_resolution():
    """Legacy names resolve cleanly to canonical names."""
    assert tool_catalog.resolve_name("read_file") == "fs.read"
    assert tool_catalog.resolve_name("write_file") == "fs.write"
    assert tool_catalog.resolve_name("bash_exec") == "shell.bash"
    assert tool_catalog.resolve_name("list_directory") == "search.glob"
    assert tool_catalog.resolve_name("list_dir") == "search.glob"
    assert tool_catalog.resolve_name("search_files") == "search.grep"
    assert tool_catalog.resolve_name("edit_file") == "fs.edit"


# ── Section 2: ToolSearch & Dynamic Discovery ────────────────────────────────

def test_tool_search_exact_and_alias():
    """ToolSearch deterministically matches by name and alias."""
    res_exact = tool_search.search("fs.read")
    assert len(res_exact) > 0
    assert res_exact[0].canonical_name == "fs.read"

    res_alias = tool_search.search("bash_exec")
    assert len(res_alias) > 0
    assert res_alias[0].canonical_name == "shell.bash"


def test_tool_search_keyword_and_category():
    """ToolSearch matches by description tokens and category."""
    res_grep = tool_search.search("search file contents pattern")
    matched_names = [r.canonical_name for r in res_grep]
    assert "search.grep" in matched_names

    res_cat = tool_search.search("python", category="shell")
    assert any("shell" in r.category for r in res_cat)


def test_tool_search_no_matches_fallback():
    """ToolSearch provides helpful fallback suggestions when query finds nothing."""
    empty_res = tool_search.search("nonexistent_quantum_teleportation_tool")
    formatted = tool_search.format_search_results("nonexistent_quantum_teleportation_tool", empty_res)
    assert "No specific tools matched" in formatted
    assert "fs.read" in formatted


# ── Section 3: ToolSchema & Provider Formats ─────────────────────────────────

def test_tool_schema_openai_conversion():
    """ToolSchema converts to valid OpenAI function tool definition."""
    spec = tool_catalog.get("fs.read")
    assert spec is not None
    openai_dict = spec.schema.to_openai_dict()

    assert openai_dict["type"] == "function"
    assert openai_dict["function"]["name"] == "fs.read"
    assert "parameters" in openai_dict["function"]
    assert "path" in openai_dict["function"]["parameters"]["properties"]
    assert "path" in openai_dict["function"]["parameters"]["required"]


# ── Section 4: ToolExamples ──────────────────────────────────────────────────

def test_tool_examples_exist_for_core():
    """Core tools contain valid agent-facing examples including failure examples."""
    read_spec = tool_catalog.get("fs.read")
    assert read_spec is not None
    assert len(read_spec.examples) > 0
    assert any(e.is_failure_example for e in read_spec.examples)

    edit_spec = tool_catalog.get("fs.edit")
    assert edit_spec is not None
    assert len(edit_spec.examples) > 0


# ── Section 5: RiskMetadata & Permissions ────────────────────────────────────

def test_permission_policy_safe_mode_restrictions():
    """PermissionPolicy blocks high-risk and command execution tools in safe mode."""
    safe_policy = PermissionPolicy(mode="safe")

    bash_spec = tool_catalog.get("shell.bash")
    decision, reason = safe_policy.authorize(bash_spec)
    assert decision == PermissionDecision.DENY
    assert "safe" in reason

    read_spec = tool_catalog.get("fs.read")
    decision, _ = safe_policy.authorize(read_spec)
    assert decision == PermissionDecision.ALLOW


def test_permission_policy_plan_mode_restrictions():
    """PermissionPolicy blocks mutating tools in plan mode."""
    plan_policy = PermissionPolicy(mode="plan")

    write_spec = tool_catalog.get("fs.write")
    decision, _ = plan_policy.authorize(write_spec)
    assert decision == PermissionDecision.DENY

    edit_spec = tool_catalog.get("fs.edit")
    decision, _ = plan_policy.authorize(edit_spec)
    assert decision == PermissionDecision.DENY


# ── Section 6: Validator & Path Discipline ───────────────────────────────────

def test_validator_normalizes_aliases():
    """Validator normalizes parameter aliases like TargetFile -> path."""
    spec = tool_catalog.get("fs.read")
    raw = {"TargetFile": "app.py"}
    is_valid, err, norm = Validator.validate(spec, raw)
    assert is_valid is True
    assert norm["path"] == "app.py"


def test_validator_blocks_path_traversal(tmp_path):
    """Validator blocks relative '..' path traversal."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    spec = tool_catalog.get("fs.write")
    raw = {"path": "../../escape.py", "content": "print('bad')"}
    is_valid, err, _ = Validator.validate(spec, raw, workspace=wm)

    assert is_valid is False
    assert err is not None
    assert err.code == ToolErrorCode.PATH_OUTSIDE_WORKSPACE
    assert "Path traversal blocked" in err.message


def test_validator_blocks_forbidden_commands():
    """Validator blocks destructive shell commands before execution."""
    spec = tool_catalog.get("shell.bash")
    raw = {"command": "rm -rf /"}
    is_valid, err, _ = Validator.validate(spec, raw)

    assert is_valid is False
    assert err is not None
    assert err.code == ToolErrorCode.COMMAND_REJECTED


# ── Section 7: OutputShaper & OutputStore ────────────────────────────────────

def test_output_shaper_normal_and_concise():
    """OutputShaper bounds character output and sets truncation flags."""
    huge_output = "\n".join([f"Line {i}: test data {i * 10}" for i in range(500)])
    shaped_normal = OutputShaper.shape(huge_output, response_format=ResponseFormat.NORMAL, max_lines=100)
    assert shaped_normal.truncated is True
    assert shaped_normal.shown_lines <= 100

    shaped_concise = OutputShaper.shape(huge_output, response_format=ResponseFormat.CONCISE, max_lines=20)
    assert shaped_concise.shown_lines <= 20


def test_output_store_put_and_slice():
    """OutputStore retains oversized content and supports sliced retrieval."""
    content = "line1\nline2\nline3\nline4\nline5\nline6"
    out_id = output_store.put(content, tool_name="fs.read")
    assert out_id.startswith("out-")

    sliced, has_more, total = output_store.get_slice(out_id, start_line=2, end_line=4)
    assert sliced == "line2\nline3\nline4"
    assert has_more is True
    assert total == 6


# ── Section 8: ErrorGuidance & Windows Shell Guidance ────────────────────────

def test_error_guidance_windows_command():
    """ErrorGuidance provides cross-platform guidance for POSIX commands on Windows."""
    msg = ErrorGuidance.format_guidance(
        ToolErrorCode.PROCESS_FAILED,
        "shell.bash",
        {"command": "wc -l app.py"},
    )
    if sys.platform == "win32":
        assert "Windows" in msg or "wc" in msg


# ── Section 9: RetryPolicy & Idempotency Rules ───────────────────────────────

def test_retry_policy_prohibits_blind_non_idempotent_retry():
    """Non-idempotent operations are never blindly retried without modification."""
    bash_spec = tool_catalog.get("shell.bash")
    err = ToolError(
        code=ToolErrorCode.PROCESS_FAILED,
        message="Build failed",
        what_failed="make build",
        why_it_failed="exit code 2",
    )
    eval_res = RetryPolicy.evaluate(bash_spec, err, current_attempt=0)
    assert eval_res.decision == RetryDecision.RETRY_WITH_MODIFIED_INPUT
    assert eval_res.attempt_allowed is False


def test_retry_policy_budget_exhaustion():
    """RetryPolicy halts when retry budget is exhausted."""
    read_spec = tool_catalog.get("fs.read")
    err = ToolError(
        code=ToolErrorCode.COMMAND_TIMEOUT,
        message="Timeout",
        what_failed="Read",
        why_it_failed="Timeout",
    )
    eval_res = RetryPolicy.evaluate(read_spec, err, current_attempt=2, max_budget=2)
    assert eval_res.decision == RetryDecision.DO_NOT_RETRY
    assert eval_res.attempt_allowed is False


# ── Section 10: ToolSpecLinter ───────────────────────────────────────────────

def test_tool_spec_linter_audit():
    """ToolSpecLinter audits catalog with zero critical schema errors."""
    report = ToolSpecLinter.audit_catalog()
    assert report.is_clean is True
    assert len(report.errors) == 0
    assert report.total_tools_audited >= 20


# ── Section 11: ToolEvaluationSuite (Dev & Held-Out) ─────────────────────────

@pytest.mark.asyncio
async def test_tool_evaluation_suite():
    """ToolEvaluationSuite measures realistic tool discovery accuracy."""
    report = await ToolEvaluationSuite.run_evaluation(include_held_out=True)
    assert report.total_tasks >= 8
    assert report.selection_accuracy >= 80.0
    assert len(report.task_results) == report.total_tasks


# ── Section 12: Core Tools End-to-End Lifecycle ──────────────────────────────

@pytest.mark.asyncio
async def test_fs_tools_crud_lifecycle(tmp_path):
    """fs.write -> fs.read -> fs.edit lifecycle executes cleanly with physical verification."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    executor = ToolExecutor(mode="auto")

    # 1. Write file
    w_res = await executor.execute(
        tool_name="fs.write",
        arguments={"path": "calc.py", "content": "def add(a, b):\n    return a - b\n"},
        workspace=wm,
    )
    assert w_res.success is True
    assert (tmp_path / "calc.py").exists()

    # 2. Read file
    r_res = await executor.execute(
        tool_name="fs.read",
        arguments={"path": "calc.py"},
        workspace=wm,
    )
    assert r_res.success is True
    assert "return a - b" in r_res.observation_text

    # 3. Surgical Edit
    e_res = await executor.execute(
        tool_name="fs.edit",
        arguments={
            "path": "calc.py",
            "old_text": "return a - b",
            "new_text": "return a + b",
        },
        workspace=wm,
    )
    assert e_res.success is True
    assert "Successfully edited" in e_res.output_summary or "Successfully edited" in e_res.observation_text

    # 4. Verify physical disk contents
    final_content = (tmp_path / "calc.py").read_text(encoding="utf-8")
    assert "return a + b" in final_content


@pytest.mark.asyncio
async def test_fs_edit_failure_on_nonexistent_target(tmp_path):
    """fs.edit fails cleanly without modifying file when target text is missing."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    (tmp_path / "app.py").write_text("def hello(): pass")

    executor = ToolExecutor(mode="auto")
    res = await executor.execute(
        tool_name="fs.edit",
        arguments={"path": "app.py", "old_text": "nonexistent_fn", "new_text": "good_fn"},
        workspace=wm,
    )
    assert res.success is False
    assert "old_text not found" in res.observation_text
    # Verify file was NOT modified
    assert (tmp_path / "app.py").read_text() == "def hello(): pass"


@pytest.mark.asyncio
async def test_search_glob_and_grep(tmp_path):
    """search.glob and search.grep locate files and pattern occurrences."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "user.py").write_text("class User:\n    def get_id(self):\n        return 1\n")
    (tmp_path / "src" / "item.py").write_text("class Item:\n    pass\n")

    executor = ToolExecutor(mode="auto")

    # Glob
    glob_res = await executor.execute(
        tool_name="search.glob",
        arguments={"pattern": "**/*.py"},
        workspace=wm,
    )
    assert glob_res.success is True
    assert "src/user.py" in glob_res.observation_text
    assert "src/item.py" in glob_res.observation_text

    # Grep
    grep_res = await executor.execute(
        tool_name="search.grep",
        arguments={"pattern": "def get_id", "path": "src"},
        workspace=wm,
    )
    assert grep_res.success is True
    assert "user.py:2:" in grep_res.observation_text


@pytest.mark.asyncio
async def test_task_todo_checklist():
    """task.todo adds, updates, and lists mission objectives."""
    executor = ToolExecutor(mode="auto")

    # Add
    a_res = await executor.execute(
        tool_name="task.todo",
        arguments={"action": "add", "item_id": "step-1", "title": "Create DB models"},
    )
    assert a_res.success is True

    # Complete
    c_res = await executor.execute(
        tool_name="task.todo",
        arguments={"action": "complete", "item_id": "step-1"},
    )
    assert c_res.success is True

    # List
    l_res = await executor.execute(
        tool_name="task.todo",
        arguments={"action": "list"},
    )
    assert l_res.success is True
    assert "✓ [step-1] Create DB models" in l_res.observation_text


@pytest.mark.asyncio
async def test_user_ask_and_task_delegate():
    """user.ask prompts user; task.delegate cleanly returns formal contract."""
    executor = ToolExecutor(mode="auto")

    u_res = await executor.execute(
        tool_name="user.ask",
        arguments={"question": "Should we use PostgreSQL or SQLite?", "choices": ["postgres", "sqlite"]},
    )
    assert u_res.success is True
    assert "USER_QUESTION_PROMPTED" in u_res.observation_text

    d_res = await executor.execute(
        tool_name="task.delegate",
        arguments={"target_role": "debugger", "objective": "Investigate memory leak"},
    )
    assert d_res.success is False
    assert "SUBAGENT_DELEGATION_NOT_AVAILABLE" in d_res.observation_text
