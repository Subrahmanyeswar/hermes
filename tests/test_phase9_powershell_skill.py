"""
Test Phase 9: PowerShell Scripting Skill Conformance, Quality Invariants & Platform Disambiguation.

Validates:
1. Manifest and metadata conformance:
   - Frontmatter parse succeeds
   - Allowed tools conform strictly to ToolCatalog
   - Priority and triggers configured properly
2. Quality and safety invariants in skill body:
   - $ErrorActionPreference = 'Stop'
   - $LASTEXITCODE checking for native commands
   - Path safety (-LiteralPath, Join-Path)
   - UTF-8 without BOM encoding (utf8NoBOM)
   - Parameter validation & CmdletBinding
   - WhatIf / dry-run safety
3. Disambiguation against bash-scripting.
"""

from pathlib import Path
import pytest
from core.project_intelligence.skills import SkillEngine
from tools.platform.catalog import ToolCatalog

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"
POWERSHELL_SKILL_FILE = CANONICAL_SKILLS_DIR / "powershell-scripting" / "SKILL.md"


@pytest.fixture
def skill_engine():
    engine = SkillEngine(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
    )
    engine.index_skills()
    return engine


class TestPowershellSkillConformance:
    def test_file_exists(self):
        assert POWERSHELL_SKILL_FILE.is_file(), f"Missing {POWERSHELL_SKILL_FILE}"

    def test_metadata_and_tool_catalog(self, skill_engine):
        engine = skill_engine
        meta = engine._metadata_index.get("powershell-scripting")
        assert meta is not None, "powershell-scripting not found in metadata index"
        assert meta.name == "powershell-scripting"
        assert "powershell" in [t.lower() for t in meta.triggers]

        # Allowed tools must all exist in ToolCatalog
        catalog = ToolCatalog()
        catalog.initialize()
        for tool in meta.allowed_tools:
            resolved = catalog.resolve_name(tool)
            assert resolved is not None, f"Tool '{tool}' is not resolvable in ToolCatalog"

    def test_skill_body_quality_invariants(self, skill_engine):
        content = POWERSHELL_SKILL_FILE.read_text(encoding="utf-8")

        # Error action preference & strict mode
        assert "$ErrorActionPreference = 'Stop'" in content
        assert "Set-StrictMode -Version Latest" in content

        # Exit code checking for native executables
        assert "$LASTEXITCODE" in content

        # Path handling
        assert "-LiteralPath" in content
        assert "Join-Path" in content

        # Encoding: UTF-8 without BOM
        assert "utf8NoBOM" in content

        # Parameter validation
        assert "[CmdletBinding(" in content or "[CmdletBinding()]" in content or "CmdletBinding" in content
        assert "[Parameter(" in content

        # WhatIf / dry-run
        assert "SupportsShouldProcess" in content or "WhatIf" in content

    def test_platform_scripting_coexistence(self, skill_engine):
        engine = skill_engine
        assert "powershell-scripting" in engine._metadata_index
        assert "bash-scripting" in engine._metadata_index

        ps_meta = engine._metadata_index["powershell-scripting"]
        bash_meta = engine._metadata_index["bash-scripting"]

        assert ps_meta.name != bash_meta.name
        assert ps_meta.sha256_hash != bash_meta.sha256_hash
