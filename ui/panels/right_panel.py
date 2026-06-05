# ui/panels/right_panel.py
# HERMES Right Panel — right 45% of the TUI.
# Contains a TabbedContent widget with 3 tabs:
#   Tab 1: Tool Trace   — every tool call: name, params, exit code, output, timestamp
#   Tab 2: Memory View  — live MEMORY.md content, lines added this session highlighted
#   Tab 3: Task Queue   — all SQLite tasks: pending, running, completed, failed
#
# All tabs update reactively when OrchestratorResponse is received.
# The Task Queue tab also polls SQLite every 30 seconds via a timer.
# Never call the orchestrator directly — only reads data from messages.

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.text import Text

from loguru import logger
from textual import on
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Label,
    Static,
    TabbedContent,
    TabPane,
    Tab,
)

from ui.app import OrchestratorResponse, OrchestratorProgress


class ToolTraceEntry(Static):
    """
    Renders one tool call entry in the Tool Trace tab.
    Format:
      ✓ write_file  0.45s  exit:0   14:32:05
        path=hello.py content=...
        Written 14 characters to hello.py
    """

    DEFAULT_CSS = """
    ToolTraceEntry {
        width: 100%;
        margin-bottom: 1;
        padding: 0 1;
        border-left: thick $panel;
    }
    ToolTraceEntry.running {
        border-left: thick #4A90D9;
    }
    ToolTraceEntry.success {
        border-left: thick $success;
    }
    ToolTraceEntry.failure {
        border-left: thick $error;
    }
    """

    def __init__(
        self,
        tool_name: str,
        success: Optional[bool],
        exit_code: int,
        output_preview: str,
        latency: float,
        tier3_called: bool,
        trace_id: str,
        skill_ids: list[str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._tool_name     = tool_name
        self._success       = success
        self._exit_code     = exit_code
        self._output_preview = output_preview
        self._latency       = latency
        self._tier3_called  = tier3_called
        self._trace_id      = trace_id
        self._skill_ids     = skill_ids
        self._timestamp     = datetime.now().strftime("%H:%M:%S")

        self.update_classes(success)

    def update_classes(self, success: Optional[bool]) -> None:
        self.remove_class("success", "failure", "running")
        if success is True:
            self.add_class("success")
        elif success is False:
            self.add_class("failure")
        else:
            self.add_class("running")

    def update_result(
        self,
        success: bool,
        exit_code: int,
        output_preview: str,
        latency: float,
        tier3_called: bool = False,
        trace_id: str = "",
        skill_ids: list[str] = None,
    ) -> None:
        self._success = success
        self._exit_code = exit_code
        self._output_preview = output_preview
        self._latency = latency
        self._tier3_called = tier3_called
        self._trace_id = trace_id
        if skill_ids:
            self._skill_ids = skill_ids
        self.update_classes(success)
        self.refresh()

    def render(self) -> Text:
        t = Text()
        
        # Line 1: timestamp + tool name
        t.append(f"[{self._timestamp}]", style="dim #4B5563")
        t.append(" tool: ", style="dim #4B5563")
        t.append(f"{self._tool_name}\n", style="bold white")
        
        # Line 2: params (abbreviated)
        t.append("  params: ", style="dim #4B5563")
        if self._success is not None:
            params_preview = f"exit_code={self._exit_code}"
            t.append(f"{{{params_preview}}}\n", style="dim #6B7280")
        else:
            t.append("{executing...}\n", style="dim #6B7280")
        
        # Line 3: result
        t.append("  result: ", style="dim #4B5563")
        if self._success is True:
            t.append("[SUCCESS]", style="bold #22C55E")
            t.append(f" exit_code={self._exit_code}", style="dim #4B5563")
        elif self._success is False:
            t.append("[FAILURE]", style="bold #EF4444")
            t.append(f" exit_code={self._exit_code}", style="dim #4B5563")
        else:
            t.append("[RUNNING]", style="bold #4A90D9")
        
        if self._skill_ids:
            t.append(f" skill:{self._skill_ids[0]}", style="dim #22C55E")
        if self._tier3_called:
            t.append(" [T3 called]", style="bold #F59E0B")
        t.append("\n")
        
        # Output preview lines (if any)
        if self._output_preview:
            for line in self._output_preview.split("\n")[:2]:
                if line.strip():
                    t.append(f"  {line[:60]}\n", style="dim #4B5563")
        
        # Dashed separator
        t.append("-" * 43 + "\n\n", style="dim #1f2937")
        
        return t


class LogTraceEntry(Static):
    """
    Renders a standard log message in the Tool Trace tab.
    """
    def __init__(self, timestamp: str, level: str, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._timestamp = timestamp
        self._level = level
        self._message = message

    def render(self) -> Text:
        t = Text()
        t.append(f"[{self._timestamp}]", style="dim #4B5563")
        t.append(" log: ", style="dim #4B5563")
        level_styles = {
            "DEBUG": "dim #4B5563",
            "INFO": "#22C55E",
            "WARNING": "#F59E0B",
            "ERROR": "bold #EF4444",
        }
        level_style = level_styles.get(self._level, "white")
        t.append(f"[{self._level}] ", style=level_style)
        t.append(self._message, style="white")
        t.append("\n" + "-" * 43 + "\n\n", style="dim #1f2937")
        return t


class ToolTracePane(Widget):
    """
    Tab 1: Tool Trace — scrollable list of all tool calls this session.
    Newest entries at the bottom. Max 100 entries kept.
    """

    DEFAULT_CSS = """
    ToolTracePane {
        width: 100%;
        height: 100%;
    }
    #tool-trace-scroll {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    #tool-trace-empty {
        color: $text-muted;
        padding: 1;
        text-style: italic;
    }
    """

    _entry_count: int = 0
    MAX_ENTRIES: int = 20
    _active_entry: Optional[ToolTraceEntry] = None

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="tool-trace-scroll"):
            yield Static(
                "No tool calls yet. Send a request to see traces here.",
                id="tool-trace-empty",
            )

    async def add_trace_entry(self, response: OrchestratorResponse) -> None:
        """Add a new tool trace entry from an OrchestratorResponse."""
        scroll = self.query_one("#tool-trace-scroll", ScrollableContainer)

        # Remove empty placeholder on first entry
        try:
            empty = self.query_one("#tool-trace-empty", Static)
            await empty.remove()
        except Exception:
            pass

        # Build the entry
        entry = ToolTraceEntry(
            tool_name=response.tool_name or "unknown",
            success=response.success,
            exit_code=0 if response.success else 1,
            output_preview=response.final_output[:300] if response.final_output else "",
            latency=response.latency_seconds,
            tier3_called=response.tier3_called,
            trace_id=response.trace_id,
            skill_ids=response.skill_ids,
        )

        await scroll.mount(entry)
        scroll.scroll_end(animate=False)
        self._entry_count += 1

        # Prune old entries if over limit
        if self._entry_count > self.MAX_ENTRIES:
            children = scroll.children
            if children:
                await children[0].remove()
                self._entry_count -= 1

    async def start_tool_trace(self, tool_name: str, parameters: dict) -> None:
        """Create and mount a running tool trace entry in real time."""
        scroll = self.query_one("#tool-trace-scroll", ScrollableContainer)

        # Remove empty placeholder on first entry
        try:
            empty = self.query_one("#tool-trace-empty", Static)
            await empty.remove()
        except Exception:
            pass

        # Build parameters preview string
        param_parts = []
        for k, v in parameters.items():
            val = str(v)
            if len(val) > 30:
                val = val[:27] + "..."
            param_parts.append(f"{k}={val}")
        params_preview = ", ".join(param_parts)[:100]

        # Build the entry in active/running state
        entry = ToolTraceEntry(
            tool_name=tool_name,
            success=None,  # Running state
            exit_code=0,
            output_preview=f"Parameters: {params_preview}",
            latency=0.0,
            tier3_called=False,
            trace_id="",
            skill_ids=[],
        )

        await scroll.mount(entry)
        scroll.scroll_end(animate=False)
        self._active_entry = entry
        self._entry_count += 1

        # Prune old entries if over limit
        if self._entry_count > self.MAX_ENTRIES:
            children = scroll.children
            if children:
                await children[0].remove()
                self._entry_count -= 1

    async def complete_tool_trace(
        self,
        success: bool,
        exit_code: int,
        output_preview: str,
        latency: float,
        tier3_called: bool = False,
        trace_id: str = "",
        skill_ids: list[str] = None,
    ) -> None:
        """Complete the currently active running tool trace."""
        if self._active_entry:
            self._active_entry.update_result(
                success=success,
                exit_code=exit_code,
                output_preview=output_preview,
                latency=latency,
                tier3_called=tier3_called,
                trace_id=trace_id,
                skill_ids=skill_ids,
            )
            try:
                scroll = self.query_one("#tool-trace-scroll", ScrollableContainer)
                scroll.scroll_end(animate=False)
            except Exception:
                pass

    async def add_log_entry(self, level: str, message: str) -> None:
        """Add a general log entry to the Tool Trace tab."""
        scroll = self.query_one("#tool-trace-scroll", ScrollableContainer)

        # Remove empty placeholder on first entry
        try:
            empty = self.query_one("#tool-trace-empty", Static)
            await empty.remove()
        except Exception:
            pass

        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = LogTraceEntry(timestamp, level, message)
        await scroll.mount(entry)
        scroll.scroll_end(animate=False)
        self._entry_count += 1

        # Prune old entries if over limit
        if self._entry_count > self.MAX_ENTRIES:
            children = scroll.children
            if children:
                await children[0].remove()
                self._entry_count -= 1


class MemoryViewPane(Widget):
    """
    Tab 2: Memory View — live display of MEMORY.md content.
    Refreshes after every successful orchestrator run.
    Lines added in the current session are highlighted in green.
    """

    DEFAULT_CSS = """
    MemoryViewPane {
        width: 100%;
        height: 100%;
    }
    #memory-scroll {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    #memory-header {
        color: $text-muted;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    _session_added_lines: set[str]  # Lines added this session (for highlighting)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_added_lines = set()

    def compose(self) -> ComposeResult:
        yield Label("Project Memory — MEMORY.md", id="memory-header")
        with ScrollableContainer(id="memory-scroll"):
            yield Static(
                "Memory is empty. Complete tasks to build project memory.",
                id="memory-empty",
            )

    async def refresh_memory(self, project: str = "default") -> None:
        """Re-read MEMORY.md and update the display."""
        try:
            from memory.store import read_memory_index
            index = read_memory_index(project=project)
        except Exception as e:
            await self._show_error(f"Could not read memory: {e}")
            return

        scroll = self.query_one("#memory-scroll", ScrollableContainer)

        # Clear existing content
        await scroll.remove_children()

        if not index.facts:
            await scroll.mount(Static(
                "Memory is empty. Complete tasks to build project memory.",
            ))
            return

        # Render each fact
        for fact in index.facts:
            try:
                line = fact.to_memory_line()
            except Exception:
                continue

            # Determine if this line was added this session
            is_new = line in self._session_added_lines

            fact_widget = Static(self._render_fact_line(line, is_new))
            await scroll.mount(fact_widget)

        scroll.scroll_end(animate=False)

    def mark_lines_as_new(self, lines: list[str]) -> None:
        """Mark specific lines as added this session (for green highlighting)."""
        self._session_added_lines.update(lines)

    def _render_fact_line(self, line: str, is_new: bool) -> Text:
        t = Text()

        display_line = line
        if display_line.startswith("[FACT]:"):
            display_line = display_line.replace("[FACT]:", "[FACT]", 1)
            prefix_style = "bold #4A90D9"
        elif display_line.startswith("[BUG]:"):
            display_line = display_line.replace("[BUG]:", "[BUG]", 1)
            prefix_style = "bold #EF4444"
        elif display_line.startswith("[TASK_DONE]:"):
            display_line = display_line.replace("[TASK_DONE]:", "[TASK_DONE]", 1)
            prefix_style = "bold #22C55E"
        elif display_line.startswith("[BLOCKED]:"):
            display_line = display_line.replace("[BLOCKED]:", "[BLOCKED]", 1)
            prefix_style = "bold #F59E0B"
        elif display_line.startswith("[DETAIL]:"):
            display_line = display_line.replace("[DETAIL]:", "[DETAIL]", 1)
            prefix_style = "bold #A78BFA"
        elif display_line.startswith("[STALE]:"):
            display_line = display_line.replace("[STALE]:", "[STALE]", 1)
            prefix_style = "dim"
        elif display_line.startswith("#"):
            prefix_style = "dim"
        else:
            prefix_style = "white"

        # New lines get a ▶ marker
        if is_new:
            t.append("▶ ", style="bold #22C55E")

        t.append(display_line, style=prefix_style if not is_new else "bold " + prefix_style.lstrip("bold "))
        return t

    async def _show_error(self, message: str) -> None:
        scroll = self.query_one("#memory-scroll", ScrollableContainer)
        await scroll.remove_children()
        await scroll.mount(Static(Text(message, style="#EF4444")))


class TaskQueuePane(Widget):
    """
    Tab 3: Task Queue — shows all SQLite tasks with their current status.
    Auto-refreshes every 30 seconds via a timer.
    Also refreshes after each orchestrator response.
    """

    DEFAULT_CSS = """
    TaskQueuePane {
        width: 100%;
        height: 100%;
    }
    #task-scroll {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    #task-queue-header {
        color: $text-muted;
        padding: 0 1;
    }
    """

    _db_path: Optional[Path] = None

    def compose(self) -> ComposeResult:
        yield Label("Task Queue — SQLite", id="task-queue-header")
        with ScrollableContainer(id="task-scroll"):
            yield Static("No tasks yet.", id="task-empty")

    def on_mount(self) -> None:
        """Start auto-refresh timer."""
        self.set_interval(30.0, self._auto_refresh)

    def _auto_refresh(self) -> None:
        """Called by timer every 30 seconds."""
        self.run_worker(self.refresh_tasks(), exclusive=False)

    async def refresh_tasks(self, session_id: Optional[str] = None) -> None:
        """Re-read the task queue from SQLite and update display, handling missing DB gracefully."""
        try:
            from kairos.db import DB_PATH, execute_read
        except Exception as e:
            logger.error(f"Failed to import DB utilities: {e}")
            return

        db_path = self._db_path or DB_PATH
        # If DB does not exist yet, show placeholder and exit
        if not db_path.exists():
            scroll = self.query_one("#task-scroll", ScrollableContainer)
            await scroll.remove_children()
            await scroll.mount(Static("Task queue initialising…"))
            return

        # Query tasks (last 50)
        try:
            rows = execute_read(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50",
                db_path=db_path,
            )
        except Exception as e:
            logger.error(f"Error reading tasks from DB: {e}")
            rows = []

        scroll = self.query_one("#task-scroll", ScrollableContainer)
        await scroll.remove_children()

        if not rows:
            await scroll.mount(Static("No tasks yet. Send requests to populate."))
            return

        # Count statuses
        counts = {"PENDING": 0, "RUNNING": 0, "COMPLETED": 0, "FAILED": 0, "STUCK": 0}
        for row in rows:
            status = row["status"] if row["status"] in counts else "COMPLETED"
            counts[status] += 1

        # Summary line
        summary = Text()
        summary.append(f"  P:{counts['PENDING']} ", style="#4A90D9")
        summary.append(f"R:{counts['RUNNING']} ", style="#22C55E")
        summary.append(f"✓:{counts['COMPLETED']} ", style="dim #22C55E")
        summary.append(f"✗:{counts['FAILED']} ", style="#EF4444")
        summary.append(f"⚠:{counts['STUCK']}", style="#F59E0B")
        await scroll.mount(Static(summary))

        # Render individual tasks (most recent first, limit 30)
        for row in rows[:30]:
            task_widget = Static(self._render_task_row(row))
            await scroll.mount(task_widget)

    def _render_task_row(self, row) -> Text:
        t = Text()

        status = row["status"]
        status_styles = {
            "PENDING":   ("○", "#4A90D9"),
            "RUNNING":   ("►", "#22C55E"),
            "COMPLETED": ("✓", "dim #22C55E"),
            "FAILED":    ("✗", "#EF4444"),
            "STUCK":     ("⚠", "#F59E0B"),
        }
        icon, colour = status_styles.get(status, ("?", "white"))

        t.append(f"  {icon} ", style=f"bold {colour}")

        title = (row["title"] or "")[:40]
        t.append(f"{title:<40} ", style="white" if status != "COMPLETED" else "dim")

        # Timestamps
        created = (row["created_at"] or "")[:16]
        t.append(f"{created}", style="dim")

        # Retry count
        retry = row.get("retry_count", 0)
        if retry and retry > 0:
            t.append(f"  retry:{retry}", style="dim #F59E0B")

        # Last error preview
        if status in ("FAILED", "STUCK") and row.get("last_error"):
            error_preview = str(row["last_error"])[:50]
            t.append(f"\n    ↳ {error_preview}", style="dim #EF4444")

        return t


class RightPanel(Widget):
    """
    The right panel — right 45% of the HERMES TUI.
    Contains TabbedContent with Tool Trace, Memory View, Task Queue.
    All tabs update when OrchestratorResponse is received.
    """

    DEFAULT_CSS = """
    RightPanel {
        width: 45%;
        height: 100%;
    }

    RightPanel TabbedContent {
        height: 100%;
    }

    RightPanel TabPane {
        height: 100%;
        padding: 0;
    }
    """

    def __init__(self, project: str = "default", **kwargs) -> None:
        super().__init__(**kwargs)
        self._project = project

    def compose(self) -> ComposeResult:
        yield Label("Dashboard", id="right-panel-header")
        with TabbedContent(id="right-tabs"):
            with TabPane("Tool Trace", id="tab-trace"):
                yield ToolTracePane(id="tool-trace-pane")
            with TabPane("Memory View", id="tab-memory"):
                yield MemoryViewPane(id="memory-pane")
            with TabPane("Task Queue", id="tab-tasks"):
                yield TaskQueuePane(id="task-queue-pane")

    def on_mount(self) -> None:
        """Initial data load and tab formatting."""
        self.run_worker(self._initial_load(), exclusive=False)
        try:
            tabbed_content = self.query_one("#right-tabs", TabbedContent)
            active_tab = tabbed_content.active
            active_tab_widget = tabbed_content.query_one(f"#--content-tab-{active_tab}", Tab)
            for tab in tabbed_content.query("Tab"):
                raw_names = {
                    "--content-tab-tab-trace": "Tool Trace",
                    "--content-tab-tab-memory": "Memory View",
                    "--content-tab-tab-tasks": "Task Queue",
                }
                tab_id = tab.id
                if tab_id in raw_names:
                    name = raw_names[tab_id]
                    if tab == active_tab_widget:
                        tab.label = f"> {name} <"
                    else:
                        tab.label = f"[ {name} ]"
        except Exception:
            pass

    async def _initial_load(self) -> None:
        """Load initial data for Memory and Task Queue tabs."""
        try:
            memory_pane = self.query_one("#memory-pane", MemoryViewPane)
            await memory_pane.refresh_memory(self._project)
        except Exception:
            pass

        try:
            task_pane = self.query_one("#task-queue-pane", TaskQueuePane)
            await task_pane.refresh_tasks()
        except Exception:
            pass

    @on(TabbedContent.TabActivated)
    def handle_tab_change(self, event: TabbedContent.TabActivated) -> None:
        try:
            tabbed_content = self.query_one("#right-tabs", TabbedContent)
            for tab in tabbed_content.query("Tab"):
                raw_names = {
                    "--content-tab-tab-trace": "Tool Trace",
                    "--content-tab-tab-memory": "Memory View",
                    "--content-tab-tab-tasks": "Task Queue",
                }
                tab_id = tab.id
                if tab_id in raw_names:
                    name = raw_names[tab_id]
                    if tab == event.tab:
                        tab.label = f"> {name} <"
                    else:
                        tab.label = f"[ {name} ]"
        except Exception as e:
            pass

    @on(OrchestratorProgress)
    async def handle_progress(self, progress: OrchestratorProgress) -> None:
        """Handle orchestrator progress updates in real-time."""
        event_type = progress.event_type
        data = progress.data
        stage = data.get("stage")

        # Stage 2 end: Task planning registered
        if event_type == "stage_end" and stage == 2:
            try:
                task_pane = self.query_one("#task-queue-pane", TaskQueuePane)
                await task_pane.refresh_tasks()
            except Exception:
                pass

        # Stage 7 start: Tool Execution starts
        elif event_type == "stage_start" and stage == 7:
            tool_name = data.get("tool_name", "unknown")
            params = data.get("parameters", {})
            try:
                trace_pane = self.query_one("#tool-trace-pane", ToolTracePane)
                await trace_pane.start_tool_trace(tool_name, params)
            except Exception:
                pass

        # Stage 7 end: Tool Execution completes
        elif event_type == "stage_end" and stage == 7:
            status = data.get("status", "success")
            success = (status == "success")
            error = data.get("error")
            target = data.get("target", "")
            duration = data.get("duration", 0.0)
            
            output_preview = f"Executed on target: {target}"
            if error:
                output_preview = f"Error: {error}"
            
            try:
                trace_pane = self.query_one("#tool-trace-pane", ToolTracePane)
                await trace_pane.complete_tool_trace(
                    success=success,
                    exit_code=0 if success else 1,
                    output_preview=output_preview,
                    latency=duration,
                )
            except Exception:
                pass

        # Stage 11 end: Memory evolved
        elif event_type == "stage_end" and stage == 11:
            try:
                memory_pane = self.query_one("#memory-pane", MemoryViewPane)
                await memory_pane.refresh_memory(self._project)
            except Exception:
                pass

    @on(OrchestratorResponse)
    async def handle_response(self, response: OrchestratorResponse) -> None:
        """Update all 3 tabs after every orchestrator response."""

        # Tab 1: Tool Trace — update active entry or add a new one
        try:
            trace_pane = self.query_one("#tool-trace-pane", ToolTracePane)
            if trace_pane._active_entry:
                await trace_pane.complete_tool_trace(
                    success=response.success,
                    exit_code=0 if response.success else 1,
                    output_preview=response.final_output[:300] if response.final_output else "",
                    latency=response.latency_seconds,
                    tier3_called=response.tier3_called,
                    trace_id=response.trace_id,
                    skill_ids=response.skill_ids,
                )
                trace_pane._active_entry = None
            else:
                await trace_pane.add_trace_entry(response)
        except Exception:
            pass

        # Tab 2: Memory View — refresh if tool succeeded
        if response.success:
            try:
                memory_pane = self.query_one("#memory-pane", MemoryViewPane)
                await memory_pane.refresh_memory(self._project)
            except Exception:
                pass

        # Tab 3: Task Queue — always refresh
        try:
            task_pane = self.query_one("#task-queue-pane", TaskQueuePane)
            await task_pane.refresh_tasks()
        except Exception:
            pass
