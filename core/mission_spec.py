# core/mission_spec.py
"""
Authoritative Mission Context & Specification for HERMES 2.x (P0.5).
Binds every website mission to a single, immutable, prompt-derived specification.
Guarantees universal generation across ANY industry or domain without generic fallbacks,
hardcoded brand contamination, or cross-domain bleed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from core.semantic_synthesizer import SemanticDomainSynthesizer, SynthesizedDomainPayload


class SectionList(list):
    """List of sections supporting membership check by string ID, component, or title."""
    def __contains__(self, item: Any) -> bool:
        if super().__contains__(item):
            return True
        for elem in self:
            if isinstance(elem, dict) and (elem.get("id") == item or elem.get("component") == item or elem.get("title") == item):
                return True
            if isinstance(elem, str) and elem == item:
                return True
        return False


@dataclass
class MissionSpecification:
    mission_id: str
    workspace_root: str
    user_prompt: str
    prompt_fingerprint: str
    requested_brand: str
    business_domain: str
    domain_subtype: str
    application_archetype: str
    purpose: str
    target_audience: str
    business_objectives: list[str] = field(default_factory=list)
    visual_direction: str = ""
    color_palette: dict[str, str] = field(default_factory=dict)
    typography: dict[str, str] = field(default_factory=dict)
    required_sections: list[dict[str, Any]] = field(default_factory=list)
    content_entities: list[dict[str, Any]] = field(default_factory=list)
    entity_schemas: dict[str, Any] = field(default_factory=dict)
    navigation_structure: list[dict[str, str]] = field(default_factory=list)
    card_specs: dict[str, Any] = field(default_factory=dict)
    required_interactions: list[str] = field(default_factory=list)
    filter_capabilities: dict[str, Any] = field(default_factory=dict)
    form_specs: list[dict[str, Any]] = field(default_factory=list)
    asset_requirements: list[dict[str, Any]] = field(default_factory=list)
    backend_requirements: dict[str, Any] = field(default_factory=dict)
    negative_constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    semantic_keywords: list[str] = field(default_factory=list)
    requirement_ledger: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.required_sections, SectionList):
            self.required_sections = SectionList(self.required_sections)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MissionSpecification:
        return cls(
            mission_id=data.get("mission_id", ""),
            workspace_root=data.get("workspace_root", ""),
            user_prompt=data.get("user_prompt", ""),
            prompt_fingerprint=data.get("prompt_fingerprint", ""),
            requested_brand=data.get("requested_brand", "Application"),
            business_domain=data.get("business_domain", "general"),
            domain_subtype=data.get("domain_subtype", ""),
            application_archetype=data.get("application_archetype", "interactive_showcase"),
            purpose=data.get("purpose", ""),
            target_audience=data.get("target_audience", ""),
            business_objectives=list(data.get("business_objectives", [])),
            visual_direction=data.get("visual_direction", ""),
            color_palette=dict(data.get("color_palette", {})),
            typography=dict(data.get("typography", {})),
            required_sections=list(data.get("required_sections", [])),
            content_entities=list(data.get("content_entities", [])),
            entity_schemas=dict(data.get("entity_schemas", {})),
            navigation_structure=list(data.get("navigation_structure", [])),
            card_specs=dict(data.get("card_specs", {})),
            required_interactions=list(data.get("required_interactions", [])),
            filter_capabilities=dict(data.get("filter_capabilities", {})),
            form_specs=list(data.get("form_specs", [])),
            asset_requirements=list(data.get("asset_requirements", [])),
            backend_requirements=dict(data.get("backend_requirements", {})),
            negative_constraints=list(data.get("negative_constraints", [])),
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            semantic_keywords=list(data.get("semantic_keywords", [])),
            requirement_ledger=list(data.get("requirement_ledger", [])),
        )

    @classmethod
    def from_prompt(
        cls,
        prompt: str,
        workspace_root: Path | str,
        mission_id: str = "",
        design_brief: Optional[Any] = None,
    ) -> MissionSpecification:
        raw_prompt = prompt or ""
        ws_str = str(Path(workspace_root).resolve())
        fp = hashlib.sha256(raw_prompt.encode("utf-8")).hexdigest()[:12]

        payload = SemanticDomainSynthesizer.synthesize(
            prompt=raw_prompt,
            workspace_root=workspace_root,
            mission_id=mission_id,
            design_brief=design_brief,
        )

        return cls(
            mission_id=mission_id,
            workspace_root=ws_str,
            user_prompt=raw_prompt,
            prompt_fingerprint=fp,
            requested_brand=payload.requested_brand,
            business_domain=payload.business_domain,
            domain_subtype=payload.domain_subtype,
            application_archetype=payload.application_archetype,
            purpose=payload.purpose,
            target_audience=payload.target_audience,
            business_objectives=payload.business_objectives,
            visual_direction=payload.visual_direction,
            color_palette=payload.color_palette,
            typography=payload.typography,
            required_sections=payload.required_sections,
            content_entities=payload.content_entities,
            entity_schemas=payload.entity_schemas,
            navigation_structure=payload.navigation_structure,
            card_specs=payload.card_specs,
            required_interactions=payload.required_interactions,
            filter_capabilities=payload.filter_capabilities,
            form_specs=payload.form_specs,
            asset_requirements=payload.asset_requirements,
            backend_requirements=payload.backend_requirements,
            negative_constraints=payload.negative_constraints,
            acceptance_criteria=payload.acceptance_criteria,
            semantic_keywords=payload.semantic_keywords,
            requirement_ledger=getattr(payload, "requirement_ledger", []),
        )

    def persist(self, workspace_root: Path | str) -> tuple[Path, Path]:
        ws = Path(workspace_root).resolve()
        h_dir = ws / ".hermes"
        h_dir.mkdir(parents=True, exist_ok=True)
        json_path = h_dir / "mission_spec.json"
        json_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

        if self.mission_id:
            m_dir = h_dir / "missions" / self.mission_id
            m_dir.mkdir(parents=True, exist_ok=True)
            (m_dir / "mission_spec.json").write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

        art_dir = ws / ".artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        md_path = art_dir / "mission_spec.md"
        md_path.write_text(self.to_markdown(), encoding="utf-8")

        return json_path, md_path

    def to_markdown(self) -> str:
        colors_table = "\n".join(f"| `--{k}` | `{v}` |" for k, v in self.color_palette.items())
        sections_list = "\n".join(f"- `{s.get('id', str(s))}` ({s.get('title', '')})" for s in self.required_sections)
        interactions_list = "\n".join(f"- {i}" for i in self.required_interactions)
        criteria_list = "\n".join(f"- {c}" for c in self.acceptance_criteria)
        entities_list = "\n".join(f"- **{e.get('title', '')}** (`{e.get('category_label', e.get('category', ''))}`): {e.get('description', '')}" for e in self.content_entities)
        ledger_table = "\n".join(
            f"| `{r.get('req_id', '')}` | `{r.get('category', '')}` | `{r.get('expected_component', '')}` | `{r.get('expected_dom_selector', '')}` | {r.get('expected_interaction', r.get('expected_content', ''))} | `{r.get('verification_status', 'PENDING')}` |"
            for r in self.requirement_ledger
        )

        return f"""# Authoritative Mission Specification: {self.requested_brand}

## 1. Mission Metadata
- **Mission ID:** `{self.mission_id}`
- **Brand Name:** `{self.requested_brand}`
- **Business Domain:** `{self.business_domain}` ({self.domain_subtype})
- **Application Archetype:** `{self.application_archetype}`
- **Purpose:** {self.purpose}
- **Target Audience:** {self.target_audience}
- **Visual Direction:** {self.visual_direction}

## 2. Color Palette & Design Tokens
| Token | Value |
|---|---|
{colors_table}

## 3. Required Semantic Sections
{sections_list}

## 4. Synthesized Domain Entities
{entities_list}

## 5. Required Interactions
{interactions_list}

## 6. Acceptance Criteria
{criteria_list}

## 7. Requirement Traceability Ledger
| Req ID | Category | Component | DOM Selector | Expected Interaction / Requirement | Verification |
|---|---|---|---|---|---|
{ledger_table}
"""

    @classmethod
    def load_from_workspace(cls, workspace_root: Path | str) -> Optional[MissionSpecification]:
        ws = Path(workspace_root).resolve()
        spec_path = ws / ".hermes" / "mission_spec.json"
        if spec_path.exists():
            try:
                data = json.loads(spec_path.read_text(encoding="utf-8", errors="ignore"))
                return cls.from_dict(data)
            except Exception as e:
                logger.warning(f"MissionSpecification: Failed to load from {spec_path}: {e}")
        return None
