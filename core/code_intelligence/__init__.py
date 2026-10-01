# core/code_intelligence/__init__.py
"""
Code Intelligence & LSP Subsystem for HERMES 2.x (Prompt 17).
"""

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
from core.code_intelligence.transport import (
    LspConnectionClosedError,
    LspTimeoutError,
    LspTransportError,
    StdioLspTransport,
)
from core.code_intelligence.registry import (
    LspServerDefinition,
    LspServerRegistry,
    lsp_registry,
)
from core.code_intelligence.client import LspClient
from core.code_intelligence.manager import (
    CodeIntelligenceManager,
    PathSecurityError,
)
from core.code_intelligence.tools import (
    LspDefinitionTool,
    LspDiagnosticsTool,
    LspReferencesTool,
    LspRenameTool,
    LspSymbolsTool,
    LspTypeInfoTool,
)

__all__ = [
    "DiagnosticSeverity",
    "DocumentSymbol",
    "IntelligenceProvenance",
    "Location",
    "LspDiagnostic",
    "Position",
    "Range",
    "ServerCapabilities",
    "ServerStatus",
    "SymbolInformation",
    "SymbolKind",
    "TextEdit",
    "TypeInfoResult",
    "WorkspaceEdit",
    "LspConnectionClosedError",
    "LspTimeoutError",
    "LspTransportError",
    "StdioLspTransport",
    "LspServerDefinition",
    "LspServerRegistry",
    "lsp_registry",
    "LspClient",
    "CodeIntelligenceManager",
    "PathSecurityError",
    "LspDefinitionTool",
    "LspDiagnosticsTool",
    "LspReferencesTool",
    "LspRenameTool",
    "LspSymbolsTool",
    "LspTypeInfoTool",
]
