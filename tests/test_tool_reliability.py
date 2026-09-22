"""
Unit and Security Tests for Tool-Call Reliability Hardening.
Guarantees that {} or malformed tool calls never silently execute,
and validates normalization, deterministic repair, schema checks, and security gates.
"""
import pytest
from unittest.mock import AsyncMock

from core.tool_validator import ToolValidator, ToolValidationResult
from tools.registry import get_tool


def test_empty_arguments_on_write_file_fails_validation():
    """write_file({}) must fail schema validation and return structured missing argument errors."""
    validator = ToolValidator(enabled=True)
    is_valid, validated_input, errors = validator.validate_schema("write_file", {})
    assert is_valid is False
    assert validated_input is None
    assert any("path" in err.lower() for err in errors)
    assert any("content" in err.lower() for err in errors)


def test_alias_normalization():
    """file_path must be normalized to path, and cmd to command."""
    validator = ToolValidator(enabled=True)
    norm, mods = validator.normalize("read_file", {"file_path": "  app.py  ", "extra": 1})
    assert norm["path"] == "app.py"
    assert "alias_file_path_to_path" in mods

    norm_cmd, mods_cmd = validator.normalize("execute_command", {"cmd": "ls -la"})
    assert norm_cmd["command"] == "ls -la"
    assert "alias_cmd_to_command" in mods_cmd


def test_default_injection_for_list_directory():
    """list_directory with empty dict must receive default path '.' without error."""
    validator = ToolValidator(enabled=True)
    norm, mods = validator.normalize("list_directory", {})
    assert norm["path"] == "."
    assert "injected_default_list_directory_path" in mods

    is_valid, validated_input, errors = validator.validate_schema("list_directory", norm)
    assert is_valid is True
    assert validated_input is not None
    assert validated_input.path == "."


def test_contextual_path_repair():
    """If task explicitly names a file, missing path is derived contextually."""
    validator = ToolValidator(enabled=True)
    norm, mods = validator.normalize(
        tool_name="write_file",
        params={"content": "print('hello')"},
        task_text="Create a file named generated_projects/hello.py"
    )
    assert norm["path"] == "generated_projects/hello.py"
    assert any("contextual_extracted_path" in m for m in mods)

    is_valid, validated_input, errors = validator.validate_schema("write_file", norm)
    assert is_valid is True
    assert validated_input.path == "generated_projects/hello.py"


def test_type_validation_failure():
    """Passing integer for string path must fail type validation."""
    validator = ToolValidator(enabled=True)
    is_valid, validated_input, errors = validator.validate_schema("read_file", {"path": 12345})
    assert is_valid is False
    assert any("type" in err.lower() or "string" in err.lower() for err in errors)


def test_path_traversal_security_blocked():
    """Paths containing null bytes must be blocked by security check."""
    validator = ToolValidator(enabled=True)
    null_path = "safe.py" + chr(0) + "hidden.txt"
    is_safe, sec_err = validator.validate_security("read_file", {"path": null_path})
    assert is_safe is False
    assert "null byte" in sec_err.lower()


def test_forbidden_command_security_blocked():
    """Dangerous forkbombs or root deletion commands must be blocked by command security."""
    validator = ToolValidator(enabled=True)
    is_safe, sec_err = validator.validate_security("execute_command", {"command": "rm -rf /"})
    assert is_safe is False
    assert "forbidden command" in sec_err.lower()


def test_unknown_tool_rejection():
    """Non-existent tool names must fail validation immediately."""
    validator = ToolValidator(enabled=True)
    is_valid, validated_input, errors = validator.validate_schema("non_existent_tool_xyz", {"foo": "bar"})
    assert is_valid is False
    assert any("not found in registry" in err.lower() for err in errors)


@pytest.mark.asyncio
async def test_t1_model_correction_recovery():
    """When raw call is {}, T1 structured correction produces valid arguments."""
    validator = ToolValidator(enabled=True)
    mock_ollama = AsyncMock()
    # Mock Ollama returning valid JSON correction
    mock_ollama.generate = AsyncMock(return_value=type("Resp", (), {
        "text": '{"tool": "write_file", "parameters": {"path": "generated_projects/calc.py", "content": "def add(a, b): return a + b"}}'
    })())

    res = await validator.process_and_validate(
        tool_name="write_file",
        raw_params={},
        task_text="Create a calculator file",
        ollama_client=mock_ollama,
        budget_manager=None,
        max_repair_attempts=1
    )

    assert res.is_valid is True
    assert res.tool_name == "write_file"
    assert res.normalized_params["path"] == "generated_projects/calc.py"
    assert res.repair_applied is True
    assert "T1_MODEL_CORRECTION" in res.repair_method


def test_feature_flag_rollback():
    """When ROBUST_TOOL_VALIDATION_ENABLED=False, bypass mode is active."""
    validator = ToolValidator(enabled=False)
    norm, mods = validator.normalize("read_file", {"file_path": "test.txt"})
    assert norm["path"] == "test.txt"
