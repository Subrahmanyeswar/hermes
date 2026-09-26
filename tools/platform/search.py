# tools/platform/search.py
"""
Deterministic Tool Search and Discovery Engine for HERMES 2.x Tool Platform.
Enables progressive tool disclosure so the model loads compact core tools initially
and discovers specialized capabilities on demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from tools.platform.specs import ToolSpec, ToolAvailability
from tools.platform.catalog import tool_catalog


@dataclass
class ToolSearchResult:
    """Lightweight search result entry for model consumption."""
    canonical_name: str
    display_name: str
    summary: str
    category: str
    score: int
    aliases: List[str] = field(default_factory=list)

    def to_compact_str(self) -> str:
        alias_str = f" (aliases: {', '.join(self.aliases)})" if self.aliases else ""
        return f"- {self.canonical_name}{alias_str}: {self.summary}"


class ToolSearch:
    """
    Deterministic search service across registered tool specifications.
    """

    def __init__(self, catalog=None) -> None:
        self.catalog = catalog or tool_catalog

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        max_results: int = 10,
    ) -> List[ToolSearchResult]:
        """
        Search tools using deterministic lexical and token scoring.
        """
        raw_query = query.strip()
        if not raw_query:
            return []

        q_lower = raw_query.lower()
        tokens = set(re.findall(r"\w+", q_lower))

        available_specs = [
            s for s in self.catalog.list_available()
            if category is None or s.category.lower() == category.lower()
        ]

        scored: List[ToolSearchResult] = []

        for spec in available_specs:
            name_lower = spec.canonical_name.lower()
            score = 0

            # 1. Exact name match
            if q_lower == name_lower:
                score += 100
            elif name_lower.startswith(q_lower):
                score += 60
            elif q_lower in name_lower:
                score += 40

            # 2. Exact alias match
            for alias in spec.aliases:
                al_lower = alias.lower()
                if q_lower == al_lower:
                    score += 90
                elif q_lower in al_lower or al_lower in q_lower:
                    score += 45

            # 3. Category match
            if spec.category.lower() == q_lower or spec.category.lower() in tokens:
                score += 30

            # 4. Tag matches (exact or prefix/stem)
            for tag in spec.tags:
                tag_l = tag.lower()
                for tok in tokens:
                    if tok == tag_l:
                        score += 30
                    elif len(tok) >= 3 and len(tag_l) >= 3 and (tok.startswith(tag_l) or tag_l.startswith(tok)):
                        score += 20

            # 5. Description token overlap (exact or prefix/stem)
            desc_tokens = set(re.findall(r"\w+", spec.description.lower()))
            overlap_score = 0
            for dt in desc_tokens:
                if len(dt) >= 3:
                    for tok in tokens:
                        if len(tok) >= 3:
                            if tok == dt:
                                overlap_score += 15
                            elif tok.startswith(dt) or dt.startswith(tok):
                                overlap_score += 10
            score += min(overlap_score, 120)

            if score > 0:
                summary = spec.description[:180] + ("..." if len(spec.description) > 180 else "")
                scored.append(ToolSearchResult(
                    canonical_name=spec.canonical_name,
                    display_name=spec.display_name,
                    summary=summary,
                    category=spec.category,
                    score=score,
                    aliases=spec.aliases,
                ))

        # Sort descending by score, tie-break alphabetically by canonical name
        scored.sort(key=lambda r: (-r.score, r.canonical_name))
        return scored[:max_results]

    def format_search_results(self, query: str, results: List[ToolSearchResult]) -> str:
        """Format search results into a clean agent-facing observation."""
        if not results:
            # Fallback suggestions from core tools
            core_tools = [s.canonical_name for s in self.catalog.list_core()]
            return (
                f"No specific tools matched query '{query}'.\n"
                f"Available core capabilities include: {', '.join(core_tools[:6])}."
            )

        lines = [f"Found {len(results)} tool capability match(es) for '{query}':"]
        for res in results:
            lines.append(res.to_compact_str())
        return "\n".join(lines)


# Global canonical ToolSearch singleton
tool_search = ToolSearch()
