# ui/panels/chat.py
# HERMES Chat Panel — left 55% of the TUI.
# Responsibilities:
#   - Display conversation history (user messages + HERMES responses)
#   - Accept user text input and post UserMessageSent message
#   - Render tool call results as styled panels inside messages
#   - Show processing indicator (spinner verb) while orchestrator runs
#   - Scroll to bottom automatically after each new message
#   - Errors shown in amber, success in green
#
# Never call the orchestrator directly — only posts messages to App.
# Never store conversation state — App owns that.

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Optional

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, Static

from ui.app import (
    ModeChanged,
    OrchestratorResponse,
    UserMessageSent,
)

SPINNER_VERBS: list[str] = [
    "Cogitating", "Ruminating", "Deliberating", "Tomfoolering",
    "Wibbling", "Prestidigitating", "Discombobulating", "Boondoggling",
    "Shenaniganing", "Contemplating", "Reasoning", "Analysing",
    "Synthesising", "Pontificating", "Extrapolating", "Hypothesising",
    "Calculating", "Processing", "Deducing", "Inferring",
    "Contextualising", "Correlating", "Distilling", "Formulating",
    "Constructing", "Orchestrating", "Coordinating", "Evaluating",
    "Deliberating", "Integrating",
]

_spinner_cycle = itertools.cycle(SPINNER_VERBS)


class UserMessageWidget(Static):
    """
    Renders one user message in the chat history.
    Styled with a navy left border and bold YOU: label.
    """
    DEFAULT_CSS = """
    UserMessageWidget {
        width: 100%;
        margin-bottom: 1;
        padding: 0 1;
        border-left: thick $accent;
        background: $surface;
    }
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text

    def render(self) -> Text:
        t = Text()
        t.append("YOU:  ", style="bold #4A90D9")
        t.append(self._text, style="white")
        return t


class HermesMessageWidget(Static):
    """
    Renders one HERMES response in the chat history.
    Success responses have a green left border.
    Error responses have an amber left border.
    Includes tool call info when available.
    """
    DEFAULT_CSS = """
    HermesMessageWidget {
        width: 100%;
        margin-bottom: 1;
        padding: 0 1;
    }

    HermesMessageWidget.success {
        border-left: thick $success;
        background: $panel;
    }

    HermesMessageWidget.error {
        border-left: thick $warning;
        background: $panel;
    }
    """

    def __init__(
        self,
        response: OrchestratorResponse,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._response = response
        # Apply CSS class based on success
        if response.success:
            self.add_class("success")
        else:
            self.add_class("error")

    def render(self) -> Text:
        r = self._response
        t = Text()

        # ── Label line ────────────────────────────────────────────────
        label_style = "bold #22C55E" if r.success else "bold #F59E0B"
        label_text = "HERMES:" if r.success else "HERMES [ERROR]:"
        t.append(f"{label_text}\n", style=label_style)

        # ── Main output ───────────────────────────────────────────────
        output_lines = r.final_output.split("\n")
        for line in output_lines[:30]:  # Cap at 30 lines per message
            t.append(f"  {line}\n", style="white")
        if len(output_lines) > 30:
            t.append(f"  ... ({len(output_lines) - 30} more lines)\n", style="dim")

        # ── Tool call summary ─────────────────────────────────────────
        if r.tool_name:
            tool_style = "bold #22C55E" if r.success else "bold #EF4444"
            tool_icon = "✓" if r.success else "✗"
            t.append(
                f"\n  {tool_icon} Tool: {r.tool_name} | "
                f"Stage: {r.stage_reached}/12 | "
                f"{r.latency_seconds:.1f}s",
                style=tool_style
            )
            if r.skill_ids:
                t.append(f" | Skill: {r.skill_ids[0]}", style="dim #22C55E")
            if r.tier3_called:
                t.append(" | [T3]", style="bold #F59E0B")
            if r.trace_id:
                t.append(f" | trace:{r.trace_id}", style="dim")

        return t


class ProcessingIndicator(Static):
    """
    Shown while the orchestrator is processing.
    Cycles through spinner verbs every 2 seconds.
    """
    DEFAULT_CSS = """
    ProcessingIndicator {
        width: 100%;
        padding: 0 1;
        color: $text-muted;
        text-style: italic;
    }
    """

    verb: reactive[str] = reactive("Cogitating")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._timer_handle: Optional[object] = None

    def on_mount(self) -> None:
        self._timer_handle = self.set_interval(2.0, self._next_verb)

    def _next_verb(self) -> None:
        self.verb = next(_spinner_cycle)

    def render(self) -> Text:
        t = Text()
        t.append("⟳ ", style="bold #4A90D9")
        t.append(f"{self.verb}...", style="italic dim")
        return t

    def on_unmount(self) -> None:
        if self._timer_handle:
            self._timer_handle.stop()


class ChatPanel(Widget):
    """
    The main chat panel — left 55% of the HERMES TUI.
    Owns the conversation history display and the text input.
    """

    DEFAULT_CSS = """
    ChatPanel {
        width: 55%;
        height: 100%;
        border-right: tall $panel;
    }

    #chat-history {
        height: 1fr;
        width: 100%;
        overflow-y: auto;
        padding: 0 1;
    }

    #chat-input-container {
        height: auto;
        width: 100%;
        border-top: tall $panel;
        padding: 0 1 1 1;
    }

    #mode-indicator {
        color: $text-muted;
        margin-bottom: 0;
        padding: 0 0;
    }

    #chat-input {
        width: 100%;
        height: 3;
        border: tall $accent;
        background: $surface;
    }

    #chat-input:focus {
        border: tall $accent-lighten-1;
    }

    #chat-input:disabled {
        border: tall $panel;
        opacity: 0.5;
    }
    """

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="chat-history"):
            yield Static(
                Text.assemble(
                    ("HERMES", "bold #4A90D9"),
                    (" — Hierarchical Execution and Reasoning with Memory-Evolving Supervision\n", "dim"),
                    ("Type your request below. ", "dim"),
                    ("Ctrl+S", "bold"),
                    ("=Safe  ", "dim"),
                    ("Ctrl+P", "bold"),
                    ("=Plan  ", "dim"),
                    ("Ctrl+A", "bold"),
                    ("=Auto  ", "dim"),
                    ("Ctrl+Q", "bold"),
                    ("=Quit", "dim"),
                ),
                id="welcome-message",
            )

        with Vertical(id="chat-input-container"):
            yield Label("[AUTO] > ", id="mode-indicator")
            yield Input(
                placeholder="Type your request and press Enter...",
                id="chat-input",
            )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#chat-input", Input).focus()

    # ── Input handling ────────────────────────────────────────────────

    @on(Input.Submitted, "#chat-input")
    async def handle_input_submitted(self, event: Input.Submitted) -> None:
        """User pressed Enter — post UserMessageSent to the App."""
        text = event.value.strip()
        if not text:
            return

        # Clear the input immediately
        event.input.value = ""

        # Handle slash commands
        if text.startswith("/"):
            await self._handle_slash_command(text)
            return

        # Post to App for orchestrator processing
        self.post_message(UserMessageSent(text))

        # Add user message to history immediately (optimistic UI)
        await self._add_user_message(text)

        # Show processing indicator
        await self._show_processing_indicator()

    async def _handle_slash_command(self, command: str) -> None:
        """Handle / commands without sending to orchestrator."""
        cmd = command.lower().strip()

        if cmd in ("/quit", "/q", "/exit"):
            self.app.exit()
        elif cmd == "/clear":
            history = self.query_one("#chat-history", ScrollableContainer)
            await history.remove_children()
            await history.mount(Static(
                "Chat cleared.", classes="hermes-message-text"
            ))
        elif cmd.startswith("/mode "):
            mode = cmd.split()[-1]
            if mode in ("safe", "plan", "auto"):
                self.app._set_mode(mode)
            else:
                await self._add_system_message(
                    f"Unknown mode '{mode}'. Use: /mode safe | /mode plan | /mode auto"
                )
        elif cmd == "/help":
            help_text = (
                "Slash commands:\n"
                "  /clear       — Clear conversation history\n"
                "  /mode safe   — Switch to Safe mode (read-only)\n"
                "  /mode plan   — Switch to Plan mode (confirm before execute)\n"
                "  /mode auto   — Switch to Auto mode (execute directly)\n"
                "  /push        — Push to GitHub (Week 17)\n"
                "  /export      — Export project as ZIP (Week 17)\n"
                "  /vscode      — Open in VS Code (Week 17)\n"
                "  /quit        — Exit HERMES"
            )
            await self._add_system_message(help_text)
        else:
            await self._add_system_message(
                f"Unknown command: {command}\nType /help for available commands."
            )

    # ── Message rendering ─────────────────────────────────────────────

    async def _add_user_message(self, text: str) -> None:
        """Add a user message bubble to the chat history."""
        history = self.query_one("#chat-history", ScrollableContainer)
        widget = UserMessageWidget(text)
        await history.mount(widget)
        history.scroll_end(animate=False)

    async def _add_system_message(self, text: str) -> None:
        """Add a system/info message (not from user or HERMES) to chat."""
        history = self.query_one("#chat-history", ScrollableContainer)
        await history.mount(Static(
            Text(f"  ℹ {text}", style="dim"),
        ))
        history.scroll_end(animate=False)

    async def _show_processing_indicator(self) -> None:
        """Mount the processing indicator while orchestrator runs."""
        history = self.query_one("#chat-history", ScrollableContainer)
        try:
            existing = self.query_one("#processing-indicator")
            # Already showing — don't add another
        except Exception:
            indicator = ProcessingIndicator(id="processing-indicator")
            await history.mount(indicator)
            history.scroll_end(animate=False)

    async def _remove_processing_indicator(self) -> None:
        """Remove the processing indicator after response arrives."""
        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            await indicator.remove()
        except Exception:
            pass

    # ── App message handlers ──────────────────────────────────────────

    @on(OrchestratorResponse)
    async def handle_orchestrator_response(self, message: OrchestratorResponse) -> None:
        """Received when orchestrator finishes. Replace spinner with response."""
        await self._remove_processing_indicator()

        history = self.query_one("#chat-history", ScrollableContainer)
        response_widget = HermesMessageWidget(message)
        await history.mount(response_widget)
        history.scroll_end(animate=False)

    @on(ModeChanged)
    def handle_mode_changed(self, message: ModeChanged) -> None:
        """Update the mode indicator label when mode changes."""
        try:
            label = self.query_one("#mode-indicator", Label)
            mode_colours = {
                "safe": "bold #F59E0B",
                "plan": "bold #4A90D9",
                "auto": "bold #22C55E",
            }
            colour = mode_colours.get(message.new_mode, "bold white")
            label.update(
                Text.assemble(
                    (f"[{message.new_mode.upper()}]", colour),
                    (" > ", "dim"),
                )
            )
        except Exception:
            pass

    # ── Input state management ────────────────────────────────────────

    def set_input_enabled(self, enabled: bool) -> None:
        """Enable or disable the text input (called by App while processing)."""
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.disabled = not enabled
            if enabled:
                chat_input.focus()
        except Exception:
            pass
