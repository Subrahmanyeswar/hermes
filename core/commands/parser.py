# core/commands/parser.py
"""
Centralized Unified Input Parser for HERMES 2.x (Prompt 16).

Transforms raw user inputs across TUI, CLI, and Headless into typed ParsedInput:
- Slash commands (/)
- Shell escapes (!)
- File/directory mentions (@)
- Normal prompts
- Command palette triggers

Guarantees:
1. DETERMINISTIC: Same input string produces identical typed structures across all surfaces.
2. ADVERSARIAL RESILIENCE: Zero crashes on malformed inputs, unclosed quotes, null bytes, huge strings.
3. ZERO EVAL/EXEC: Strict lexical analysis only.
"""

from __future__ import annotations

import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from core.commands.models import (
    AtMention,
    AtMentionInput,
    CommandIntent,
    CommandOrigin,
    NormalPromptInput,
    PaletteTriggerInput,
    ParsedInput,
    ShellEscapeInput,
    SlashCommandInput,
)

# Email address regex to avoid false-positive @ mentions
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

# Regex to find @mentions: either @"quoted path" or @path/to/file
_MENTION_PATTERN = re.compile(
    r'(?<!\S)@(?:"([^"\n]+)"|\'([^\'\n]+)\'|([^\s@,;:\(\)\[\]{}<>"\']+))'
)


class UnifiedInputParser:
    """Central parser for all operator and prompt input across HERMES surfaces."""

    @classmethod
    def parse(
        cls,
        text: Any,
        origin: CommandOrigin = CommandOrigin.USER_CLI,
        session_id: Optional[str] = None,
        mission_id: Optional[str] = None,
    ) -> ParsedInput:
        """
        Parse raw input into a canonical ParsedInput.
        Never raises exceptions on malformed text.
        """
        if text is None:
            return NormalPromptInput(prompt="")

        if not isinstance(text, str):
            text = str(text)

        # Sanitize raw control null bytes to prevent tokenizer truncation attacks
        text = text.replace("\x00", "")
        stripped = text.strip()

        if not stripped:
            return NormalPromptInput(prompt="")

        # 1. Deterministic Escapes (//, @@, !!)
        if stripped.startswith("//"):
            return NormalPromptInput(prompt=stripped[1:])
        if stripped.startswith("@@"):
            return NormalPromptInput(prompt=stripped[1:])
        if stripped.startswith("!!"):
            return NormalPromptInput(prompt=stripped[1:])

        # 2. Command Palette Trigger
        if stripped == "/":
            return PaletteTriggerInput()

        # 3. Slash Command Namespace (/)
        if stripped.startswith("/"):
            return cls._parse_slash_command(
                raw_text=stripped,
                origin=origin,
                session_id=session_id,
                mission_id=mission_id,
            )

        # 4. OS / Shell Escape (!)
        if stripped.startswith("!"):
            return cls._parse_shell_escape(
                raw_text=stripped,
                origin=origin,
                session_id=session_id,
                mission_id=mission_id,
            )

        # 5. File / Directory Mentions (@)
        mentions = cls._extract_mentions(stripped)
        if mentions:
            return AtMentionInput(prompt=stripped, mentions=tuple(mentions))

        # 6. Normal Agent Prompt
        return NormalPromptInput(prompt=stripped)

    @classmethod
    def _parse_slash_command(
        cls,
        raw_text: str,
        origin: CommandOrigin,
        session_id: Optional[str],
        mission_id: Optional[str],
    ) -> SlashCommandInput:
        body = raw_text[1:].strip()
        if not body:
            return SlashCommandInput(
                intent=CommandIntent.create(
                    name="help",
                    raw_text=raw_text,
                    origin=origin,
                    session_id=session_id,
                    mission_id=mission_id,
                )
            )

        # Safe tokenization handling unclosed quotes
        try:
            tokens = shlex.split(body)
        except ValueError:
            tokens = body.split()

        if not tokens:
            return SlashCommandInput(
                intent=CommandIntent.create(
                    name="help",
                    raw_text=raw_text,
                    origin=origin,
                    session_id=session_id,
                    mission_id=mission_id,
                )
            )

        cmd_name = tokens[0].lower()
        raw_args = tokens[1:]

        # Separate positional args and flags (--flag or --key=val or -k val)
        args: List[str] = []
        kwargs: Dict[str, Any] = {}
        i = 0
        while i < len(raw_args):
            arg = raw_args[i]
            if arg.startswith("--"):
                flag_body = arg[2:]
                if "=" in flag_body:
                    k, v = flag_body.split("=", 1)
                    kwargs[k.replace("-", "_")] = v
                else:
                    k = flag_body.replace("-", "_")
                    if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                        kwargs[k] = raw_args[i + 1]
                        i += 1
                    else:
                        kwargs[k] = True
            elif arg.startswith("-") and len(arg) > 1 and not arg[1:].isdigit():
                flag_body = arg[1:]
                if "=" in flag_body:
                    k, v = flag_body.split("=", 1)
                    kwargs[k] = v
                else:
                    k = flag_body
                    if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                        kwargs[k] = raw_args[i + 1]
                        i += 1
                    else:
                        kwargs[k] = True
            else:
                args.append(arg)
            i += 1

        intent = CommandIntent.create(
            name=cmd_name,
            raw_text=raw_text,
            args=tuple(args),
            kwargs=kwargs,
            origin=origin,
            session_id=session_id,
            mission_id=mission_id,
        )
        return SlashCommandInput(intent=intent)

    @classmethod
    def _parse_shell_escape(
        cls,
        raw_text: str,
        origin: CommandOrigin,
        session_id: Optional[str],
        mission_id: Optional[str],
    ) -> ShellEscapeInput:
        command_line = raw_text[1:].strip()
        intent = CommandIntent.create(
            name="shell",
            raw_text=raw_text,
            args=(command_line,),
            kwargs={"command_line": command_line},
            origin=origin,
            session_id=session_id,
            mission_id=mission_id,
        )
        return ShellEscapeInput(
            command_line=command_line,
            raw_text=raw_text,
            intent=intent,
        )

    @classmethod
    def _extract_mentions(cls, text: str) -> List[AtMention]:
        """Extract valid @path mentions from text while ignoring email addresses."""
        # Find all email matches first to avoid mentioning emails
        email_spans = [m.span() for m in _EMAIL_PATTERN.finditer(text)]

        mentions: List[AtMention] = []
        for match in _MENTION_PATTERN.finditer(text):
            start, end = match.span()
            # Check if this match falls inside any email span
            inside_email = any(e_start <= start and end <= e_end for e_start, e_end in email_spans)
            if inside_email:
                continue

            raw_token = match.group(0)
            # The capture groups are: 1 for double quoted, 2 for single quoted, 3 for bare path
            path_str = match.group(1) or match.group(2) or match.group(3) or ""
            path_str = path_str.strip()

            if not path_str:
                continue

            mentions.append(
                AtMention(
                    raw_token=raw_token,
                    path_str=path_str,
                    is_valid_path=True,
                )
            )

        return mentions
