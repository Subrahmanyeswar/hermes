# core/commands/__init__.py
"""
HERMES 2.x Command Operating System (Prompt 16).

Central Invariants:
ONE ENGINE, MANY SURFACES.
All surfaces (TUI, CLI run, headless, replay) share:
- The same command definitions and metadata
- The same unified input parser (/ @ !)
- The same command dispatcher
- The same security authority (Prompt 13)
- The same persistent state model (Prompt 14)
"""

from core.commands.dispatcher import CommandDispatcher
from core.commands.mentions import MentionResolver
from core.commands.models import (
    AtMention,
    AtMentionInput,
    CommandDefinition,
    CommandErrorCode,
    CommandExecutionClass,
    CommandIntent,
    CommandOrigin,
    CommandResult,
    CommandStatus,
    LlmPolicy,
    NormalPromptInput,
    PaletteTriggerInput,
    ParsedInput,
    ShellEscapeInput,
    SlashCommandInput,
)
from core.commands.parser import UnifiedInputParser
from core.commands.registry import CommandRegistry, command_registry
from core.commands.shell import ShellExecutor

__all__ = [
    "CommandDefinition",
    "CommandIntent",
    "CommandResult",
    "CommandStatus",
    "CommandErrorCode",
    "CommandOrigin",
    "CommandExecutionClass",
    "LlmPolicy",
    "ParsedInput",
    "NormalPromptInput",
    "SlashCommandInput",
    "AtMentionInput",
    "ShellEscapeInput",
    "PaletteTriggerInput",
    "AtMention",
    "UnifiedInputParser",
    "MentionResolver",
    "ShellExecutor",
    "CommandRegistry",
    "command_registry",
    "CommandDispatcher",
]
