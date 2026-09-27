# HERMES 2.x — TUI 2.x Rendering Model Specification

## 1. Screen Representation and Buffers

### 1.1 ScreenCell
The atomic unit of terminal display is the immutable `ScreenCell`:
- `char: str`: A single Unicode codepoint or empty string for wide character continuations.
- `fg: Optional[str]`: Foreground color (named ANSI color, 8-bit index, or 24-bit `#rrggbb`).
- `bg: Optional[str]`: Background color.
- `bold: bool`: Bold / bright text attribute.
- `dim: bool`: Dim text attribute.
- `italic: bool`: Italic text attribute.
- `underline: bool`: Underline text attribute.
- `reverse: bool`: Inverted colors attribute.
- `width: int`: Visual display columns occupied (1 for normal ASCII/Latin, 2 for CJK / fullwidth emoji, 0 for continuations).

### 1.2 ScreenFrame
An immutable, frozen 2D snapshot of cells:
- Dimensions: `width: int`, `height: int`.
- Grid: `cells: Tuple[Tuple[ScreenCell, ...], ...]`.
- Metadata: `frame_id: int`, `state_revision: int`.
- Export: `to_plain_text()` strips all ANSI styling and produces clean raw text for verification and debugging.

### 1.3 ScreenBuffer
The mutable canvas used during frame construction:
- `put_char(x, y, char, ...)`: Clips out-of-bounds coordinates, resolves character visual width, and inserts continuation cells for double-width CJK codepoints.
- `put_string(x, y, text, ...)`: Sanitizes untrusted text and draws strings with horizontal clipping.
- `fill_rect(rect, char, ...)`: Clears or paints rectangular bounding boxes.
- `draw_box(rect, title, ...)`: Renders Unicode box-drawing borders (`┌─┐│└─┘`) with optional titled headers.
- `freeze(frame_id, state_revision)`: Returns an immutable `ScreenFrame`.

---

## 2. Frame Differencing Algorithm

Rather than emitting full-screen repaints or clearing the screen on every frame, `FrameDiffer` computes a minimal delta:

1. **Dimension Mismatch / First Frame:** If dimensions change or no previous frame exists, a full repaint is performed.
2. **Row Hash / Identity Fast-Path:** Each row in `previous` and `current` is compared by reference or tuple equality. Unchanged rows are skipped entirely in $O(1)$.
3. **Contiguous Run Extraction:** For rows with differences, contiguous spans of modified cells are grouped into `DiffRun(x, y, cells)`.
4. **Bandwidth Optimization:** Minimizes cursor repositioning sequences (`\033[y;xH`) by only moving the cursor to the start of each contiguous run.

---

## 3. Terminal Capabilities and Safe ANSI Emission

`TerminalWriter` communicates directly with stdout using negotiated capabilities:

| Capability | Detection Heuristic | Behavior |
| :--- | :--- | :--- |
| **Color Depth** | `$COLORTERM`, `$TERM`, Windows VT | Downgrades TRUECOLOR to ANSI 256 or ANSI 16 when unsupported. If `NO_COLOR` is set, all color attributes are suppressed. |
| **Alternate Screen** | TTY probe, VT support | Emits `\033[?1049h` on start, `\033[?1049l` on exit. Leaves user shell scrollback clean. |
| **Cursor Visibility** | TTY probe | Emits `\033[?25l` to hide cursor during active rendering; restores `\033[?25h` on exit. |
| **Broken Pipe / Redirect** | `BrokenPipeError`, `OSError` | Catches pipe closures cleanly without throwing exceptions into the agent loop. |

---

## 4. Text Safety and Hostile Input Defense

Untrusted text from tool executions, model deltas, git logs, and file content must never compromise the host terminal. `sanitize_terminal_text()` guarantees:

1. **ANSI / CSI / OSC Neutralization:**
   - Strips ANSI sequences (color codes, cursor moves).
   - Neutralizes OSC commands (e.g. `\033]0;Injected Title\007`) that attempt window title tampering or clipboard hijacking.
2. **Control Character Stripping:**
   - Strips carriage return (`\r`) and backspace (`\b`) overwrite attacks.
   - Strips C0 (`0x00`-`0x1F` except `\n`) and C1 (`0x80`-`0x9F`) control characters.
3. **Reasoning Block Redaction:**
   - Removes private `<think>...</think>` internal reasoning blocks.
4. **Unicode Normalization:**
   - Normalizes text with NFC Unicode normalization and preserves valid multilingual text (CJK, Arabic, European accents).

---

## 5. Large Dataset Virtualization

To prevent memory leaks and maintain 60 FPS streaming during 10,000+ line execution traces:
- `VirtualList.slice_viewport(items, viewport_height, scroll_offset)` calculates the visible range with $O(\text{viewport})$ space and time complexity.
- Slicing 10,000 items takes **0.0024 ms (p50)**.
- Default bottom-anchoring keeps the newest messages in view as streaming deltas arrive, while scrolling up detaches anchoring until the user returns to the bottom.

---

## 6. Responsive Layout and Graceful Degradation

`LayoutEngine` partitions the terminal grid based on available geometry:

| Dimensions | Mode | Layout Behavior |
| :--- | :--- | :--- |
| **>= 90 x 20** | Full Layout | Header, ActiveBar, Split Chat (60%) + Operations/Tasks (40%), InputBar. |
| **60 x 15 to 89 x 19** | Compact Layout | Operations pane collapsed; Chat expanded to 100% width; Header compressed. |
| **20 x 5 to 59 x 14** | Minimal Layout | Single-line Header, 1-line Mission status, active task, 1-line input prompt. |
| **< 20 x 5** | Emergency Minimal | Clamped to non-negative coordinates; renders single truthful status line without crashing. |
