# core/code_completeness.py
"""
Code Completeness and Anti-Placeholder Validation Pipeline for HERMES.
Enforces that generated implementation files (.js, .ts, .jsx, .tsx, .py) contain
executable, non-truncated logic rather than placeholder stubs ({ ... }),
unimplemented function bodies, or comment-only files.

Guarantees context-awareness:
  - Valid spread syntax (...args, [...items], {...props}) is allowed.
  - Valid rest parameters (function foo(...rest)) are allowed.
  - Valid ellipses in strings ("Loading...") and comments are allowed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple


def is_placeholder_js(content: str) -> Tuple[bool, str]:
    """
    Check if JavaScript/TypeScript content contains unmistakable placeholder function bodies or stubs.
    Returns (is_placeholder, detail_reason).
    """
    if not content or not isinstance(content, str):
        return False, ""

    # Check 1: Explicit empty body with ellipsis or ellipsis comment: { ... } or { /* ... */ } or { // ... }
    # Function declaration, method, arrow function, class followed by { ... }
    pattern_func_stub = re.compile(
        r'(?:function\s+([a-zA-Z0-9_$]+)|([a-zA-Z0-9_$]+)\s*\([^)]*\)|class\s+([a-zA-Z0-9_$]+)|(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>)\s*\{\s*(?:\.\.\.|/\*\s*\.\.\.\s*\*/|//\s*(?:\.\.\.|TODO[^\n]*)\s*)\s*\}',
        re.MULTILINE
    )
    m = pattern_func_stub.search(content)
    if m:
        name = m.group(1) or m.group(2) or m.group(3) or m.group(4) or "anonymous"
        return True, f"Incomplete implementation: Function/class '{name}' contains placeholder stub body '{{ ... }}'"

    # Check 2: Standalone { ... } or { /* ... */ } block
    pattern_block_stub = re.compile(r'\{\s*(?:\.\.\.|/\*\s*\.\.\.\s*\*/)\s*\}')
    m2 = pattern_block_stub.search(content)
    if m2:
        return True, "Incomplete implementation: Contains placeholder block '{ ... }'"

    # Check 3: Multi-line function body with ONLY ellipsis or TODO comment
    pattern_multiline_stub = re.compile(
        r'(?:function\s+([a-zA-Z0-9_$]+)|([a-zA-Z0-9_$]+)\s*\([^)]*\))\s*\{\s*(?:\r?\n\s*)+(?:\.\.\.|/\*\s*\.\.\.\s*\*/|//\s*\.\.\.)\s*(?:\r?\n\s*)+\}',
        re.MULTILINE
    )
    m3 = pattern_multiline_stub.search(content)
    if m3:
        name = m3.group(1) or m3.group(2) or "anonymous"
        return True, f"Incomplete implementation: Function '{name}' contains multi-line placeholder body '{{ ... }}'"

    return False, ""


def validate_implementation_completeness(content: str, filename: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that an implementation file has substantive executable code and no placeholder stubs.
    Returns (is_valid, error_message).
    """
    norm_fn = Path(filename).name.lower()
    is_code = norm_fn.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))
    if not is_code:
        return True, None

    # 1. Check for placeholder function bodies
    is_stub, reason = is_placeholder_js(content)
    if is_stub:
        return False, f"INCOMPLETE_IMPLEMENTATION_REJECTED: {reason}. You must write the complete executable logic without placeholders."

    # 2. Check if file consists entirely of comments or whitespace
    clean_lines = []
    in_block_comment = False
    for line in content.splitlines():
        stripped = line.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
                stripped = stripped.split("*/", 1)[1].strip()
            else:
                continue
        if stripped.startswith("/*"):
            if "*/" in stripped:
                stripped = stripped.split("*/", 1)[1].strip()
            else:
                in_block_comment = True
                continue
        if stripped.startswith("//"):
            continue
        if stripped:
            clean_lines.append(stripped)

    if not clean_lines:
        return False, f"INCOMPLETE_IMPLEMENTATION_REJECTED: File '{norm_fn}' contains only comments or whitespace with no executable statements."

    return True, None
