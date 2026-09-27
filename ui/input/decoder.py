# ui/input/decoder.py
"""
Safe Terminal Input Decoder.

Translates raw bytes / keystrokes into typed InputEvent dataclasses.
Guarantees:
1. Bounded buffer: No unbounded stdin accumulation.
2. Malformed escape sequence protection.
3. Bracketed paste boundary handling.
4. Clean Ctrl+C / EOF detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from ui.rendering.text_safety import sanitize_terminal_text


@dataclass(frozen=True)
class KeyPressEvent:
    key: str                # e.g., "enter", "up", "down", "tab", "esc", "char"
    char: Optional[str] = None
    ctrl: bool = False
    alt: bool = False


@dataclass(frozen=True)
class TextInputEvent:
    text: str


@dataclass(frozen=True)
class PasteEvent:
    text: str
    is_bracketed: bool = False


@dataclass(frozen=True)
class MouseEvent:
    action: str             # "press", "release", "scroll_up", "scroll_down"
    x: int
    y: int
    button: int = 1


@dataclass(frozen=True)
class ResizeEvent:
    width: int
    height: int


@dataclass(frozen=True)
class InterruptEvent:
    """Triggered by Ctrl+C / SIGINT."""
    pass


@dataclass(frozen=True)
class EOFEvent:
    """Triggered by stdin EOF."""
    pass


InputEvent = Union[
    KeyPressEvent,
    TextInputEvent,
    PasteEvent,
    MouseEvent,
    ResizeEvent,
    InterruptEvent,
    EOFEvent,
]


class InputDecoder:
    """Translates characters and escape sequences into typed InputEvents."""

    MAX_BUFFER_LEN = 16384  # 16 KB input cap to prevent memory exhaustion

    def __init__(self):
        self._buffer: str = ""

    def feed(self, raw_input: str) -> List[InputEvent]:
        """Process incoming raw string and return decoded events."""
        events: List[InputEvent] = []

        if len(self._buffer) + len(raw_input) > self.MAX_BUFFER_LEN:
            # Drop input overflow
            return events

        self._buffer += raw_input
        i = 0
        n = len(self._buffer)

        while i < n:
            ch = self._buffer[i]

            # 1. Ctrl+C (0x03)
            if ch == "\x03":
                events.append(InterruptEvent())
                i += 1
                continue

            # 2. Ctrl+D / EOF (0x04)
            if ch == "\x04":
                events.append(EOFEvent())
                i += 1
                continue

            # 3. Enter (\r or \n)
            if ch in ("\r", "\n"):
                if i + 1 < n and ch == "\r" and self._buffer[i + 1] == "\n":
                    i += 1
                events.append(KeyPressEvent(key="enter"))
                i += 1
                continue

            # 4. Tab
            if ch == "\t":
                events.append(KeyPressEvent(key="tab"))
                i += 1
                continue

            # 5. Backspace (\x08 or \x7f)
            if ch in ("\x08", "\x7f"):
                events.append(KeyPressEvent(key="backspace"))
                i += 1
                continue

            # 6. Escape sequences
            if ch == "\x1b":
                if i + 1 == n:
                    # Incomplete escape at end of buffer: wait for more input unless flush
                    break

                next_ch = self._buffer[i + 1]
                if next_ch == "[":
                    # CSI sequence
                    seq_end = i + 2
                    while seq_end < n and not (0x40 <= ord(self._buffer[seq_end]) <= 0x7E):
                        seq_end += 1

                    if seq_end < n:
                        csi_body = self._buffer[i + 2:seq_end + 1]
                        parsed_ev = self._parse_csi(csi_body)
                        if parsed_ev:
                            events.append(parsed_ev)
                        i = seq_end + 1
                        continue
                    else:
                        # Incomplete sequence: hold in buffer
                        break
                else:
                    # Alt + character or standalone Escape
                    events.append(KeyPressEvent(key="esc"))
                    i += 1
                    continue

            # 7. Normal printable character
            events.append(KeyPressEvent(key="char", char=ch))
            i += 1

        self._buffer = self._buffer[i:]
        return events

    def _parse_csi(self, csi: str) -> Optional[InputEvent]:
        """Decode common CSI escape sequences."""
        if csi == "A":
            return KeyPressEvent(key="up")
        elif csi == "B":
            return KeyPressEvent(key="down")
        elif csi == "C":
            return KeyPressEvent(key="right")
        elif csi == "D":
            return KeyPressEvent(key="left")
        elif csi in ("H", "1~"):
            return KeyPressEvent(key="home")
        elif csi in ("F", "4~"):
            return KeyPressEvent(key="end")
        elif csi == "3~":
            return KeyPressEvent(key="delete")
        elif csi == "5~":
            return KeyPressEvent(key="page_up")
        elif csi == "6~":
            return KeyPressEvent(key="page_down")
        elif csi.startswith("200~"):
            # Bracketed paste start
            return None
        return None
