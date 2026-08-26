# ui/app.py
# HERMES Textual TUI — main application class.
# Matches the reference design exactly:
#   - StatusBar (docked top, 1 line)
#   - HermesLayout (left ChatPanel 55% + right RightPanel 45%)
#   - ModeButtonsBar (3 equal buttons)
#   - LogBar (docked bottom, 1 line)

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static, Label
from rich.text import Text
from loguru import logger
from textual.message import Message
from textual.screen import ModalScreen
from ui.panels.status_bar import StatusBar

from core.mission_planner import MissionPlanner, Mission, TaskState
from core.mission_runner import MissionRunner, MissionEvent
from core.workspace import workspace_manager as global_workspace
from kairos.mission_driver import MissionDriver
from ui.panels.startup import StartupScreen


# ── Message types ─────────────────────────────────────────────────

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
        is_plan_update: bool = False,
        is_walkthrough: bool = False,
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
        self.is_plan_update  = is_plan_update
        self.is_walkthrough  = is_walkthrough


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


class OrchestratorProgress(Message):
    """Posted when the orchestrator reaches a new stage or event in the pipeline."""
    def __init__(self, event_type: str, data: dict) -> None:
        super().__init__()
        self.event_type = event_type
        self.data = data


# ── LogBar widget ──────────────────────────────────────────────────

class LogBar(Widget):
    """
    Single-line log bar docked at the very bottom of the screen.
    Shows: LOG: <last log message>     Uptime: HH:MM:SS
    """

    DEFAULT_CSS = """
    LogBar {
        height: 3;
        width: 100%;
        background: #0a0a0a;
        padding: 0 1;
        border: round #1a1a1a;
    }
    """

    _log_text: reactive[str] = reactive("System ready. All security gates loaded.")
    _uptime_seconds: int = 0

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick_uptime)

    def _tick_uptime(self) -> None:
        self._uptime_seconds += 1
        self.refresh()

    def update_log(self, message: str) -> None:
        """Call this to update the log message."""
        self._log_text = message
        self.refresh()

    def render(self) -> Text:
        hours   = self._uptime_seconds // 3600
        mins    = (self._uptime_seconds % 3600) // 60
        secs    = self._uptime_seconds % 60
        uptime  = f"{hours:02d}:{mins:02d}:{secs:02d}"

        t = Text(no_wrap=True)
        t.append("LOG: ", style="bold #4B5563")
        clipped_log = self._log_text[:50]
        t.append(clipped_log, style="#4B5563")
        
        width = self.size.width if self.size.width else 80
        left_len = 5 + len(clipped_log)
        right_len = 16
        spaces_count = max(1, width - left_len - right_len - 2)
        
        t.append(" " * spaces_count)
        t.append(f"Uptime: {uptime}", style="#4B5563")
        return t


# ── ConfirmScreen ──────────────────────────────────────────────────

class ConfirmScreen(ModalScreen[bool]):
    """A screen that asks for confirmation before exiting."""
    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #confirm-dialog {
        width: 44;
        height: 11;
        background: #111111;
        border: round #DC2626;
        padding: 1 2;
    }
    #confirm-msg {
        text-align: center;
        margin-bottom: 2;
        color: white;
        text-style: bold;
    }
    #confirm-buttons {
        align: center middle;
        height: 3;
    }
    #confirm-buttons Button {
        margin: 0 1;
        width: 12;
    }
    #confirm-yes {
        background: #DC2626;
        color: white;
        border: none;
    }
    #confirm-no {
        background: #2a2a2a;
        color: white;
        border: none;
    }
    """
    
    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Are you sure you want to quit HERMES?", id="confirm-msg")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", id="confirm-yes")
                yield Button("No", id="confirm-no")
                
    @on(Button.Pressed, "#confirm-yes")
    def on_yes(self) -> None:
        self.dismiss(True)
        
    @on(Button.Pressed, "#confirm-no")
    def on_no(self) -> None:
        self.dismiss(False)


# ── HermesApp ─────────────────────────────────────────────────────

class HermesApp(App):
    """
    HERMES Terminal User Interface.
    Layout (top to bottom):
      StatusBar          — docked top, 1 line
      workspace-container — main body (main-layout) + mode buttons bar
      LogBar             — docked bottom, 1 line
    """

    CSS_PATH = Path(__file__).parent / "hermes.css"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+s", "set_mode_safe",  "Safe mode",  show=False),
        Binding("ctrl+p", "set_mode_plan",  "Plan mode",  show=False),
        Binding("ctrl+a", "set_mode_auto",  "Auto mode",  show=False),
        Binding("ctrl+q", "quit",           "Quit",       show=False),
        Binding("ctrl+l", "show_logs",      "Logs",       show=False),
    ]

    # ── Reactive state ─────────────────────────────────────────────
    current_mode:     reactive[str]   = reactive("auto")
    current_skill:    reactive[str]   = reactive("none")
    is_processing:    reactive[bool]  = reactive(False)
    session_cost:     reactive[float] = reactive(0.0)
    kairos_status:    reactive[str]   = reactive("idle")
    mission_phase:    reactive[str]   = reactive("idle")
    mission_progress: reactive[str]   = reactive("")
    current_task_title: reactive[str] = reactive("")
    workspace_root:   reactive[str]   = reactive("")

    def __init__(
        self,
        mode: str = "auto",
        project: str = "default",
        debug: bool = False,
        show_startup: bool = True,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._project = project
        self._debug = debug
        self._show_startup = show_startup
        self._orchestrator: Optional[object] = None
        self._mission_driver: Optional[MissionDriver] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()

    # ── Lifecycle ──────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Show startup screen first, then initialise."""
        self.current_mode = self._mode
        self._init_orchestrator()

        if self._show_startup and not global_workspace.is_locked:
            # Show startup screen — user picks workspace
            self.push_screen(
                StartupScreen(),
                callback=self._on_startup_complete
            )
        else:
            workspace_path = global_workspace.root_str if global_workspace.is_locked else str(Path.cwd())
            self.run_worker(self._on_startup_complete(workspace_path), exclusive=True, name="startup-complete")

    async def _on_startup_complete(self, workspace_path: str) -> None:
        """Called when user dismisses startup screen with workspace path."""
        # Start KAIROS
        self.run_worker(self._start_kairos(), exclusive=True, name="kairos-starter")
        self.run_worker(self._kairos_monitor(), exclusive=False, name="kairos-monitor")

        # Initialise workspace
        if self._mission_driver:
            summary = await self._mission_driver.initialise_workspace(workspace_path)
            self.workspace_root = summary.get("root", workspace_path)

            # Update status bar with workspace info
            try:
                from ui.panels.status_bar import StatusBar
                sb = self.query_one("#status-bar", StatusBar)
                sb.workspace_name = Path(self.workspace_root).name
                sb.framework = summary.get("framework", "unknown")
            except Exception:
                pass

            # Show welcome message in chat
            try:
                from ui.panels.chat import ChatPanel
                panel = self.query_one(ChatPanel)
                workspace_name = Path(self.workspace_root).name
                framework = summary.get("framework", "unknown")
                file_count = summary.get("total_files", 0)
                await panel._add_system_message(
                    f"Workspace locked: {workspace_name} [{framework}] — {file_count} files indexed\n"
                    f"Type your request. Ctrl+Enter to submit. Ctrl+Q to quit."
                )
            except Exception:
                pass

    def watch_mission_progress(self, progress: str) -> None:
        try:
            from ui.panels.status_bar import StatusBar
            sb = self.query_one("#status-bar", StatusBar)
            sb.mission_tasks = progress
        except Exception:
            pass

    def _init_orchestrator(self) -> None:
        try:
            from core.orchestrator import Orchestrator
            self._orchestrator = Orchestrator(
                mode=self._mode,
                project=self._project,
            )
            self._mission_driver = MissionDriver(self._orchestrator)
            logger.info(f"HermesApp: orchestrator + MissionDriver ready | mode={self._mode} | project={self._project}")
        except Exception as e:
            logger.error(f"HermesApp: failed to initialise orchestrator: {e}")
            self._orchestrator = None
            self._mission_driver = None

    async def _start_kairos(self) -> None:
        if self._orchestrator is None:
            return
        try:
            await self._orchestrator.start_kairos()
            logger.info("HermesApp: KAIROS daemon started")
            # Initialise workspace on startup
            if self._mission_driver:
                summary = await self._mission_driver.initialise_workspace()
                self.workspace_root = summary.get("root", "")
                logger.info(f"Workspace ready: {self.workspace_root}")
        except Exception as e:
            logger.error(f"HermesApp startup error: {e}")

    async def _kairos_monitor(self) -> None:
        while True:
            await asyncio.sleep(30)
            if self._orchestrator is None:
                continue
            try:
                stats = self._orchestrator.kairos.get_stats()
                self.post_message(KairosStatusUpdate(stats))
                self.session_cost  = stats.get("total_api_cost", 0.0)
                self.kairos_status = "running" if stats.get("is_running") else "idle"
            except Exception:
                pass

    async def on_unmount(self) -> None:
        if self._orchestrator is not None:
            try:
                await self._orchestrator.stop_kairos()
            except Exception:
                pass

    # ── Layout ─────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        """Build the complete layout matching reference design. Note: Footer is omitted."""
        from ui.panels.status_bar import StatusBar
        from ui.panels.chat import ChatPanel
        from ui.panels.right_panel import RightPanel

        # 1. Status bar — docked top
        yield StatusBar(id="status-bar")

        # 2. Central workspace container (resolves layout clipping / buttons stacked)
        with Vertical(id="workspace-container"):
            with Horizontal(id="main-layout"):
                yield ChatPanel(id="chat-panel")
                yield RightPanel(project=self._project, id="right-panel")

            # 3. Mode buttons row
            with Horizontal(id="mode-buttons-bar"):
                yield Button(Text("[ SAFE MODE ]"),  id="mode-btn-safe")
                yield Button(Text("[ AUTO MODE ]"),  id="mode-btn-auto")
                yield Button(Text("[ PLAN MODE ]"),  id="mode-btn-plan")

        # 4. Log bar — docked bottom
        yield LogBar(id="log-bar")

    # ── Request processing ─────────────────────────────────────────

    @on(UserMessageSent)
    async def handle_user_message(self, message: UserMessageSent) -> None:
        if self.is_processing:
            return
        self.is_processing = True
        self._current_worker = self._process_request(message.text)

    @work(thread=False)
    async def _process_request(self, user_request: str) -> None:
        """
        Mission-driven request handler using MissionDriver.
        Delegates all planning and execution to MissionDriver.
        """
        if self._mission_driver is None:
            self.post_message(OrchestratorResponse(
                user_request=user_request,
                final_output="HERMES not initialised. Check logs.",
                tool_name=None, success=False, stage_reached=0,
                tier3_called=False, latency_seconds=0.0, trace_id="",
                skill_ids=[], error="Not initialised",
            ))
            self.is_processing = False
            return

        try:
            # Get the event queue from MissionDriver
            self._event_queue = self._mission_driver.get_event_queue()

            # Post the mission plan as soon as it's ready
            plan_task = asyncio.create_task(
                self._wait_for_plan_and_post(user_request),
                name="plan-poster"
            )

            # Start event consumer for live TUI updates
            consumer_task = asyncio.create_task(
                self._consume_mission_events(None),
                name="event-consumer"
            )

            # Run the mission
            mission_result = await self._mission_driver.run_mission(user_request)

            # Clean up background tasks
            plan_task.cancel()
            consumer_task.cancel()
            try:
                await asyncio.gather(plan_task, consumer_task, return_exceptions=True)
            except Exception:
                pass

            # Post final walkthrough
            self.session_cost = mission_result.total_cost_usd
            self.post_message(OrchestratorResponse(
                user_request=user_request,
                final_output=mission_result.walkthrough_text,
                tool_name=None,
                success=mission_result.success,
                stage_reached=12,
                tier3_called=mission_result.tier3_calls > 0,
                latency_seconds=mission_result.total_latency_seconds,
                trace_id=mission_result.mission_id,
                skill_ids=[],
                is_walkthrough=True,
            ))

            # Update right panel
            try:
                from ui.panels.right_panel import RightPanel
                right = self.query_one(RightPanel)
                self.run_worker(
                    right._update_all_tabs(
                        OrchestratorResponse(
                            user_request=user_request,
                            final_output=mission_result.walkthrough_text,
                            tool_name="mission_complete",
                            success=mission_result.success,
                            stage_reached=12,
                            tier3_called=mission_result.tier3_calls > 0,
                            latency_seconds=mission_result.total_latency_seconds,
                            trace_id=mission_result.mission_id,
                            skill_ids=[],
                        ),
                        self._project,
                    ),
                    exclusive=False,
                )
            except Exception:
                pass

        except Exception as exc:
            logger.error(f"HermesApp._process_request error: {exc}")
            self.post_message(OrchestratorResponse(
                user_request=user_request,
                final_output=f"Error: {type(exc).__name__}: {str(exc)[:200]}",
                tool_name=None, success=False, stage_reached=0,
                tier3_called=False, latency_seconds=0.0, trace_id="",
                skill_ids=[], error=str(exc),
            ))
        finally:
            self.is_processing = False

    async def _wait_for_plan_and_post(self, user_request: str) -> None:
        """Wait for mission_planned event and post the plan to the chat panel."""
        try:
            while True:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=30.0)
                if event.event_type == "mission_planned":
                    mission_tasks = event.payload.get("tasks", [])
                    plan_lines = [
                        f"  {i+1:2d}. {t.get('title',''):<45} ○ Pending"
                        for i, t in enumerate(mission_tasks)
                    ]
                    plan_text = "\n".join(plan_lines)
                    self.post_message(OrchestratorResponse(
                        user_request=user_request,
                        final_output=f"Mission: {len(mission_tasks)} tasks\n{plan_text}",
                        tool_name=None, success=True, stage_reached=2,
                        tier3_called=False, latency_seconds=0.0,
                        trace_id=event.payload.get("mission_id", ""),
                        skill_ids=[], is_plan_update=True,
                    ))
                    return
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            pass

    async def _consume_mission_events(self, mission: Optional[Mission]) -> None:
        """
        Consume events from MissionRunner and update the TUI in real-time.
        Runs as a background task alongside the mission.
        Gets mission state from MissionDriver.
        """
        try:
            while True:
                try:
                    event: MissionEvent = await asyncio.wait_for(
                        self._event_queue.get(),
                        timeout=0.5
                    )
                except asyncio.TimeoutError:
                    continue

                event_type = event.event_type
                payload = event.payload

                if event_type == "thought":
                    # Update the spinner verb with the current thought
                    try:
                        from ui.panels.status_bar import StatusBar
                        sb = self.query_one("#status-bar", StatusBar)
                        sb.spinner_verb = payload.get("text", "Thinking")[:20]
                    except Exception:
                        pass

                elif event_type in ("task_start", "task_complete", "task_failed", "repair_attempt"):
                    # Update the checklist in the chat panel
                    current_mission = self._mission_driver.current_mission if self._mission_driver else mission
                    if current_mission:
                        plan_lines = current_mission.get_status_lines()
                        try:
                            from ui.panels.chat import ChatPanel
                            panel = self.query_one(ChatPanel)
                            await panel.update_execution_plan(plan_lines, payload.get("title", ""))
                        except Exception:
                            pass

                        # Update mission progress reactive
                        completed, total = current_mission.progress
                        self.mission_progress = f"{completed}/{total}"
                    if "title" in payload:
                        self.current_task_title = payload["title"]

                elif event_type == "phase_change":
                    self.mission_phase = payload.get("phase", "")

        except asyncio.CancelledError:
            pass

    def action_stop_mission(self) -> None:
        """Stop the currently running mission at the next safe checkpoint."""
        if self._mission_driver:
            self._mission_driver.abort_current_mission()
            logger.info("HermesApp: mission abort requested by user")

    def action_show_logs(self) -> None:
        from utils.logging import search_session_logs
        results = search_session_logs("pipeline", max_results=5)
        if results:
            lines = [f"{r.get('timestamp','')[:19]} | {r.get('event', r.get('message',''))[:60]}" for r in results]
            log_text = "\n".join(lines)
            try:
                from ui.panels.chat import ChatPanel
                panel = self.query_one(ChatPanel)
                self.run_worker(panel._add_system_message(f"Recent logs:\n{log_text}"), exclusive=False)
            except Exception:
                pass

    # ── Mode button handlers ───────────────────────────────────────

    @on(Button.Pressed, "#mode-btn-safe")
    def on_safe_pressed(self, _) -> None:
        self._set_mode("safe")
        self._focus_chat_input()

    @on(Button.Pressed, "#mode-btn-auto")
    def on_auto_pressed(self, _) -> None:
        self._set_mode("auto")
        self._focus_chat_input()

    @on(Button.Pressed, "#mode-btn-plan")
    def on_plan_pressed(self, _) -> None:
        self._set_mode("plan")
        self._focus_chat_input()

    def _focus_chat_input(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    # ── Mode switching ─────────────────────────────────────────────

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

    def _update_mode_buttons(self, active_mode: str) -> None:
        """Update which mode button shows as active."""
        mode_ids = {
            "safe": "mode-btn-safe",
            "auto": "mode-btn-auto",
            "plan": "mode-btn-plan",
        }
        for mode, btn_id in mode_ids.items():
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                if mode == active_mode:
                    btn.add_class("mode-active")
                else:
                    btn.remove_class("mode-active")
            except Exception:
                pass

    def action_quit(self) -> None:
        def check_exit(quit_app: bool) -> None:
            if quit_app:
                self.exit()
        self.push_screen(ConfirmScreen(), check_exit)

    @on(Button.Pressed, "#quit-btn")
    def on_quit_btn_pressed(self) -> None:
        self.action_quit()

    @on(Button.Pressed, "#stop-btn")
    async def on_stop_pressed(self) -> None:
        if self.is_processing:
            self.action_stop_mission()
            if hasattr(self, "_current_worker") and self._current_worker:
                self._current_worker.cancel()
            try:
                log_bar = self.query_one("#log-bar", LogBar)
                log_bar.update_log("Generation stopped by user.")
            except Exception:
                pass
            self.is_processing = False
            self._focus_chat_input()
        else:
            try:
                chat_panel = self.query_one("#chat-panel")
                await chat_panel.submit_prompt()
            except Exception:
                pass

    # ── Watch reactive changes ──────────────────────────────────────────

    def watch_is_processing(self, processing: bool) -> None:
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_processing(processing)
        except Exception:
            pass
        try:
            from ui.panels.chat import ChatPanel
            panel = self.query_one(ChatPanel)
            panel.set_input_enabled(not processing)
        except Exception:
            pass

    def watch_current_mode(self, new_mode: str) -> None:
        self.sub_title = f"mode:{new_mode.upper()}"
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.mode = new_mode
        except Exception:
            pass
        self._update_mode_buttons(new_mode)

    def watch_current_skill(self, new_skill: str) -> None:
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.skill = new_skill
        except Exception:
            pass

    def watch_session_cost(self, new_cost: float) -> None:
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.cost = new_cost
        except Exception:
            pass

    def watch_kairos_status(self, new_status: str) -> None:
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.kairos_status = new_status
        except Exception:
            pass

    def handle_log_record(self, record: dict) -> None:
        """Handle a log record from loguru and update the TUI components in real time."""
        message = record.get("message", "")
        level = record.get("level", {}).name if hasattr(record.get("level"), "name") else str(record.get("level", ""))
        
        # 1. Update bottom LogBar
        try:
            log_bar = self.query_one("#log-bar", LogBar)
            log_bar.update_log(f"{level}: {message}")
        except Exception:
            pass

        # 2. Append to Tool Trace pane in RightPanel
        try:
            right_panel = self.query_one("#right-panel")
            trace_pane = right_panel.query_one("#tool-trace-pane")
            self.run_worker(trace_pane.add_log_entry(level, message))
        except Exception:
            pass

    @on(OrchestratorProgress)
    def handle_orchestrator_progress(self, message: OrchestratorProgress) -> None:
        if message.event_type == "stage_end" and message.data.get("stage") == 3:
            matched = message.data.get("matched", [])
            if matched:
                self.current_skill = matched[0]
            else:
                self.current_skill = "none"

        try:
            chat_panel = self.query_one("#chat-panel")
            progress_widget = chat_panel.query_one("#processing-indicator")
            progress_widget.update_progress(message.event_type, message.data)
        except Exception:
            pass

        try:
            right_panel = self.query_one("#right-panel")
            right_panel.post_message(message)
        except Exception:
            pass

    @on(OrchestratorResponse)
    def handle_orchestrator_response(self, message: OrchestratorResponse) -> None:
        try:
            chat_panel = self.query_one("#chat-panel")
            chat_panel.post_message(message)
        except Exception:
            pass

        try:
            right_panel = self.query_one("#right-panel")
            right_panel.post_message(message)
        except Exception:
            pass
