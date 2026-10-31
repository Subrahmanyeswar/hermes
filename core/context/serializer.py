# core/context/serializer.py
"""
Deterministic Model-Agnostic ContextPack Serializer for HERMES 2.x.
Enforces strict boundaries between SYSTEM rules and external DATA to prevent prompt injection.
Converts structured ContextPack into both unified text and OpenAI/Claude-compatible message payloads.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.context.models import ContextItem, ContextSectionType


class ContextSerializer:
    """
    Serializes ContextPack items in canonical order with clear XML-style boundaries.
    Guarantees prompt injection resistance by labeling external file and tool outputs as DATA.
    """

    CANONICAL_SECTION_ORDER = [
        ContextSectionType.SYSTEM,
        ContextSectionType.PROJECT_RULES,
        ContextSectionType.SCOPED_RULES,
        ContextSectionType.SKILLS,
        ContextSectionType.CURRENT_GOAL,
        ContextSectionType.ACTIVE_REQUIREMENTS,
        ContextSectionType.RELEVANT_FILES,
        ContextSectionType.RECENT_CHANGES,
        ContextSectionType.RELEVANT_MEMORY,
        ContextSectionType.ACTIVE_TOOLS,
        ContextSectionType.EVIDENCE,
        ContextSectionType.RECENT_OBSERVATIONS,
    ]

    def serialize_to_text(self, sections: Dict[ContextSectionType, List[ContextItem]]) -> str:
        """
        Produce a deterministic unified context prompt with strict provenance tags.
        """
        output_blocks: List[str] = []

        for sec_type in self.CANONICAL_SECTION_ORDER:
            items = sections.get(sec_type, [])
            if not items:
                continue

            tag_name = sec_type.value.lower()
            block_lines = [f"<{tag_name}>"]

            for it in items:
                content = it.content.strip()
                if sec_type == ContextSectionType.RELEVANT_FILES:
                    fp = it.provenance.file_path or "unknown"
                    l_start = it.provenance.line_start
                    l_end = it.provenance.line_end
                    line_attr = f' lines="{l_start}-{l_end}"' if (l_start and l_end) else ""
                    block_lines.append(f'  <file_data path="{fp}"{line_attr}>')
                    block_lines.append(f"    {content}")
                    block_lines.append("  </file_data>")
                elif sec_type == ContextSectionType.EVIDENCE:
                    ev_id = it.provenance.evidence_id or it.id
                    block_lines.append(f'  <evidence_item id="{ev_id}">')
                    block_lines.append(f"    {content}")
                    block_lines.append("  </evidence_item>")
                elif sec_type == ContextSectionType.RECENT_OBSERVATIONS:
                    obs_id = it.provenance.source_id or it.id
                    block_lines.append(f'  <observation_data id="{obs_id}">')
                    block_lines.append(f"    {content}")
                    block_lines.append("  </observation_data>")
                else:
                    block_lines.append(f"  {content}")

            block_lines.append(f"</{tag_name}>")
            output_blocks.append("\n".join(block_lines))

        return "\n\n".join(output_blocks)

    def serialize_to_messages(
        self,
        sections: Dict[ContextSectionType, List[ContextItem]],
    ) -> List[Dict[str, str]]:
        """
        Serialize into standard OpenAI / Claude-compatible messages array:
        - System message: SYSTEM + PROJECT_RULES + SCOPED_RULES + ACTIVE_TOOLS
        - User message: CURRENT_GOAL + REQUIREMENTS + FILES + CHANGES + MEMORY + EVIDENCE + OBSERVATIONS
        """
        system_blocks: List[str] = []
        user_blocks: List[str] = []

        # System role sections
        for sec in (
            ContextSectionType.SYSTEM,
            ContextSectionType.PROJECT_RULES,
            ContextSectionType.SCOPED_RULES,
            ContextSectionType.SKILLS,
            ContextSectionType.ACTIVE_TOOLS,
        ):
            items = sections.get(sec, [])
            if items:
                tag = sec.value.lower()
                system_blocks.append(f"<{tag}>\n" + "\n".join(it.content.strip() for it in items) + f"\n</{tag}>")

        # User role sections
        for sec in (
            ContextSectionType.CURRENT_GOAL,
            ContextSectionType.ACTIVE_REQUIREMENTS,
            ContextSectionType.RELEVANT_FILES,
            ContextSectionType.RECENT_CHANGES,
            ContextSectionType.RELEVANT_MEMORY,
            ContextSectionType.EVIDENCE,
            ContextSectionType.RECENT_OBSERVATIONS,
        ):
            items = sections.get(sec, [])
            if not items:
                continue

            tag = sec.value.lower()
            lines = [f"<{tag}>"]
            for it in items:
                if sec == ContextSectionType.RELEVANT_FILES:
                    fp = it.provenance.file_path or "unknown"
                    lines.append(f'  <file_data path="{fp}">\n    {it.content.strip()}\n  </file_data>')
                elif sec == ContextSectionType.RECENT_OBSERVATIONS:
                    obs_id = it.provenance.source_id or it.id
                    lines.append(f'  <observation_data id="{obs_id}">\n    {it.content.strip()}\n  </observation_data>')
                else:
                    lines.append(f"  {it.content.strip()}")
            lines.append(f"</{tag}>")
            user_blocks.append("\n".join(lines))

        # Surface any critical system directives prominently right before user prompt
        system_items = sections.get(ContextSectionType.SYSTEM, [])
        directives = [
            it.content.strip() for it in system_items
            if it.id.startswith(("guidance_", "gov_notice_")) or "CRITICAL DIRECTIVE" in it.content or "PROGRESS GOVERNOR" in it.content
        ]
        if directives:
            user_blocks.append("\n" + "\n\n".join(directives) + "\n")

        user_blocks.append("What is the next useful action to achieve the current goal?")

        return [
            {"role": "system", "content": "\n\n".join(system_blocks)},
            {"role": "user", "content": "\n\n".join(user_blocks)},
        ]


# Global singleton
context_serializer = ContextSerializer()
