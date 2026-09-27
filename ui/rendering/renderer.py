# ui/rendering/renderer.py
"""
Primary TUI 2.x Layout and Frame Renderer.

Features:
1. Pure layout assembly across Header, Chat, Operational Panel, and Modals.
2. Complete panel-level crash isolation (a failing panel cannot crash the frame).
3. Wide-character and ANSI safety enforcement.
4. Visible-range virtualization for chat and traces.
"""

from __future__ import annotations

import time
from typing import Optional

from ui.rendering.layout import LayoutEngine, Rect
from ui.rendering.renderer_protocol import RendererProtocol
from ui.rendering.screen_buffer import ScreenBuffer, ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.rendering.text_safety import sanitize_terminal_text
from ui.rendering.virtualization import VirtualList
from ui.viewmodels.chat import ChatEntryKind
from ui.viewmodels.root import HermesViewModel


class TuiRenderer(RendererProtocol):
    """Primary multi-panel frame renderer."""

    def build_frame(
        self,
        view_model: HermesViewModel,
        capabilities: TerminalCapabilities,
        frame_id: int = 0,
    ) -> ScreenFrame:
        width = max(10, capabilities.width)
        height = max(5, capabilities.height)
        buf = ScreenBuffer(width, height)

        has_modal = bool(
            (view_model.security.modal and view_model.security.modal.visible)
            or (view_model.rewind_preview and view_model.rewind_preview.visible)
        )

        geo = LayoutEngine.compute(width, height, has_modal=has_modal)

        # 1. Render Header
        try:
            self._render_header(buf, geo.header, view_model)
        except Exception as e:
            self._render_panel_error(buf, geo.header, "Header", e)

        # 2. Render Active Operation Bar
        try:
            self._render_active_bar(buf, geo.active_operation, view_model)
        except Exception as e:
            self._render_panel_error(buf, geo.active_operation, "ActiveBar", e)

        # 3. Render Chat / Conversation
        try:
            self._render_chat(buf, geo.chat, view_model)
        except Exception as e:
            self._render_panel_error(buf, geo.chat, "Chat", e)

        # 4. Render Right Panel (if visible)
        if geo.right_panel:
            try:
                self._render_right_panel(buf, geo.right_panel, view_model)
            except Exception as e:
                self._render_panel_error(buf, geo.right_panel, "RightPanel", e)

        # 5. Render Input Bar
        try:
            self._render_input_bar(buf, geo.input_bar, view_model)
        except Exception as e:
            self._render_panel_error(buf, geo.input_bar, "InputBar", e)

        # 6. Render Modal (if active)
        if geo.modal and has_modal:
            try:
                self._render_modal(buf, geo.modal, view_model)
            except Exception as e:
                self._render_panel_error(buf, geo.modal, "Modal", e)

        return buf.snapshot(frame_id=frame_id, state_revision=view_model.revision)

    def _render_header(self, buf: ScreenBuffer, r: Rect, vm: HermesViewModel) -> None:
        if r.h <= 0 or r.w <= 0:
            return

        m = vm.mission
        net = vm.network
        sess = vm.session

        status_color = "green" if m.status == "COMPLETED" else ("red" if m.status == "FAILED" else "cyan")

        # Line 1: Title and Status
        buf.put_string(r.x, r.y, "HERMES 2.x", fg="bright_cyan", bold=True)
        buf.put_string(r.x + 12, r.y, f"[{m.status}]", fg=status_color, bold=True)
        buf.put_string(r.x + 26, r.y, f"T1:{net.t1_provider}", fg="gray")
        buf.put_string(r.x + 44, r.y, f"Net:{net.connectivity}", fg="green" if net.connectivity == "CONNECTED" else "yellow")

        # Line 2 (if available): Mission and Session info
        if r.h > 1:
            title_text = m.title[:35] if m.title else "No Active Mission"
            buf.put_string(r.x, r.y + 1, f"Mission: {title_text}", fg="white")
            buf.put_string(r.x + 46, r.y + 1, f"Session: {sess.session_id[:10]}", fg="gray")
            chk = sess.current_checkpoint_id[:8] if sess.current_checkpoint_id else "None"
            buf.put_string(r.x + 66, r.y + 1, f"Chk: {chk}", fg="gray")

    def _render_active_bar(self, buf: ScreenBuffer, r: Rect, vm: HermesViewModel) -> None:
        if r.h <= 0 or r.w <= 0:
            return

        p = vm.progress
        task_str = f"▶ Task: {p.active_task_title[:35]}"
        action_str = f"Action: {p.current_action[:30]}"
        prog_str = f"[{p.percentage_str}]"

        buf.put_string(r.x, r.y, task_str, fg="bright_white", bold=True)
        buf.put_string(r.x + 42, r.y, action_str, fg="cyan")
        buf.put_string(r.x + 78, r.y, prog_str, fg="green" if p.percentage_str == "100%" else "yellow")

    def _render_chat(self, buf: ScreenBuffer, r: Rect, vm: HermesViewModel) -> None:
        if r.h <= 0 or r.w <= 0:
            return

        buf.draw_box(r.x, r.y, r.w, r.h, title="Conversation", fg="cyan")

        content_h = max(1, r.h - 2)
        content_w = max(1, r.w - 2)

        # Virtualize chat messages
        v_range = VirtualList.slice_viewport(
            items=vm.chat.messages,
            viewport_height=content_h,
            scroll_offset=vm.chat.scroll_offset,
            anchor_to_bottom=True,
        )

        curr_y = r.y + 1
        for msg in v_range.visible_items:
            if curr_y >= r.y + r.h - 1:
                break

            role_color = "cyan" if msg.author_role.lower() == "user" else "green"
            icon = "👤" if msg.author_role.lower() == "user" else "🤖"
            header = f"{icon} {msg.author_role} [{msg.timestamp_str}]:"
            buf.put_string(r.x + 1, curr_y, header, fg=role_color, bold=True, max_width=content_w)
            curr_y += 1

            if curr_y >= r.y + r.h - 1:
                break

            # Message content line
            c_text = sanitize_terminal_text(msg.content, allow_newlines=False)
            text_color = "bright_red" if msg.is_error else "white"
            buf.put_string(r.x + 3, curr_y, c_text, fg=text_color, max_width=content_w - 2)
            curr_y += 1

        # Streaming indicator at bottom of chat
        if vm.chat.is_streaming and curr_y < r.y + r.h - 1:
            partial = sanitize_terminal_text(vm.chat.streaming_partial_content, allow_newlines=False)
            stream_line = f"🤖 Generating: {partial[-content_w + 16:]} ▋"
            buf.put_string(r.x + 1, curr_y, stream_line, fg="bright_cyan", bold=True)

    def _render_right_panel(self, buf: ScreenBuffer, r: Rect, vm: HermesViewModel) -> None:
        if r.h <= 0 or r.w <= 0:
            return

        # Header with tabs
        buf.draw_box(r.x, r.y, r.w, r.h, title="Operations", fg="gray")

        content_h = max(1, r.h - 2)
        content_w = max(1, r.w - 2)

        # Tasks / Tools list
        curr_y = r.y + 1
        buf.put_string(r.x + 1, curr_y, "TASKS & EVIDENCE:", fg="white", bold=True)
        curr_y += 1

        for task in vm.tasks.tasks[:min(content_h - 1, 8)]:
            if curr_y >= r.y + r.h - 1:
                break
            icon = "✓" if task.status == "COMPLETED" else ("▶" if task.status == "RUNNING" else "○")
            color = "green" if task.status == "COMPLETED" else ("cyan" if task.status == "RUNNING" else "gray")
            t_line = f"{icon} {task.title[:content_w - 4]}"
            buf.put_string(r.x + 1, curr_y, t_line, fg=color, max_width=content_w)
            curr_y += 1

        if curr_y < r.y + r.h - 2 and vm.tools.recent_tools:
            curr_y += 1
            buf.put_string(r.x + 1, curr_y, "RECENT TOOLS:", fg="white", bold=True)
            curr_y += 1
            for tool in vm.tools.recent_tools[-4:]:
                if curr_y >= r.y + r.h - 1:
                    break
                t_icon = "✓" if not tool.is_error else "✗"
                t_col = "green" if not tool.is_error else "red"
                t_str = f"{t_icon} {tool.tool_name} ({tool.duration_str})"
                buf.put_string(r.x + 1, curr_y, t_str, fg=t_col, max_width=content_w)
                curr_y += 1

    def _render_input_bar(self, buf: ScreenBuffer, r: Rect, vm: HermesViewModel) -> None:
        if r.h <= 0 or r.w <= 0:
            return

        buf.draw_box(r.x, r.y, r.w, r.h, title="Command & Input", fg="gray")
        if r.h > 1:
            buf.put_string(r.x + 2, r.y + 1, f"> {vm.input_prompt_placeholder}", fg="gray", dim=True)

    def _render_modal(self, buf: ScreenBuffer, r: Rect, vm: HermesViewModel) -> None:
        if r.h <= 0 or r.w <= 0:
            return

        # Security modal takes priority
        if vm.security.modal and vm.security.modal.visible:
            modal = vm.security.modal
            buf.fill_rect(r.x, r.y, r.w, r.h, ch=" ", fg="white", bg="black")
            buf.draw_box(r.x, r.y, r.w, r.h, title="Security Authorization Required", fg="bright_yellow", style="double")
            buf.put_string(r.x + 2, r.y + 2, f"Action: {modal.action_summary}", fg="white", bold=True)
            buf.put_string(r.x + 2, r.y + 3, f"Risk Level: {modal.risk_level}", fg="red" if modal.risk_level in ("HIGH", "CRITICAL") else "yellow")
            buf.put_string(r.x + 2, r.y + 4, f"Explanation: {modal.explanation[:r.w - 6]}", fg="gray")
            buf.put_string(r.x + 2, r.y + r.h - 2, "[y] Approve  [n] Deny  [Esc] Cancel", fg="bright_white", bold=True)

        elif vm.rewind_preview and vm.rewind_preview.visible:
            rw = vm.rewind_preview
            buf.fill_rect(r.x, r.y, r.w, r.h, ch=" ", fg="white", bg="black")
            buf.draw_box(r.x, r.y, r.w, r.h, title="Rewind Preview", fg="bright_cyan", style="double")
            buf.put_string(r.x + 2, r.y + 2, f"Target Checkpoint: {rw.checkpoint_id}", fg="white", bold=True)
            buf.put_string(r.x + 2, r.y + 3, f"Files to Restore: {rw.restore_files_count} | Preserving: {rw.preserve_files_count}", fg="yellow")
            if rw.user_conflicts_count > 0:
                buf.put_string(r.x + 2, r.y + 4, f"USER CONFLICTS DETECTED: {rw.user_conflicts_count} files preserved!", fg="bright_red", bold=True)
            buf.put_string(r.x + 2, r.y + r.h - 2, "[y] Confirm Rewind  [n] Cancel", fg="bright_white", bold=True)

    def _render_panel_error(self, buf: ScreenBuffer, r: Rect, panel_name: str, error: Exception) -> None:
        """Render a bounded error placeholder without crashing the frame."""
        if r.h <= 0 or r.w <= 0:
            return
        buf.draw_box(r.x, r.y, r.w, r.h, title=f"{panel_name} Error", fg="red")
        buf.put_string(r.x + 2, r.y + 1, f"[{panel_name} unavailable: {str(error)[:r.w - 10]}]", fg="red")
