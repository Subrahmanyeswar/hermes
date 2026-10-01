# core/commands/models.py
"""
Authoritative Command Metadata and Intent Models for HERMES 2.x (Prompt 16).

Central Invariants:
1. ONE COMMAND MODEL: Shared across TUI, CLI, Headless, Replay, and future SDKs.
2. STRICT TYPING: Immutable/frozen dataclasses with explicit LLM and mutation policies.
3. TRUTHFUL ATTRIBUTION: Explicit CommandOrigin and CommandExecutionClass tracking.
4. ZERO EVAL/EXEC: All arguments parsed and passed as typed structures.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Union


class LlmPolicy(str, Enum):
    """Explicit model invocation policy for commands."""
    NEVER = "NEVER"         # Must NEVER invoke LLM (status, context, cost, doctor, diff, tasks, clear, rewind, resume, goal)
    OPTIONAL = "OPTIONAL"   # May invoke LLM depending on arguments/task (plan, compact, btw)
    REQUIRED = "REQUIRED"   # Genuinely cannot execute without model reasoning


class CommandExecutionClass(str, Enum):
    """Classification of command execution side effects and boundaries."""
    PURE_QUERY = "PURE_QUERY"                 # Read-only observation, zero mutation, zero external side effects
    STATE_MUTATION = "STATE_MUTATION"         # Modifies authoritative runtime or durable state
    CONTROL_OPERATION = "CONTROL_OPERATION"   # Mode changes, workflow lifecycle (plan mode, resume, rewind)
    MODEL_OPERATION = "MODEL_OPERATION"       # Triggers model reasoning/inference (btw, directed plan)
    EXTERNAL_ACTION = "EXTERNAL_ACTION"       # OS process, shell execution (! commands)


class CommandOrigin(str, Enum):
    """Source principal of command invocation."""
    USER_TUI = "USER_TUI"
    USER_CLI = "USER_CLI"
    USER_HEADLESS = "USER_HEADLESS"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    REPLAY = "REPLAY"


class CommandStatus(str, Enum):
    """Standardized outcome status of command execution."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class CommandErrorCode(str, Enum):
    """Typed error codes for command dispatch failures."""
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    UNAVAILABLE_MODE = "UNAVAILABLE_MODE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SECURITY_DENIED = "SECURITY_DENIED"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    CHECKPOINT_NOT_FOUND = "CHECKPOINT_NOT_FOUND"
    WORKSPACE_ERROR = "WORKSPACE_ERROR"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CANCELLED = "CANCELLED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    CONFLICT_ERROR = "CONFLICT_ERROR"


@dataclass(frozen=True)
class CommandDefinition:
    """Authoritative metadata and policy specification for a command."""
    name: str
    aliases: Tuple[str, ...] = ()
    category: str = "Core"
    description: str = ""
    usage: str = ""
    arguments_summary: str = ""
    llm_policy: LlmPolicy = LlmPolicy.NEVER
    execution_class: CommandExecutionClass = CommandExecutionClass.PURE_QUERY
    may_mutate: bool = False
    requires_confirmation: bool = False
    headless_supported: bool = True
    tui_supported: bool = True
    replay_supported: bool = False
    idempotent: bool = True
    handler_name: Optional[str] = None


@dataclass(frozen=True)
class CommandIntent:
    """Canonical typed request representation of a parsed user command."""
    command_id: str
    name: str
    raw_text: str
    args: Tuple[str, ...] = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    origin: CommandOrigin = CommandOrigin.USER_CLI
    session_id: Optional[str] = None
    mission_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        name: str,
        raw_text: str,
        args: Tuple[str, ...] = (),
        kwargs: Optional[Dict[str, Any]] = None,
        origin: CommandOrigin = CommandOrigin.USER_CLI,
        session_id: Optional[str] = None,
        mission_id: Optional[str] = None,
    ) -> CommandIntent:
        return cls(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            name=name.lower().lstrip("/"),
            raw_text=raw_text,
            args=args,
            kwargs=kwargs or {},
            origin=origin,
            session_id=session_id,
            mission_id=mission_id,
            timestamp=time.time(),
        )


@dataclass(frozen=True)
class CommandResult:
    """Canonical typed result returned by command handlers."""
    command_id: str
    name: str
    status: CommandStatus
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    llm_called: bool = False
    execution_class: CommandExecutionClass = CommandExecutionClass.PURE_QUERY
    duration_seconds: float = 0.0
    error_code: Optional[CommandErrorCode] = None

    @classmethod
    def success(
        cls,
        intent: CommandIntent,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
        llm_called: bool = False,
        execution_class: CommandExecutionClass = CommandExecutionClass.PURE_QUERY,
        duration_seconds: float = 0.0,
    ) -> CommandResult:
        return cls(
            command_id=intent.command_id,
            name=intent.name,
            status=CommandStatus.SUCCESS,
            message=message,
            data=data or {},
            exit_code=0,
            llm_called=llm_called,
            execution_class=execution_class,
            duration_seconds=duration_seconds,
        )

    @classmethod
    def failure(
        cls,
        intent: CommandIntent,
        message: str,
        error_code: CommandErrorCode = CommandErrorCode.EXECUTION_ERROR,
        exit_code: int = 1,
        data: Optional[Dict[str, Any]] = None,
        duration_seconds: float = 0.0,
    ) -> CommandResult:
        return cls(
            command_id=intent.command_id,
            name=intent.name,
            status=CommandStatus.FAILURE,
            message=message,
            data=data or {},
            exit_code=exit_code,
            llm_called=False,
            execution_class=CommandExecutionClass.PURE_QUERY,
            duration_seconds=duration_seconds,
            error_code=error_code,
        )

    @classmethod
    def denied(
        cls,
        intent: CommandIntent,
        reason: str,
        error_code: CommandErrorCode = CommandErrorCode.SECURITY_DENIED,
        exit_code: int = 3,
        data: Optional[Dict[str, Any]] = None,
    ) -> CommandResult:
        return cls(
            command_id=intent.command_id,
            name=intent.name,
            status=CommandStatus.DENIED,
            message=f"Action denied: {reason}",
            data=data or {},
            exit_code=exit_code,
            llm_called=False,
            execution_class=CommandExecutionClass.PURE_QUERY,
            error_code=error_code,
        )

    @classmethod
    def cancelled(
        cls,
        intent: CommandIntent,
        reason: str = "Operation cancelled by user",
    ) -> CommandResult:
        return cls(
            command_id=intent.command_id,
            name=intent.name,
            status=CommandStatus.CANCELLED,
            message=reason,
            exit_code=5,
            error_code=CommandErrorCode.CANCELLED,
        )


@dataclass(frozen=True)
class AtMention:
    """Structured representation of a parsed @-file or @-directory mention."""
    raw_token: str
    path_str: str
    is_valid_path: bool
    resolved_path: Optional[Path] = None
    is_directory: bool = False
    is_contained: bool = True
    content_or_summary: Optional[str] = None
    error: Optional[str] = None
    file_size_bytes: int = 0
    is_binary: bool = False


@dataclass(frozen=True)
class NormalPromptInput:
    """Unprefixed natural-language prompt directed to AgentLoop."""
    prompt: str


@dataclass(frozen=True)
class SlashCommandInput:
    """Explicit /-prefixed command intent."""
    intent: CommandIntent


@dataclass(frozen=True)
class AtMentionInput:
    """Prompt enriched with resolved @-file mentions."""
    prompt: str
    mentions: Tuple[AtMention, ...] = ()


@dataclass(frozen=True)
class ShellEscapeInput:
    """Explicit !-prefixed user shell command."""
    command_line: str
    raw_text: str
    intent: CommandIntent


@dataclass(frozen=True)
class PaletteTriggerInput:
    """Bare / input requesting interactive command palette."""
    pass


ParsedInput = Union[
    NormalPromptInput,
    SlashCommandInput,
    AtMentionInput,
    ShellEscapeInput,
    PaletteTriggerInput,
]
