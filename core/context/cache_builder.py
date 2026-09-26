# core/context/cache_builder.py
"""
Cache-Aware Prompt Builder for HERMES 2.x Context Engine.
Partitions ContextPack into deterministic segments (STABLE_PREFIX, SEMI_STABLE, DYNAMIC_SUFFIX)
to maximize KV-cache reuse on providers supporting prefix caching, while remaining completely
provider-agnostic and fully functional when caching is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.context.models import ContextItem, ContextSectionType


class CacheSegmentType(str, Enum):
    """Partition tier for prompt cache affinity."""
    STABLE_PREFIX = "STABLE_PREFIX"     # System prompt, invariant project rules, core tool schemas
    SEMI_STABLE = "SEMI_STABLE"         # Scoped rules, architectural memory, workspace structure
    DYNAMIC_SUFFIX = "DYNAMIC_SUFFIX"   # Active goal, requirements, active files, recent observations


class CachePolicy(str, Enum):
    """Cache hint policy."""
    CACHE_PREFERRED = "CACHE_PREFERRED"
    CACHE_IF_SUPPORTED = "CACHE_IF_SUPPORTED"
    DYNAMIC = "DYNAMIC"
    NEVER_CACHE = "NEVER_CACHE"


@dataclass
class CacheCapabilities:
    """Provider cache capability flags."""
    cache_supported: bool = False
    provider: str = "nvidia_nim"
    min_cache_tokens: int = 1024
    cache_control_type: str = "none"  # "ephemeral", "block", "none"


@dataclass
class CacheSegment:
    """A deterministic segment of the serialized prompt."""
    segment_type: CacheSegmentType
    name: str
    content: str
    cache_policy: CachePolicy
    estimated_tokens: int = 0
    is_cache_eligible: bool = False

    def __post_init__(self):
        if not self.estimated_tokens:
            self.estimated_tokens = max(1, len(self.content) // 4) if self.content else 0


@dataclass
class CacheMetrics:
    """Observability tracking for cache utilization."""
    stable_prefix_estimated_tokens: int = 0
    semi_stable_estimated_tokens: int = 0
    dynamic_suffix_estimated_tokens: int = 0
    cache_eligible_tokens: int = 0
    cache_hits: Optional[int] = None
    cache_misses: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stable_prefix_estimated_tokens": self.stable_prefix_estimated_tokens,
            "semi_stable_estimated_tokens": self.semi_stable_estimated_tokens,
            "dynamic_suffix_estimated_tokens": self.dynamic_suffix_estimated_tokens,
            "cache_eligible_tokens": self.cache_eligible_tokens,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


class CacheAwarePromptBuilder:
    """
    Builds structured, partitioned prompt segments in strict deterministic order.
    Ensures stable prefix invariant sections do not mutate turn-to-turn.
    """

    def __init__(self, capabilities: Optional[CacheCapabilities] = None) -> None:
        self.capabilities = capabilities or CacheCapabilities()

    def build_segments(
        self,
        sections: Dict[ContextSectionType, List[ContextItem]],
    ) -> Tuple[List[CacheSegment], CacheMetrics]:
        """
        Group sections into CacheSegments and compute cache metrics.
        Returns: (segments, metrics)
        """
        segments: List[CacheSegment] = []

        # ── 1. STABLE PREFIX: SYSTEM, PROJECT_RULES, ACTIVE_TOOLS ─────────────
        stable_items: List[str] = []

        # System
        for it in sections.get(ContextSectionType.SYSTEM, []):
            stable_items.append(f"<system>\n{it.content.strip()}\n</system>")

        # Project rules
        for it in sections.get(ContextSectionType.PROJECT_RULES, []):
            stable_items.append(f"<project_rules>\n{it.content.strip()}\n</project_rules>")

        # Active tool definitions
        for it in sections.get(ContextSectionType.ACTIVE_TOOLS, []):
            stable_items.append(f"<active_tools>\n{it.content.strip()}\n</active_tools>")

        stable_content = "\n\n".join(stable_items)
        stable_segment = CacheSegment(
            segment_type=CacheSegmentType.STABLE_PREFIX,
            name="stable_prefix",
            content=stable_content,
            cache_policy=CachePolicy.CACHE_PREFERRED if self.capabilities.cache_supported else CachePolicy.DYNAMIC,
            is_cache_eligible=self.capabilities.cache_supported and len(stable_content) > 200,
        )
        segments.append(stable_segment)

        # ── 2. SEMI-STABLE: SCOPED_RULES, RELEVANT_MEMORY ─────────────────────
        semi_items: List[str] = []

        for it in sections.get(ContextSectionType.SCOPED_RULES, []):
            semi_items.append(f"<scoped_rules>\n{it.content.strip()}\n</scoped_rules>")

        for it in sections.get(ContextSectionType.RELEVANT_MEMORY, []):
            semi_items.append(f"<memory>\n{it.content.strip()}\n</memory>")

        semi_content = "\n\n".join(semi_items)
        semi_segment = CacheSegment(
            segment_type=CacheSegmentType.SEMI_STABLE,
            name="semi_stable",
            content=semi_content,
            cache_policy=CachePolicy.CACHE_IF_SUPPORTED if self.capabilities.cache_supported else CachePolicy.DYNAMIC,
            is_cache_eligible=self.capabilities.cache_supported and len(semi_content) > 400,
        )
        segments.append(semi_segment)

        # ── 3. DYNAMIC SUFFIX: GOAL, REQUIREMENTS, FILES, CHANGES, EVIDENCE, OBS ─
        dyn_items: List[str] = []

        for it in sections.get(ContextSectionType.CURRENT_GOAL, []):
            dyn_items.append(f"<current_goal>\n{it.content.strip()}\n</current_goal>")

        for it in sections.get(ContextSectionType.ACTIVE_REQUIREMENTS, []):
            dyn_items.append(f"<active_requirements>\n{it.content.strip()}\n</active_requirements>")

        for it in sections.get(ContextSectionType.RELEVANT_FILES, []):
            fp = it.provenance.file_path or "unknown"
            dyn_items.append(f'<file path="{fp}">\n{it.content.strip()}\n</file>')

        for it in sections.get(ContextSectionType.RECENT_CHANGES, []):
            dyn_items.append(f"<recent_changes>\n{it.content.strip()}\n</recent_changes>")

        for it in sections.get(ContextSectionType.EVIDENCE, []):
            ev_id = it.provenance.evidence_id or it.id
            dyn_items.append(f'<evidence id="{ev_id}">\n{it.content.strip()}\n</evidence>')

        for it in sections.get(ContextSectionType.RECENT_OBSERVATIONS, []):
            obs_id = it.provenance.source_id or it.id
            dyn_items.append(f'<observation id="{obs_id}">\n{it.content.strip()}\n</observation>')

        dyn_content = "\n\n".join(dyn_items)
        dyn_segment = CacheSegment(
            segment_type=CacheSegmentType.DYNAMIC_SUFFIX,
            name="dynamic_suffix",
            content=dyn_content,
            cache_policy=CachePolicy.DYNAMIC,
            is_cache_eligible=False,
        )
        segments.append(dyn_segment)

        # ── 4. Metrics ────────────────────────────────────────────────────────
        metrics = CacheMetrics(
            stable_prefix_estimated_tokens=stable_segment.estimated_tokens,
            semi_stable_estimated_tokens=semi_segment.estimated_tokens,
            dynamic_suffix_estimated_tokens=dyn_segment.estimated_tokens,
            cache_eligible_tokens=(
                (stable_segment.estimated_tokens if stable_segment.is_cache_eligible else 0)
                + (semi_segment.estimated_tokens if semi_segment.is_cache_eligible else 0)
            ),
        )

        return segments, metrics

    def assemble_prompt(self, segments: List[CacheSegment]) -> str:
        """Join all segments deterministically into complete prompt text."""
        parts = [s.content for s in segments if s.content.strip()]
        return "\n\n".join(parts)
