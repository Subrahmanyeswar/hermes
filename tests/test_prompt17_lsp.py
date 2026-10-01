# tests/test_prompt17_lsp.py
"""
Test Suite: Prompt 17 Code Intelligence & LSP Subsystem.
Tests transport framing, models, security containment, language registry,
manager diagnostics/navigation/symbols/rename, and BaseTool adapters.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.code_intelligence.client import LspClient
from core.code_intelligence.manager import CodeIntelligenceManager, PathSecurityError
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
from core.code_intelligence.registry import LspServerDefinition, LspServerRegistry
from core.code_intelligence.tools import (
    LspDefinitionTool,
    LspDiagnosticsTool,
    LspReferencesTool,
    LspRenameTool,
    LspSymbolsTool,
    LspTypeInfoTool,
)
from core.code_intelligence.transport import StdioLspTransport


def test_lsp_models_positions_and_ranges():
    """Verify Position, Range, and Location conversion and human indexing."""
    pos1 = Position(line=4, character=10)
    assert pos1.human_line == 5
    assert pos1.human_col == 11
    assert pos1.to_lsp() == {"line": 4, "character": 10}

    rg = Range(start=pos1, end=Position(line=4, character=15))
    assert rg.to_lsp() == {
        "start": {"line": 4, "character": 10},
        "end": {"line": 4, "character": 15},
    }

    loc = Location(uri="file:///test.py", range=rg, file_path="/test.py")
    d = loc.to_dict()
    assert d["line"] == 5
    assert d["col"] == 11
    assert d["file_path"] == "/test.py"


def test_lsp_diagnostic_models():
    """Verify diagnostic severity mapping and dictionary representation."""
    diag = LspDiagnostic(
        file_path="src/app.py",
        range=Range.single_line(9, 4, 12),
        message="Unused variable 'x'",
        severity=DiagnosticSeverity.WARNING,
        source="ruff",
    )
    assert not diag.is_error
    d = diag.to_dict()
    assert d["line"] == 10
    assert d["column"] == 5
    assert d["severity"] == "WARNING"
    assert d["message"] == "Unused variable 'x'"


def test_lsp_registry_extension_mapping():
    """Verify registry resolves language servers by file extension."""
    registry = LspServerRegistry()
    py_srv = registry.get_server_for_file("main.py")
    assert py_srv is not None
    assert py_srv.language_id == "python"

    ts_srv = registry.get_server_for_file("components/App.tsx")
    assert ts_srv is not None
    assert ts_srv.language_id == "typescript"

    html_srv = registry.get_server_for_file("templates/index.html")
    assert html_srv is not None
    assert html_srv.language_id == "html"

    unknown = registry.get_server_for_file("data.xyz_unknown")
    assert unknown is None


def test_manager_path_security_containment(tmp_path: Path):
    """Verify CodeIntelligenceManager strictly rejects path traversal and breakouts."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    secret_file = secret_dir / "keys.env"
    secret_file.write_text("API_SECRET=123", encoding="utf-8")

    mgr = CodeIntelligenceManager(workspace_root=workspace)

    # Valid relative file inside workspace
    valid_file = workspace / "src" / "test.py"
    valid_file.parent.mkdir(parents=True)
    valid_file.write_text("x = 1", encoding="utf-8")
    assert mgr.validate_path("src/test.py") == valid_file.resolve()

    # Traversal breakout
    with pytest.raises(PathSecurityError):
        mgr.validate_path("../../secret/keys.env")

    # Absolute path breakout
    with pytest.raises(PathSecurityError):
        mgr.validate_path(secret_file)


@pytest.mark.asyncio
async def test_manager_syntax_diagnostics_and_symbols(tmp_path: Path):
    """Verify fallback Python syntax diagnostics and AST document symbol discovery."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # 1. Clean file
    good_file = workspace / "good.py"
    good_file.write_text(
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n\n"
        "def main():\n"
        "    c = Calculator()\n"
        "    return c.add(1, 2)\n",
        encoding="utf-8",
    )

    mgr = CodeIntelligenceManager(workspace_root=workspace, enable_lsp=False)
    diags = await mgr.get_diagnostics(good_file)
    assert len(diags) == 0

    symbols = await mgr.get_document_symbols(good_file)
    assert len(symbols) == 2
    assert symbols[0].name == "Calculator"
    assert symbols[0].kind == SymbolKind.CLASS
    assert len(symbols[0].children) == 1
    assert symbols[0].children[0].name == "add"
    assert symbols[1].name == "main"

    # 2. Syntax error file
    bad_file = workspace / "bad.py"
    bad_file.write_text("def broken_syntax(\n    return 42\n", encoding="utf-8")
    bad_diags = await mgr.get_diagnostics(bad_file)
    assert len(bad_diags) == 1
    assert bad_diags[0].is_error
    assert "SyntaxError" in bad_diags[0].message


@pytest.mark.asyncio
async def test_manager_definitions_and_references(tmp_path: Path):
    """Verify definition jumping and reference resolution."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    calc_file = workspace / "calc.py"
    calc_file.write_text(
        "def multiply_numbers(a, b):\n"
        "    return a * b\n\n"
        "val = multiply_numbers(2, 3)\n",
        encoding="utf-8",
    )

    mgr = CodeIntelligenceManager(workspace_root=workspace, enable_lsp=False)

    # Search definition of multiply_numbers from call site (line 4, col 8)
    defs = await mgr.get_definition(calc_file, line=4, col=8)
    assert len(defs) > 0
    assert any(d.range.start.human_line == 1 for d in defs)

    # Search references
    refs = await mgr.get_references(calc_file, line=1, col=5)
    assert len(refs) >= 2  # definition and call site


@pytest.mark.asyncio
async def test_manager_rename_symbol(tmp_path: Path):
    """Verify rename computation and multi-file edit application."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    f1 = workspace / "module.py"
    f1.write_text("old_function = 42\nx = old_function + 1\n", encoding="utf-8")

    mgr = CodeIntelligenceManager(workspace_root=workspace, enable_lsp=False)

    # Preview rename
    preview = await mgr.rename_symbol(f1, line=1, col=2, new_name="new_function", apply_edits=False)
    assert preview.total_edits == 2
    assert str(f1) in preview.changes

    # Content unchanged after preview
    assert "old_function" in f1.read_text(encoding="utf-8")

    # Apply rename
    applied = await mgr.rename_symbol(f1, line=1, col=2, new_name="new_function", apply_edits=True)
    assert applied.total_edits == 2

    # Content updated
    updated_content = f1.read_text(encoding="utf-8")
    assert "old_function" not in updated_content
    assert "new_function = 42" in updated_content
    assert "x = new_function + 1" in updated_content


def test_lsp_tools_execution(tmp_path: Path):
    """Verify BaseTool adapters execute and return structured ToolResult."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sample = workspace / "sample.py"
    sample.write_text(
        "def greet(name: str) -> str:\n"
        "    '''Greet user.'''\n"
        "    return f'Hello {name}'\n",
        encoding="utf-8",
    )

    mgr = CodeIntelligenceManager(workspace_root=workspace, enable_lsp=False)

    # 1. Diagnostics Tool
    diag_tool = LspDiagnosticsTool(manager=mgr)
    res_diag = diag_tool.execute({"file_path": str(sample)})
    assert res_diag.success
    assert "No diagnostics/errors found" in res_diag.output

    # 2. Symbols Tool
    sym_tool = LspSymbolsTool(manager=mgr)
    res_sym = sym_tool.execute({"file_path": str(sample)})
    assert res_sym.success
    assert "greet" in res_sym.output

    # 3. Type Info Tool
    type_tool = LspTypeInfoTool(manager=mgr)
    res_type = type_tool.execute({"file_path": str(sample), "line": 1, "col": 5})
    assert res_type.success

    # 4. Definition Tool
    def_tool = LspDefinitionTool(manager=mgr)
    res_def = def_tool.execute({"file_path": str(sample), "line": 1, "col": 5})
    assert res_def.success

    # 5. References Tool
    ref_tool = LspReferencesTool(manager=mgr)
    res_ref = ref_tool.execute({"file_path": str(sample), "line": 1, "col": 5})
    assert res_ref.success

    # 6. Rename Tool
    rename_tool = LspRenameTool(manager=mgr)
    res_rename = rename_tool.execute({
        "file_path": str(sample),
        "line": 1,
        "col": 5,
        "new_name": "welcome_user",
        "apply": True,
    })
    assert res_rename.success
    assert "Applied rename to 'welcome_user'" in res_rename.output
    assert "welcome_user" in sample.read_text(encoding="utf-8")
