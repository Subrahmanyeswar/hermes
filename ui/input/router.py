# ui/input/router.py
"""
Typed Input Router.

Guarantees:
1. TUI OBSERVES; TUI DOES NOT DECIDE.
2. Input events are classified into typed intent and dispatched to registered handlers.
3. Security modals and commands route through authoritative service callbacks.
"""

from __future__ import annotations

from typing import Callable, Optional

from ui.input.command_parser import CommandParser, ParsedCommand
from ui.input.decoder import (
    EOFEvent,
    InputEvent,
    InterruptEvent,
    KeyPressEvent,
    PasteEvent,
    ResizeEvent,
    TextInputEvent,
)


class InputRouter:
    """Routes decoded input events to authoritative service callbacks."""

    def __init__(
        self,
        on_prompt_submit: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[ParsedCommand], None]] = None,
        on_permission_response: Optional[Callable[[bool], None]] = None,
        on_rewind_confirm: Optional[Callable[[bool], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        on_resize: Optional[Callable[[int, int], None]] = None,
    ):
        self.on_prompt_submit = on_prompt_submit
        self.on_command = on_command
        self.on_permission_response = on_permission_response
        self.on_rewind_confirm = on_rewind_confirm
        self.on_cancel = on_cancel
        self.on_resize = on_resize

        self.input_buffer: str = ""
        self.cursor_pos: int = 0
        self.is_security_modal_active: bool = False
        self.is_rewind_modal_active: bool = False

    def handle_event(self, event: InputEvent) -> None:
        """Route an input event."""
        # 1. Interrupt / Cancel
        if isinstance(event, InterruptEvent):
            if self.on_cancel:
                self.on_cancel()
            return

        # 2. Resize
        if isinstance(event, ResizeEvent):
            if self.on_resize:
                self.on_resize(event.width, event.height)
            return

        # 3. Security Modal Handling
        if self.is_security_modal_active and isinstance(event, KeyPressEvent):
            if event.char in ("y", "Y"):
                if self.on_permission_response:
                    self.on_permission_response(True)
                self.is_security_modal_active = False
                return
            elif event.char in ("n", "N") or event.key == "esc":
                if self.on_permission_response:
                    self.on_permission_response(False)
                self.is_security_modal_active = False
                return

        # 4. Rewind Modal Handling
        if self.is_rewind_modal_active and isinstance(event, KeyPressEvent):
            if event.char in ("y", "Y"):
                if self.on_rewind_confirm:
                    self.on_rewind_confirm(True)
                self.is_rewind_modal_active = False
                return
            elif event.char in ("n", "N") or event.key == "esc":
                if self.on_rewind_confirm:
                    self.on_rewind_confirm(False)
                self.is_rewind_modal_active = False
                return

        # 5. Standard Text Input & Editing
        if isinstance(event, KeyPressEvent):
            if event.key == "enter":
                self._submit_buffer()
            elif event.key == "backspace":
                if self.cursor_pos > 0:
                    self.input_buffer = (
                        self.input_buffer[: self.cursor_pos - 1]
                        + self.input_buffer[self.cursor_pos :]
                    )
                    self.cursor_pos -= 1
            elif event.key == "char" and event.char:
                self.input_buffer = (
                    self.input_buffer[: self.cursor_pos]
                    + event.char
                    + self.input_buffer[self.cursor_pos :]
                )
                self.cursor_pos += len(event.char)

        elif isinstance(event, (TextInputEvent, PasteEvent)):
            # Append sanitized text
            self.input_buffer = (
                self.input_buffer[: self.cursor_pos]
                + event.text
                + self.input_buffer[self.cursor_pos :]
            )
            self.cursor_pos += len(event.text)

    def _submit_buffer(self) -> None:
        """Submit the current command line or prompt."""
        text = self.input_buffer.strip()
        self.input_buffer = ""
        self.cursor_pos = 0

        if not text:
            return

        if CommandParser.is_command(text):
            parsed = CommandParser.parse(text)
            if parsed and self.on_command:
                self.on_command(parsed)
        else:
            if self.on_prompt_submit:
                self.on_prompt_submit(text)
