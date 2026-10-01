# core/code_intelligence/client.py
"""
LSP Client for Language Server Protocol (LSP 3.17).
Handles initialization handshake, capability negotiation, document syncing,
semantic requests, incoming diagnostics, and crash recovery.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from core.code_intelligence.models import (
    DiagnosticSeverity,
    DocumentSymbol,
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
from core.code_intelligence.transport import (
    LspConnectionClosedError,
    LspTimeoutError,
    LspTransportError,
    StdioLspTransport,
)

logger = logging.getLogger("hermes.code_intelligence.client")


class LspClient:
    """Manages an active LSP server process and protocol interaction."""

    def __init__(
        self,
        command: List[str],
        workspace_root: Path,
        language_id: str,
        initialization_options: Optional[Dict[str, Any]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.command = command
        self.workspace_root = workspace_root.resolve()
        self.language_id = language_id
        self.initialization_options = initialization_options or {}
        self.env = env

        self.transport = StdioLspTransport(
            command=self.command,
            cwd=str(self.workspace_root),
            env=self.env,
        )

        self.status = ServerStatus.DISCOVERED
        self.capabilities = ServerCapabilities()
        self._diagnostics: Dict[str, List[LspDiagnostic]] = {}
        self._open_documents: Set[str] = set()
        self._document_versions: Dict[str, int] = {}
        self._init_lock = asyncio.Lock()
        self._crash_count: int = 0
        self.max_crashes: int = 3

    @property
    def is_ready(self) -> bool:
        return self.status == ServerStatus.READY and self.transport.is_running

    async def start_and_initialize(self, timeout: float = 15.0) -> bool:
        """Start the server process and complete the initialize/initialized handshake."""
        async with self._init_lock:
            if self.is_ready:
                return True

            self.status = ServerStatus.STARTING
            try:
                await self.transport.start()
                self.transport.register_notification_handler(
                    "textDocument/publishDiagnostics",
                    self._handle_publish_diagnostics,
                )

                # Send initialize request
                root_uri = self._path_to_uri(str(self.workspace_root))
                client_caps = {
                    "textDocument": {
                        "synchronization": {"dynamicRegistration": False, "willSave": False, "willSaveWaitUntil": False, "didSave": True},
                        "publishDiagnostics": {"relatedInformation": True, "versionSupport": True},
                        "definition": {"dynamicRegistration": False, "linkSupport": True},
                        "references": {"dynamicRegistration": False},
                        "documentSymbol": {"dynamicRegistration": False, "hierarchicalDocumentSymbolSupport": True},
                        "hover": {"dynamicRegistration": False, "contentFormat": ["markdown", "plaintext"]},
                        "rename": {"dynamicRegistration": False, "prepareSupport": True},
                    },
                    "workspace": {
                        "symbol": {"dynamicRegistration": False},
                        "workspaceEdit": {"documentChanges": True},
                    },
                }

                params = {
                    "processId": None,
                    "rootPath": str(self.workspace_root),
                    "rootUri": root_uri,
                    "capabilities": client_caps,
                    "initializationOptions": self.initialization_options,
                    "trace": "off",
                }

                init_result = await self.transport.send_request("initialize", params, timeout=timeout)
                if init_result:
                    self.capabilities = ServerCapabilities.from_initialize_result(init_result)

                # Send initialized notification
                await self.transport.send_notification("initialized", {})
                self.status = ServerStatus.READY
                logger.info(f"LSP server for '{self.language_id}' ready | capabilities: {self.capabilities}")
                return True

            except Exception as e:
                self.status = ServerStatus.FAILED
                logger.error(f"LSP initialization failed for '{self.language_id}': {e}")
                await self.shutdown()
                return False

    async def notify_did_open(self, file_path: str, content: str) -> None:
        """Notify language server that a document was opened."""
        if not self.is_ready:
            return
        uri = self._path_to_uri(file_path)
        version = self._document_versions.get(uri, 1)
        self._document_versions[uri] = version
        self._open_documents.add(uri)

        params = {
            "textDocument": {
                "uri": uri,
                "languageId": self.language_id,
                "version": version,
                "text": content,
            }
        }
        try:
            await self.transport.send_notification("textDocument/didOpen", params)
        except Exception as e:
            logger.warning(f"LSP didOpen failed: {e}")

    async def notify_did_change(self, file_path: str, content: str) -> None:
        """Notify language server that document content was updated."""
        if not self.is_ready:
            return
        uri = self._path_to_uri(file_path)
        version = self._document_versions.get(uri, 0) + 1
        self._document_versions[uri] = version

        params = {
            "textDocument": {
                "uri": uri,
                "version": version,
            },
            "contentChanges": [{"text": content}],
        }
        try:
            await self.transport.send_notification("textDocument/didChange", params)
        except Exception as e:
            logger.warning(f"LSP didChange failed: {e}")

    async def notify_did_close(self, file_path: str) -> None:
        """Notify language server that a document was closed."""
        if not self.is_ready:
            return
        uri = self._path_to_uri(file_path)
        if uri in self._open_documents:
            self._open_documents.remove(uri)
            try:
                await self.transport.send_notification("textDocument/didClose", {"textDocument": {"uri": uri}})
            except Exception:
                pass

    def get_diagnostics(self, file_path: str) -> List[LspDiagnostic]:
        """Retrieve stored diagnostics for a file."""
        uri = self._path_to_uri(file_path)
        return list(self._diagnostics.get(uri, []))

    def get_all_diagnostics(self) -> Dict[str, List[LspDiagnostic]]:
        """Retrieve all currently reported diagnostics across files."""
        return dict(self._diagnostics)

    async def request_definition(self, file_path: str, position: Position, timeout: float = 10.0) -> List[Location]:
        """Query definition location(s) for symbol at given position."""
        if not self.is_ready:
            return []
        uri = self._path_to_uri(file_path)
        params = {
            "textDocument": {"uri": uri},
            "position": position.to_lsp(),
        }
        try:
            res = await self.transport.send_request("textDocument/definition", params, timeout=timeout)
        except Exception as e:
            logger.warning(f"LSP definition request failed: {e}")
            return []

        if not res:
            return []
        if isinstance(res, dict):
            res = [res]

        locations: List[Location] = []
        for item in res:
            try:
                loc = Location.from_lsp(item, self.workspace_root)
                locations.append(loc)
            except Exception:
                pass
        return locations

    async def request_references(
        self,
        file_path: str,
        position: Position,
        include_declaration: bool = True,
        timeout: float = 10.0,
    ) -> List[Location]:
        """Find references to symbol across workspace."""
        if not self.is_ready:
            return []
        uri = self._path_to_uri(file_path)
        params = {
            "textDocument": {"uri": uri},
            "position": position.to_lsp(),
            "context": {"includeDeclaration": include_declaration},
        }
        try:
            res = await self.transport.send_request("textDocument/references", params, timeout=timeout)
        except Exception as e:
            logger.warning(f"LSP references request failed: {e}")
            return []

        if not isinstance(res, list):
            return []

        locations: List[Location] = []
        for item in res:
            try:
                loc = Location.from_lsp(item, self.workspace_root)
                locations.append(loc)
            except Exception:
                pass
        return locations

    async def request_document_symbols(self, file_path: str, timeout: float = 10.0) -> List[DocumentSymbol]:
        """Fetch hierarchical symbols for a file."""
        if not self.is_ready:
            return []
        uri = self._path_to_uri(file_path)
        params = {"textDocument": {"uri": uri}}
        try:
            res = await self.transport.send_request("textDocument/documentSymbol", params, timeout=timeout)
        except Exception as e:
            logger.warning(f"LSP documentSymbol request failed: {e}")
            return []

        if not isinstance(res, list):
            return []

        def parse_symbol(item: Dict[str, Any]) -> DocumentSymbol:
            children = [parse_symbol(c) for c in item.get("children", [])]
            return DocumentSymbol(
                name=str(item.get("name", "")),
                kind=SymbolKind.from_wire(item.get("kind", 13)),
                range=Range.from_lsp(item.get("range", {})),
                selection_range=Range.from_lsp(item.get("selectionRange", item.get("range", {}))),
                detail=item.get("detail"),
                children=children,
            )

        symbols: List[DocumentSymbol] = []
        for item in res:
            try:
                symbols.append(parse_symbol(item))
            except Exception:
                pass
        return symbols

    async def request_workspace_symbols(self, query: str, timeout: float = 10.0) -> List[SymbolInformation]:
        """Search workspace symbols matching query."""
        if not self.is_ready:
            return []
        params = {"query": query}
        try:
            res = await self.transport.send_request("workspace/symbol", params, timeout=timeout)
        except Exception as e:
            logger.warning(f"LSP workspace/symbol request failed: {e}")
            return []

        if not isinstance(res, list):
            return []

        symbols: List[SymbolInformation] = []
        for item in res:
            try:
                loc = Location.from_lsp(item.get("location", {}), self.workspace_root)
                symbols.append(
                    SymbolInformation(
                        name=str(item.get("name", "")),
                        kind=SymbolKind.from_wire(item.get("kind", 13)),
                        location=loc,
                        container_name=item.get("containerName"),
                    )
                )
            except Exception:
                pass
        return symbols

    async def request_hover(self, file_path: str, position: Position, timeout: float = 5.0) -> TypeInfoResult:
        """Fetch hover / type information for symbol at position."""
        if not self.is_ready:
            return TypeInfoResult(symbol="", type_name="UNKNOWN", is_known=False)
        uri = self._path_to_uri(file_path)
        params = {"textDocument": {"uri": uri}, "position": position.to_lsp()}
        try:
            res = await self.transport.send_request("textDocument/hover", params, timeout=timeout)
        except Exception as e:
            logger.warning(f"LSP hover request failed: {e}")
            return TypeInfoResult(symbol="", type_name="UNKNOWN", is_known=False)

        if not res or not isinstance(res, dict):
            return TypeInfoResult(symbol="", type_name="UNKNOWN", is_known=False)

        contents = res.get("contents", "")
        doc_text = ""
        type_str = "UNKNOWN"

        if isinstance(contents, str):
            doc_text = contents
        elif isinstance(contents, dict) and "value" in contents:
            doc_text = str(contents["value"])
        elif isinstance(contents, list):
            doc_text = "\n".join(str(c.get("value", c) if isinstance(c, dict) else c) for c in contents)

        # Heuristic parse of first markdown code fence as type signature
        lines = doc_text.strip().splitlines()
        for line in lines:
            cleaned = line.strip().strip("`")
            if cleaned and not cleaned.startswith("#") and not cleaned.startswith("```"):
                type_str = cleaned
                break

        return TypeInfoResult(
            symbol="",
            type_name=type_str if type_str != "UNKNOWN" else (doc_text[:100] if doc_text else "UNKNOWN"),
            documentation=doc_text if doc_text else None,
            is_known=bool(doc_text),
            provenance="SEMANTIC_LSP",
        )

    async def request_rename(
        self,
        file_path: str,
        position: Position,
        new_name: str,
        timeout: float = 10.0,
    ) -> WorkspaceEdit:
        """Request workspace edits to rename symbol."""
        if not self.is_ready:
            return WorkspaceEdit()
        uri = self._path_to_uri(file_path)
        params = {
            "textDocument": {"uri": uri},
            "position": position.to_lsp(),
            "newName": new_name,
        }
        try:
            res = await self.transport.send_request("textDocument/rename", params, timeout=timeout)
        except Exception as e:
            logger.warning(f"LSP rename request failed: {e}")
            return WorkspaceEdit()

        if not res or not isinstance(res, dict):
            return WorkspaceEdit()

        return self._parse_workspace_edit(res)

    def _parse_workspace_edit(self, data: Dict[str, Any]) -> WorkspaceEdit:
        """Convert LSP WorkspaceEdit structure to internal model."""
        changes: Dict[str, List[TextEdit]] = {}

        # 1. Normal changes dict { uri: [TextEdit] }
        raw_changes = data.get("changes", {})
        for uri, edits in raw_changes.items():
            path_str = self._uri_to_path(uri)
            change_list = changes.setdefault(path_str, [])
            for e in edits:
                try:
                    change_list.append(TextEdit(range=Range.from_lsp(e.get("range", {})), new_text=e.get("newText", "")))
                except Exception:
                    pass

        # 2. DocumentChanges list
        doc_changes = data.get("documentChanges", [])
        for doc_edit in doc_changes:
            if isinstance(doc_edit, dict) and "textDocument" in doc_edit:
                uri = doc_edit["textDocument"].get("uri", "")
                path_str = self._uri_to_path(uri)
                change_list = changes.setdefault(path_str, [])
                for e in doc_edit.get("edits", []):
                    try:
                        change_list.append(TextEdit(range=Range.from_lsp(e.get("range", {})), new_text=e.get("newText", "")))
                    except Exception:
                        pass

        return WorkspaceEdit(changes=changes)

    def _handle_publish_diagnostics(self, notification: Dict[str, Any]) -> None:
        """Callback for incoming diagnostics push from server."""
        params = notification.get("params", {})
        uri = params.get("uri", "")
        raw_diags = params.get("diagnostics", [])
        file_path = self._uri_to_path(uri)

        parsed_diags: List[LspDiagnostic] = []
        for item in raw_diags:
            try:
                parsed_diags.append(
                    LspDiagnostic(
                        file_path=file_path,
                        range=Range.from_lsp(item.get("range", {})),
                        message=str(item.get("message", "")),
                        severity=DiagnosticSeverity.from_wire(item.get("severity", 1)),
                        code=str(item.get("code")) if item.get("code") is not None else None,
                        source=item.get("source"),
                        related_information=item.get("relatedInformation", []),
                    )
                )
            except Exception as e:
                logger.debug(f"Error parsing diagnostic: {e}")

        self._diagnostics[uri] = parsed_diags

    def _path_to_uri(self, path_str: str) -> str:
        """Convert local path to standard file:// URI."""
        p = Path(path_str).resolve()
        return p.as_uri()

    def _uri_to_path(self, uri: str) -> str:
        """Convert file:// URI back to resolved filesystem path."""
        if uri.startswith("file:///"):
            part = uri[8:] if uri.startswith("file:////") else uri[7:]
            if part.startswith("/") and len(part) > 2 and part[2] == ":":
                part = part[1:]
            return str(Path(part).resolve())
        elif uri.startswith("file://"):
            return str(Path(uri[7:]).resolve())
        return uri

    async def shutdown(self) -> None:
        """Gracefully shut down and exit server."""
        self.status = ServerStatus.STOPPED
        try:
            if self.transport.is_running:
                await self.transport.send_request("shutdown", {}, timeout=2.0)
                await self.transport.send_notification("exit", {})
        except Exception:
            pass
        finally:
            await self.transport.close()
