# core/code_intelligence/tools.py
"""
LSP / Code Intelligence Tools for HERMES AgentLoop (Prompt 17).
Exposes diagnostics, definitions, references, symbols, hover/types, and rename.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.code_intelligence.manager import CodeIntelligenceManager, PathSecurityError
from tools.base import BaseTool, ToolResult


def _run_async(coro):
    """Safely run async coroutine synchronously or in existing loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Running inside an event loop — schedule as a task with future
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(coro)).result(timeout=30.0)
    else:
        return asyncio.run(coro)


class LspDiagnosticsTool(BaseTool):
    name = "lsp_diagnostics"
    description = "Inspect compiler/linter diagnostics, syntax errors, and type warnings for a file."
    risk_score = 0.0

    def __init__(self, manager: Optional[CodeIntelligenceManager] = None) -> None:
        self.manager = manager or CodeIntelligenceManager(workspace_root=Path.cwd())

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            file_path = inp.get("file_path", "")
        else:
            file_path = str(inp)

        if not file_path:
            return ToolResult(success=False, error="Missing required parameter 'file_path'", exit_code=1)

        try:
            diags = _run_async(self.manager.get_diagnostics(file_path))
            duration = time.monotonic() - start_time
            if not diags:
                return ToolResult(
                    success=True,
                    output=f"No diagnostics/errors found in {file_path}.",
                    duration_seconds=duration,
                    details={"count": 0, "file": file_path, "diagnostics": []},
                )

            lines = [f"Found {len(diags)} diagnostic(s) in {file_path}:"]
            for d in diags:
                lines.append(f"  • Line {d.range.start.human_line}:{d.range.start.human_col} [{d.severity.name}] {d.message} (source: {d.source or 'lsp'})")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                duration_seconds=duration,
                details={
                    "count": len(diags),
                    "file": file_path,
                    "diagnostics": [d.to_dict() for d in diags],
                },
            )
        except PathSecurityError as e:
            return ToolResult(success=False, error=str(e), exit_code=3, duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            return ToolResult(success=False, error=f"Diagnostics failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class LspDefinitionTool(BaseTool):
    name = "lsp_definition"
    description = "Jump to the definition of a symbol at the specified line and column."
    risk_score = 0.0

    def __init__(self, manager: Optional[CodeIntelligenceManager] = None) -> None:
        self.manager = manager or CodeIntelligenceManager(workspace_root=Path.cwd())

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            file_path = inp.get("file_path", "")
            line = int(inp.get("line", 1))
            col = int(inp.get("col", 1))
        else:
            return ToolResult(success=False, error="Input must be a dictionary with file_path, line, col", exit_code=1)

        try:
            locs = _run_async(self.manager.get_definition(file_path, line, col))
            duration = time.monotonic() - start_time
            if not locs:
                return ToolResult(
                    success=True,
                    output=f"No definition found for symbol at {file_path}:{line}:{col}.",
                    duration_seconds=duration,
                    details={"locations": []},
                )

            lines = [f"Found {len(locs)} definition location(s):"]
            for loc in locs:
                lines.append(f"  • {loc.file_path}:{loc.range.start.human_line}:{loc.range.start.human_col}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                duration_seconds=duration,
                details={"locations": [loc.to_dict() for loc in locs]},
            )
        except PathSecurityError as e:
            return ToolResult(success=False, error=str(e), exit_code=3, duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            return ToolResult(success=False, error=f"Definition lookup failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class LspReferencesTool(BaseTool):
    name = "lsp_references"
    description = "Find all semantic references to a symbol across the workspace."
    risk_score = 0.0

    def __init__(self, manager: Optional[CodeIntelligenceManager] = None) -> None:
        self.manager = manager or CodeIntelligenceManager(workspace_root=Path.cwd())

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            file_path = inp.get("file_path", "")
            line = int(inp.get("line", 1))
            col = int(inp.get("col", 1))
            include_decl = bool(inp.get("include_declaration", True))
        else:
            return ToolResult(success=False, error="Input must be a dictionary with file_path, line, col", exit_code=1)

        try:
            locs = _run_async(self.manager.get_references(file_path, line, col, include_declaration=include_decl))
            duration = time.monotonic() - start_time
            if not locs:
                return ToolResult(
                    success=True,
                    output=f"No references found for symbol at {file_path}:{line}:{col}.",
                    duration_seconds=duration,
                    details={"references": []},
                )

            lines = [f"Found {len(locs)} reference(s):"]
            for loc in locs:
                lines.append(f"  • {loc.file_path}:{loc.range.start.human_line}:{loc.range.start.human_col}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                duration_seconds=duration,
                details={"references": [loc.to_dict() for loc in locs]},
            )
        except PathSecurityError as e:
            return ToolResult(success=False, error=str(e), exit_code=3, duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            return ToolResult(success=False, error=f"References lookup failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class LspSymbolsTool(BaseTool):
    name = "lsp_symbols"
    description = "List document symbols (classes, functions, variables) or search workspace symbols."
    risk_score = 0.0

    def __init__(self, manager: Optional[CodeIntelligenceManager] = None) -> None:
        self.manager = manager or CodeIntelligenceManager(workspace_root=Path.cwd())

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        query = None
        file_path = None
        if isinstance(inp, dict):
            file_path = inp.get("file_path")
            query = inp.get("query")
        elif isinstance(inp, str):
            if inp.endswith((".py", ".ts", ".js", ".html", ".css", ".json")):
                file_path = inp
            else:
                query = inp

        try:
            duration = 0.0
            if file_path:
                symbols = _run_async(self.manager.get_document_symbols(file_path))
                duration = time.monotonic() - start_time
                lines = [f"Symbols in {file_path}:"]
                for sym in symbols:
                    lines.append(f"  • [{sym.kind.label}] {sym.name} (Line {sym.range.start.human_line})")
                    for child in sym.children:
                        lines.append(f"      └─ [{child.kind.label}] {child.name} (Line {child.range.start.human_line})")

                return ToolResult(
                    success=True,
                    output="\n".join(lines),
                    duration_seconds=duration,
                    details={"symbols": [s.to_dict() for s in symbols]},
                )
            elif query:
                symbols = _run_async(self.manager.get_workspace_symbols(query))
                duration = time.monotonic() - start_time
                lines = [f"Workspace symbols matching '{query}':"]
                for sym in symbols:
                    lines.append(f"  • [{sym.kind.label}] {sym.name} in {sym.location.file_path}:{sym.location.range.start.human_line}")

                return ToolResult(
                    success=True,
                    output="\n".join(lines),
                    duration_seconds=duration,
                    details={"symbols": [s.to_dict() for s in symbols]},
                )
            else:
                return ToolResult(success=False, error="Must specify either 'file_path' or 'query'", exit_code=1)

        except PathSecurityError as e:
            return ToolResult(success=False, error=str(e), exit_code=3, duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            return ToolResult(success=False, error=f"Symbols request failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class LspTypeInfoTool(BaseTool):
    name = "lsp_type_info"
    description = "Get semantic type signature and docstring hover information for a symbol."
    risk_score = 0.0

    def __init__(self, manager: Optional[CodeIntelligenceManager] = None) -> None:
        self.manager = manager or CodeIntelligenceManager(workspace_root=Path.cwd())

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            file_path = inp.get("file_path", "")
            line = int(inp.get("line", 1))
            col = int(inp.get("col", 1))
        else:
            return ToolResult(success=False, error="Input must be a dictionary with file_path, line, col", exit_code=1)

        try:
            res = _run_async(self.manager.get_type_info(file_path, line, col))
            duration = time.monotonic() - start_time
            lines = [
                f"Symbol: {res.symbol or 'at position'}",
                f"Type: {res.type_name}",
                f"Provenance: {res.provenance}",
            ]
            if res.documentation:
                lines.append(f"Documentation:\n{res.documentation}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                duration_seconds=duration,
                details=res.to_dict(),
            )
        except PathSecurityError as e:
            return ToolResult(success=False, error=str(e), exit_code=3, duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            return ToolResult(success=False, error=f"Type info failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class LspRenameTool(BaseTool):
    name = "lsp_rename"
    description = "Rename a symbol project-wide using semantic code intelligence."
    risk_score = 1.0  # Mutating operation

    def __init__(self, manager: Optional[CodeIntelligenceManager] = None) -> None:
        self.manager = manager or CodeIntelligenceManager(workspace_root=Path.cwd())

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            file_path = inp.get("file_path", "")
            line = int(inp.get("line", 1))
            col = int(inp.get("col", 1))
            new_name = str(inp.get("new_name", ""))
            apply_edits = bool(inp.get("apply", False))
        else:
            return ToolResult(success=False, error="Input must be a dictionary with file_path, line, col, new_name", exit_code=1)

        if not new_name:
            return ToolResult(success=False, error="Missing required parameter 'new_name'", exit_code=1)

        try:
            edit = _run_async(self.manager.rename_symbol(file_path, line, col, new_name, apply_edits=apply_edits))
            duration = time.monotonic() - start_time

            if not edit.changes:
                return ToolResult(
                    success=False,
                    error=f"No rename edits could be computed for symbol at {file_path}:{line}:{col}",
                    exit_code=1,
                    duration_seconds=duration,
                )

            lines = [
                f"{'Applied' if apply_edits else 'Preview of'} rename to '{new_name}':",
                f"  Total edits: {edit.total_edits} across {len(edit.affected_files)} file(s)",
            ]
            for path, edits in edit.changes.items():
                lines.append(f"  • {path}: {len(edits)} replacement(s)")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                duration_seconds=duration,
                details=edit.to_dict(),
            )
        except PathSecurityError as e:
            return ToolResult(success=False, error=str(e), exit_code=3, duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            return ToolResult(success=False, error=f"Rename failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)
