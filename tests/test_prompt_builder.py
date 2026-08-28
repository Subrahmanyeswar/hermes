import pytest

from core.prompt_builder import (
    PromptContext,
    build_system_prompt,
    build_user_message,
    truncate_memory_context,
)


def make_ctx(**kwargs) -> PromptContext:
    defaults = dict(
        user_task="create a hello world python file",
        mode="auto",
        available_tools=["write_file", "read_file"],
        tool_descriptions="- write_file: Write content to a file\n- read_file: Read a file",
        memory_context="",
        skill_context="",
        active_skill_name="none",
    )
    defaults.update(kwargs)
    return PromptContext(**defaults)


def test_system_prompt_contains_role():
    ctx = make_ctx()
    prompt = build_system_prompt(ctx)
    assert "HERMES" in prompt
    assert "valid JSON" in prompt


def test_system_prompt_contains_tool_descriptions():
    ctx = make_ctx()
    prompt = build_system_prompt(ctx)
    assert "write_file" in prompt
    assert "read_file" in prompt


def test_skill_context_injected_when_present():
    ctx = make_ctx(
        skill_context="You are a Flask expert.", active_skill_name="flask-rest-api"
    )
    prompt = build_system_prompt(ctx)
    assert "Flask expert" in prompt


def test_skill_context_absent_when_empty():
    ctx = make_ctx(skill_context="", active_skill_name="none")
    prompt = build_system_prompt(ctx)
    assert "No specific skill loaded." in prompt


def test_memory_context_injected_when_present():
    ctx = make_ctx(memory_context="[FACT]: Uses Flask 3.1")
    prompt = build_system_prompt(ctx)
    assert "Flask 3.1" in prompt


def test_mode_safe_instructions_present():
    ctx = make_ctx(mode="safe")
    prompt = build_system_prompt(ctx)
    assert "Mode: SAFE" in prompt or "Safe mode" in prompt


def test_mode_auto_instructions_present():
    ctx = make_ctx(mode="auto")
    prompt = build_system_prompt(ctx)
    assert "Mode: AUTO" in prompt or "Auto mode" in prompt


def test_truncate_memory_context_limits_lines():
    lines = [f"[FACT]: fact {i}" for i in range(50)]
    result = truncate_memory_context(lines, max_lines=10)
    assert result.count("\n") == 9  # 10 lines = 9 newlines


def test_truncate_memory_context_empty_input():
    assert truncate_memory_context([]) == ""


def test_build_user_message_strips_whitespace():
    msg = build_user_message("  create a file  ")
    assert msg == "Task: create a file"
