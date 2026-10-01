# core/commands/registry.py
"""
Central Command Registry for HERMES 2.x (Prompt 16).

Central Invariants:
1. CANONICAL DEFINITIONS: All commands registered with explicit LLM, mutation, and execution policies.
2. ALIAS RESOLUTION: Multiple names resolve to a single canonical CommandDefinition without duplication.
3. EXTENSIBLE: Supports skill / custom command fallbacks from Project Intelligence (Prompt 8).
4. COMPLETION ENGINE: Fast prefix and fuzzy matching for the interactive TUI command palette.
"""

from __future__ import annotations

import difflib
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from core.commands.models import (
    CommandDefinition,
    CommandExecutionClass,
    CommandIntent,
    CommandResult,
    LlmPolicy,
)


class CommandRegistry:
    """Authoritative registry for all HERMES slash commands."""

    def __init__(self) -> None:
        self._commands: Dict[str, CommandDefinition] = {}
        self._aliases: Dict[str, str] = {}  # alias -> canonical_name
        self._handlers: Dict[str, Callable[..., Coroutine[Any, Any, CommandResult]]] = {}
        self._skill_provider: Optional[Any] = None

        # Register standard built-in commands
        self._register_builtins()

    def set_skill_provider(self, skill_provider: Any) -> None:
        """Connect Project Intelligence skill registry (Prompt 8)."""
        self._skill_provider = skill_provider

    def register(
        self,
        definition: CommandDefinition,
        handler: Optional[Callable[..., Coroutine[Any, Any, CommandResult]]] = None,
    ) -> None:
        """Register a command definition and its execution handler."""
        canon = definition.name.lower().lstrip("/")
        self._commands[canon] = definition

        for alias in definition.aliases:
            a_clean = alias.lower().lstrip("/")
            self._aliases[a_clean] = canon

        if handler:
            self._handlers[canon] = handler

    def get_definition(self, name: str) -> Optional[CommandDefinition]:
        """Look up canonical command definition by name or alias."""
        clean = name.lower().lstrip("/")
        if clean in self._commands:
            return self._commands[clean]
        if clean in self._aliases:
            canon = self._aliases[clean]
            return self._commands.get(canon)
        return None

    def get_handler(self, name: str) -> Optional[Callable[..., Coroutine[Any, Any, CommandResult]]]:
        """Retrieve handler for command by name or alias."""
        clean = name.lower().lstrip("/")
        canon = self._aliases.get(clean, clean)
        return self._handlers.get(canon)

    def list_commands(self) -> List[CommandDefinition]:
        """List all canonical command definitions in deterministic order."""
        return sorted(self._commands.values(), key=lambda c: (c.category, c.name))

    def complete(self, prefix: str) -> List[Tuple[str, str]]:
        """
        Return command completion suggestions for palette.
        Returns list of (command_name, description).
        """
        clean = prefix.lower().lstrip("/")
        results: List[Tuple[str, str]] = []

        # 1. Exact prefix matches
        for cmd in self.list_commands():
            if cmd.name.startswith(clean):
                results.append((f"/{cmd.name}", cmd.description))

        # 2. Alias prefix matches
        for alias, canon in sorted(self._aliases.items()):
            if alias.startswith(clean) and alias not in [r[0].lstrip("/") for r in results]:
                def_obj = self._commands.get(canon)
                desc = f"Alias for /{canon}"
                if def_obj:
                    desc += f" — {def_obj.description}"
                results.append((f"/{alias}", desc))

        # 3. Fuzzy matches if few results
        if len(results) < 3 and clean:
            all_names = list(self._commands.keys()) + list(self._aliases.keys())
            close = difflib.get_close_matches(clean, all_names, n=3, cutoff=0.5)
            for name in close:
                if f"/{name}" not in [r[0] for r in results]:
                    canon = self._aliases.get(name, name)
                    def_obj = self._commands.get(canon)
                    desc = def_obj.description if def_obj else ""
                    results.append((f"/{name}", desc))

        return results

    def get_help_text(self, command_name: Optional[str] = None) -> str:
        """Generate structured, inspectable help documentation."""
        if command_name:
            cmd = self.get_definition(command_name)
            if not cmd:
                return f"Unknown command: /{command_name}. Use /help to see all commands."

            lines = [
                f"Command: /{cmd.name}",
                f"Category:     {cmd.category}",
                f"Description:  {cmd.description}",
                f"Usage:        {cmd.usage}",
                f"LLM Policy:   {cmd.llm_policy.value}",
                f"Mutates:      {'YES' if cmd.may_mutate else 'NO'}",
                f"Headless:     {'YES' if cmd.headless_supported else 'NO'}",
                f"Replay:       {'YES' if cmd.replay_supported else 'NO'}",
            ]
            if cmd.aliases:
                lines.append(f"Aliases:      {', '.join('/' + a for a in cmd.aliases)}")
            return "\n".join(lines)

        # Full catalog grouped by category
        lines = [
            "HERMES Command Operating System (/help)",
            "=" * 50,
            "Built-in Commands:",
        ]
        by_cat: Dict[str, List[CommandDefinition]] = {}
        for cmd in self.list_commands():
            by_cat.setdefault(cmd.category, []).append(cmd)

        for cat, cmds in sorted(by_cat.items()):
            lines.append(f"\n[{cat}]")
            for c in cmds:
                alias_str = f" (aliases: {', '.join('/' + a for a in c.aliases)})" if c.aliases else ""
                lines.append(f"  /{c.name:<10} - {c.description}{alias_str}")
                lines.append(f"               LLM: {c.llm_policy.value} | Mutates: {'YES' if c.may_mutate else 'NO'} | Headless: {'YES' if c.headless_supported else 'NO'}")

        lines.append("\nPrefixes:")
        lines.append("  /  - Slash Command Namespace (e.g. /status, /diff, /help)")
        lines.append("  @  - Workspace File / Directory Mention (e.g. @src/main.py)")
        lines.append("  !  - Host Shell / OS Execution (e.g. !pytest -q)")
        lines.append("  // - Literal leading slash prompt")

        return "\n".join(lines)

    def _register_builtins(self) -> None:
        """Register canonical HERMES 2.x command definitions."""
        builtins = [
            CommandDefinition(
                name="plan",
                aliases=("planning",),
                category="Planning",
                description="Enter read-only Plan Mode or generate structured task plan.",
                usage="/plan [task description]",
                llm_policy=LlmPolicy.OPTIONAL,
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
            ),
            CommandDefinition(
                name="compact",
                aliases=("compress", "squash"),
                category="Context",
                description="Trigger context compaction and prune transient memory caches.",
                usage="/compact [focus]",
                llm_policy=LlmPolicy.OPTIONAL,
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                may_mutate=True,
                headless_supported=True,
                tui_supported=True,
            ),
            CommandDefinition(
                name="context",
                aliases=("ctx",),
                category="Context",
                description="Display context window composition, token usage, and bloat warnings.",
                usage="/context",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.PURE_QUERY,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
                replay_supported=True,
            ),
            CommandDefinition(
                name="cost",
                aliases=("usage", "tokens"),
                category="Telemetry",
                description="Inspect token usage and model cost breakdown across tiers.",
                usage="/cost",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.PURE_QUERY,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
                replay_supported=True,
            ),
            CommandDefinition(
                name="doctor",
                aliases=("check", "diagnose"),
                category="Diagnostics",
                description="Run system, environment, network, and dependency health checks.",
                usage="/doctor [--probe]",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.PURE_QUERY,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
            ),
            CommandDefinition(
                name="status",
                aliases=("info", "st"),
                category="Core",
                description="Project authoritative runtime, session, and mission status.",
                usage="/status",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.PURE_QUERY,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
                replay_supported=True,
            ),
            CommandDefinition(
                name="rewind",
                aliases=("revert", "rollback", "checkpoint"),
                category="Persistence",
                description="Safely rewind workspace and state to an authoritative checkpoint.",
                usage="/rewind <checkpoint_id> [--confirm]",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                may_mutate=True,
                requires_confirmation=True,
                headless_supported=True,
                tui_supported=True,
            ),
            CommandDefinition(
                name="resume",
                aliases=("continue", "load"),
                category="Persistence",
                description="Resume previous session via 16-step recovery protocol.",
                usage="/resume [session_id]",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                may_mutate=True,
                headless_supported=True,
                tui_supported=True,
            ),
            CommandDefinition(
                name="clear",
                aliases=("reset", "new"),
                category="Persistence",
                description="Start a fresh conversation epoch while preserving durable history.",
                usage="/clear",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.STATE_MUTATION,
                may_mutate=True,
                headless_supported=True,
                tui_supported=True,
            ),
            CommandDefinition(
                name="diff",
                aliases=("changes",),
                category="Inspection",
                description="Inspect uncommitted workspace diffs or changes since checkpoint.",
                usage="/diff",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.PURE_QUERY,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
                replay_supported=True,
            ),
            CommandDefinition(
                name="tasks",
                aliases=("queue", "jobs"),
                category="Inspection",
                description="Display active task queue, progress, and background jobs.",
                usage="/tasks",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.PURE_QUERY,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
                replay_supported=True,
            ),
            CommandDefinition(
                name="goal",
                aliases=("target", "objective"),
                category="Planning",
                description="Set or inspect the authoritative mission goal.",
                usage="/goal [goal description]",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.STATE_MUTATION,
                may_mutate=True,
                headless_supported=True,
                tui_supported=True,
                replay_supported=True,
            ),
            CommandDefinition(
                name="btw",
                aliases=("side", "ask"),
                category="Core",
                description="Ask an isolated side question without polluting mission context.",
                usage="/btw <question>",
                llm_policy=LlmPolicy.OPTIONAL,
                execution_class=CommandExecutionClass.MODEL_OPERATION,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
            ),
            CommandDefinition(
                name="help",
                aliases=("?", "commands"),
                category="Core",
                description="Display help and documentation for all commands.",
                usage="/help [command]",
                llm_policy=LlmPolicy.NEVER,
                execution_class=CommandExecutionClass.PURE_QUERY,
                may_mutate=False,
                headless_supported=True,
                tui_supported=True,
            ),
        ]

        for d in builtins:
            self.register(d)


# Global registry singleton
command_registry = CommandRegistry()
