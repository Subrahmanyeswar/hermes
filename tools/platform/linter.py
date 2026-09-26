# tools/platform/linter.py
"""
Deterministic Tool Specification Linter for HERMES 2.x Tool Platform.
Statically audits all registered tool definitions for schema validity,
documentation quality, risk completeness, and alias hygiene.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from tools.platform.catalog import ToolCatalog, tool_catalog
from tools.platform.specs import ToolSpec


@dataclass
class LintReport:
    """Diagnostic outcome of tool specification audit."""
    is_clean: bool
    total_tools_audited: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ToolSpecLinter:
    """
    Validates canonical ToolSpecs against quality and consistency invariants.
    """

    MAX_DESCRIPTION_LENGTH = 500
    MIN_DESCRIPTION_LENGTH = 15

    @classmethod
    def audit_catalog(cls, catalog: Optional[ToolCatalog] = None) -> LintReport:
        cat = catalog or tool_catalog
        specs = cat.list_all()
        errors: List[str] = []
        warnings: List[str] = []

        seen_names = set()
        seen_aliases = {}

        for s in specs:
            # 1. Canonical name integrity
            if not s.canonical_name:
                errors.append("Found ToolSpec with empty canonical_name.")
                continue
            if s.canonical_name in seen_names:
                errors.append(f"Duplicate canonical tool name '{s.canonical_name}'.")
            seen_names.add(s.canonical_name)

            # 2. Namespace / Category integrity
            if not s.category:
                errors.append(f"Tool '{s.canonical_name}' has empty category namespace.")

            # 3. Description checks
            desc = s.description or ""
            if len(desc) < cls.MIN_DESCRIPTION_LENGTH:
                errors.append(f"Tool '{s.canonical_name}' description is too short ({len(desc)} chars).")
            if len(desc) > cls.MAX_DESCRIPTION_LENGTH:
                warnings.append(f"Tool '{s.canonical_name}' description exceeds recommended {cls.MAX_DESCRIPTION_LENGTH} chars ({len(desc)} chars).")

            # 4. Schema checks
            if not s.schema:
                errors.append(f"Tool '{s.canonical_name}' is missing ToolSchema.")
            else:
                props = s.schema.parameters.get("properties", {})
                req = s.schema.required or s.schema.parameters.get("required", [])
                for r in req:
                    if r not in props:
                        errors.append(f"Tool '{s.canonical_name}' specifies required parameter '{r}' not present in properties.")

            # 5. Risk metadata checks
            if not s.risk:
                errors.append(f"Tool '{s.canonical_name}' is missing RiskMetadata.")
            else:
                if s.risk.risk_score < 0.0 or s.risk.risk_score > 1.0:
                    errors.append(f"Tool '{s.canonical_name}' has invalid risk_score {s.risk.risk_score} (must be in 0.0..1.0).")

            # 6. Aliases conflict checks
            for al in s.aliases:
                if al in seen_aliases and seen_aliases[al] != s.canonical_name:
                    errors.append(f"Alias collision: '{al}' registered to both '{seen_aliases[al]}' and '{s.canonical_name}'.")
                seen_aliases[al] = s.canonical_name

            # 7. Examples checks for core tools
            if s.is_core and not s.examples:
                warnings.append(f"Core tool '{s.canonical_name}' has no agent-facing ToolExamples.")

        is_clean = len(errors) == 0
        return LintReport(
            is_clean=is_clean,
            total_tools_audited=len(specs),
            errors=errors,
            warnings=warnings,
        )
