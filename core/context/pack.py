# core/context/pack.py
"""
ContextPack Model and Assembly for HERMES 2.x Context Engine.
Structured projection of authoritative state, active files, memory, and observations
in strict canonical section order.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.context.budget import ContextBudgetReport
from core.context.models import ContextItem, ContextSectionType, ContextVersion
from core.context.serializer import context_serializer


@dataclass
class ContextPack:
    """
    The structured, budgeted projection of context sent to the model for a turn.
    Contains strictly partitioned, ordered sections with token and provenance accounting.
    """
    version: ContextVersion
    sections: Dict[ContextSectionType, List[ContextItem]]
    budget_report: ContextBudgetReport
    items: List[ContextItem] = field(default_factory=list)
    build_duration_ms: float = 0.0
    created_at: float = field(default_factory=time.time)

    def get_section_items(self, section: ContextSectionType) -> List[ContextItem]:
        """Retrieve all items for a given section."""
        return self.sections.get(section, [])

    @property
    def total_estimated_tokens(self) -> int:
        return self.budget_report.used_tokens

    def to_prompt_string(self) -> str:
        """Serialize into a deterministic prompt text block."""
        return context_serializer.serialize_to_text(self.sections)

    def to_messages(self) -> List[Dict[str, str]]:
        """Serialize into standard system/user messages."""
        return context_serializer.serialize_to_messages(self.sections)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version.to_dict(),
            "total_tokens": self.total_estimated_tokens,
            "items_count": len(self.items),
            "budget": self.budget_report.to_dict(),
            "sections": {
                sec.value: [it.to_dict() for it in items]
                for sec, items in self.sections.items()
                if items
            },
            "build_duration_ms": self.build_duration_ms,
            "created_at": self.created_at,
        }
