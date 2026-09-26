# core/context/relevance.py
"""
Deterministic Relevance Engine and Candidate Scorer for HERMES 2.x Context Engine.
Ranks context candidates transparently without heavy ML overhead while strictly
protecting mandatory state, security constraints, and critical evidence from being pruned.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Set

from core.context.models import ContextFreshness, ContextItem, ContextPriority, ContextSectionType


class RelevanceEngine:
    """
    Computes deterministic relevance scores for candidate context items.
    Enforces that priority classification always precedes numerical ranking.
    """

    def __init__(self) -> None:
        self._keyword_cleaner = re.compile(r"[^\w\s]")

    def extract_keywords(self, text: str) -> Set[str]:
        """Extract alphanumeric token set for keyword overlap calculation."""
        cleaned = self._keyword_cleaner.sub(" ", text.lower())
        tokens = set(cleaned.split())
        stopwords = {"the", "a", "an", "is", "in", "to", "and", "or", "of", "for", "with", "at", "by", "on"}
        return {t for t in tokens if len(t) > 2 and t not in stopwords}

    def score_item(
        self,
        item: ContextItem,
        current_goal: str = "",
        active_requirements: Optional[List[str]] = None,
        active_files: Optional[Set[str]] = None,
        current_turn: int = 1,
    ) -> float:
        """
        Calculate deterministic relevance score between 0.0 and 1.0.
        MANDATORY items return 1.0 regardless of keyword overlap.
        """
        # 1. MANDATORY items are always maximum score
        if item.priority == ContextPriority.MANDATORY:
            item.relevance_score = 1.0
            return 1.0

        # 2. INVALIDATED items are dropped to zero
        if item.freshness == ContextFreshness.INVALIDATED:
            item.relevance_score = 0.0
            return 0.0

        # 3. STALE items receive heavy penalty
        stale_factor = 0.2 if item.freshness == ContextFreshness.STALE else 1.0

        score = 0.5  # Baseline

        # 4. Priority tier baseline
        if item.priority == ContextPriority.IMPORTANT:
            score += 0.25
        elif item.priority == ContextPriority.DISCARDABLE:
            score -= 0.35

        # 5. Pinned boost
        if item.pinned:
            score += 0.20

        # 6. Keyword overlap with goal
        if current_goal:
            goal_keywords = self.extract_keywords(current_goal)
            item_keywords = self.extract_keywords(item.content[:1000])
            if goal_keywords and item_keywords:
                overlap = len(goal_keywords.intersection(item_keywords))
                score += min(0.20, overlap * 0.04)

        # 7. Active file set match
        if active_files and item.provenance.file_path:
            norm_path = item.provenance.file_path.replace("\\", "/").lower()
            if any(norm_path.endswith(af.replace("\\", "/").lower()) for af in active_files):
                score += 0.25

        # 8. Section-specific adjustments
        if item.section == ContextSectionType.EVIDENCE:
            score += 0.15
        elif item.section == ContextSectionType.RECENT_CHANGES:
            score += 0.10
        elif item.section == ContextSectionType.RECENT_OBSERVATIONS:
            # Check if this observation reported a failure / blocker
            if item.metadata.get("is_error") or "failed" in item.content.lower() or "error" in item.content.lower():
                score += 0.20

        # 9. Recency adjustment for observations (older observations decay unless pinned/important)
        if item.section == ContextSectionType.RECENT_OBSERVATIONS and not item.pinned:
            item_turn = item.metadata.get("turn_number", current_turn)
            turn_age = max(0, current_turn - item_turn)
            if turn_age > 10:
                score -= 0.20
            elif turn_age > 5:
                score -= 0.10

        # Architectural decisions in memory never decay below 0.70
        if item.section == ContextSectionType.RELEVANT_MEMORY and item.metadata.get("is_decision"):
            score = max(score, 0.75)

        final_score = max(0.01, min(1.0, score * stale_factor))
        item.relevance_score = round(final_score, 4)
        return item.relevance_score

    def score_all(
        self,
        items: List[ContextItem],
        current_goal: str = "",
        active_requirements: Optional[List[str]] = None,
        active_files: Optional[Set[str]] = None,
        current_turn: int = 1,
    ) -> List[ContextItem]:
        """Score all items in place and return them."""
        for item in items:
            self.score_item(
                item=item,
                current_goal=current_goal,
                active_requirements=active_requirements,
                active_files=active_files,
                current_turn=current_turn,
            )
        return items


# Global singleton
relevance_engine = RelevanceEngine()
