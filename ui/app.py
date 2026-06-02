# ui/app.py
# HERMES Textual TUI — main application class.
# The App wires the Orchestrator to the terminal interface.
# Architecture:
#   HermesApp (Textual App)
#     └── HermesLayout (Horizontal)
#           ├── ChatPanel (left 55%) — Week 15
#           └── RightPanel (right 45%) — Week 16
#
# The App owns the Orchestrator instance.
# The App starts/stops the KAIROS daemon.
# Panels receive data via Textual reactive attributes and message passing.
# Never import orchestrator inside a panel — always pass data from the App level.

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Footer, Header
from loguru import logger
from textual.message import Message
from ui.panels.status_bar import StatusBar


class UserMessageSent(Message):
    """Posted when the user submits a message in the chat input."""
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class OrchestratorResponse(Message):
    """Posted when the orchestrator finishes processing a request."""
    def __init__(
        self,
        user_request: str,
        final_output: str,
        tool_name: Optional[str],
        success: bool,
        stage_reached: int,
        tier3_called: bool,
        latency_seconds: float,
        trace_id: str,
        skill_ids: list[str],
        error: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.user_request    = user_request
        self.final_output    = final_output
        self.tool_name       = tool_name
        self.success         = success
        self.stage_reached   = stage_reached
        self.tier3_called    = tier3_called
        self.latency_seconds = latency_seconds
        self.trace_id        = trace_id
        self.skill_ids       = skill_ids
        self.error           = error


class ModeChanged(Message):
    """Posted when the user switches Safe/Plan/Auto mode."""
    def __init__(self, new_mode: str) -> None:
        super().__init__()
        self.new_mode = new_mode


class KairosStatusUpdate(Message):
    """Posted by the KAIROS monitor to update the status bar."""
    def __init__(self, stats: dict) -> None:
        super().__init__()
        self.stats = stats


class HermesApp(App):
    """
    HERMES Terminal User Interface.
    Wires the Orchestrator to Textual panels.
    """

    CSS_PATH = Path(__file__).parent / "hermes.css"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+s", "set_mode_safe",  "Safe mode",  show=True),
        Binding("ctrl+p", "set_mode_plan",  "Plan mode",  show=True),
        Binding("ctrl+a", "set_mode_auto",  "Auto mode",  show=True),
        Binding("ctrl+q", "quit",           "Quit",       show=True),
        Binding("ctrl+l", "show_logs",      "Logs",       show=False),
    ]

    # ── Reactive state ────────────────────────────────────────────────
    current_mode: reactive[str]    = reactive("auto")
    current_skill: reactive[str]   = reactive("none")
    is_processing: reactive[bool]  = reactive(False)
    session_cost: reactive[float]  = reactive(0.0)
    kairos_status: reactive[str]   = reactive("idle")

    def __init__(
        self,
        mode: str = "auto",
        project: str = "default",
        debug: bool = False,
    ) -> None:
        super().__init__()
        self._mode    = mode
        self._project = project
        self._debug   = debug
        self._orchestrator: Optional[object] = None
        self._request_queue: asyncio.Queue = asyncio.Queue()

    # ── Lifecycle ─────────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Called when the app starts. Initialise orchestrator and KAIROS."""
        self.current_mode = self._mode
        self._init_orchestrator()
        self.run_worker(self._start_kairos(), exclusive=True, name="kairos-starter")
        self.run_worker(self._kairos_monitor(), exclusive=False, name="kairos-monitor")

    def _init_orchestrator(self) -> None:
        """Initialise the orchestrator. Called synchronously on mount."""
        try:
            from core.orchestrator import Orchestrator
            self._orchestrator = Orchestrator(
                mode=self._mode,
                project=self._project,
            )
            logger.info(f"HermesApp: orchestrator ready | mode={self._mode} | project={self._project}")
        except Exception as e:
            logger.error(f"HermesApp: failed to initialise orchestrator: {e}")
            self._orchestrator = None

    async def _start_kairos(self) -> None:
        """Start KAIROS daemon in background."""
        if self._orchestrator is None:
            return
        try:
            await self._orchestrator.start_kairos()
            logger.info("HermesApp: KAIROS daemon started")
        except Exception as e:
            logger.error(f"HermesApp: KAIROS start failed: {e}")

    async def _kairos_monitor(self) -> None:
        """Poll KAIROS stats every 30 seconds and update status bar."""
        while True:
            await asyncio.sleep(30)
            if self._orchestrator is None:
                continue
            try:
                stats = self._orchestrator.kairos.get_stats()
                self.post_message(KairosStatusUpdate(stats))
                pending = stats.get("pending_tasks", 0)
                cost = stats.get("total_api_cost", 0.0)
                self.session_cost = cost
                self.kairos_status = "running" if stats.get("is_running") else "idle"
            except Exception:
                pass

    async def on_unmount(self) -> None:
        """Stop KAIROS when the app exits."""
        if self._orchestrator is not None:
            try:
                await self._orchestrator.stop_kairos()
            except Exception:
                pass

    # ── Layout ────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        """Build the TUI layout."""
        yield StatusBar(id="status-bar")
        with Horizontal(id="main-layout"):
            from ui.panels.chat import ChatPanel
            yield ChatPanel(id="chat-panel")
            # RightPanel added in Week 16
        yield Footer()

    # ── Request processing ────────────────────────────────────────────

    @on(UserMessageSent)
    async def handle_user_message(self, message: UserMessageSent) -> None:
        """
        Received when the user submits a message.
        Runs the orchestrator in a Textual worker so the UI stays responsive.
        """
        if self.is_processing:
            logger.warning("HermesApp: request received while already processing — queued")
            return

        self.is_processing = True
        self.run_worker(
            self._process_request(message.text),
            exclusive=False,
            name=f"request-{message.text[:20]}",
        )

    async def _process_request(self, user_request: str) -> None:
        """Worker that runs the orchestrator and posts the result."""
        if self._orchestrator is None:
            self.post_message(OrchestratorResponse(
                user_request=user_request,
                final_output="HERMES orchestrator is not initialised. Check the logs.",
                tool_name=None, success=False, stage_reached=0,
                tier3_called=False, latency_seconds=0.0, trace_id="",
                skill_ids=[], error="Orchestrator not initialised",
            ))
            self.is_processing = False
            return

        try:
            result = await self._orchestrator.run(user_request)

            # Update reactive state from result
            if result.skill_ids_used:
                self.current_skill = result.skill_ids_used[0]
            else:
                self.current_skill = "none"

            if result.tier3_called:
                cost = self._orchestrator.claude.get_cost_summary()
                self.session_cost = cost.get("total_spent", 0.0)

            self.post_message(OrchestratorResponse(
                user_request=user_request,
                final_output=result.final_output or "(no output)",
                tool_name=result.tool_name,
                success=result.success,
                stage_reached=result.pipeline_stage_reached,
                tier3_called=result.tier3_called,
                latency_seconds=result.total_latency_seconds,
                trace_id=result.trace_id,
                skill_ids=result.skill_ids_used,
                error=result.error,
            ))

        except Exception as e:
            logger.error(f"HermesApp: orchestrator error: {type(e).__name__}: {e}")
            self.post_message(OrchestratorResponse(
                user_request=user_request,
                final_output=f"Unexpected error: {type(e).__name__}: {str(e)[:200]}",
                tool_name=None, success=False, stage_reached=0,
                tier3_called=False, latency_seconds=0.0, trace_id="",
                skill_ids=[], error=str(e),
            ))
        finally:
            self.is_processing = False

    # ── Mode switching actions ─────────────────────────────────────────

    def action_set_mode_safe(self) -> None:
        self._set_mode("safe")

    def action_set_mode_plan(self) -> None:
        self._set_mode("plan")

    def action_set_mode_auto(self) -> None:
        self._set_mode("auto")

    def _set_mode(self, mode: str) -> None:
        if self._orchestrator is None:
            return
        try:
            self._orchestrator.set_mode(mode)
            self.current_mode = mode
            self.post_message(ModeChanged(mode))
            logger.info(f"HermesApp: mode changed to {mode}")
        except ValueError as e:
            logger.error(f"HermesApp: invalid mode {mode}: {e}")

    def action_show_logs(self) -> None:
        """Open log search — placeholder for Week 16."""
        pass

    # ── Watch reactive changes ────────────────────────────────────────

    def watch_current_mode(self, new_mode: str) -> None:
        self.sub_title = f"mode:{new_mode.upper()}"
        try:
            self.query_one("#status-bar", StatusBar).mode = new_mode
        except Exception:
            pass

    def watch_current_skill(self, new_skill: str) -> None:
        try:
            self.query_one("#status-bar", StatusBar).skill = new_skill
        except Exception:
            pass

    def watch_session_cost(self, new_cost: float) -> None:
        try:
            self.query_one("#status-bar", StatusBar).cost = new_cost
        except Exception:
            pass

    def watch_kairos_status(self, new_status: str) -> None:
        try:
            self.query_one("#status-bar", StatusBar).kairos = new_status
        except Exception:
            pass

    def watch_is_processing(self, processing: bool) -> None:
        try:
            from ui.panels.chat import ChatPanel
            panel = self.query_one(ChatPanel)
            panel.set_input_enabled(not processing)
        except Exception:
            pass
        try:
            self.query_one("#status-bar", StatusBar).processing = processing
        except Exception:
            pass
