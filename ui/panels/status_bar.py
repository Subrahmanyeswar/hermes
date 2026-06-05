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
from textual.widgets import Static, Button


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
    StatusBar at the top, 1 line, full width.
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
    _last_log_entry: reactive[str] = reactive("", layout=False)

    # Internal timer handle
    _spinner_timer: Optional[object] = None

    def compose(self) -> ComposeResult:
        yield Static(self._render_status_line(), id="status-line")
        yield Button(Text("[ QUIT ]"), id="quit-btn")

    def on_mount(self) -> None:
        try:
            self.mode = self.app.current_mode
            self.skill = self.app.current_skill
            self.cost = self.app.session_cost
            self.kairos_status = self.app.kairos_status
            self.processing = self.app.is_processing
        except Exception:
            pass
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

    def update_log_line(self, log_entry: str) -> None:
        """Update the bottom log line with the latest pipeline event.
        Truncate to 120 characters for brevity.
        """
        if len(log_entry) > 120:
            log_entry = log_entry[:117] + "..."
        self._last_log_entry = log_entry
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
        
        mode_colours = {"safe": "#F59E0B", "plan": "#4A90D9", "auto": "#22C55E"}
        mode_colour = mode_colours.get(self.mode, "white")
        t.append(f"[{self.mode.upper()}]", style=f"bold {mode_colour}")
        
        t1_name = "Qwen2.5-Coder" if "Qwen" in self.tier1_model else self.tier1_model
        t.append(f"  [T1: {t1_name}]", style="#4A90D9")
        
        if self.skill and self.skill != "none":
            t.append(f"  [Skill: {self.skill}]", style="bold #4A90D9")
        else:
            t.append("  [Skill: none]", style="dim #6B7280")
        
        t.append("  [KAIROS: ")
        if self.kairos_status == "running":
            t.append("running", style="bold #22C55E")
        else:
            t.append("idle", style="dim #6B7280")
        t.append("]")
        
        t.append(f"  [Cost: ${self.cost:.2f}]", style="#F59E0B")
        
        t.append("  |  ", style="dim #6B7280")
        
        if self.processing:
            t.append(f"{self.spinner_verb}...", style="italic dim #4A90D9")
        else:
            t.append("Ready", style="dim #6B7280")
        
        return t

    def _render(self) -> Text:
        """Render full status bar including bottom log line."""
        status = self._render_status_line()
        if self._last_log_entry:
            status.append("\n")
            status.append(self._last_log_entry, style="dim #6B7280")
        return status

    def _update_display(self) -> None:
        """Re-render the status line."""
        try:
            label = self.query_one("#status-line", Static)
            label.update(self._render())
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
