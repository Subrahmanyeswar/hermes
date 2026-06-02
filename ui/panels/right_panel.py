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
)

from ui.app import OrchestratorResponse


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
        success: bool,
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

        if success:
            self.add_class("success")
        else:
            self.add_class("failure")

    def render(self) -> Text:
        t = Text()

        # ── Header line ───────────────────────────────────────────────
        icon = "✓" if self._success else "✗"
        icon_style = "bold #22C55E" if self._success else "bold #EF4444"
        t.append(f"{icon} ", style=icon_style)
        t.append(f"{self._tool_name:<20}", style="bold white")
        t.append(f"  {self._latency:.2f}s", style="dim")
        t.append(f"  exit:{self._exit_code}", style="dim")
        t.append(f"  {self._timestamp}\n", style="dim")

        # ── Trace ID and skill ────────────────────────────────────────
        if self._trace_id:
            t.append(f"  trace:{self._trace_id}", style="dim #4A90D9")
        if self._skill_ids:
            t.append(f"  skill:{self._skill_ids[0]}", style="dim #22C55E")
        if self._tier3_called:
            t.append("  [T3 called]", style="bold #F59E0B")
        if self._trace_id or self._skill_ids or self._tier3_called:
            t.append("\n")

        # ── Output preview ────────────────────────────────────────────
        if self._output_preview:
            preview_lines = self._output_preview.split("\n")[:5]
            for line in preview_lines:
                if line.strip():
                    t.append(f"  {line[:70]}\n", style="dim")
            if len(self._output_preview.split("\n")) > 5:
                remaining = len(self._output_preview.split("\n")) - 5
                t.append(f"  ... ({remaining} more lines)\n", style="dim")

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
    MAX_ENTRIES: int = 100

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
            entries = scroll.query(ToolTraceEntry)
            if entries:
                await entries.first().remove()
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

        # Colour by fact type
        if line.startswith("[FACT]:"):
            prefix_style = "bold #4A90D9"
        elif line.startswith("[BUG]:"):
            prefix_style = "bold #EF4444"
        elif line.startswith("[TASK_DONE]:"):
            prefix_style = "bold #22C55E"
        elif line.startswith("[BLOCKED]:"):
            prefix_style = "bold #F59E0B"
        elif line.startswith("[DETAIL]:"):
            prefix_style = "bold #A78BFA"
        elif line.startswith("[STALE]:"):
            prefix_style = "dim"
        elif line.startswith("#"):
            prefix_style = "dim"
        else:
            prefix_style = "white"

        # New lines get a ▶ marker
        if is_new:
            t.append("▶ ", style="bold #22C55E")

        t.append(line, style=prefix_style if not is_new else "bold " + prefix_style.lstrip("bold "))
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
        """Re-read the task queue from SQLite and update display."""
        try:
            from kairos.task_queue import get_pending_tasks, get_running_tasks
            from kairos.db import execute_read, DB_PATH

            db_path = self._db_path or DB_PATH

            # Get all tasks (last 50)
            rows = execute_read(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50",
                db_path=db_path
            )

        except Exception as e:
            return  # Silently fail — DB may not exist yet

        scroll = self.query_one("#task-scroll", ScrollableContainer)
        await scroll.remove_children()

        if not rows:
            await scroll.mount(Static("No tasks yet. Send requests to populate."))
            return

        # Status counts
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

        # Individual task rows (most recent first)
        for row in rows[:30]:
            task_widget = Static(self._render_task_row(row))
            await scroll.mount(task_widget)

    def _render_task_row(self, row) -> Text:
        t = Text()

        status = row["status"]
        status_styles = {
            "PENDING":   ("⋯", "#4A90D9"),
            "RUNNING":   ("⟳", "#22C55E"),
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
        with TabbedContent(id="right-tabs"):
            with TabPane("Tool Trace", id="tab-trace"):
                yield ToolTracePane(id="tool-trace-pane")
            with TabPane("Memory", id="tab-memory"):
                yield MemoryViewPane(id="memory-pane")
            with TabPane("Tasks", id="tab-tasks"):
                yield TaskQueuePane(id="task-queue-pane")

    def on_mount(self) -> None:
        """Initial data load."""
        self.run_worker(self._initial_load(), exclusive=False)

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

    @on(OrchestratorResponse)
    async def handle_response(self, response: OrchestratorResponse) -> None:
        """Update all 3 tabs after every orchestrator response."""

        # Tab 1: Tool Trace — always add entry
        try:
            trace_pane = self.query_one("#tool-trace-pane", ToolTracePane)
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
