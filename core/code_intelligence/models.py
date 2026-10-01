# core/code_intelligence/models.py
"""
Data models and representations for Code Intelligence & LSP Subsystem (Prompt 17).
Adheres to Language Server Protocol 3.17 conventions while providing
strongly-typed internal abstractions for HERMES.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class DiagnosticSeverity(int, Enum):
    """LSP DiagnosticSeverity values (1-4)."""
    ERROR = 1
    WARNING = 2
    INFO = 3
    HINT = 4

    @classmethod
    def from_wire(cls, value: int) -> DiagnosticSeverity:
        try:
            return cls(value)
        except ValueError:
            return cls.ERROR

    @property
    def label(self) -> str:
        return self.name.lower()


class SymbolKind(int, Enum):
    """LSP SymbolKind enumeration."""
    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUM_MEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPE_PARAMETER = 26

    @classmethod
    def from_wire(cls, value: int) -> SymbolKind:
        try:
            return cls(value)
        except ValueError:
            return cls.VARIABLE

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Position:
    """Zero-based line and character position within a document."""
    line: int
    character: int

    def to_lsp(self) -> Dict[str, int]:
        return {"line": self.line, "character": self.character}

    @classmethod
    def from_lsp(cls, data: Dict[str, Any]) -> Position:
        return cls(line=int(data.get("line", 0)), character=int(data.get("character", 0)))

    @property
    def human_line(self) -> int:
        """1-based line number for user displays."""
        return self.line + 1

    @property
    def human_col(self) -> int:
        """1-based column number for user displays."""
        return self.character + 1


@dataclass(frozen=True)
class Range:
    """A range in a text document expressed as (start, end) positions."""
    start: Position
    end: Position

    def to_lsp(self) -> Dict[str, Any]:
        return {"start": self.start.to_lsp(), "end": self.end.to_lsp()}

    @classmethod
    def from_lsp(cls, data: Dict[str, Any]) -> Range:
        return cls(
            start=Position.from_lsp(data.get("start", {})),
            end=Position.from_lsp(data.get("end", {})),
        )

    @classmethod
    def single_line(cls, line: int, start_char: int, end_char: int) -> Range:
        return cls(start=Position(line, start_char), end=Position(line, end_char))


@dataclass
class Location:
    """Represents a location inside a resource, such as a line inside a text file."""
    uri: str
    range: Range
    file_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uri": self.uri,
            "file_path": self.file_path or self.uri,
            "range": {
                "start": {"line": self.range.start.line, "character": self.range.start.character},
                "end": {"line": self.range.end.line, "character": self.range.end.character},
            },
            "line": self.range.start.human_line,
            "col": self.range.start.human_col,
        }

    @classmethod
    def from_lsp(cls, data: Dict[str, Any], workspace_root: Optional[Path] = None) -> Location:
        uri = data.get("uri", "")
        rg = Range.from_lsp(data.get("range", {}))
        file_path = None
        if uri.startswith("file:///"):
            # strip file:/// schema
            path_part = uri[8:] if uri.startswith("file:////") else uri[7:]
            if path_part.startswith("/") and len(path_part) > 2 and path_part[2] == ":":
                path_part = path_part[1:]  # /C:/path -> C:/path on Windows
            file_path = str(Path(path_part).resolve())
        elif uri.startswith("file://"):
            file_path = str(Path(uri[7:]).resolve())
        return cls(uri=uri, range=rg, file_path=file_path)


@dataclass
class LspDiagnostic:
    """Represents a diagnostic, such as a compiler error or warning."""
    file_path: str
    range: Range
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    code: Optional[str] = None
    source: Optional[str] = None
    related_information: List[Dict[str, Any]] = field(default_factory=list)
    generation: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line": self.range.start.human_line,
            "column": self.range.start.human_col,
            "end_line": self.range.end.human_line,
            "end_column": self.range.end.human_col,
            "severity": self.severity.name,
            "message": self.message,
            "code": self.code,
            "source": self.source,
            "generation": self.generation,
        }

    @property
    def is_error(self) -> bool:
        return self.severity == DiagnosticSeverity.ERROR


@dataclass
class DocumentSymbol:
    """Represents programming constructs like variables, functions, classes in a file."""
    name: str
    kind: SymbolKind
    range: Range
    selection_range: Range
    detail: Optional[str] = None
    children: List[DocumentSymbol] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.label,
            "detail": self.detail,
            "line": self.range.start.human_line,
            "col": self.range.start.human_col,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class SymbolInformation:
    """Represents information about programming constructs identified in the workspace."""
    name: str
    kind: SymbolKind
    location: Location
    container_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.label,
            "container": self.container_name,
            "location": self.location.to_dict(),
        }


@dataclass
class TypeInfoResult:
    """Semantic type or hover information for a symbol."""
    symbol: str
    type_name: str
    documentation: Optional[str] = None
    location: Optional[Location] = None
    is_known: bool = True
    provenance: str = "SEMANTIC_LSP"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "type": self.type_name,
            "documentation": self.documentation,
            "is_known": self.is_known,
            "provenance": self.provenance,
            "location": self.location.to_dict() if self.location else None,
        }


@dataclass
class TextEdit:
    """A text edit applicable to a text document."""
    range: Range
    new_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "range": {
                "start": {"line": self.range.start.line, "character": self.range.start.character},
                "end": {"line": self.range.end.line, "character": self.range.end.character},
            },
            "new_text": self.new_text,
        }


@dataclass
class WorkspaceEdit:
    """A workspace edit represents changes to many resources managed in the workspace."""
    changes: Dict[str, List[TextEdit]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            path: [e.to_dict() for e in edits]
            for path, edits in self.changes.items()
        }

    @property
    def affected_files(self) -> List[str]:
        return list(self.changes.keys())

    @property
    def total_edits(self) -> int:
        return sum(len(edits) for edits in self.changes.values())


@dataclass
class ServerCapabilities:
    """Advertised capabilities negotiated with an LSP server."""
    diagnostics: bool = False
    definition: bool = False
    references: bool = False
    document_symbols: bool = False
    workspace_symbols: bool = False
    hover: bool = False
    rename: bool = False
    completion: bool = False

    @classmethod
    def from_initialize_result(cls, result: Dict[str, Any]) -> ServerCapabilities:
        caps = result.get("capabilities", {})
        return cls(
            diagnostics=True,  # Most servers push diagnostics via publishDiagnostics
            definition=bool(caps.get("definitionProvider")),
            references=bool(caps.get("referencesProvider")),
            document_symbols=bool(caps.get("documentSymbolProvider")),
            workspace_symbols=bool(caps.get("workspaceSymbolProvider")),
            hover=bool(caps.get("hoverProvider")),
            rename=bool(caps.get("renameProvider")),
            completion=bool(caps.get("completionProvider")),
        )


class ServerStatus(str, Enum):
    """Lifecycle status of a language server process."""
    DISCOVERED = "DISCOVERED"
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    CRASHED = "CRASHED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class IntelligenceProvenance(str, Enum):
    """Provenance tracking distinguishing genuine LSP results from fallbacks."""
    SEMANTIC_LSP = "SEMANTIC_LSP"
    HEURISTIC_FALLBACK = "HEURISTIC_FALLBACK"
    CACHE = "CACHE"
