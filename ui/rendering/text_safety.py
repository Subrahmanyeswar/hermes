# ui/rendering/text_safety.py
"""
Deterministic, side-effect-free terminal text sanitizer.

Guarantees:
1. Untrusted text (tool results, model outputs, file names, git logs) cannot inject
   ANSI/CSI/OSC control sequences, change terminal titles, trigger clipboard operations,
   or perform cursor-overwrite attacks.
2. Strips private reasoning blocks (<think>...</think>) without exposing them.
3. Preserves legitimate printable Unicode (including CJK, emoji, accented characters).
4. Strictly side-effect free: NO file access, NO network, NO logging, NO model calls.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# Regex to match ANSI escape sequences (OSC, CSI, ESC sequences)
_ANSI_ESCAPE_RE: Final[re.Pattern] = re.compile(
    r"\x1B(?:\][^\x07\x1B]*(?:\x07|\x1B\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])",
    re.DOTALL,
)

# Regex to detect and strip internal reasoning / chain-of-thought blocks
_THINK_BLOCK_RE: Final[re.Pattern] = re.compile(
    r"<think>.*?</think>",
    re.DOTALL | re.IGNORECASE,
)

# Regex for unclosed think block at the end of a partial stream
_THINK_UNCLOSED_RE: Final[re.Pattern] = re.compile(
    r"<think>.*$",
    re.DOTALL | re.IGNORECASE,
)

# C0 controls to strip (excluding \n and optionally \t)
# Keep \n (0x0A); strip \r (0x0D - carriage return overwrite attack), \b (0x08 - backspace attack), \x00-\x08, \x0B-\x0C, \x0E-\x1F, \x7F
_C0_STRIP_RE: Final[re.Pattern] = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# C1 controls (0x80 - 0x9F)
_C1_STRIP_RE: Final[re.Pattern] = re.compile(r"[\x80-\x9F]")


def sanitize_terminal_text(
    value: Any,
    *,
    allow_newlines: bool = True,
    allow_tabs: bool = False,
    preserve_unicode: bool = True,
    max_length: Optional[int] = None,
) -> str:
    """
    Sanitize untrusted text for safe terminal display.
    """
    if value is None:
        return ""

    if not isinstance(value, str):
        value = str(value)

    # 1. Strip internal reasoning/think blocks
    text = _THINK_BLOCK_RE.sub("", value)
    text = _THINK_UNCLOSED_RE.sub("", text)

    # 2. Strip ANSI escape sequences (CSI, OSC, etc.)
    text = _ANSI_ESCAPE_RE.sub("", text)

    # 3. Strip dangerous C0 control characters (\r, \b, etc.)
    # Carriage return overwrite attack: remove \r entirely
    text = text.replace("\r\n", "\n").replace("\r", "")

    # Handle tabs
    if not allow_tabs:
        text = text.replace("\t", "    ")

    # Handle newlines
    if not allow_newlines:
        text = text.replace("\n", " ")

    # Strip remaining C0 and C1 controls
    text = _C0_STRIP_RE.sub("", text)
    text = _C1_STRIP_RE.sub("", text)

    # 4. Unicode normalization & sanitization
    if preserve_unicode:
        # Normalize to NFC for consistent width and rendering
        text = unicodedata.normalize("NFC", text)
        # Filter out non-printable format characters except newline/space
        cleaned_chars = []
        for ch in text:
            cat = unicodedata.category(ch)
            # Cc = Control, Cf = Format (zero-width joiners, bidi controls, etc. can be manipulated)
            if cat == "Cc" and ch != "\n":
                continue
            # Filter dangerous bidi override characters (U+202A to U+202E, U+2066 to U+2069)
            if 0x202A <= ord(ch) <= 0x202E or 0x2066 <= ord(ch) <= 0x2069:
                continue
            cleaned_chars.append(ch)
        text = "".join(cleaned_chars)
    else:
        text = text.encode("ascii", "replace").decode("ascii")

    # 5. Bound length if specified
    if max_length is not None and len(text) > max_length:
        text = text[:max_length] + "…"

    return text


def get_char_width(ch: str) -> int:
    """
    Return terminal character display cell width (1 for regular/narrow, 2 for fullwidth/wide/emoji, 0 for combining).
    """
    if not ch:
        return 0
    # Combining characters have zero display width
    if unicodedata.combining(ch):
        return 0
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me", "Cf"):
        return 0
    ea = unicodedata.east_asian_width(ch)
    if ea in ("W", "F"):
        return 2
    return 1


def get_string_display_width(text: str) -> int:
    """Compute total terminal display width of a string."""
    return sum(get_char_width(ch) for ch in text)
