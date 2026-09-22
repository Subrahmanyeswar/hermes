import pytest
from tools.registry import (
    tool_schema_for_prompt,
    selective_tool_schema_for_prompt,
    list_tools,
)
from core.tool_validator import ToolValidator
from core.verification_gate import VerificationGate, ToolRiskCategory
from core.workspace import workspace_manager


# ── Benchmark Isolation ───────────────────────────────────────────────────────

def test_benchmark_mode_strictly_excludes_write_files_batch():
    """Benchmark mode must always see exactly the 20 frozen canonical tools."""
    bench_schema = selective_tool_schema_for_prompt(
        required_tools=["write_file"],
        execution_mode="benchmark",
        allow_batch_tools=True,  # Even if requested, benchmark mode must ignore it
    )
    lines = bench_schema.splitlines()
    assert len(lines) == 20
    assert "write_files_batch" not in bench_schema
    assert tool_schema_for_prompt() == bench_schema


def test_production_single_file_excludes_batch_tool():
    """Single-file tasks in production must not expose write_files_batch."""
    prod_schema = selective_tool_schema_for_prompt(
        required_tools=["write_file"],
        execution_mode="production",
        allow_batch_tools=False,
    )
    lines = prod_schema.splitlines()
    assert len(lines) == 4
    tool_names = [line.split(":")[0].strip("- ") for line in lines]
    assert "write_file" in tool_names
    assert "write_files_batch" not in tool_names


def test_production_multi_file_eligible_exposes_batch_tool():
    """Multi-file eligible tasks (2-3 files) in production expose write_files_batch."""
    prod_schema = selective_tool_schema_for_prompt(
        required_tools=["write_file"],
        execution_mode="production",
        allow_batch_tools=True,
    )
    lines = prod_schema.splitlines()
    assert len(lines) == 5
    tool_names = [line.split(":")[0].strip("- ") for line in lines]
    assert "write_file" in tool_names
    assert "write_files_batch" in tool_names
    assert "read_file" in tool_names
    assert "list_directory" in tool_names
    assert "create_folder" in tool_names


def test_production_four_or_more_files_falls_back_to_single_file():
    """Tasks with 4+ files must not expose write_files_batch (hard <=3 file bound)."""
    # 4+ files falls back to allow_batch_tools=False
    prod_schema = selective_tool_schema_for_prompt(
        required_tools=["write_file"],
        execution_mode="production",
        allow_batch_tools=False,
    )
    assert "write_files_batch" not in prod_schema


# ── ToolValidator Hardening ───────────────────────────────────────────────────

def test_tool_validator_normalizes_batch_aliases():
    tv = ToolValidator()
    raw_params = {
        "files": [
            {"target_file": "app.py", "CodeContent": "print('ok')", "mode": "overwrite"},
            {"path": "config.json", "file_content": "{}", "mode": "overwrite"},
        ]
    }
    normalized, mods = tv.normalize("write_files_batch", raw_params)
    assert len(normalized["files"]) == 2
    assert normalized["files"][0]["path"] == "app.py"
    assert normalized["files"][0]["content"] == "print('ok')"
    assert normalized["files"][1]["path"] == "config.json"
    assert normalized["files"][1]["content"] == "{}"


def test_tool_validator_security_blocks_traversal_in_batch(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    workspace_manager.lock(ws)
    try:
        tv = ToolValidator()
        params = {
            "files": [
                {"path": "ok.txt", "content": "1"},
                {"path": "../../escape.txt", "content": "2"},
            ]
        }
        is_safe, err = tv.validate_security("write_files_batch", params)
        assert is_safe is False
        assert "Path traversal violation" in err
    finally:
        workspace_manager.unlock()


def test_tool_validator_security_blocks_duplicates_in_batch(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    workspace_manager.lock(ws)
    try:
        tv = ToolValidator()
        params = {
            "files": [
                {"path": "foo.py", "content": "1"},
                {"path": "./foo.py", "content": "2"},
            ]
        }
        is_safe, err = tv.validate_security("write_files_batch", params)
        assert is_safe is False
        assert "Duplicate path detected in batch" in err
    finally:
        workspace_manager.unlock()


# ── VerificationGate Hardening ────────────────────────────────────────────────

def test_verification_gate_classifies_write_files_batch():
    gate = VerificationGate()
    assert gate.classify_tool("write_files_batch") == ToolRiskCategory.LOW_RISK_WRITE


def test_verification_gate_deterministic_checks_batch(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    workspace_manager.lock(ws)
    try:
        f1 = ws / "one.txt"
        f2 = ws / "two.txt"
        f1.write_text("1", encoding="utf-8")
        f2.write_text("2", encoding="utf-8")

        gate = VerificationGate()
        params = {
            "files": [
                {"path": "one.txt", "content": "1"},
                {"path": "two.txt", "content": "2"},
            ]
        }
        passed, checks, issues = gate.run_deterministic_checks(
            tool_name="write_files_batch",
            tool_parameters=params,
            tool_result_output="Successfully wrote 2 files",
            tool_exit_code=0,
            tool_success=True,
        )
        assert passed is True
        assert len(issues) == 0
        assert "check_batch_files_exist_and_non_empty" in checks
    finally:
        workspace_manager.unlock()


def test_verification_gate_structural_ast_checks_batch():
    gate = VerificationGate()
    valid_params = {
        "files": [
            {"path": "module.py", "content": "def add(a, b): return a + b"},
            {"path": "manifest.json", "content": '{"name": "test", "version": 1}'},
        ]
    }
    passed, checks, issues = gate.run_structural_checks("write_files_batch", valid_params)
    assert passed is True
    assert len(issues) == 0
    assert "python_ast_parse:module.py" in checks
    assert "json_syntax_parse:manifest.json" in checks

    # Invalid Python syntax in batch
    invalid_params = {
        "files": [
            {"path": "broken.py", "content": "def broken(:"},
        ]
    }
    passed_bad, checks_bad, issues_bad = gate.run_structural_checks("write_files_batch", invalid_params)
    assert passed_bad is False
    assert len(issues_bad) > 0
    assert "Python syntax error" in issues_bad[0]
