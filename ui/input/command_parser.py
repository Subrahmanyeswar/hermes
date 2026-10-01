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
class PlanCommand:
    task: Optional[str] = None


@dataclass(frozen=True)
class CompactCommand:
    focus: Optional[str] = None


@dataclass(frozen=True)
class ContextCommand:
    pass


@dataclass(frozen=True)
class CostCommand:
    pass


@dataclass(frozen=True)
class DoctorCommand:
    probe: bool = False


@dataclass(frozen=True)
class DiffCommand:
    pass


@dataclass(frozen=True)
class TasksCommand:
    pass


@dataclass(frozen=True)
class GoalCommand:
    goal: Optional[str] = None


@dataclass(frozen=True)
class BtwCommand:
    question: str = ""


@dataclass(frozen=True)
class ShellCommand:
    command_line: str = ""


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
    PlanCommand,
    CompactCommand,
    ContextCommand,
    CostCommand,
    DoctorCommand,
    DiffCommand,
    TasksCommand,
    GoalCommand,
    BtwCommand,
    ShellCommand,
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

        elif cmd == "plan":
            task = " ".join(args).strip() if args else None
            return PlanCommand(task=task)

        elif cmd == "compact":
            focus = " ".join(args).strip() if args else None
            return CompactCommand(focus=focus)

        elif cmd in ("context", "ctx"):
            return ContextCommand()

        elif cmd in ("cost", "usage"):
            return CostCommand()

        elif cmd in ("doctor", "check"):
            probe = "--probe" in args or "-p" in args
            return DoctorCommand(probe=probe)

        elif cmd in ("diff", "changes"):
            return DiffCommand()

        elif cmd in ("tasks", "queue"):
            return TasksCommand()

        elif cmd in ("goal", "target"):
            goal_text = " ".join(args).strip() if args else None
            return GoalCommand(goal=goal_text)

        elif cmd in ("btw", "ask"):
            q_text = " ".join(args).strip() if args else ""
            return BtwCommand(question=q_text)

        return UnknownCommand(name=cmd, raw_args=args)

    @classmethod
    def to_command_intent(cls, cmd: ParsedCommand, origin: Any = None) -> Any:
        """Convert a ParsedCommand into canonical core.commands.CommandIntent."""
        from core.commands.models import CommandIntent, CommandOrigin
        eff_origin = origin or CommandOrigin.USER_TUI

        if isinstance(cmd, ResumeCommand):
            return CommandIntent.create(
                name="resume",
                raw_text=f"/resume {cmd.session_id or ''} {cmd.checkpoint_id or ''}".strip(),
                args=tuple(a for a in (cmd.session_id, cmd.checkpoint_id) if a),
                origin=eff_origin,
            )
        elif isinstance(cmd, ClearCommand):
            return CommandIntent.create(name="clear", raw_text="/clear", origin=eff_origin)
        elif isinstance(cmd, CheckpointCommand):
            return CommandIntent.create(name="checkpoint", raw_text=f"/checkpoint {cmd.reason}", args=(cmd.reason,), origin=eff_origin)
        elif isinstance(cmd, RewindCommand):
            return CommandIntent.create(name="rewind", raw_text=f"/rewind {cmd.checkpoint_id}", args=(cmd.checkpoint_id, cmd.mode), origin=eff_origin)
        elif isinstance(cmd, ForkCommand):
            return CommandIntent.create(name="fork", raw_text=f"/fork {cmd.checkpoint_id}", args=(cmd.checkpoint_id,), origin=eff_origin)
        elif isinstance(cmd, BranchCommand):
            return CommandIntent.create(name="branch", raw_text=f"/branch {cmd.branch_name}", args=(cmd.branch_name,), origin=eff_origin)
        elif isinstance(cmd, CancelCommand):
            return CommandIntent.create(name="cancel", raw_text="/cancel", origin=eff_origin)
        elif isinstance(cmd, StatusCommand):
            return CommandIntent.create(name="status", raw_text="/status", origin=eff_origin)
        elif isinstance(cmd, HelpCommand):
            return CommandIntent.create(name="help", raw_text="/help", origin=eff_origin)
        elif isinstance(cmd, PlanCommand):
            args = (cmd.task,) if cmd.task else ()
            return CommandIntent.create(name="plan", raw_text="/plan", args=args, origin=eff_origin)
        elif isinstance(cmd, CompactCommand):
            args = (cmd.focus,) if cmd.focus else ()
            return CommandIntent.create(name="compact", raw_text="/compact", args=args, origin=eff_origin)
        elif isinstance(cmd, ContextCommand):
            return CommandIntent.create(name="context", raw_text="/context", origin=eff_origin)
        elif isinstance(cmd, CostCommand):
            return CommandIntent.create(name="cost", raw_text="/cost", origin=eff_origin)
        elif isinstance(cmd, DoctorCommand):
            args = ("--probe",) if cmd.probe else ()
            return CommandIntent.create(name="doctor", raw_text="/doctor", args=args, origin=eff_origin)
        elif isinstance(cmd, DiffCommand):
            return CommandIntent.create(name="diff", raw_text="/diff", origin=eff_origin)
        elif isinstance(cmd, TasksCommand):
            return CommandIntent.create(name="tasks", raw_text="/tasks", origin=eff_origin)
        elif isinstance(cmd, GoalCommand):
            args = (cmd.goal,) if cmd.goal else ()
            return CommandIntent.create(name="goal", raw_text="/goal", args=args, origin=eff_origin)
        elif isinstance(cmd, BtwCommand):
            return CommandIntent.create(name="btw", raw_text=f"/btw {cmd.question}", args=(cmd.question,), origin=eff_origin)
        elif isinstance(cmd, ShellCommand):
            return CommandIntent.create(name="shell", raw_text=f"!{cmd.command_line}", args=(cmd.command_line,), origin=eff_origin)
        elif isinstance(cmd, UnknownCommand):
            return CommandIntent.create(name=cmd.name, raw_text=f"/{cmd.name}", args=tuple(cmd.raw_args), origin=eff_origin)
        return CommandIntent.create(name="unknown", raw_text=str(cmd), origin=eff_origin)
