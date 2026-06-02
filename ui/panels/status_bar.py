# ui/panels/status_bar.py
# HERMES Status Bar — single line at the top of the TUI.
# Shows: mode, active model tier, active skill name, KAIROS status,
#        session cost, and spinner verb during generation.
# Updated reactively from HermesApp reactive attributes.
# Week 15: basic version — expands in Week 16 with full wiring.

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Widget):
    """
    Single-line status bar for HERMES TUI.
    Displays: [MODE] [Tier] [Skill: name] [KAIROS: status] [$cost] | verb...
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 100%;
        background: $panel;
        padding: 0 1;
    }
    """

    mode: reactive[str]     = reactive("auto")
    skill: reactive[str]    = reactive("none")
    cost: reactive[float]   = reactive(0.0)
    kairos: reactive[str]   = reactive("idle")
    processing: reactive[bool] = reactive(False)
    spinner_verb: reactive[str] = reactive("Ready")

    def compose(self) -> ComposeResult:
        yield Static("", id="status-text")

    def _render_status(self) -> Text:
        t = Text()

        # Mode
        mode_colours = {
            "safe": "#F59E0B",
            "plan": "#4A90D9",
            "auto": "#22C55E",
        }
        colour = mode_colours.get(self.mode, "white")
        t.append(f"[{self.mode.upper()}]", style=f"bold {colour}")

        # Tier indicator (always T1+T2 in HERMES)
        t.append("  [T1:Qwen+T2:Mistral]", style="dim")

        # Active skill
        skill_text = self.skill if self.skill != "none" else "none"
        skill_colour = "#22C55E" if self.skill != "none" else "dim"
        t.append(f"  [Skill: {skill_text}]", style=skill_colour)

        # KAIROS status
        kairos_colour = "#22C55E" if self.kairos == "running" else "dim"
        t.append(f"  [KAIROS:{self.kairos}]", style=kairos_colour)

        # Cost
        t.append(f"  [${self.cost:.3f}]", style="dim")

        # Separator + verb
        t.append("  |  ", style="dim")
        if self.processing:
            t.append(f"{self.spinner_verb}...", style="italic dim")
        else:
            t.append("Ready", style="dim")

        return t

    def watch_mode(self, _: str)         -> None: self._update()
    def watch_skill(self, _: str)        -> None: self._update()
    def watch_cost(self, _: float)       -> None: self._update()
    def watch_kairos(self, _: str)       -> None: self._update()
    def watch_processing(self, _: bool)  -> None: self._update()
    def watch_spinner_verb(self, _: str) -> None: self._update()

    def _update(self) -> None:
        try:
            label = self.query_one("#status-text", Static)
            label.update(self._render_status())
        except Exception:
            pass
