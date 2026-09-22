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
        self._t3_ok: bool = False

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
        """Check providers and model availability, update status display."""
        status_widget = self.query_one("#status-section", Static)

        lines: list[tuple[str, str]] = []
        lines.append(("  Checking system status...", "dim"))

        status_widget.update(
            Text.assemble(*[(text + "\n", style) for text, style in lines])
        )

        import os
        from config.model_config import (
            TIER1_PROVIDER, TIER1_MODEL, NVIDIA_API_KEY,
            TIER2_PROVIDER, TIER2_MODEL,
            TIER3_PROVIDER, TIER3_MODEL,
        )

        # 1. Tier 1 Check
        if TIER1_PROVIDER == "nvidia_nim":
            has_t1_key = bool(os.environ.get("NVIDIA_API_KEY", "").strip() or NVIDIA_API_KEY)
            self._t1_ok = has_t1_key
            t1_text = f"✓ {TIER1_MODEL} (NVIDIA NIM)" if has_t1_key else f"✗ missing NVIDIA_API_KEY for {TIER1_MODEL}"
            t1_style = "#22C55E" if has_t1_key else "#EF4444"
        else:
            t1_text = f"✓ {TIER1_MODEL} ({TIER1_PROVIDER})"
            t1_style = "#22C55E"
            self._t1_ok = True

        # 2. Check Ollama (for Tier 2 and Tier 3)
        try:
            from models.ollama_client import OllamaClient
            client = OllamaClient()
            ollama_running = await client.is_running()
            self._ollama_ok = ollama_running

            if ollama_running:
                models = await client.list_models()
                t2_found = any(TIER2_MODEL in m or m in TIER2_MODEL or "gpt-oss" in m.lower() for m in models)
                t3_found = any(TIER3_MODEL in m or m in TIER3_MODEL or "nemotron" in m.lower() for m in models)
                self._t2_ok = t2_found
                self._t3_ok = t3_found
            else:
                models = []
                t2_found = False
                t3_found = False
                self._t2_ok = False
                self._t3_ok = False
        except Exception:
            ollama_running = False
            t2_found = False
            t3_found = False
            self._ollama_ok = False
            self._t2_ok = False
            self._t3_ok = False

        lines = []
        lines.append((
            f"  Ollama:  {'✓ running' if ollama_running else '✗ not running — start with: ollama serve'}",
            "#22C55E" if ollama_running else "#EF4444"
        ))
        lines.append((
            f"  T1:      {t1_text}",
            t1_style
        ))
        t2_status = f"✓ {TIER2_MODEL} (Ollama Cloud)" if (ollama_running and t2_found) else (f"✓ {TIER2_MODEL}" if ollama_running else f"✗ missing — {TIER2_MODEL}")
        lines.append((
            f"  T2:      {t2_status}",
            "#22C55E" if ollama_running else "#EF4444"
        ))
        t3_status = f"✓ {TIER3_MODEL} (Ollama Cloud)" if (ollama_running and t3_found) else (f"✓ {TIER3_MODEL}" if ollama_running else f"✗ missing — {TIER3_MODEL}")
        lines.append((
            f"  T3:      {t3_status}",
            "#22C55E" if ollama_running else "#EF4444"
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
