# core/code_intelligence/registry.py
"""
LSP Server Registry for HERMES 2.x (Prompt 17).
Maintains language server definitions, extension mappings,
and capability discovery rules.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class LspServerDefinition:
    """Configuration for a specific language server."""
    language_id: str
    extensions: List[str]
    command: List[str]
    args: List[str] = field(default_factory=list)
    initialization_options: Dict[str, Any] = field(default_factory=dict)
    env_overrides: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @property
    def full_command(self) -> List[str]:
        return self.command + self.args

    def is_available(self) -> bool:
        """Check if the server executable is actually present on PATH or filesystem."""
        if not self.command:
            return False
        binary = self.command[0]
        # Handle python module invocations
        if binary == sys.executable:
            return True
        return shutil.which(binary) is not None


class LspServerRegistry:
    """Registry mapping file types to language servers."""

    def __init__(self) -> None:
        self._servers: Dict[str, LspServerDefinition] = {}
        self._extension_map: Dict[str, str] = {}
        self._register_default_servers()

    def _register_default_servers(self) -> None:
        """Register canonical language server configurations."""
        # 1. Python — ruff server (default on modern systems)
        self.register(
            LspServerDefinition(
                language_id="python",
                extensions=[".py", ".pyi"],
                command=["ruff", "server", "--preview"],
            )
        )

        # 2. TypeScript / JavaScript
        self.register(
            LspServerDefinition(
                language_id="typescript",
                extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"],
                command=["typescript-language-server", "--stdio"],
            )
        )

        # 3. JSON
        self.register(
            LspServerDefinition(
                language_id="json",
                extensions=[".json", ".jsonc"],
                command=["vscode-json-language-server", "--stdio"],
            )
        )

        # 4. HTML
        self.register(
            LspServerDefinition(
                language_id="html",
                extensions=[".html", ".htm"],
                command=["vscode-html-language-server", "--stdio"],
            )
        )

        # 5. CSS
        self.register(
            LspServerDefinition(
                language_id="css",
                extensions=[".css", ".scss", ".less"],
                command=["vscode-css-language-server", "--stdio"],
            )
        )

    def register(self, definition: LspServerDefinition) -> None:
        """Register a server definition and update its extension associations."""
        self._servers[definition.language_id] = definition
        for ext in definition.extensions:
            norm_ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            self._extension_map[norm_ext] = definition.language_id

    def get_server_for_file(self, file_path: Path | str) -> Optional[LspServerDefinition]:
        """Find the matching language server definition for a file path."""
        p = Path(file_path)
        ext = p.suffix.lower()
        lang_id = self._extension_map.get(ext)
        if not lang_id:
            return None
        server = self._servers.get(lang_id)
        if server and server.enabled:
            return server
        return None

    def get_server_for_language(self, language_id: str) -> Optional[LspServerDefinition]:
        return self._servers.get(language_id.lower())

    def list_available_servers(self) -> List[Dict[str, Any]]:
        """List registered servers along with their availability status."""
        result = []
        for lang_id, server in self._servers.items():
            result.append({
                "language_id": lang_id,
                "command": server.full_command,
                "extensions": server.extensions,
                "available": server.is_available(),
                "enabled": server.enabled,
            })
        return result


# Global default registry
lsp_registry = LspServerRegistry()
