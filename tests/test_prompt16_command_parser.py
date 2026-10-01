# tests/test_prompt16_command_parser.py
"""Tests for UnifiedInputParser adversarial safety and prefix parsing."""

import pytest
from core.commands.models import (
    AtMentionInput,
    CommandOrigin,
    NormalPromptInput,
    PaletteTriggerInput,
    ShellEscapeInput,
    SlashCommandInput,
)
from core.commands.parser import UnifiedInputParser


def test_empty_and_whitespace_inputs():
    """Verify empty or whitespace inputs produce safe normal prompts."""
    res_none = UnifiedInputParser.parse(None)
    assert isinstance(res_none, NormalPromptInput)
    assert res_none.prompt == ""

    res_empty = UnifiedInputParser.parse("")
    assert isinstance(res_empty, NormalPromptInput)
    assert res_empty.prompt == ""

    res_spaces = UnifiedInputParser.parse("   \t\n  ")
    assert isinstance(res_spaces, NormalPromptInput)
    assert res_spaces.prompt == ""


def test_literal_escapes():
    """Verify //, @@, and !! escapes produce unescaped normal prompts."""
    # //literal
    res_slash = UnifiedInputParser.parse("//not a command")
    assert isinstance(res_slash, NormalPromptInput)
    assert res_slash.prompt == "/not a command"

    # @@literal
    res_at = UnifiedInputParser.parse("@@not a mention")
    assert isinstance(res_at, NormalPromptInput)
    assert res_at.prompt == "@not a mention"

    # !!literal
    res_bang = UnifiedInputParser.parse("!!not a shell escape")
    assert isinstance(res_bang, NormalPromptInput)
    assert res_bang.prompt == "!not a shell escape"


def test_palette_trigger():
    """Single / triggers the command palette."""
    res = UnifiedInputParser.parse("/")
    assert isinstance(res, PaletteTriggerInput)

    res_space = UnifiedInputParser.parse("  /  ")
    assert isinstance(res_space, PaletteTriggerInput)


def test_slash_command_parsing():
    """Verify structured parsing of slash commands and flags."""
    # Simple command
    res1 = UnifiedInputParser.parse("/status")
    assert isinstance(res1, SlashCommandInput)
    assert res1.intent.name == "status"
    assert len(res1.intent.args) == 0

    # Command with positional args
    res2 = UnifiedInputParser.parse("/rewind chk_12345")
    assert isinstance(res2, SlashCommandInput)
    assert res2.intent.name == "rewind"
    assert res2.intent.args == ("chk_12345",)

    # Command with flags
    res3 = UnifiedInputParser.parse("/compact --focus=authentication")
    assert isinstance(res3, SlashCommandInput)
    assert res3.intent.name == "compact"
    assert res3.intent.kwargs.get("focus") == "authentication"

    # Quoted arguments
    res4 = UnifiedInputParser.parse('/plan "Build complete authentication backend"')
    assert isinstance(res4, SlashCommandInput)
    assert res4.intent.name == "plan"
    assert res4.intent.args == ("Build complete authentication backend",)


def test_shell_escape_parsing():
    """Verify ! shell command extraction."""
    res = UnifiedInputParser.parse("!pytest -q tests/test_agent.py")
    assert isinstance(res, ShellEscapeInput)
    assert res.command_line == "pytest -q tests/test_agent.py"
    assert res.intent.name == "shell"
    assert res.intent.args == ("pytest -q tests/test_agent.py",)


def test_at_mentions_and_email_exclusion():
    """Verify @mentions are extracted while email addresses are ignored."""
    # Standard mention
    res1 = UnifiedInputParser.parse("Inspect @src/main.py and fix bug")
    assert isinstance(res1, AtMentionInput)
    assert len(res1.mentions) == 1
    assert res1.mentions[0].path_str == "src/main.py"
    assert res1.mentions[0].raw_token == "@src/main.py"

    # Quoted mention with spaces
    res2 = UnifiedInputParser.parse('Read @"documents/my report.txt" please')
    assert isinstance(res2, AtMentionInput)
    assert len(res2.mentions) == 1
    assert res2.mentions[0].path_str == "documents/my report.txt"

    # Multiple mentions
    res3 = UnifiedInputParser.parse("Compare @file1.py with @file2.py")
    assert isinstance(res3, AtMentionInput)
    assert len(res3.mentions) == 2
    paths = [m.path_str for m in res3.mentions]
    assert "file1.py" in paths
    assert "file2.py" in paths

    # Email address: must NOT become a mention
    res_email = UnifiedInputParser.parse("Send updates to engineer@example.com please")
    assert isinstance(res_email, NormalPromptInput)
    assert res_email.prompt == "Send updates to engineer@example.com please"


def test_adversarial_malformed_inputs():
    """Verify parser never crashes on malformed, unclosed quotes, null bytes, or huge strings."""
    # Unclosed double quote
    res_unclosed = UnifiedInputParser.parse('/plan "unclosed argument without end')
    assert isinstance(res_unclosed, SlashCommandInput)
    assert res_unclosed.intent.name == "plan"

    # Null bytes embedded
    res_null = UnifiedInputParser.parse("/status\x00extra_injected_code")
    assert isinstance(res_null, SlashCommandInput)
    assert "\x00" not in res_null.intent.raw_text

    # Extremely long string (100,000 characters)
    huge_text = "word " * 20000
    res_huge = UnifiedInputParser.parse(huge_text)
    assert isinstance(res_huge, NormalPromptInput)

    # Unicode & emoji
    res_unicode = UnifiedInputParser.parse("Explain this function 🚀 漢字")
    assert isinstance(res_unicode, NormalPromptInput)
    assert "🚀" in res_unicode.prompt
