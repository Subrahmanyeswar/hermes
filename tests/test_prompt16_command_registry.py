# tests/test_prompt16_command_registry.py
"""Tests for CommandRegistry and CommandDefinition metadata."""

import pytest
from core.commands.models import (
    CommandDefinition,
    CommandExecutionClass,
    LlmPolicy,
)
from core.commands.registry import CommandRegistry, command_registry


def test_builtin_commands_registered():
    """Verify all 13 canonical slash commands plus help are registered."""
    expected_commands = {
        "plan",
        "compact",
        "context",
        "cost",
        "doctor",
        "status",
        "rewind",
        "resume",
        "clear",
        "diff",
        "tasks",
        "goal",
        "btw",
        "help",
    }
    registry = CommandRegistry()
    registered_names = {c.name for c in registry.list_commands()}

    for expected in expected_commands:
        assert expected in registered_names, f"Expected command '{expected}' not registered"


def test_command_llm_policies():
    """Ensure pure query commands have LlmPolicy.NEVER."""
    registry = CommandRegistry()
    never_commands = [
        "status",
        "context",
        "cost",
        "doctor",
        "diff",
        "tasks",
        "rewind",
        "resume",
        "clear",
        "goal",
        "help",
    ]
    for name in never_commands:
        defn = registry.get_definition(name)
        assert defn is not None, f"Definition for '{name}' missing"
        assert defn.llm_policy == LlmPolicy.NEVER, f"Command '{name}' should have NEVER policy"


def test_command_execution_classes():
    """Verify execution classes distinguish queries vs control vs mutation."""
    registry = CommandRegistry()

    status_cmd = registry.get_definition("status")
    assert status_cmd.execution_class == CommandExecutionClass.PURE_QUERY
    assert status_cmd.may_mutate is False

    clear_cmd = registry.get_definition("clear")
    assert clear_cmd.execution_class == CommandExecutionClass.STATE_MUTATION
    assert clear_cmd.may_mutate is True

    rewind_cmd = registry.get_definition("rewind")
    assert rewind_cmd.execution_class == CommandExecutionClass.CONTROL_OPERATION
    assert rewind_cmd.may_mutate is True

    plan_cmd = registry.get_definition("plan")
    assert plan_cmd.execution_class == CommandExecutionClass.CONTROL_OPERATION

    btw_cmd = registry.get_definition("btw")
    assert btw_cmd.execution_class == CommandExecutionClass.MODEL_OPERATION


def test_alias_resolution():
    """Verify aliases resolve to the same canonical definition."""
    registry = CommandRegistry()

    # /reset -> /clear
    assert registry.get_definition("reset").name == "clear"
    # /continue -> /resume
    assert registry.get_definition("continue").name == "resume"
    # /info -> /status
    assert registry.get_definition("info").name == "status"
    # /st -> /status
    assert registry.get_definition("st").name == "status"
    # /ctx -> /context
    assert registry.get_definition("ctx").name == "context"
    # /? -> /help
    assert registry.get_definition("?").name == "help"


def test_command_completion_prefix_and_fuzzy():
    """Verify palette completion engine."""
    registry = CommandRegistry()

    # Prefix match "st"
    completions = registry.complete("st")
    names = [c[0] for c in completions]
    assert "/status" in names

    # Prefix match "co"
    co_completions = registry.complete("co")
    co_names = [c[0] for c in co_completions]
    assert "/compact" in co_names
    assert "/context" in co_names
    assert "/cost" in co_names

    # Unknown prefix
    empty = registry.complete("nonexistent_command_prefix_xyz")
    assert len(empty) == 0


def test_help_text_generation():
    """Verify help documentation output."""
    registry = CommandRegistry()

    # Full help
    full_help = registry.get_help_text()
    assert "HERMES Command Operating System" in full_help
    assert "/plan" in full_help
    assert "/status" in full_help
    assert "/doctor" in full_help

    # Specific command help
    status_help = registry.get_help_text("status")
    assert "Command: /status" in status_help
    assert "LLM Policy:   NEVER" in status_help
    assert "Mutates:      NO" in status_help

    # Unknown command help
    unknown_help = registry.get_help_text("not_a_cmd")
    assert "Unknown command: /not_a_cmd" in unknown_help


def test_custom_command_registration():
    """Verify extensibility of registry for future plugins/commands."""
    registry = CommandRegistry()
    custom = CommandDefinition(
        name="custom",
        aliases=("cstm",),
        description="Custom operator command",
    )
    registry.register(custom)

    assert registry.get_definition("custom").name == "custom"
    assert registry.get_definition("cstm").name == "custom"
