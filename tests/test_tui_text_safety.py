# tests/test_tui_text_safety.py
"""Tests for terminal text safety and Unicode width calculations."""

import pytest
from ui.rendering.text_safety import (
    get_char_width,
    get_string_display_width,
    sanitize_terminal_text,
)


def test_strip_ansi_csi_osc_escapes():
    # CSI sequence for red color
    dirty = "\033[31mHello World\033[0m"
    clean = sanitize_terminal_text(dirty)
    assert clean == "Hello World"

    # OSC sequence setting window title
    dirty_title = "\033]0;Injected Title\007Safe Text"
    clean_title = sanitize_terminal_text(dirty_title)
    assert clean_title == "Safe Text"

    # Cursor movement and screen clear
    dirty_cursor = "\033[2J\033[H\033[10;20HAttacking Cursor"
    clean_cursor = sanitize_terminal_text(dirty_cursor)
    assert clean_cursor == "Attacking Cursor"


def test_strip_cr_and_bs_overwrite_attacks():
    # Carriage return overwrite attack
    attack_cr = "Initial Text\rOverwritten"
    clean_cr = sanitize_terminal_text(attack_cr)
    assert clean_cr == "Initial TextOverwritten"

    # Backspace attack
    attack_bs = "Pass\b\b\b\bFail"
    clean_bs = sanitize_terminal_text(attack_bs)
    assert clean_bs == "PassFail"


def test_strip_hidden_think_reasoning_blocks():
    text_with_think = "Hello user. <think>This is secret reasoning that should not be visible</think> Final answer."
    cleaned = sanitize_terminal_text(text_with_think)
    assert "<think>" not in cleaned
    assert "secret reasoning" not in cleaned
    assert cleaned.strip() == "Hello user.  Final answer."

    # Partial unclosed think block at stream end
    unclosed = "Thinking... <think>Deliberating without closing tag"
    cleaned_unclosed = sanitize_terminal_text(unclosed)
    assert "<think>" not in cleaned_unclosed
    assert "Deliberating" not in cleaned_unclosed
    assert cleaned_unclosed.strip() == "Thinking..."


def test_preserve_unicode_and_cjk():
    cjk = "你好，世界！"
    assert sanitize_terminal_text(cjk) == cjk

    accents = "Café résumé naïve"
    assert sanitize_terminal_text(accents) == accents

    emoji = "🚀 HERMES Runtime ⚡"
    assert sanitize_terminal_text(emoji) == emoji


def test_char_width_and_string_width():
    # ASCII
    assert get_char_width("A") == 1
    assert get_string_display_width("Hello") == 5

    # CJK wide characters (width = 2)
    assert get_char_width("你") == 2
    assert get_char_width("好") == 2
    assert get_string_display_width("你好") == 4

    # Fullwidth punctuation
    assert get_char_width("！") == 2

    # Combining characters (width = 0)
    combining_accent = "\u0301"  # Combining acute accent
    assert get_char_width(combining_accent) == 0

    # Mixed string
    assert get_string_display_width("Hi 你好") == 2 + 1 + 4 == 7
