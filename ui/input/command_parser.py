# ui/input/command_parser.py
"""
Structural Command Parser for User TUI Commands.

Guarantees:
1. Zero eval / exec / shell=True.
2. Structured parsing into typed Command objects.
3. Clean error reporting for unknown or malformed commands.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import List, Optional, Union

from ui.rendering.text_safety import sanitize_terminal_text


@dataclass(frozen=True)
class ResumeCommand:
    session_id: Optional[str] = None
    checkpoint_id: Optional[str] = None


@dataclass(frozen=True)
class ClearCommand:
    new_mission_id: Optional[str] = None


@dataclass(frozen=True)
class CheckpointCommand:
    reason: str = "MANUAL"


@dataclass(frozen=True)
class RewindCommand:
    checkpoint_id: str
    mode: str = "CODE_AND_CONVERSATION"


@dataclass(frozen=True)
class ForkCommand:
    checkpoint_id: str
    branch_name: Optional[str] = None


@dataclass(frozen=True)
class BranchCommand:
    branch_name: str


@dataclass(frozen=True)
class CancelCommand:
    reason: str = "USER_REQUESTED"


@dataclass(frozen=True)
class StatusCommand:
    pass


@dataclass(frozen=True)
class HelpCommand:
    pass


@dataclass(frozen=True)
class UnknownCommand:
    name: str
    raw_args: List[str]


ParsedCommand = Union[
    ResumeCommand,
    ClearCommand,
    CheckpointCommand,
    RewindCommand,
    ForkCommand,
    BranchCommand,
    CancelCommand,
    StatusCommand,
    HelpCommand,
    UnknownCommand,
]


class CommandParser:
    """Safely parses slash commands from terminal input."""

    @staticmethod
    def is_command(text: str) -> bool:
        return text.strip().startswith("/")

    @classmethod
    def parse(cls, text: str) -> Optional[ParsedCommand]:
        clean = text.strip()
        if not clean.startswith("/"):
            return None

        # Safe tokenization
        try:
            tokens = shlex.split(clean[1:])
        except ValueError:
            tokens = clean[1:].split()

        if not tokens:
            return HelpCommand()

        cmd = tokens[0].lower()
        args = tokens[1:]

        if cmd == "resume":
            sess_id = args[0] if len(args) > 0 else None
            chk_id = args[1] if len(args) > 1 else None
            return ResumeCommand(session_id=sess_id, checkpoint_id=chk_id)

        elif cmd == "clear":
            m_id = args[0] if len(args) > 0 else None
            return ClearCommand(new_mission_id=m_id)

        elif cmd == "checkpoint":
            reason = args[0].upper() if len(args) > 0 else "MANUAL"
            return CheckpointCommand(reason=reason)

        elif cmd == "rewind":
            if not args:
                return UnknownCommand(name="rewind", raw_args=["Missing required checkpoint_id argument."])
            chk_id = args[0]
            mode = args[1].upper() if len(args) > 1 else "CODE_AND_CONVERSATION"
            return RewindCommand(checkpoint_id=chk_id, mode=mode)

        elif cmd in ("fork", "cow"):
            if not args:
                return UnknownCommand(name="fork", raw_args=["Missing required checkpoint_id argument."])
            chk_id = args[0]
            branch = args[1] if len(args) > 1 else None
            return ForkCommand(checkpoint_id=chk_id, branch_name=branch)

        elif cmd == "branch":
            if not args:
                return UnknownCommand(name="branch", raw_args=["Missing required branch_name argument."])
            return BranchCommand(branch_name=args[0])

        elif cmd in ("cancel", "abort", "stop"):
            return CancelCommand()

        elif cmd in ("status", "info"):
            return StatusCommand()

        elif cmd in ("help", "?"):
            return HelpCommand()

        return UnknownCommand(name=cmd, raw_args=args)
