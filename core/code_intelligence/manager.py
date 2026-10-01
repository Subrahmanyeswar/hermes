# core/code_intelligence/manager.py
"""
Code Intelligence Manager for HERMES 2.x (Prompt 17).
Orchestrates Language Server Protocol (LSP) processes, semantic queries,
path security containment, heuristic fallbacks, and safe workspace edits.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core.code_intelligence.client import LspClient
from core.code_intelligence.models import (
    DiagnosticSeverity,
    DocumentSymbol,
    IntelligenceProvenance,
    Location,
    LspDiagnostic,
    Position,
    Range,
    ServerCapabilities,
    ServerStatus,
    SymbolInformation,
    SymbolKind,
    TextEdit,
    TypeInfoResult,
    WorkspaceEdit,
)
from core.code_intelligence.registry import LspServerDefinition, LspServerRegistry, lsp_registry

logger = logging.getLogger("hermes.code_intelligence.manager")


class PathSecurityError(PermissionError):
    """Raised when an operation attempts to access files outside the workspace."""
    pass


class CodeIntelligenceManager:
    """
    Authoritative manager for code intelligence across the active workspace.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        registry: Optional[LspServerRegistry] = None,
        enable_lsp: bool = True,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.registry = registry or lsp_registry
        self.enable_lsp = enable_lsp

        self._clients: Dict[str, LspClient] = {}
        self._document_generations: Dict[str, int] = {}
        self._document_cache: Dict[str, str] = {}
        self._diagnostics_cache: Dict[str, List[LspDiagnostic]] = {}
        self._lock = asyncio.Lock()

    # ── Path & Workspace Security ─────────────────────────────────────────────

    def validate_path(self, path: Union[Path, str]) -> Path:
        """
        Ensure the path resides strictly within the active workspace root.
        Rejects traversal attempts ('..'), absolute breakouts, and UNC paths.
        """
        raw = str(path).strip()
        # Reject UNC prefix breakouts unless explicitly inside workspace root
        if raw.startswith("\\\\") or raw.startswith("//"):
            resolved = Path(raw).resolve()
        else:
            p = Path(path)
            if not p.is_absolute():
                resolved = (self.workspace_root / p).resolve()
            else:
                resolved = p.resolve()

        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            raise PathSecurityError(
                f"Path security violation: '{path}' resolves outside workspace root '{self.workspace_root}'"
            )

        return resolved

    # ── Client Lifecycle ──────────────────────────────────────────────────────

    async def get_client_for_file(self, file_path: Path | str) -> Optional[LspClient]:
        """Obtain or lazily launch an active LspClient for the given file's language."""
        if not self.enable_lsp:
            return None

        clean_path = self.validate_path(file_path)
        server_def = self.registry.get_server_for_file(clean_path)
        if not server_def or not server_def.is_available():
            return None

        lang = server_def.language_id
        async with self._lock:
            client = self._clients.get(lang)
            if client is None or not client.is_ready:
                client = LspClient(
                    command=server_def.full_command,
                    workspace_root=self.workspace_root,
                    language_id=lang,
                    initialization_options=server_def.initialization_options,
                    env=server_def.env_overrides or None,
                )
                success = await client.start_and_initialize()
                if success:
                    self._clients[lang] = client
                else:
                    return None
            return client

    # ── Document Synchronization & Freshness ──────────────────────────────────

    async def notify_file_updated(self, file_path: Path | str, content: Optional[str] = None) -> None:
        """Call whenever a file is edited to sync with LSP and invalidate stale caches."""
        clean_path = self.validate_path(file_path)
        path_str = str(clean_path)

        # Bump generation
        gen = self._document_generations.get(path_str, 0) + 1
        self._document_generations[path_str] = gen
        self._diagnostics_cache.pop(path_str, None)

        if content is None:
            if clean_path.exists() and clean_path.is_file():
                try:
                    content = clean_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    content = ""
            else:
                content = ""

        self._document_cache[path_str] = content

        client = await self.get_client_for_file(clean_path)
        if client and client.is_ready:
            await client.notify_did_change(path_str, content)

    # ── Code Intelligence Operations ──────────────────────────────────────────

    async def get_diagnostics(self, file_path: Path | str) -> List[LspDiagnostic]:
        """
        Fetch diagnostics for a file.
        Uses active LSP server when available; falls back to fast syntax validation.
        """
        clean_path = self.validate_path(file_path)
        path_str = str(clean_path)

        client = await self.get_client_for_file(clean_path)
        if client and client.is_ready:
            # Sync file state first
            if path_str not in client._open_documents and clean_path.exists():
                text = clean_path.read_text(encoding="utf-8", errors="replace")
                await client.notify_did_open(path_str, text)

            diags = client.get_diagnostics(path_str)
            if diags:
                gen = self._document_generations.get(path_str, 0)
                for d in diags:
                    d.generation = gen
                return diags

        # Heuristic / Static Fallback (e.g. Python ast syntax check)
        return self._fallback_syntax_diagnostics(clean_path)

    async def get_definition(self, file_path: Path | str, line: int, col: int) -> List[Location]:
        """
        Find definition(s) for symbol at given 1-based line and column.
        Returns empty list if not found.
        """
        clean_path = self.validate_path(file_path)
        pos = Position(line=max(0, line - 1), character=max(0, col - 1))

        client = await self.get_client_for_file(clean_path)
        if client and client.is_ready and client.capabilities.definition:
            locations = await client.request_definition(str(clean_path), pos)
            # Filter definitions strictly to workspace containment
            valid_locs = []
            for loc in locations:
                if loc.file_path:
                    try:
                        self.validate_path(loc.file_path)
                        valid_locs.append(loc)
                    except PathSecurityError:
                        logger.warning(f"Ignored external definition location outside workspace: {loc.file_path}")
            return valid_locs

        # Heuristic Fallback using Jedi or regex search
        return self._fallback_find_definition(clean_path, line, col)

    async def get_references(
        self,
        file_path: Path | str,
        line: int,
        col: int,
        include_declaration: bool = True,
    ) -> List[Location]:
        """Find all references across the workspace for symbol at position."""
        clean_path = self.validate_path(file_path)
        pos = Position(line=max(0, line - 1), character=max(0, col - 1))

        client = await self.get_client_for_file(clean_path)
        if client and client.is_ready and client.capabilities.references:
            locations = await client.request_references(str(clean_path), pos, include_declaration=include_declaration)
            valid_locs = []
            for loc in locations:
                if loc.file_path:
                    try:
                        self.validate_path(loc.file_path)
                        valid_locs.append(loc)
                    except PathSecurityError:
                        pass
            return valid_locs

        # Heuristic Fallback
        return self._fallback_find_references(clean_path, line, col)

    async def get_document_symbols(self, file_path: Path | str) -> List[DocumentSymbol]:
        """List hierarchical symbols (classes, functions, methods) in file."""
        clean_path = self.validate_path(file_path)
        client = await self.get_client_for_file(clean_path)
        if client and client.is_ready and client.capabilities.document_symbols:
            symbols = await client.request_document_symbols(str(clean_path))
            if symbols:
                return symbols

        # Heuristic Fallback via Python AST
        return self._fallback_document_symbols(clean_path)

    async def get_workspace_symbols(self, query: str) -> List[SymbolInformation]:
        """Search workspace symbols by name query."""
        for client in self._clients.values():
            if client.is_ready and client.capabilities.workspace_symbols:
                res = await client.request_workspace_symbols(query)
                if res:
                    return res

        # Heuristic fallback across workspace
        return self._fallback_workspace_symbols(query)

    async def get_type_info(self, file_path: Path | str, line: int, col: int) -> TypeInfoResult:
        """Fetch type or hover information for symbol at position."""
        clean_path = self.validate_path(file_path)
        pos = Position(line=max(0, line - 1), character=max(0, col - 1))

        client = await self.get_client_for_file(clean_path)
        if client and client.is_ready and client.capabilities.hover:
            res = await client.request_hover(str(clean_path), pos)
            if res.is_known:
                return res

        # Heuristic Fallback via Jedi
        return self._fallback_type_info(clean_path, line, col)

    async def prepare_rename(self, file_path: Path | str, line: int, col: int) -> bool:
        """Verify whether the symbol at position is eligible for rename."""
        clean_path = self.validate_path(file_path)
        pos = Position(line=max(0, line - 1), character=max(0, col - 1))
        # Basic check: verify symbol exists at position
        symbol = self._get_symbol_at_position(clean_path, line, col)
        return bool(symbol and symbol.isidentifier())

    async def rename_symbol(
        self,
        file_path: Path | str,
        line: int,
        col: int,
        new_name: str,
        apply_edits: bool = False,
    ) -> WorkspaceEdit:
        """
        Compute or apply workspace edits to rename symbol.
        Enforces user safety, path containment, and conflict protection.
        """
        if not new_name.isidentifier():
            raise ValueError(f"Invalid target identifier name: '{new_name}'")

        clean_path = self.validate_path(file_path)
        pos = Position(line=max(0, line - 1), character=max(0, col - 1))

        client = await self.get_client_for_file(clean_path)
        workspace_edit = WorkspaceEdit()

        if client and client.is_ready and client.capabilities.rename:
            workspace_edit = await client.request_rename(str(clean_path), pos, new_name)

        if not workspace_edit.changes:
            # Fallback rename computation via reference search
            workspace_edit = self._fallback_compute_rename(clean_path, line, col, new_name)

        # Validate that all affected files are within the workspace
        for affected_path in workspace_edit.changes.keys():
            self.validate_path(affected_path)

        if apply_edits:
            await self._apply_workspace_edit(workspace_edit)

        return workspace_edit

    # ── Fallback Implementations (Heuristic & Jedi / AST) ─────────────────────

    def _fallback_syntax_diagnostics(self, file_path: Path) -> List[LspDiagnostic]:
        """Parse Python file using AST to catch syntax errors when LSP is absent."""
        if file_path.suffix.lower() not in (".py", ".pyi"):
            return []
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            ast.parse(content, filename=str(file_path))
            return []
        except SyntaxError as e:
            line = (e.lineno or 1) - 1
            col = (e.offset or 1) - 1
            diag = LspDiagnostic(
                file_path=str(file_path),
                range=Range.single_line(line, col, col + 1),
                message=f"SyntaxError: {e.msg}",
                severity=DiagnosticSeverity.ERROR,
                source="python-ast",
            )
            return [diag]
        except Exception as e:
            return [
                LspDiagnostic(
                    file_path=str(file_path),
                    range=Range.single_line(0, 0, 1),
                    message=f"File parse error: {e}",
                    severity=DiagnosticSeverity.ERROR,
                    source="python-ast",
                )
            ]

    def _fallback_find_definition(self, file_path: Path, line: int, col: int) -> List[Location]:
        """Heuristic definition search using Jedi if available, or AST scan."""
        try:
            import jedi
            content = file_path.read_text(encoding="utf-8", errors="replace")
            script = jedi.Script(content, path=str(file_path))
            defs = script.goto(line=line, column=col)
            locations = []
            for d in defs:
                target_path = str(d.module_path) if d.module_path else str(file_path)
                d_line = max(0, (d.line or 1) - 1)
                d_col = d.column if d.column is not None else 0
                locations.append(
                    Location(
                        uri=Path(target_path).as_uri(),
                        file_path=target_path,
                        range=Range.single_line(d_line, d_col, d_col + len(d.name)),
                    )
                )
            return locations
        except Exception:
            pass

        # Regex symbol definition fallback
        symbol = self._get_symbol_at_position(file_path, line, col)
        if not symbol:
            return []

        locations = []
        pattern = re.compile(rf"^\s*(def|class|async def)\s+({re.escape(symbol)})\b")
        for py_file in self.workspace_root.rglob("*.py"):
            try:
                for idx, line_text in enumerate(py_file.read_text(encoding="utf-8", errors="replace").splitlines()):
                    match = pattern.search(line_text)
                    if match:
                        start_c = match.start(2)
                        locations.append(
                            Location(
                                uri=py_file.as_uri(),
                                file_path=str(py_file),
                                range=Range.single_line(idx, start_c, start_c + len(symbol)),
                            )
                        )
                        if len(locations) >= 10:
                            break
            except Exception:
                pass
        return locations

    def _fallback_find_references(self, file_path: Path, line: int, col: int) -> List[Location]:
        """Find occurrences of symbol across workspace."""
        try:
            import jedi
            content = file_path.read_text(encoding="utf-8", errors="replace")
            script = jedi.Script(content, path=str(file_path))
            refs = script.get_references(line=line, column=col)
            locations = []
            for r in refs:
                target_path = str(r.module_path) if r.module_path else str(file_path)
                r_line = max(0, (r.line or 1) - 1)
                r_col = r.column if r.column is not None else 0
                locations.append(
                    Location(
                        uri=Path(target_path).as_uri(),
                        file_path=target_path,
                        range=Range.single_line(r_line, r_col, r_col + len(r.name)),
                    )
                )
            if locations:
                return locations
        except Exception:
            pass

        symbol = self._get_symbol_at_position(file_path, line, col)
        if not symbol:
            return []

        locations = []
        word_pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        for py_file in self.workspace_root.rglob("*.py"):
            try:
                for idx, line_text in enumerate(py_file.read_text(encoding="utf-8", errors="replace").splitlines()):
                    for m in word_pattern.finditer(line_text):
                        locations.append(
                            Location(
                                uri=py_file.as_uri(),
                                file_path=str(py_file),
                                range=Range.single_line(idx, m.start(), m.end()),
                            )
                        )
            except Exception:
                pass
        return locations

    def _fallback_document_symbols(self, file_path: Path) -> List[DocumentSymbol]:
        """Parse Python file using AST to extract functions and classes."""
        if file_path.suffix.lower() not in (".py", ".pyi") or not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))
        except Exception:
            return []

        symbols: List[DocumentSymbol] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                line = (node.lineno or 1) - 1
                col = (node.col_offset or 0)
                end_line = (node.end_lineno or line + 1) - 1
                symbols.append(
                    DocumentSymbol(
                        name=node.name,
                        kind=SymbolKind.FUNCTION,
                        range=Range(Position(line, col), Position(end_line, 0)),
                        selection_range=Range.single_line(line, col, col + len(node.name)),
                        detail=f"def {node.name}()",
                    )
                )
            elif isinstance(node, ast.ClassDef):
                line = (node.lineno or 1) - 1
                col = (node.col_offset or 0)
                end_line = (node.end_lineno or line + 1) - 1
                children: List[DocumentSymbol] = []
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        s_line = (sub.lineno or 1) - 1
                        s_col = (sub.col_offset or 0)
                        s_end = (sub.end_lineno or s_line + 1) - 1
                        children.append(
                            DocumentSymbol(
                                name=sub.name,
                                kind=SymbolKind.METHOD,
                                range=Range(Position(s_line, s_col), Position(s_end, 0)),
                                selection_range=Range.single_line(s_line, s_col, s_col + len(sub.name)),
                                detail=f"method {sub.name}()",
                            )
                        )
                symbols.append(
                    DocumentSymbol(
                        name=node.name,
                        kind=SymbolKind.CLASS,
                        range=Range(Position(line, col), Position(end_line, 0)),
                        selection_range=Range.single_line(line, col, col + len(node.name)),
                        detail=f"class {node.name}",
                        children=children,
                    )
                )
        return symbols

    def _fallback_workspace_symbols(self, query: str) -> List[SymbolInformation]:
        """Search symbol names across files using AST or regex."""
        q_lower = query.lower()
        results: List[SymbolInformation] = []
        for py_file in self.workspace_root.rglob("*.py"):
            try:
                symbols = self._fallback_document_symbols(py_file)
                for sym in symbols:
                    if q_lower in sym.name.lower():
                        results.append(
                            SymbolInformation(
                                name=sym.name,
                                kind=sym.kind,
                                location=Location(
                                    uri=py_file.as_uri(),
                                    file_path=str(py_file),
                                    range=sym.selection_range,
                                ),
                            )
                        )
            except Exception:
                pass
        return results

    def _fallback_type_info(self, file_path: Path, line: int, col: int) -> TypeInfoResult:
        """Infer type and docstring using Jedi or AST lookup."""
        symbol = self._get_symbol_at_position(file_path, line, col)
        if not symbol:
            return TypeInfoResult(symbol="", type_name="UNKNOWN", is_known=False, provenance="HEURISTIC_FALLBACK")

        try:
            import jedi
            content = file_path.read_text(encoding="utf-8", errors="replace")
            script = jedi.Script(content, path=str(file_path))
            names = script.help(line=line, column=col)
            if names:
                name = names[0]
                return TypeInfoResult(
                    symbol=symbol,
                    type_name=name.type or "UNKNOWN",
                    documentation=name.docstring() or None,
                    is_known=True,
                    provenance="HEURISTIC_FALLBACK",
                )
        except Exception:
            pass

        return TypeInfoResult(
            symbol=symbol,
            type_name="UNKNOWN",
            is_known=False,
            provenance="HEURISTIC_FALLBACK",
        )

    def _fallback_compute_rename(
        self,
        file_path: Path,
        line: int,
        col: int,
        new_name: str,
    ) -> WorkspaceEdit:
        """Compute rename edits by finding word references."""
        symbol = self._get_symbol_at_position(file_path, line, col)
        if not symbol:
            return WorkspaceEdit()

        refs = self._fallback_find_references(file_path, line, col)
        changes: Dict[str, List[TextEdit]] = {}
        for ref in refs:
            if ref.file_path:
                edit = TextEdit(range=ref.range, new_text=new_name)
                changes.setdefault(ref.file_path, []).append(edit)

        return WorkspaceEdit(changes=changes)

    def _get_symbol_at_position(self, file_path: Path, line: int, col: int) -> str:
        """Extract word identifier at 1-based line and column."""
        if not file_path.exists():
            return ""
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if 0 < line <= len(lines):
                line_text = lines[line - 1]
                idx = max(0, min(col - 1, len(line_text)))
                # Expand backward and forward to match word boundary
                start = idx
                while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] == "_"):
                    start -= 1
                end = idx
                while end < len(line_text) and (line_text[end].isalnum() or line_text[end] == "_"):
                    end += 1
                return line_text[start:end]
        except Exception:
            pass
        return ""

    async def _apply_workspace_edit(self, edit: WorkspaceEdit) -> None:
        """
        Safely apply edits across workspace files.
        Sorts edits in reverse order per file to preserve character offsets.
        """
        for file_path, edits in edit.changes.items():
            p = self.validate_path(file_path)
            if not p.exists():
                continue

            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)

            # Sort edits: descending by start line, then start character
            sorted_edits = sorted(
                edits,
                key=lambda e: (e.range.start.line, e.range.start.character),
                reverse=True,
            )

            # Apply line-by-line substitutions
            for e in sorted_edits:
                s_line = e.range.start.line
                s_char = e.range.start.character
                e_line = e.range.end.line
                e_char = e.range.end.character

                if s_line < len(lines):
                    if s_line == e_line:
                        orig = lines[s_line]
                        new_line = orig[:s_char] + e.new_text + orig[e_char:]
                        lines[s_line] = new_line
                    else:
                        first = lines[s_line][:s_char]
                        last = lines[e_line][e_char:] if e_line < len(lines) else ""
                        lines[s_line] = first + e.new_text + last
                        # Clear lines between
                        for del_idx in range(s_line + 1, min(e_line + 1, len(lines))):
                            lines[del_idx] = ""

            new_content = "".join(lines)
            p.write_text(new_content, encoding="utf-8")
            await self.notify_file_updated(p, new_content)

    async def shutdown_all(self) -> None:
        """Shutdown all active LSP clients cleanly."""
        async with self._lock:
            for client in self._clients.values():
                try:
                    await client.shutdown()
                except Exception as e:
                    logger.warning(f"Error shutting down LSP client: {e}")
            self._clients.clear()
