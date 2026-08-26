# ui/panels/startup.py
# HERMES Startup Screen — shown before the main TUI when no workspace is locked.
# Displays system status, model availability, and asks for workspace path.

from __future__ import annotations

import asyncio
from pathlib import Path
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, Center
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static
from textual.message import Message


class WorkspaceSelected(Message):
    """Posted when user selects a workspace path."""
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


class StartupScreen(Screen):
    """
    Full-screen startup overlay displayed before the main TUI.
    Checks Ollama availability, shows model status, and gets workspace path.
    """

    CSS = """
    StartupScreen {
        align: center middle;
        background: $background;
    }
    #startup-container {
        width: 70;
        height: auto;
        border: double #22C55E;
        padding: 1 2;
        background: #0d1117;
    }
    #hermes-title {
        color: #22C55E;
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }
    #status-section {
        margin-top: 1;
        margin-bottom: 1;
    }
    #workspace-input {
        width: 100%;
        height: 3;
        border: tall #F59E0B;
        background: #111111;
        margin-bottom: 1;
    }
    #launch-btn {
        width: 100%;
        background: #22C55E;
        color: black;
        text-style: bold;
    }
    #launch-btn:hover {
        background: #16a34a;
    }
    #status-ok { color: #22C55E; }
    #status-warn { color: #F59E0B; }
    #status-err { color: #EF4444; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ollama_ok: bool = False
        self._t1_ok: bool = False
        self._t2_ok: bool = False

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="startup-container"):
                yield Static(
                    "HERMES\nHierarchical Execution and Reasoning\nwith Memory-Evolving Supervision",
                    id="hermes-title"
                )
                yield Static("─" * 60)
                yield Static("", id="status-section")
                yield Static("─" * 60)
                yield Label("Workspace directory (leave blank for current directory):")
                yield Input(
                    placeholder=str(Path.cwd()),
                    id="workspace-input",
                )
                yield Button("[ LAUNCH HERMES ]", id="launch-btn")

    def on_mount(self) -> None:
        self.run_worker(self._check_system_status(), exclusive=True, name="status-check")

    async def _check_system_status(self) -> None:
        """Check Ollama and model availability, update status display."""
        status_widget = self.query_one("#status-section", Static)

        lines: list[tuple[str, str]] = []
        lines.append(("  Checking system status...", "dim"))

        status_widget.update(
            Text.assemble(*[(text + "\n", style) for text, style in lines])
        )

        # Check Ollama
        try:
            from models.ollama_client import OllamaClient
            client = OllamaClient()
            ollama_running = await client.is_running()
            self._ollama_ok = ollama_running

            if ollama_running:
                models = await client.list_models()
                t1_found = any("qwen2.5-coder" in m for m in models)
                t2_found = any("mistral" in m for m in models)
                self._t1_ok = t1_found
                self._t2_ok = t2_found
            else:
                models = []
                t1_found = False
                t2_found = False
        except Exception as e:
            ollama_running = False
            t1_found = False
            t2_found = False
            models = []

        lines = []
        lines.append((
            f"  Ollama:  {'✓ running' if ollama_running else '✗ not running — start with: ollama serve'}",
            "#22C55E" if ollama_running else "#EF4444"
        ))
        lines.append((
            f"  T1:      {'✓ qwen2.5-coder:7b' if t1_found else '✗ missing — ollama pull qwen2.5-coder:7b'}",
            "#22C55E" if t1_found else "#F59E0B"
        ))
        lines.append((
            f"  T2:      {'✓ mistral:7b-instruct' if t2_found else '✗ missing — ollama pull mistral:7b-instruct-q4_K_M'}",
            "#22C55E" if t2_found else "#F59E0B"
        ))

        # Check ANTHROPIC_API_KEY
        import os
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        lines.append((
            f"  T3 API:  {'✓ ANTHROPIC_API_KEY set' if has_key else '⚠ not set — Tier 3 disabled'}",
            "#22C55E" if has_key else "dim"
        ))

        status_widget.update(
            Text.assemble(*[(text + "\n", style) for text, style in lines])
        )

    @on(Button.Pressed, "#launch-btn")
    def handle_launch(self) -> None:
        workspace_input = self.query_one("#workspace-input", Input)
        path = workspace_input.value.strip()
        if not path:
            path = str(Path.cwd())

        # Validate path exists
        if not Path(path).exists():
            self.query_one("#workspace-input", Input).styles.border = ("tall", "red")
            return

        self.dismiss(path)

    @on(Input.Submitted, "#workspace-input")
    def handle_input_submit(self, event: Input.Submitted) -> None:
        self.handle_launch()
