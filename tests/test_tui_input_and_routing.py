# tests/test_tui_input_and_routing.py
"""Tests for InputDecoder, CommandParser, and InputRouter."""

import pytest
from ui.input.command_parser import (
    BranchCommand,
    CancelCommand,
    CheckpointCommand,
    ClearCommand,
    CommandParser,
    ForkCommand,
    HelpCommand,
    ResumeCommand,
    RewindCommand,
    StatusCommand,
    UnknownCommand,
)
from ui.input.decoder import (
    EOFEvent,
    InputDecoder,
    InterruptEvent,
    KeyPressEvent,
)
from ui.input.router import InputRouter


def test_input_decoder_basic_keys_and_ctrl_c():
    decoder = InputDecoder()

    # Normal characters
    events = decoder.feed("abc")
    assert len(events) == 3
    assert all(e.key == "char" for e in events)

    # Enter
    ev_enter = decoder.feed("\n")
    assert len(ev_enter) == 1
    assert ev_enter[0].key == "enter"

    # Ctrl+C
    ev_interrupt = decoder.feed("\x03")
    assert len(ev_interrupt) == 1
    assert isinstance(ev_interrupt[0], InterruptEvent)

    # EOF
    ev_eof = decoder.feed("\x04")
    assert len(ev_eof) == 1
    assert isinstance(ev_eof[0], EOFEvent)

    # Arrows (CSI sequence)
    ev_up = decoder.feed("\x1b[A")
    assert len(ev_up) == 1
    assert ev_up[0].key == "up"


def test_command_parser_slash_commands():
    # /resume
    cmd_res = CommandParser.parse("/resume sess_123 chk_456")
    assert isinstance(cmd_res, ResumeCommand)
    assert cmd_res.session_id == "sess_123"
    assert cmd_res.checkpoint_id == "chk_456"

    # /checkpoint
    cmd_chk = CommandParser.parse("/checkpoint manual")
    assert isinstance(cmd_chk, CheckpointCommand)
    assert cmd_chk.reason == "MANUAL"

    # /rewind
    cmd_rew = CommandParser.parse("/rewind chk_999 code_only")
    assert isinstance(cmd_rew, RewindCommand)
    assert cmd_rew.checkpoint_id == "chk_999"
    assert cmd_rew.mode == "CODE_ONLY"

    # /fork
    cmd_fork = CommandParser.parse("/fork chk_111 experiment-branch")
    assert isinstance(cmd_fork, ForkCommand)
    assert cmd_fork.checkpoint_id == "chk_111"
    assert cmd_fork.branch_name == "experiment-branch"

    # /clear
    cmd_clear = CommandParser.parse("/clear")
    assert isinstance(cmd_clear, ClearCommand)

    # /cancel
    cmd_cancel = CommandParser.parse("/cancel")
    assert isinstance(cmd_cancel, CancelCommand)

    # Not a command
    assert CommandParser.parse("This is just regular text") is None


def test_input_router_security_modal_routing():
    approved = []
    denied = []

    router = InputRouter(
        on_permission_response=lambda grant: approved.append(True) if grant else denied.append(True)
    )
    router.is_security_modal_active = True

    # User presses 'y' to approve
    router.handle_event(KeyPressEvent(key="char", char="y"))
    assert len(approved) == 1
    assert router.is_security_modal_active is False

    # Next modal: user presses 'n' to deny
    router.is_security_modal_active = True
    router.handle_event(KeyPressEvent(key="char", char="n"))
    assert len(denied) == 1
    assert router.is_security_modal_active is False


def test_input_router_command_dispatch():
    commands = []
    prompts = []

    router = InputRouter(
        on_prompt_submit=lambda p: prompts.append(p),
        on_command=lambda c: commands.append(c),
    )

    # Type command /status and enter
    for ch in "/status":
        router.handle_event(KeyPressEvent(key="char", char=ch))
    router.handle_event(KeyPressEvent(key="enter"))

    assert len(commands) == 1
    assert isinstance(commands[0], StatusCommand)
    assert len(prompts) == 0

    # Type normal prompt and enter
    for ch in "Create a login form":
        router.handle_event(KeyPressEvent(key="char", char=ch))
    router.handle_event(KeyPressEvent(key="enter"))

    assert len(prompts) == 1
    assert prompts[0] == "Create a login form"
