# ui/panels/status_bar.py
# HERMES Status Bar — full Week 16 implementation.
# Single line at the top of the terminal showing:
#   [MODE] [T1:Model] [Skill: name] [KAIROS:status] [$cost] | SpinnerVerb...
#
# During generation: cycles through spinner verbs every 1.5 seconds (random selection).
# When idle: shows "Ready" in dim style.
# Updates reactively via watch_* methods called from HermesApp.

from __future__ import annotations

import random
from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


# ── 30 spinner verbs — exactly as specified in the master plan ────────

SPINNER_VERBS: list[str] = [
    "Cogitating",      "Ruminating",      "Deliberating",    "Tomfoolering",
    "Wibbling",        "Prestidigitating","Discombobulating","Boondoggling",
    "Shenaniganing",   "Contemplating",   "Reasoning",       "Analysing",
    "Synthesising",    "Pontificating",   "Extrapolating",   "Hypothesising",
    "Calculating",     "Processing",      "Deducing",        "Inferring",
    "Contextualising", "Correlating",     "Distilling",      "Formulating",
    "Constructing",    "Orchestrating",   "Coordinating",    "Evaluating",
    "Pondering",       "Integrating",
]

_VERB_INTERVAL_SECONDS: float = 1.5


def _random_verb() -> str:
    """Return a random verb from SPINNER_VERBS."""
    return random.choice(SPINNER_VERBS)


class StatusBar(Widget):
    """
    HERMES Status Bar — single line docked at the top.
    Format: [MODE] [T1:Model] [Skill: name] [KAIROS:status] [$cost] | Verb...
    All fields update reactively. Spinner cycles during generation.
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 100%;
        background: $panel;
        padding: 0 1;
        dock: top;
        layer: above;
    }
    #status-line {
        width: 100%;
        height: 1;
    }
    """

    # ── Reactive state ────────────────────────────────────────────────
    mode: reactive[str]          = reactive("auto",   layout=False)
    skill: reactive[str]         = reactive("none",   layout=False)
    cost: reactive[float]        = reactive(0.0,      layout=False)
    kairos_status: reactive[str] = reactive("idle",   layout=False)
    processing: reactive[bool]   = reactive(False,    layout=False)
    spinner_verb: reactive[str]  = reactive("Ready",  layout=False)
    tier1_model: reactive[str]   = reactive("Qwen",   layout=False)
    tier2_model: reactive[str]   = reactive("Mistral",layout=False)

    # Internal timer handle
    _spinner_timer: Optional[object] = None

    def compose(self) -> ComposeResult:
        yield Static(self._render_status_line(), id="status-line")

    def on_mount(self) -> None:
        self._update_display()

    # ── Reactive watchers ─────────────────────────────────────────────

    def watch_mode(self, _: str) -> None:
        self._update_display()

    def watch_skill(self, _: str) -> None:
        self._update_display()

    def watch_cost(self, _: float) -> None:
        self._update_display()

    def watch_kairos_status(self, _: str) -> None:
        self._update_display()

    def watch_processing(self, processing: bool) -> None:
        if processing:
            self._start_spinner()
        else:
            self._stop_spinner()
        self._update_display()

    def watch_spinner_verb(self, _: str) -> None:
        self._update_display()

    # ── Spinner management ────────────────────────────────────────────

    def _start_spinner(self) -> None:
        """Start cycling through spinner verbs."""
        if self._spinner_timer is not None:
            return  # Already running
        self.spinner_verb = _random_verb()
        self._spinner_timer = self.set_interval(
            _VERB_INTERVAL_SECONDS,
            self._cycle_verb
        )

    def _stop_spinner(self) -> None:
        """Stop the spinner and reset to Ready."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self.spinner_verb = "Ready"

    def _cycle_verb(self) -> None:
        """Pick a new random verb. Called by timer every 1.5 seconds."""
        current = self.spinner_verb
        new_verb = _random_verb()
        # Avoid showing the same verb twice in a row
        while new_verb == current and len(SPINNER_VERBS) > 1:
            new_verb = _random_verb()
        self.spinner_verb = new_verb

    # ── Rendering ─────────────────────────────────────────────────────

    def _render_status(self) -> Text:
        """Alias for compatibility with test suites."""
        return self._render_status_line()

    def _render_status_line(self) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")

        # ── Mode ──────────────────────────────────────────────────────
        mode_colours = {
            "safe": "#F59E0B",
            "plan": "#4A90D9",
            "auto": "#22C55E",
        }
        mode_colour = mode_colours.get(self.mode, "white")
        t.append(f"[{self.mode.upper()}]", style=f"bold {mode_colour}")

        # ── Active model tier ─────────────────────────────────────────
        t.append(f"  T1:{self.tier1_model}", style="dim")
        t.append(f"+T2:{self.tier2_model}", style="dim")

        # ── Active skill ──────────────────────────────────────────────
        if self.skill and self.skill != "none":
            t.append(f"  [Skill: {self.skill}]", style="#22C55E")
        else:
            t.append("  [Skill: none]", style="dim")

        # ── KAIROS status ─────────────────────────────────────────────
        kairos_colour = "#22C55E" if self.kairos_status == "running" else "dim"
        t.append(f"  [KAIROS:{self.kairos_status}]", style=kairos_colour)

        # ── Session cost ──────────────────────────────────────────────
        cost_colour = "#F59E0B" if self.cost > 15.0 else "dim"
        t.append(f"  [${self.cost:.3f}]", style=cost_colour)

        # ── Separator ─────────────────────────────────────────────────
        t.append("  |  ", style="dim")

        # ── Spinner verb or Ready ─────────────────────────────────────
        if self.processing:
            t.append(f"{self.spinner_verb}...", style="italic dim #4A90D9")
        else:
            t.append("Ready", style="dim")

        return t

    def _update_display(self) -> None:
        """Re-render the status line."""
        try:
            label = self.query_one("#status-line", Static)
            label.update(self._render_status_line())
        except Exception:
            pass

    # ── Public API for HermesApp ──────────────────────────────────────

    def set_processing(self, processing: bool, verb: Optional[str] = None) -> None:
        """Called by HermesApp to start/stop the spinner."""
        if verb:
            self.spinner_verb = verb
        self.processing = processing

    def update_all(
        self,
        mode: Optional[str] = None,
        skill: Optional[str] = None,
        cost: Optional[float] = None,
        kairos: Optional[str] = None,
    ) -> None:
        """Batch update multiple fields at once."""
        if mode is not None:
            self.mode = mode
        if skill is not None:
            self.skill = skill
        if cost is not None:
            self.cost = cost
        if kairos is not None:
            self.kairos_status = kairos
