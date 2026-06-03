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
from textual import on, work
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, Static, Button

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
    "Pondering", "Integrating",
]

_spinner_cycle = itertools.cycle(SPINNER_VERBS)


class UserMessageWidget(Static):
    """
    Renders one user message in the chat history.
    """
    DEFAULT_CSS = """
    UserMessageWidget {
        width: 100%;
        margin-bottom: 0;
        padding: 0 1;
        background: transparent;
    }
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text

    def render(self) -> Text:
        t = Text()
        t.append("User: ", style="bold #4A90D9")
        t.append(self._text, style="white")
        return t


class HermesMessageContent(Static):
    """
    Renders the response box of a HERMES response.
    """
    def __init__(self, response: OrchestratorResponse, **kwargs) -> None:
        super().__init__(**kwargs)
        self._response = response

    def render(self) -> Text:
        r = self._response
        t = Text()
        
        # Show thought process header if output has reasoning-like content
        if len(r.final_output) > 50:
            t.append("  Thought Process\n", style="italic #22C55E")
            
        output_lines = r.final_output.split("\n")
        for line in output_lines:
            t.append(f"  {line}\n", style="white")
            
        if r.tool_name:
            tool_style = "bold #22C55E" if r.success else "bold #EF4444"
            icon = "✓" if r.success else "✗"
            t.append(f"\n  ⚙ Tier 1 ({r.tool_name}) — ", style="#22C55E")
            t.append(f"Stage {r.stage_reached}/12 | {r.latency_seconds:.1f}s", style="dim")
            
        return t


class HermesMessageWidget(Widget):
    """
    Renders one HERMES response in the chat history.
    Success responses have a green border.
    Error responses have an amber border.
    """
    DEFAULT_CSS = """
    HermesMessageWidget {
        width: 100%;
        height: auto;
        margin-top: 1;
        margin-bottom: 1;
        padding: 0 1;
    }
    .hermes-message-header {
        color: #22C55E;
        text-style: bold;
        padding: 0 1;
        margin-bottom: 0;
    }
    HermesMessageContent {
        width: 100%;
        height: auto;
        padding: 1 2;
        margin-top: 1;
        margin-bottom: 1;
    }
    HermesMessageWidget.success HermesMessageContent {
        border: round #22C55E;
        background: #0d1a0d;
    }
    HermesMessageWidget.error HermesMessageContent {
        border: round #F59E0B;
        background: #1a110d;
    }
    HermesMessageWidget.error .hermes-message-header {
        color: #F59E0B;
    }
    """

    def __init__(
        self,
        response: OrchestratorResponse,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._response = response
        if response.success:
            self.add_class("success")
        else:
            self.add_class("error")

    def compose(self) -> ComposeResult:
        yield Label("HERMES:", classes="hermes-message-header")
        yield HermesMessageContent(self._response)

    def render(self) -> Text:
        """Fallback for unit tests that call render() directly."""
        r = self._response
        t = Text()
        label_style = "bold #22C55E" if r.success else "bold #F59E0B"
        label_text = "HERMES:" if r.success else "HERMES [ERROR]:"
        t.append(f"{label_text}\n", style=label_style)

        if len(r.final_output) > 50:
            t.append("  Thought Process\n", style="italic #22C55E")

        output_lines = r.final_output.split("\n")
        for line in output_lines:
            t.append(f"  {line}\n", style="white")

        if r.tool_name:
            tool_style = "bold #22C55E" if r.success else "bold #EF4444"
            icon = "✓" if r.success else "✗"
            t.append(f"\n  {icon} Tool: {r.tool_name} | Stage: {r.stage_reached}/12 | {r.latency_seconds:.1f}s", style=tool_style)
        return t


class ProcessingIndicator(Static):
    """
    Shown while the orchestrator is processing.
    Displays the live 12-stage pipeline progress, thought processes, subtasks,
    skills, memory, verification, and Claude escalation status.
    """
    DEFAULT_CSS = """
    ProcessingIndicator {
        width: 100%;
        padding: 0 2;
        color: #22C55E;
        margin-bottom: 1;
        height: auto;
    }
    """

    verb: reactive[str] = reactive("Analyzing")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.show_detailed_trace = False
        self.current_stage = 1
        self.stage_status = {i: "pending" for i in range(1, 13)}
        self.stage_status[1] = "running"
        self.thought = "Analyzing user request..."
        self.live_feed = []
        self.subtasks = []
        self.skills = {}
        self.memories = []
        self.tool_execution = {}
        self.verification = {}
        self.disagreement = {}
        self.tier3 = {}
        self.memory_updates = {}

    def on_mount(self) -> None:
        pass

    def on_click(self, event) -> None:
        """Toggle detailed trace view on click."""
        self.show_detailed_trace = not self.show_detailed_trace
        self.refresh()

    def update_progress(self, event_type: str, data: dict) -> None:
        stage = data.get("stage")
        if stage:
            self.current_stage = stage
            for i in range(1, stage):
                if self.stage_status[i] != "failed":
                    self.stage_status[i] = "success"
            self.stage_status[stage] = "running"
            
        if "thought" in data:
            self.thought = data["thought"]
            
        spinner_verb = data.get("spinner_verb")
        if spinner_verb:
            self.verb = spinner_verb
            try:
                status_bar = self.app.query_one("#status-bar")
                status_bar.spinner_verb = spinner_verb
                status_bar.set_processing(True)
            except Exception:
                pass

        if event_type == "stage_end":
            st_num = data.get("stage")
            if st_num:
                status = data.get("status", "success")
                self.stage_status[st_num] = status
                
        if event_type == "stage_end" and stage == 2:
            self.subtasks = data.get("subtasks", [])
            
        if event_type == "stage_end" and stage == 3:
            self.skills = {
                "matched": data.get("matched", []),
                "rejected": data.get("rejected", []),
                "confidence": data.get("confidence", 0)
            }
            
        if event_type == "stage_end" and stage == 4:
            self.memories = data.get("memories", [])
            
        if event_type == "stage_start" and stage == 7:
            tool_name = data.get("tool_name")
            params = data.get("parameters", {})
            target = params.get("TargetFile") or params.get("path") or params.get("filename") or str(params)
            content = params.get("CodeContent") or params.get("content") or params.get("code")
            lines_count = len(content.split('\n')) if content else 0
            attempt = data.get("attempt", 1)
            
            for subtask in self.subtasks:
                if subtask.get("status") == "pending":
                    subtask["status"] = "running"
                    break

            self.tool_execution = {
                "tool": tool_name,
                "target": target,
                "lines": lines_count,
                "status": "Running...",
                "attempts": self.tool_execution.get("attempts", []),
                "current_attempt": attempt
            }
            
        if event_type == "stage_end" and stage == 7:
            tool_name = data.get("tool_name")
            target = data.get("target")
            lines = data.get("lines")
            duration = data.get("duration")
            status = data.get("status", "success")
            attempt = data.get("attempt", 1)
            error = data.get("error")
            
            success = (status == "success")
            self.tool_execution["status"] = "Success" if success else "Failed"
            self.tool_execution["duration"] = duration
            
            attempts = self.tool_execution.setdefault("attempts", [])
            if not any(a["attempt"] == attempt for a in attempts):
                attempts.append({
                    "attempt": attempt,
                    "status": "SUCCESS" if success else "FAILED",
                    "reason": error or ""
                })
            
            self.live_feed.append({
                "tool": tool_name,
                "success": success,
                "duration": duration
            })
            
            for subtask in self.subtasks:
                if subtask.get("status") == "running":
                    subtask["status"] = "completed" if success else "failed"
                    break
                    
        if event_type == "stage_end" and stage == 8:
            self.verification = {
                "verifier": data.get("verifier"),
                "agree": data.get("agree"),
                "confidence": data.get("confidence"),
                "critical_issues": data.get("critical_issues", 0)
            }
            
        if event_type == "stage_end" and stage == 9:
            decision = data.get("decision")
            if decision == "escalate" or decision == "block":
                self.disagreement = {
                    "reason": data.get("reason"),
                    "threshold": data.get("threshold"),
                    "actual": data.get("actual"),
                    "action": data.get("action")
                }
                
        if event_type == "stage_start" and stage == 10:
            if data.get("needed"):
                self.tier3 = {
                    "reason": data.get("reason", "Low confidence / disagreement"),
                    "model": "Claude Sonnet",
                    "status": "Reviewing solution..."
                }
                
        if event_type == "stage_end" and stage == 10:
            if data.get("needed") and self.tier3:
                self.tier3["status"] = data.get("verdict", "Approved")
                self.tier3["verdict"] = data.get("verdict", "Approved")
                
        if event_type == "stage_end" and stage == 11:
            self.memory_updates = {
                "added": data.get("added", []),
                "updated": data.get("updated", [])
            }
            
        self.refresh()

    def _get_stage_indicator(self, status: str):
        if status == "success":
            return "✓", "bold #22C55E"
        elif status == "failed":
            return "✗", "bold #EF4444"
        elif status == "running":
            return "►", "bold #4A90D9 blink"
        else:
            return "○", "dim #4B5563"

    def render(self) -> Text:
        t = Text()
        t.append("════════════════════════════════════════════════════════════\n", style="dim #22C55E")
        t.append("                    HERMES PIPELINE ACTIVE                  \n", style="bold #22C55E")
        t.append("════════════════════════════════════════════════════════════\n", style="dim #22C55E")
        t.append("Click dashboard area to toggle Detailed Trace view.\n", style="dim #4B5563")
        t.append(f"Detailed Trace: {'[ Expanded ]' if self.show_detailed_trace else '[ Collapsed ]'}\n\n", style="bold #4A90D9")

        stage_names = {
            1: "Input Sanitization",
            2: "Task Planning",
            3: "Skill Detection",
            4: "Memory Injection",
            5: "Tier 1 Reasoning",
            6: "Tool Validation",
            7: "Tool Execution",
            8: "Tier 2 Verification",
            9: "Disagreement Analysis",
            10: "Tier 3 Escalation",
            11: "Memory Update",
            12: "Final Response"
        }

        # ── Expanded View: 12-Stage Pipeline Visualizer ──
        if self.show_detailed_trace:
            t.append("Pipeline Stages\n", style="bold #4A90D9")
            for i in range(1, 7):
                status_i = self.stage_status.get(i, "pending")
                sym_i, style_i = self._get_stage_indicator(status_i)
                name_i = stage_names[i]
                col1 = Text.assemble((f" {sym_i} ", style_i), (f"{name_i:<25}", "white" if status_i != "pending" else "dim"))
                
                j = i + 6
                status_j = self.stage_status.get(j, "pending")
                sym_j, style_j = self._get_stage_indicator(status_j)
                name_j = stage_names[j]
                col2 = Text.assemble((f" {sym_j} ", style_j), (f"{name_j:<25}", "white" if status_j != "pending" else "dim"))
                
                t.append_text(col1)
                t.append("   │   ")
                t.append_text(col2)
                t.append("\n")
            t.append("\n")
        else:
            # Collapsed View: Lightweight Execution History (Compact Pipeline State)
            t.append("Execution History\n", style="bold #4A90D9")
            history_items = []
            for st_num in range(1, 13):
                status = self.stage_status.get(st_num, "pending")
                if status == "success":
                    history_items.append(Text(f"✓ {stage_names[st_num]}", style="bold #22C55E"))
                elif status == "running":
                    history_items.append(Text(f"► {stage_names[st_num]}", style="bold #4A90D9 blink"))
                elif status == "failed":
                    history_items.append(Text(f"✗ {stage_names[st_num]}", style="bold #EF4444"))
            
            # Print only past completed and running stages to keep it compact
            for item in history_items:
                t.append("  ")
                t.append_text(item)
                t.append("\n")
            t.append("\n")

        # ── Current thought & stage (Always Visible) ──
        current_name = stage_names.get(self.current_stage, "Initializing")
        t.append("Current Stage: ", style="bold #4B5563")
        t.append(f"{current_name}\n", style="bold #22C55E")

        t.append("Thought: ", style="bold #4B5563")
        t.append(f"{self.thought}\n\n", style="italic #F59E0B")

        # ── Execution plan (Always Visible if populated) ──
        if self.subtasks:
            t.append("Execution Plan\n", style="bold #4A90D9")
            for idx, subtask in enumerate(self.subtasks, 1):
                title = subtask.get("title", "")
                status = subtask.get("status", "pending")
                if status == "completed":
                    sym, style = "✓", "bold #22C55E"
                elif status == "failed":
                    sym, style = "✗", "bold #EF4444"
                elif status == "running":
                    sym, style = "►", "bold #4A90D9 blink"
                else:
                    sym, style = "○", "dim #4B5563"
                t.append(f"  {idx}. {title:<30} ", style="white" if status != "pending" else "dim")
                t.append(f"{sym} {status.capitalize()}\n", style=style)
            t.append("\n")

        # ── Skill Detection (Always Visible if populated) ──
        if self.skills and self.skills.get("matched"):
            t.append("Skills Loaded\n", style="bold #4A90D9")
            for s in self.skills.get("matched", []):
                t.append(f"  ✓ {s}\n", style="bold #22C55E")
            t.append(f"  Skill Confidence: {self.skills.get('confidence', 0)}%\n\n", style="bold #F59E0B")

        # ── Memory Visibility (Always Visible if populated) ──
        if self.memories:
            t.append("Memory Retrieved\n", style="bold #4A90D9")
            for mem in self.memories[:3]:
                t.append(f"  ✓ {mem}\n", style="#22C55E")
            t.append("\n")

        # ── Tool execution + retries + error block (Always Visible if populated) ──
        if self.tool_execution:
            t.append("Tool Execution\n", style="bold #4A90D9")
            t.append(f"  Tool:   {self.tool_execution.get('tool')}\n", style="white")
            t.append(f"  Target: {self.tool_execution.get('target')}\n", style="white")
            if self.tool_execution.get("lines"):
                t.append(f"  Lines:  {self.tool_execution.get('lines')}\n", style="white")
            
            attempts = self.tool_execution.get("attempts", [])
            for att in attempts:
                att_num = att["attempt"]
                att_status = att["status"]
                reason_str = f" - {att['reason']}" if att.get("reason") else ""
                style = "bold #22C55E" if att_status == "SUCCESS" else "bold #EF4444"
                t.append(f"  Attempt {att_num}/3  {att_status}{reason_str}\n", style=style)
                
            curr_att = self.tool_execution.get("current_attempt", 1)
            if self.tool_execution.get("status") == "Running..." and not any(a["attempt"] == curr_att for a in attempts):
                t.append(f"  Attempt {curr_att}/3  ► Running...\n", style="bold #4A90D9 blink")
                
            if self.tool_execution.get("status") == "Failed" or (attempts and attempts[-1]["status"] == "FAILED"):
                last_reason = attempts[-1]["reason"] if attempts else "Unknown error"
                t.append("\n  ┌────────────────────────────────────────────────────────┐\n", style="bold #EF4444")
                t.append("  │                     ERROR DETECTED                     │\n", style="bold #EF4444")
                t.append("  ├────────────────────────────────────────────────────────┤\n", style="bold #EF4444")
                t.append(f"  │ Stage:  Tool Execution                                 │\n", style="white")
                t.append(f"  │ Tool:   {self.tool_execution.get('tool'):<46} │\n", style="white")
                t.append(f"  │ Reason: {last_reason[:46]:<46} │\n", style="bold #EF4444")
                
                if len(attempts) < 3:
                    t.append("  │ Status: Retrying...                                    │\n", style="italic #F59E0B")
                    t.append(f"  │ Retry:  {len(attempts)} / 3                                    │\n", style="white")
                else:
                    t.append("  │ Status: Failed (Max Retries Exhausted)                 │\n", style="bold #EF4444")
                t.append("  └────────────────────────────────────────────────────────┘\n\n", style="bold #EF4444")
            t.append("\n")

        # ── Detailed Trace Pane (Only Visible if Expanded) ──
        if self.show_detailed_trace:
            if self.live_feed:
                t.append("Live Execution Feed\n", style="bold #4A90D9")
                for entry in self.live_feed[-5:]:
                    t.append(f"  ⚙ {entry.get('tool')}\n", style="bold #22C55E")
                    dur_str = f" ({entry.get('duration'):.2f}s)" if entry.get('duration') else ""
                    res_style = "bold #22C55E" if entry.get('success') else "bold #EF4444"
                    res_symbol = "✓ Success" if entry.get('success') else "✗ Failed"
                    t.append(f"  {res_symbol}{dur_str}\n", style=res_style)
                t.append("\n")

            if self.verification:
                t.append("Verification Stage\n", style="bold #4A90D9")
                t.append(f"  Verifier: {self.verification.get('verifier')}\n", style="white")
                agree = self.verification.get('agree')
                agree_style = "bold #22C55E" if agree else "bold #EF4444"
                t.append(f"  Agreement: {'YES' if agree else 'NO'}\n", style=agree_style)
                t.append(f"  Confidence: {self.verification.get('confidence'):.2f}\n", style="white")
                issues = self.verification.get('critical_issues', 0)
                if issues > 0:
                    t.append(f"  Issues: {issues} (Escalation Required)\n", style="bold #EF4444")
                else:
                    t.append(f"  Critical Issues: {issues}\n", style="bold #22C55E")
                t.append("\n")

            if self.disagreement:
                t.append("Escalation Triggered\n", style="bold #EF4444")
                t.append(f"  Reason:    {self.disagreement.get('reason')}\n", style="white")
                t.append(f"  Threshold: {self.disagreement.get('threshold'):.2f}\n", style="white")
                t.append(f"  Actual:    {self.disagreement.get('actual'):.2f}\n", style="white")
                t.append(f"  Action:    {self.disagreement.get('action')}\n", style="bold #F59E0B")
                t.append("\n")

            if self.tier3:
                t.append("External Verification Required\n", style="bold #4A90D9")
                t.append(f"  Reason: {self.tier3.get('reason')}\n", style="white")
                t.append(f"  Model:  {self.tier3.get('model')}\n", style="white")
                status = self.tier3.get('status')
                status_style = "bold #4A90D9 blink" if status == "Reviewing solution..." else ("bold #22C55E" if status == "Approved" else "bold #EF4444")
                t.append(f"  Status: {status}\n", style=status_style)
                if self.tier3.get('verdict'):
                    t.append(f"  Verdict: {self.tier3.get('verdict')}\n", style="bold #22C55E" if self.tier3.get('verdict') == "Approved" else "bold #EF4444")
                t.append("\n")

            if self.memory_updates:
                t.append("Memory Updates\n", style="bold #4A90D9")
                for item in self.memory_updates.get("added", []):
                    t.append(f"  ✓ Added: {item}\n", style="bold #22C55E")
                for item in self.memory_updates.get("updated", []):
                    t.append(f"  ✓ Updated: {item}\n", style="bold #22C55E")
                t.append("\n")

        return t


class ChatPanel(Widget):
    """
    The main chat panel — left 55% of the HERMES TUI.
    Owns the conversation history display and the text input.
    """

    DEFAULT_CSS = """
    ChatPanel {
        width: 55%;
        height: 100%;
    }

    #chat-history {
        height: 1fr;
        width: 100%;
        overflow-y: auto;
    }

    #chat-input-container {
        height: 4;
        width: 100%;
        layout: horizontal;
        align-vertical: middle;
    }

    #chat-input {
        width: 1fr;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("HERMES - Chat", id="chat-panel-header")
        with ScrollableContainer(id="chat-history"):
            pass

        with Horizontal(id="chat-input-container"):
            yield Label("Input command:", id="input-command-label")
            yield Input(
                placeholder="Type your request and press Enter...",
                id="chat-input",
            )
            yield Button(Text("[ SEND ]"), id="stop-btn")

    def on_mount(self) -> None:
        """Focus the input on mount and initialize SEND button."""
        chat_input = self.query_one("#chat-input", Input)
        chat_input.focus()
        try:
            stop_btn = self.query_one("#stop-btn", Button)
            stop_btn.label = Text("[ SEND ]")
            stop_btn.disabled = True
            stop_btn.display = True
        except Exception:
            pass

    # ── Input handling ────────────────────────────────────────────────

    @on(Input.Changed, "#chat-input")
    def handle_input_changed(self, event: Input.Changed) -> None:
        """Enable or disable the SEND button based on input value when idle."""
        try:
            chat_input = event.input
            if chat_input.disabled:
                if event.value != "":
                    chat_input.value = ""
                return
            stop_btn = self.query_one("#stop-btn", Button)
            stop_btn.disabled = not bool(event.value.strip())
        except Exception:
            pass

    async def submit_prompt(self) -> None:
        """Submit the prompt typed in the input field."""
        chat_input = self.query_one("#chat-input", Input)
        text = chat_input.value.strip()
        if not text:
            return

        # Clear the input immediately
        chat_input.value = ""

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

    @on(Input.Submitted, "#chat-input")
    async def handle_input_submitted(self, event: Input.Submitted) -> None:
        """User pressed Enter — submit the prompt."""
        await self.submit_prompt()

    async def _handle_slash_command(self, command: str) -> None:
        """
        Handle / commands — these run tools directly without going through
        the full 12-stage orchestrator pipeline.
        """
        parts = command.strip().split()
        cmd = parts[0].lower() if parts else ""

        if cmd in ("/quit", "/q", "/exit"):
            self.app.exit()

        elif cmd == "/clear":
            history = self.query_one("#chat-history", ScrollableContainer)
            await history.remove_children()
            await self._add_system_message("Chat cleared. Memory and tasks are preserved.")

        elif cmd.startswith("/mode") and len(parts) >= 2:
            mode = parts[1].lower()
            if mode in ("safe", "plan", "auto"):
                self.app._set_mode(mode)
                await self._add_system_message(f"Mode changed to {mode.upper()}")
            else:
                await self._add_system_message(
                    f"Unknown mode '{mode}'. Use: /mode safe | /mode plan | /mode auto"
                )

        elif cmd == "/export":
            await self._run_export_command(parts)

        elif cmd == "/vscode":
            await self._run_vscode_command(parts)

        elif cmd == "/push":
            await self._run_push_command(parts)

        elif cmd == "/screenshot":
            await self._run_screenshot_command(parts)

        elif cmd == "/help":
            help_lines = [
                "Available slash commands:",
                "  /clear              — Clear conversation history",
                "  /mode safe|plan|auto — Switch permission mode",
                "  /export [path]      — Export project folder as ZIP",
                "                        Example: /export generated_projects/myapp",
                "  /vscode [path]      — Open file or folder in VS Code",
                "                        Example: /vscode generated_projects/myapp",
                "  /push [dir] [branch]— Push to GitHub (needs GITHUB_TOKEN env var)",
                "                        Example: /push generated_projects/myapp main",
                "  /screenshot <image> [html|react] — Convert screenshot to code",
                "                        Example: /screenshot tests/screenshots/test_login_form.png html",
                "  /help               — Show this message",
                "  /quit               — Exit HERMES",
            ]
            await self._add_system_message("\n".join(help_lines))

        else:
            await self._add_system_message(
                f"Unknown command: {command}\nType /help for available commands."
            )

    async def _run_export_command(self, parts: list[str]) -> None:
        """Handle /export [path] command."""
        from tools.export_tools import ExportZipTool

        path = parts[1] if len(parts) >= 2 else "generated_projects"
        await self._add_system_message(f"Exporting {path} as ZIP...")

        tool = ExportZipTool()
        result = tool.execute(ExportZipTool.Input(project_path=path))

        if result.success:
            await self._add_system_message(f"✓ Export complete:\n{result.output}")
        else:
            await self._add_system_message(f"✗ Export failed: {result.error}")

    async def _run_vscode_command(self, parts: list[str]) -> None:
        """Handle /vscode [path] command."""
        from tools.export_tools import OpenInVSCodeTool

        path = parts[1] if len(parts) >= 2 else "."
        await self._add_system_message(f"Opening {path} in VS Code...")

        tool = OpenInVSCodeTool()
        result = tool.execute(OpenInVSCodeTool.Input(path=path))

        if result.success:
            await self._add_system_message(f"✓ {result.output}")
        else:
            await self._add_system_message(f"✗ {result.error}")

    async def _run_push_command(self, parts: list[str]) -> None:
        """Handle /push [directory] [branch] command."""
        from tools.git_tools import GitPushTool

        directory = parts[1] if len(parts) >= 2 else "."
        branch = parts[2] if len(parts) >= 3 else "main"

        await self._add_system_message(
            f"Pushing {directory} to GitHub (branch: {branch})...\n"
            f"Make sure GITHUB_TOKEN is set in your environment."
        )

        tool = GitPushTool()
        result = tool.execute(GitPushTool.Input(
            directory=directory,
            branch=branch,
        ))

        if result.success:
            await self._add_system_message(f"✓ {result.output}")
        else:
            await self._add_system_message(f"✗ Push failed: {result.error}")

    async def _run_screenshot_command(self, parts: list[str]) -> None:
        """Handle /screenshot <image_path> [html|react] command."""
        if len(parts) < 2:
            await self._add_system_message(
                "Usage: /screenshot <image_path> [html|react]\n"
                "Example: /screenshot tests/screenshots/test_login_form.png html"
            )
            return

        image_path = parts[1]
        output_format = parts[2].lower() if len(parts) >= 3 else "html"

        if output_format not in ("html", "react"):
            await self._add_system_message(
                f"Unknown format '{output_format}'. Use: html or react"
            )
            return

        await self._add_system_message(
            f"Converting {image_path} to {output_format.upper()}...\n"
            f"This may take 20-60 seconds (vision inference is slow)."
        )

        # Run in a worker so UI stays responsive
        self.run_worker(
            self._screenshot_worker(image_path, output_format),
            exclusive=False,
            name="screenshot-worker",
        )

    @work(thread=False)
    async def _screenshot_worker(self, image_path: str, output_format: str) -> None:
        """Worker for screenshot-to-code — runs async without blocking UI."""
        from tools.vision_tools import ScreenshotToCodeTool

        tool = ScreenshotToCodeTool()
        result = tool.execute(ScreenshotToCodeTool.Input(
            image_path=image_path,
            output_format=output_format,
        ))

        if result.success:
            await self._add_system_message(f"✓ Screenshot converted:\n{result.output}")
        else:
            await self._add_system_message(f"✗ Conversion failed: {result.error}")

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
            
            stop_btn = self.query_one("#stop-btn", Button)
            if enabled:
                stop_btn.label = Text("[ SEND ]")
                stop_btn.disabled = not bool(chat_input.value.strip())
                chat_input.focus()
                # Ensure the thinking spinner is completely removed when going back to idle
                self.run_worker(self._remove_processing_indicator())
            else:
                chat_input.blur()
                stop_btn.label = Text("[ STOP ]")
                stop_btn.disabled = False
        except Exception:
            pass
