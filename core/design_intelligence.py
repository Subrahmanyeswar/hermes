# core/design_intelligence.py
"""
Design Intelligence and Content Coverage Engine for HERMES 2.x.
Establishes compact, professional Design Briefs before website generation,
enforces visual design principles, guides photographic asset selection,
and tracks comprehensive content coverage across multi-section missions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


@dataclass
class DesignBrief:
    """
    Compact architectural design brief synthesizing visual direction,
    brand personality, color palette, typography, spacing, component standards,
    and responsive behavior.
    """
    domain: str
    purpose: str
    target_audience: str
    brand_personality: str
    visual_direction: str
    color_palette: Dict[str, str] = field(default_factory=dict)
    typography: Dict[str, str] = field(default_factory=dict)
    spacing_system: Dict[str, str] = field(default_factory=dict)
    component_styling: Dict[str, str] = field(default_factory=dict)
    image_direction: Dict[str, str] = field(default_factory=dict)
    responsive_breakpoints: Dict[str, str] = field(default_factory=dict)
    brand_identity: str = ""
    cuisine_subtype: str = ""
    requested_content: List[str] = field(default_factory=list)
    brand_positioning: str = ""
    layout_strategy: str = ""
    component_language: Dict[str, str] = field(default_factory=dict)
    navigation_strategy: str = ""
    interaction_specs: Dict[str, str] = field(default_factory=dict)
    asset_plan_requirements: List[str] = field(default_factory=list)

    @property
    def personality(self) -> str:
        return self.brand_personality

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DesignBrief:
        return cls(
            domain=data.get("domain", "modern_editorial"),
            purpose=data.get("purpose", "Web Application"),
            target_audience=data.get("target_audience", "General Public"),
            brand_personality=data.get("brand_personality", data.get("personality", "Clean, modern, professional")),
            visual_direction=data.get("visual_direction", "Modern layout with crisp hierarchy"),
            color_palette=dict(data.get("color_palette", {})),
            typography=dict(data.get("typography", {})),
            spacing_system=dict(data.get("spacing_system", {})),
            component_styling=dict(data.get("component_styling", {})),
            image_direction=dict(data.get("image_direction", {})),
            responsive_breakpoints=dict(data.get("responsive_breakpoints", {})),
            brand_positioning=data.get("brand_positioning", ""),
            layout_strategy=data.get("layout_strategy", ""),
            component_language=dict(data.get("component_language", {})),
            navigation_strategy=data.get("navigation_strategy", ""),
            interaction_specs=dict(data.get("interaction_specs", {})),
            asset_plan_requirements=list(data.get("asset_plan_requirements", [])),
        )

    def persist_artifacts(self, workspace_root: Path | str) -> Tuple[Path, Path]:
        """
        Persist design brief into .hermes/design_brief.json and .artifacts/design_brief.md.
        """
        ws = Path(workspace_root).resolve()
        h_dir = ws / ".hermes"
        h_dir.mkdir(parents=True, exist_ok=True)
        json_path = h_dir / "design_brief.json"
        json_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

        art_dir = ws / ".artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        md_path = art_dir / "design_brief.md"
        md_path.write_text(self.to_markdown(), encoding="utf-8")

        return json_path, md_path

    def to_markdown(self) -> str:
        colors_table = "\n".join(f"| `--{k}` | `{v}` |" for k, v in self.color_palette.items())
        typo_table = "\n".join(f"| {k} | {v} |" for k, v in self.typography.items())
        comps_table = "\n".join(f"| {k} | {v} |" for k, v in self.component_styling.items())
        comp_lang_table = "\n".join(f"| {k} | {v} |" for k, v in self.component_language.items())
        
        return f"""# Authoritative Design Brief: {self.domain.replace('_', ' ').title()}

## Executive Summary
- **Domain:** {self.domain}
- **Brand Personality:** {self.brand_personality}
- **Brand Positioning:** {self.brand_positioning}
- **Visual Direction:** {self.visual_direction}
- **Layout Strategy:** {self.layout_strategy}
- **Navigation Strategy:** {self.navigation_strategy}

## Color Tokens (:root)
| CSS Token | Value |
|---|---|
{colors_table}

## Typography
| Property | Value |
|---|---|
{typo_table}

## Component Language & Styling
| Component | Specification |
|---|---|
{comp_lang_table or comps_table}

## Responsive Breakpoints
- Mobile: `{self.responsive_breakpoints.get('mobile_max', '768px')}`
- Tablet: `{self.responsive_breakpoints.get('tablet_max', '1024px')}`
- Desktop: `{self.responsive_breakpoints.get('desktop_min', '1025px')}`

## Asset Strategy
- Object fit: `{self.image_direction.get('object_fit', 'cover')}`
- Aspect ratios: Hero `{self.image_direction.get('hero_aspect', '16/9')}`, Cards `{self.image_direction.get('aspect_ratio', '4/3')}`
- Requirements: {', '.join(self.asset_plan_requirements) if self.asset_plan_requirements else 'Pre-provisioned local workspace photography'}
"""

    def to_compact_directive(self) -> str:
        """
        Produce a compact, high-density actionable design directive
        suitable for model context injection during Phase B, Phase C, and Phase D.
        """
        colors_css = ", ".join(f"{k}: {v}" for k, v in list(self.color_palette.items())[:5])
        typo_str = f"Headings: {self.typography.get('heading_font', 'sans-serif')} | Body: {self.typography.get('body_font', 'sans-serif')}"
        cards_str = f"Radius: {self.component_styling.get('card_radius', '12px')} | Shadow: {self.component_styling.get('card_shadow', '0 4px 20px rgba(0,0,0,0.08)')}"
        img_str = f"Object-fit: {self.image_direction.get('object_fit', 'cover')} | Card Aspect: {self.image_direction.get('aspect_ratio', '4/3')}"
        
        lines = [
            "=== AUTHORITATIVE DESIGN BRIEF & HIGH-FIDELITY UI SPECIFICATION ===",
            f"Domain & Personality: {self.domain.upper()} -- {self.brand_personality}",
            f"Visual Direction: {self.visual_direction}",
            f"Color Palette: {colors_css}",
            f"Typography: {typo_str}; Fluid clamp() headings and subheads.",
            "Hero Architecture: Full-bleed photography (min-height: 85vh; cover; center; full gradient overlay via absolute inset: 0 or .hero::before; content at z-index: 2).",
            "Header & Nav: Sticky header. Mobile hamburger (.mobile-menu-btn span) with responsive drawer (.nav-links.active) closing on link click or Escape.",
            f"Card Styling: {cards_str}; Card images must use fixed aspect-ratio and overflow: hidden",
            f"Photography: {img_str} (Use verified local assets in assets/images/ from manifest)",
            f"Layout: Container max-width: {self.spacing_system.get('container_max_width', '1200px')} centered; padding: 4rem 1.5rem;",
            f"Interactive Components: Filter pills with active state, search input, backdrop blur modal, validated booking form;",
            f"Responsive: Mobile breakpoint {self.responsive_breakpoints.get('mobile_max', '768px')}; Zero horizontal overflow (overflow-x: hidden);",
            "MANDATE: Every element styled. Zero raw unstyled links/buttons. Never overwrite <section> roots during JS render.",
            "===================================================================",
        ]
        return "\n".join(lines)


def strip_negative_constraints(prompt: str) -> str:
    """
    Remove lines or clauses containing negative instructions, prohibitions, or exclusions
    (e.g., 'do not', 'avoid', 'never', 'do not copy', 'do not reuse') so that negative mentions
    of unrelated brands or domains (such as 'Do not copy Saffron & Stone' or 'Do not reuse NOVA')
    never trigger false positive domain matching or context contamination.
    """
    if not prompt:
        return ""
    cleaned_lines = []
    in_neg_block = False
    for line in prompt.splitlines():
        ls = line.strip().lower()
        if any(h in ls for h in ["## negative constraints", "### negative constraints", "## avoid", "### avoid", "## restrictions"]):
            in_neg_block = True
            continue
        if in_neg_block and ls.startswith("#"):
            in_neg_block = False
        if in_neg_block:
            continue
        # Strip trailing negative clauses within a line (e.g. "Build Logistics. Do not reuse NOVA.")
        line_clean = re.sub(r'[\.\;\,\:]\s*(?:do not|don\'t|avoid|never|must not|not reuse|not copy)\b.*$', '', line, flags=re.I)
        # If the entire line is a negative bullet or prohibition, skip it
        if re.search(r'^\s*[-*•]?\s*(?:do not|don\'t|avoid|never|must not|not reuse|not copy|prohibit)\b', line_clean.strip(), re.I):
            continue
        cleaned_lines.append(line_clean)
    return "\n".join(cleaned_lines)

PROMPT_COLOR_KEYWORDS: dict[str, str] = {
    "warm ivory": "#fbf9f5",
    "ivory": "#fdfbf7",
    "charcoal": "#1c1d21",
    "muted olive": "#556b2f",
    "olive": "#556b2f",
    "terracotta": "#c85a32",
    "saffron": "#e65100",
    "gold": "#d4af37",
    "navy": "#0a192f",
    "royal blue": "#1d4ed8",
    "electric cyan": "#00d2ff",
    "cyan": "#06b6d4",
    "emerald": "#059669",
    "mint": "#10b981",
    "amber": "#d97706",
    "coral": "#f43f5e",
    "bronze": "#8c6239",
    "sand": "#e8d8c8",
    "cream": "#fffdd0",
    "slate": "#334155",
    "graphite": "#242526",
    "obsidian": "#0b0f17",
    "teal": "#0d9488",
    "rose": "#e11d48",
}

def extract_prompt_color_palette(prompt: str) -> dict[str, str]:
    """Extracts custom color tokens specified in user prompt (e.g. 'warm ivory, charcoal, muted olive')."""
    if not prompt:
        return {}
    p_lower = prompt.lower()
    found: list[tuple[str, str]] = []
    for name in sorted(PROMPT_COLOR_KEYWORDS.keys(), key=len, reverse=True):
        if re.search(r'\b' + re.escape(name) + r'\b', p_lower):
            found.append((name, PROMPT_COLOR_KEYWORDS[name]))
            p_lower = p_lower.replace(name, " ")

    tokens: dict[str, str] = {}
    if found:
        bg = next((h for n, h in found if any(l in n for l in ["ivory", "cream", "sand", "white"])), None)
        dark = next((h for n, h in found if any(d in n for d in ["charcoal", "obsidian", "graphite", "navy", "slate"])), None)
        accent = next((h for n, h in found if any(a in n for a in ["olive", "gold", "amber", "cyan", "emerald", "terracotta", "coral", "teal", "bronze", "saffron", "rose", "mint"])), None)

        if dark:
            tokens["primary"] = dark
            tokens["text_primary"] = dark
        if bg:
            tokens["background"] = bg
            tokens["surface"] = "#ffffff"
        if accent:
            tokens["accent"] = accent
            tokens["secondary"] = accent

    return tokens

def detect_brand_name(prompt: str) -> str:
    """
    Universally extracts the requested brand name or entity title from a website mission prompt.
    Prevents downstream components from falling back to hardcoded brands like NOVA or Saffron & Stone.
    """
    if not prompt:
        return "Application"
    p = strip_negative_constraints(prompt).strip()

    blacklist = {
        "identity", "identity studio", "brand identity", "guidelines", "aesthetic",
        "strategy", "voice", "personality", "positioning", "values", "concept",
        "overview", "website", "web portal", "brand", "company", "business",
        "application", "studio", "independent", "modern", "portfolio", "app",
        "platform", "portal", "fictional", "discerning users", "following completely new business",
        "completely new business", "new business"
    }

    def _clean_candidate(cand: str) -> str:
        if not cand:
            return ""
        # Strip markdown bold/italic/quotes
        cand = cand.strip(" *\"'_`#")
        # Split on common punctuation that ends a name (period, comma, semicolon, newline, colon, or spaced dash)
        cand = re.split(r"[\r\n.,;:]|\s+[\u2014\u2013-]\s+", cand)[0].strip()
        # Strip leading lowercase articles and descriptive filler words (preserve uppercase THE in proper titles)
        cand = re.sub(r"^(?:a|an|the)\s+", "", cand).strip()
        cand = re.sub(
            r"^(?:modern|visually impressive|fresh|new|fictional|independent|completely new)\s+",
            "",
            cand,
            flags=re.I,
        ).strip()
        # Strip trailing noise like 'website', 'web portal', 'platform', 'app'
        cand = re.sub(r"\s+(?:website|web\s+portal|portal|application|app)\b.*$", "", cand, flags=re.I).strip()
        cand = cand.strip(" *\"'_`#")
        if cand.lower() in blacklist or len(cand) < 2:
            return ""
        if any(b in cand.lower() for b in ["brand identity", "brand guidelines", "brand aesthetic", "brand personality"]):
            return ""
        return cand

    # 1. Explicit structured fields: Brand:, Brand Name:, Company:, Business:, Organization:
    # Handles markdown headers like '## Brand: VERDANT LOOP' or '**Brand:** VERDANT LOOP' or 'Brand Name: VERDANT LOOP'
    m_structured = re.search(
        r"(?:^|\n)\s*(?:#+\s*)?(?:\*{0,2}(?:Brand(?:\s*Name)?|Company(?:\s*Name)?|Business(?:\s*Name)?|Organization)\*{0,2})\s*[:=]\s*[*\"'_`]*([^\r\n*\"'_`#]+)",
        p,
        re.I,
    )
    if m_structured:
        cleaned = _clean_candidate(m_structured.group(1))
        if cleaned:
            return cleaned

    # 2. Explicit quoted names: called "VERDANT LOOP", named "VERDANT LOOP", for "VERDANT LOOP"
    m_quoted = re.search(r'\b(?:called|named|brand\s+is|brand\s*[:=])\s+["\']([^"\']{2,60})["\']', p, re.I)
    if m_quoted:
        cleaned = _clean_candidate(m_quoted.group(1))
        if cleaned:
            return cleaned

    # 3. Explicit bolded names: called **VERDANT LOOP**, named **VERDANT LOOP**
    m_bold = re.search(r'\b(?:called|named)\s+\*\*([^*]{2,60})\*\*', p, re.I)
    if m_bold:
        cleaned = _clean_candidate(m_bold.group(1))
        if cleaned:
            return cleaned

    # 4. Check for "Build ... (website/portal/publication) for Brand" BEFORE loose title-dash heuristic
    m_for = re.search(
        r"(?i:(?:website|web\s+portal|portal|application|publication|platform|dashboard)\s+for)\s+(?:a\s+|an\s+|the\s+)?([A-Za-z0-9&'\-]+(?:\s+[A-Za-z0-9&'\-]+)*?)(?=,\s*a|\s*[\u2014\u2013]\s*|\s+-\s+|\s+(?:called|named|with|and|focused|providing|specializing|dedicated|offering|featuring|showcasing|delivering|building|selling|operating|developing|producing|that|which|where|built|designed|created)\b|[.,;\n]|\Z)",
        p,
    )
    if m_for:
        cleaned = _clean_candidate(m_for.group(1))
        if cleaned:
            return cleaned

    # 5. Check title line: Build/Create Brand — ... or direct Brand — Description
    # Require spaced hyphen or en/em-dash so mid-word hyphens like 'project-management' never split
    for line in p.splitlines()[:6]:
        line_s = line.strip()
        m_title_dash = re.search(
            r"^(?:#+\s*(?:Mission:\s*)?)?(?:Build|Create|Design|Develop)\s+(?:an?\s+|the\s+)?(?!website\b|web\s+portal\b|app\b|application\b|portal\b)([A-Za-z0-9\s&'.-]+?)(?:\s+[\u2014\u2013-]\s+|\s*[\u2014\u2013]\s*)",
            line_s,
            re.I,
        )
        if m_title_dash:
            cleaned = _clean_candidate(m_title_dash.group(1))
            if cleaned:
                return cleaned

        # Direct title line: Brand — Description (e.g. NOVA — Cutting-edge..., FORM & FIELD — ...)
        m_direct_dash = re.search(
            r"^(?:#+\s*(?:Mission:\s*)?)?(?!Build\b|Create\b|Design\b|Develop\b|Welcome\b|Website\b|The\s+following\b)([A-Z0-9][A-Za-z0-9\s&'.-]{1,50}?)(?:\s+[\u2014\u2013-]\s+|\s*[\u2014\u2013]\s+)",
            line_s,
        )
        if m_direct_dash:
            cleaned = _clean_candidate(m_direct_dash.group(1))
            if cleaned:
                return cleaned

    # 6. Natural language: called Brand / named Brand (must NOT match 'with brand identity')
    m_called = re.search(r'\b(?:called|named)\s+([A-Z0-9][A-Za-z0-9\s&-]{2,40})(?:[.,;\n]|\Z)', p)
    if m_called:
        cleaned = _clean_candidate(m_called.group(1))
        if cleaned:
            return cleaned

    # 7. Check title line: Build/Create/Design Brand, a/an/the ... OR Build Brand website
    for line in p.splitlines()[:6]:
        line_s = line.strip()
        m_title_comma = re.search(
            r"^(?:#+\s*(?:Mission:\s*)?)?(?:Build|Create|Design|Develop)\s+(?!a\b|an\b|the\b|some\b|modern\b|complex\b|website\b|web\b|app\b|application\b|portal\b|platform\b|dashboard\b)([A-Z0-9][A-Za-z0-9&'.-]*(?:\s+(?:[A-Z0-9&][A-Za-z0-9&'.-]*|and|of|the|&)){0,5})(?=\s*,\s*(?:a|an|the)\b)",
            line_s,
        )
        if m_title_comma:
            cleaned = _clean_candidate(m_title_comma.group(1))
            if cleaned:
                return cleaned
        m_title_end = re.search(
            r"^(?:#+\s*(?:Mission:\s*)?)?(?:Build|Create|Design|Develop)\s+(?:an?\s+|the\s+)?(?!website\b|web\s+portal\b|app\b|application\b|portal\b)([A-Za-z0-9\s&'.-]+?)(?:\s+website|\s+web\s+portal|[.;\n]|\Z)",
            line_s,
            re.I,
        )
        if m_title_end:
            cleaned = _clean_candidate(m_title_end.group(1))
            if cleaned:
                return cleaned

    return "Application"

class DesignBriefGenerator:
    """
    Synthesizes domain-tailored design briefs based on user prompt analysis
    and active skill instructions (taste-design, design-engineering, design-system).
    """

    DOMAIN_PALETTES = {
        "architecture_interior": {
            "primary": "#1c1d21",       # deep architectural charcoal
            "secondary": "#556b2f",     # muted olive
            "accent": "#8c7b65",        # warm stone / bronze
            "background": "#fbf9f5",    # warm ivory
            "surface": "#ffffff",       # pure white card surface
            "text_primary": "#1c1d21",  # deep charcoal
            "text_muted": "#6b7280",    # muted graphite
            "border": "#e5e2da",        # warm ivory border
        },
        "veterinary_pet_care": {
            "primary": "#0f766e",       # deep medical teal
            "secondary": "#14b8a6",     # friendly mint teal
            "accent": "#f59e0b",        # warm playful amber
            "background": "#f0fdfa",    # soft clean mint white
            "surface": "#ffffff",       # card surface
            "text_primary": "#134e4a",  # dark teal
            "text_muted": "#5eead4",    # soft teal
            "border": "#ccfbf1",        # gentle border
        },
        "legal_consulting": {
            "primary": "#1e293b",       # authoritative navy slate
            "secondary": "#0f172a",     # midnight slate
            "accent": "#c29b38",        # prestige legal gold
            "background": "#f8fafc",    # clean crisp white
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_muted": "#475569",
            "border": "#e2e8f0",
        },
        "architecture_interior": {
            "heading_font": "'Playfair Display', 'Cormorant Garamond', 'Cinzel', Georgia, serif",
            "body_font": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
            "scale": "1.333 (Perfect Fourth)",
            "base_size": "16px",
        },
        "veterinary_pet_care": {
            "heading_font": "'Plus Jakarta Sans', system-ui, -apple-system, sans-serif",
            "body_font": "'Inter', -apple-system, system-ui, sans-serif",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "legal_consulting": {
            "heading_font": "'Cinzel', 'Merriweather', Georgia, serif",
            "body_font": "'Inter', -apple-system, system-ui, sans-serif",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "robotics_automation": {
            "primary": "#00d2ff",       # electric cyan
            "secondary": "#162032",     # midnight navy
            "accent": "#10b981",        # subtle precision lime
            "background": "#0b0f17",    # deep graphite obsidian
            "surface": "#131b28",       # industrial card surface
            "text_primary": "#f8fafc",  # bright crisp white
            "text_muted": "#94a3b8",    # precision silver
            "border": "#243248",        # engineered boundary
        },
        "healthcare_medical": {
            "primary": "#0284c7",       # clinical cyan / sky
            "secondary": "#0f766e",     # deep medical teal
            "accent": "#10b981",        # health green
            "background": "#f8fafc",    # sterile warm white
            "surface": "#ffffff",       # card surface
            "text_primary": "#0f172a",  # slate 900
            "text_muted": "#475569",    # slate 600
            "border": "#e2e8f0",        # clean border
        },
        "real_estate": {
            "primary": "#0f172a",       # luxury obsidian
            "secondary": "#78350f",     # warm bronze
            "accent": "#d97706",        # architectural amber
            "background": "#fafaf9",    # warm stone white
            "surface": "#ffffff",       # clean white
            "text_primary": "#1c1917",  # warm ink
            "text_muted": "#78716c",    # stone muted
            "border": "#e7e5e4",        # warm border
        },
        "logistics_supply_chain": {
            "primary": "#0369a1",       # maritime blue
            "secondary": "#0f172a",     # industrial navy
            "accent": "#f59e0b",        # logistics amber
            "background": "#f8fafc",
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_muted": "#64748b",
            "border": "#e2e8f0",
        },
        "travel_tourism": {
            "primary": "#0e7490",       # deep cyan / ocean teal
            "secondary": "#0369a1",     # azure sky
            "accent": "#f59e0b",        # warm sunset amber
            "background": "#f8fafc",    # crisp warm white
            "surface": "#ffffff",       # card surface
            "text_primary": "#0f172a",  # slate 900
            "text_muted": "#64748b",    # slate 500
            "border": "#e2e8f0",        # slate 200
        },
        "culinary_restaurant": {
            "primary": "#b45309",       # artisanal amber / coffee
            "secondary": "#78350f",     # rich espresso
            "accent": "#d97706",        # golden crust
            "background": "#fbf9f5",    # warm canvas
            "surface": "#ffffff",       # pure white
            "text_primary": "#1c1917",  # warm ink
            "text_muted": "#78716c",    # warm stone
            "border": "#e7e5e4",        # warm gray
        },
        "saas_tech": {
            "primary": "#4f46e5",       # indigo
            "secondary": "#6366f1",     # modern violet
            "accent": "#10b981",        # emerald success
            "background": "#0f172a",    # dark obsidian
            "surface": "#1e293b",       # slate surface
            "text_primary": "#f8fafc",  # bright slate
            "text_muted": "#94a3b8",    # muted slate
            "border": "#334155",        # subtle dark border
        },
        "ecommerce_electronics": {
            "primary": "#0284c7",       # electric blue / tech cyan
            "secondary": "#0f172a",     # deep charcoal obsidian
            "accent": "#38bdf8",        # vibrant blue / subtle silver
            "background": "#0b0f17",    # dark obsidian
            "surface": "#1e293b",       # sleek slate surface
            "text_primary": "#f8fafc",  # crisp bright white
            "text_muted": "#94a3b8",    # subtle silver
            "border": "#334155",        # modern border
        },
        "ecommerce_store": {
            "primary": "#0284c7",
            "secondary": "#0f172a",
            "accent": "#38bdf8",
            "background": "#0b0f17",
            "surface": "#1e293b",
            "text_primary": "#f8fafc",
            "text_muted": "#94a3b8",
            "border": "#334155",
        },
        "ecommerce_marketplace": {
            "primary": "#1c1d21",       # charcoal
            "secondary": "#2d5a27",     # forest green
            "accent": "#556b2f",        # earthy olive
            "accent_secondary": "#c5a880", # warm sand/stone
            "background": "#fbf9f5",    # warm off-white canvas
            "surface": "#ffffff",
            "surface_border": "#e4e4e7",
            "text_primary": "#1c1d21",
            "text_muted": "#52525b",
            "border": "#e4e4e7",
        },
        "fintech_commerce": {
            "primary": "#0f766e",       # deep teal / trust
            "secondary": "#115e59",     # pine
            "accent": "#eab308",        # gold
            "background": "#f8fafc",    # clean white
            "surface": "#ffffff",
            "text_primary": "#020617",
            "text_muted": "#475569",
            "border": "#cbd5e1",
        },
        "automotive_luxury": {
            "primary": "#e11d48",       # velocity red
            "secondary": "#0f172a",     # carbon black
            "accent": "#fbbf24",        # tachometer amber
            "background": "#020617",    # midnight black
            "surface": "#0f172a",       # carbon surface
            "text_primary": "#f8fafc",
            "text_muted": "#94a3b8",
            "border": "#1e293b",
        },
        "education_institution": {
            "primary": "#1e3a8a",       # collegiate navy
            "secondary": "#1d4ed8",     # royal blue
            "accent": "#b45309",        # heritage bronze
            "background": "#fcfbf9",    # warm ivory
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_muted": "#475569",
            "border": "#e2e8f0",
        },
        "creative_portfolio": {
            "primary": "#18181b",       # minimalist zinc
            "secondary": "#27272a",     # muted zinc
            "accent": "#3b82f6",        # sharp cobalt
            "background": "#fafafa",    # minimalist off-white
            "surface": "#ffffff",
            "text_primary": "#09090b",
            "text_muted": "#71717a",
            "border": "#e4e4e7",
        },
        "modern_editorial": {
            "primary": "#1e293b",
            "secondary": "#334155",
            "accent": "#2563eb",
            "background": "#f8fafc",
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_muted": "#64748b",
            "border": "#e2e8f0",
        },
        "editorial_publication": {
            "primary": "#111827",       # deep editorial ink
            "secondary": "#1f2937",
            "accent": "#0f766e",        # archival emerald teal
            "accent_secondary": "#b45309", # amber footnote accent
            "background": "#faf9f5",    # warm newsprint ivory
            "surface": "#ffffff",
            "text_primary": "#111827",
            "text_muted": "#4b5563",
            "border": "#e5e7eb",
        },
        "geospatial_intelligence": {
            "primary": "#0f172a",
            "secondary": "#1e293b",
            "accent": "#0ea5e9",
            "accent_secondary": "#10b981",
            "background": "#f8fafc",
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_muted": "#475569",
            "border": "#e2e8f0",
        },
    }

    DOMAIN_TYPOGRAPHY = {
        "robotics_automation": {
            "font_family_display": "'Inter', 'SF Pro Display', -apple-system, sans-serif",
            "font_family_body": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
            "h1_size": "clamp(2.5rem, 5vw, 4.2rem)",
            "h2_size": "clamp(2rem, 3.5vw, 3rem)",
            "h3_size": "clamp(1.25rem, 2vw, 1.75rem)",
            "body_size": "1rem",
            "line_height_base": "1.6",
            "font_weight_bold": "700",
        },
        "ecommerce_electronics": {
            "heading_font": "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
            "body_font": "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "ecommerce_store": {
            "heading_font": "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
            "body_font": "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "ecommerce_marketplace": {
            "heading_font": "'Plus Jakarta Sans', system-ui, -apple-system, sans-serif",
            "body_font": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
            "font_mono": "'JetBrains Mono', monospace",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "travel_tourism": {
            "heading_font": "'Plus Jakarta Sans', 'Segoe UI', system-ui, sans-serif",
            "body_font": "'Inter', -apple-system, system-ui, sans-serif",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "culinary_restaurant": {
            "heading_font": "'Playfair Display', Georgia, serif",
            "body_font": "'Inter', -apple-system, sans-serif",
            "scale": "1.333 (Perfect Fourth)",
            "base_size": "16px",
        },
        "saas_tech": {
            "heading_font": "'Inter', system-ui, sans-serif",
            "body_font": "'Inter', system-ui, sans-serif",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "automotive_luxury": {
            "heading_font": "'Montserrat', 'Arial Black', sans-serif",
            "body_font": "'Inter', system-ui, sans-serif",
            "scale": "1.333 (Perfect Fourth)",
            "base_size": "16px",
        },
        "modern_editorial": {
            "heading_font": "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
            "body_font": "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
        "editorial_publication": {
            "heading_font": "'Playfair Display', Georgia, 'Times New Roman', serif",
            "body_font": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
            "font_mono": "'JetBrains Mono', monospace",
            "scale": "1.333 (Perfect Fourth)",
            "base_size": "17px",
        },
        "geospatial_intelligence": {
            "heading_font": "'Plus Jakarta Sans', system-ui, -apple-system, sans-serif",
            "body_font": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
            "font_mono": "'JetBrains Mono', monospace",
            "scale": "1.25 (Major Third)",
            "base_size": "16px",
        },
    }

    @classmethod
    def detect_cuisine_subtype(cls, prompt: str) -> Optional[str]:
        p_clean = strip_negative_constraints(prompt or "")
        p_lower = p_clean.lower()
        domain = cls.detect_domain(prompt or "")
        if domain != "culinary_restaurant":
            return None
        import re
        if re.search(r'\b(indian|curry|tandoor|tandoori|biryani|paneer|tikka|naan|masala|roti|kebab|dal|korma|kulfi|rasmalai|gulab jamun|chaat|contemporary indian)\b', p_lower):
            return "Contemporary Indian"
        if re.search(r'\b(mediterranean|greek|mezze|tagine|lebanese|falafel|hummus)\b', p_lower):
            return "Artisanal Mediterranean"
        if re.search(r'\b(italian|pasta|pizza|trattoria|risotto)\b', p_lower):
            return "Regional Italian"
        if re.search(r'\b(japanese|sushi|ramen|izakaya|omakase)\b', p_lower):
            return "Contemporary Japanese"
        if re.search(r'\b(french|bistro|brasserie|patisserie)\b', p_lower):
            return "Modern French"
        if re.search(r'\b(saffron|stone)\b', p_lower) and not re.search(r'\b(mediterranean|greek|italian)\b', p_lower):
            return "Contemporary Indian"
        return "Artisanal Dining"

    @classmethod
    def detect_archetype(cls, prompt: str, domain: str = "") -> str:
        """
        Determines the primary application archetype independently from the business domain.
        Separates 'marketplace' from 'portfolio_studio', 'saas_product', 'ecommerce_store', etc.
        """
        p_lower = (prompt or "").lower()
        if not domain:
            domain = cls.detect_domain(prompt)

        if any(k in p_lower for k in [
            "marketplace", "materials marketplace", "digital marketplace", "b2b marketplace",
            "material recovery suppliers", "quote basket", "add to quote", "buy and sell",
            "catalog containing at least", "catalogue containing at least"
        ]):
            return "marketplace"
        if domain in ("architecture_interior", "creative_portfolio") or any(k in p_lower for k in [
            "architecture studio", "interior design studio", "architecture and interior",
            "portfolio", "architectural project", "studio manifesto", "spatial design"
        ]):
            return "portfolio_studio"
        if domain in ("saas_tech", "saas_software") or (any(k in p_lower for k in ["saas", "dashboard", "sprint planning", "pricing toggle"]) and any(w in p_lower for w in ["software", "saas", "developer", "cloud", "orbit"])):
            return "saas_product"
        if domain == "geospatial_intelligence" or any(k in p_lower for k in ["geospatial", "aerial surveying", "geomatics", "drone-based terrain", "lidar scanning", "skytrace"]):
            return "interactive_showcase"
        if domain == "education_institution" or any(k in p_lower for k in ["museum", "science center", "discovery museum", "planetarium dome", "sparkfield"]):
            return "interactive_showcase"
        if domain in ("travel_tourism", "tourism_adventure") or any(k in p_lower for k in ["expedition", "guided treks", "itinerary", "packing list"]):
            return "tourism_adventure"
        if domain in ("culinary_restaurant",) or any(k in p_lower for k in ["restaurant", "menu", "dining", "chef"]):
            return "culinary_restaurant"
        if domain in ("astronomy_observatory", "oceanographic_marine_research", "volcanology_geothermal_research") or any(k in p_lower for k in ["observatory", "research institute"]):
            return "research_institution"
        if domain == "editorial_publication" or any(k in p_lower for k in ["digital editorial", "journalism", "featured stories", "article categories", "reading-time", "newsletter subscription", "magazine"]):
            return "editorial_publication"
        if domain in ("ecommerce_electronics", "ecommerce_store"):
            return "ecommerce_store"
        return "interactive_showcase"

    @classmethod
    def detect_domain(cls, prompt: str) -> str:
        """
        Extracts the primary business domain using hierarchical intent classification:
        Primary Business Purpose > Secondary Catalogue Vocabulary > Generic Modifiers > Meta-instructions.
        Prevents secondary keywords (e.g. 'reclaimed architectural fixtures') from hijacking business domain.
        """
        p_clean = strip_negative_constraints(prompt or "")
        p_lower = p_clean.lower()
        lines = [l.strip() for l in p_lower.splitlines() if l.strip()]
        first_lines = " ".join(lines[:6])

        # Extract structured business fields: Business:, Concept:, Industry:, Primary Purpose:
        structured_business = ""
        for line in lines:
            m = re.search(r"^(?:#+\s*)?(?:\*{0,2}(?:business|concept|industry|primary purpose|product category)\*{0,2})\s*[:=]\s*(.+)$", line)
            if m:
                structured_business += " " + m.group(1).strip()

        primary_text = (first_lines + " " + structured_business).strip()

        scores = {
            "ecommerce_marketplace": 0,
            "robotics_automation": 0,
            "healthcare_medical": 0,
            "real_estate": 0,
            "logistics_supply_chain": 0,
            "ecommerce_electronics": 0,
            "culinary_restaurant": 0,
            "education_institution": 0,
            "travel_tourism": 0,
            "saas_tech": 0,
            "automotive_luxury": 0,
            "fintech_commerce": 0,
            "creative_portfolio": 0,
            "architecture_interior": 0,
            "veterinary_pet_care": 0,
            "legal_consulting": 0,
            "geospatial_intelligence": 0,
            "editorial_publication": 0,
        }

        # 1. High-weight intent in structured business fields or title / initial statement (40-45 pts)
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in [
            "marketplace", "materials marketplace", "digital marketplace", "b2b marketplace",
            "material recovery", "circular construction", "reclaimed and recycled", "buy and sell"
        ]):
            scores["ecommerce_marketplace"] += 45

        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in [
            "architecture studio", "interior design studio", "architectural studio", "architectural firm",
            "architecture firm", "architecture practice", "spatial design studio", "form & field", "form and field", "atelier kroma"
        ]):
            scores["architecture_interior"] += 45
        elif any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["architecture", "interior design", "spatial design"]) and not any(k in primary_text for k in ["marketplace", "materials", "recycled", "reclaimed"]):
            scores["architecture_interior"] += 30

        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["veterinary", "vet clinic", "pet care", "animal hospital", "veterinarian", "paws & claws", "paws and claws"]):
            scores["veterinary_pet_care"] += 40
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["law firm", "attorney", "legal services", "counsel", "lawyer", "litigation"]):
            scores["legal_consulting"] += 40
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["robotics", "robot", "robots", "atlas robotics", "robotic arm", "automation company", "autonomous mobile"]):
            scores["robotics_automation"] += 40
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["hospital", "clinic", "healthcare", "medical center", "patient care"]):
            scores["healthcare_medical"] += 35
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["real estate", "realty", "property management", "luxury villas", "apartments"]):
            scores["real_estate"] += 35
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["logistics", "freight forwarding", "supply chain management", "warehousing", "cargo"]):
            scores["logistics_supply_chain"] += 35
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["consumer electronics", "smartphones", "laptops", "headphones", "nova"]):
            scores["ecommerce_electronics"] += 35
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["restaurant", "dining", "kitchen", "culinary", "bistro", "cafe", "saffron & stone", "saffron and stone"]):
            scores["culinary_restaurant"] += 35
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in [
            "geospatial", "aerial surveying", "geomatics", "drone-based terrain", "lidar scanning",
            "volumetric stockpile", "skytrace", "aerial survey", "orthomosaic", "photogrammetry", "land surveys"
        ]):
            scores["geospatial_intelligence"] += 45
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in [
            "museum", "discovery museum", "science center", "innovation center", "children's science",
            "sparkfield", "planetarium", "university", "college", "northstar", "academy", "higher education"
        ]):
            scores["education_institution"] += 45
        elif any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["university", "college", "northstar", "academy", "higher education"]):
            scores["education_institution"] += 35
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in ["travel agency", "tourism", "wanderworld", "expedition", "vacation"]):
            scores["travel_tourism"] += 35
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in [
            "saas", "software as a service", "project-management", "project management", "workflow platform",
            "kanban", "billing switcher", "orbit pm", "b2b saas"
        ]):
            scores["saas_tech"] += 45
        if any(re.search(r'\b' + re.escape(k) + r'\b', primary_text) for k in [
            "editorial publication", "digital editorial", "journalism", "online magazine", "digital publication",
            "field journal", "featured stories", "newsroom", "newspaper", "publication"
        ]):
            scores["editorial_publication"] += 45

        # 2. Body keywords scoring - strictly domain-specific with word boundary matching
        body_keywords = {
            "ecommerce_marketplace": ["marketplace", "quote basket", "suppliers", "vendor", "catalog", "catalogue", "material recovery", "circular economy"],
            "robotics_automation": ["robotics", "robot", "robots", "robotic arm", "autonomous mobile", "cobot", "machine vision", "industrial automation", "intelligent automation", "inspection systems", "assembly automation"],
            "healthcare_medical": ["hospital", "clinic", "healthcare", "medical", "patient", "physician", "doctor", "health"],
            "real_estate": ["real estate", "realty", "property", "properties", "realtor", "villas", "condos", "listing"],
            "logistics_supply_chain": ["logistics", "supply chain", "freight", "warehousing", "cargo", "fleet", "shipping"],
            "ecommerce_electronics": ["smartphones", "laptops", "headphones", "smartwatches", "earbuds", "consumer electronics", "gadgets", "nova"],
            "culinary_restaurant": ["restaurant", "dining", "kitchen", "culinary", "bistro", "cafe", "menu", "chef", "dishes", "dish", "tasting", "cuisine", "tandoori", "biryani", "reservations", "reservation", "party-size", "gourmet", "spices", "cooking"],
            "education_institution": ["museum", "science center", "discovery center", "planetarium", "exhibits", "exhibit", "camps", "workshops", "stem", "discovery", "university", "college", "school", "academy", "curriculum", "courses", "education", "campus", "academic", "admissions", "degree", "faculty"],
            "geospatial_intelligence": ["geospatial", "geomatics", "surveying", "drone", "terrain", "lidar", "volumetric", "stockpile", "photogrammetry", "orthomosaic", "topographic", "mapping", "elevation"],
            "editorial_publication": ["editorial", "journalism", "publication", "magazine", "journal", "featured stories", "stories", "article", "articles", "reading-time", "newsletter", "contributors", "author"],
            "travel_tourism": ["wanderworld", "travel", "tourism", "vacation", "resort", "safari", "tourist", "airline", "flight", "itinerary", "holiday"],
            "saas_tech": ["saas", "dashboard", "kanban", "analytics", "developer", "cloud", "api", "ai engine", "infrastructure", "billing", "sprint"],
            "automotive_luxury": ["car", "automotive", "hypercar", "dealership", "vehicle", "race", "motor"],
            "fintech_commerce": ["fintech", "banking", "finance", "crypto", "trading", "investment"],
            "creative_portfolio": ["portfolio", "agency", "photographer", "creative studio", "designer showcase"],
            "architecture_interior": ["architecture studio", "architectural studio", "interior design studio", "blueprints", "residence", "spatial design", "building design"],
            "veterinary_pet_care": ["veterinary", "vet", "pets", "pet", "animal", "canine", "feline", "vaccination", "surgery", "pet care"],
            "legal_consulting": ["legal", "law firm", "attorney", "lawyer", "litigation", "counsel", "practice areas", "consultation", "corporate law"],
        }

        for d, words in body_keywords.items():
            for w in words:
                scores[d] += len(re.findall(r'\b' + re.escape(w) + r'\b', p_lower))

        # Secondary keyword disambiguation: marketplace intent overrides secondary architectural fixtures
        if scores["ecommerce_marketplace"] > 0:
            scores["architecture_interior"] = 0

        best_domain = max(scores, key=scores.get)
        if scores[best_domain] < 3:
            return "modern_editorial"
        return best_domain

    @classmethod
    def generate_brief(
        cls,
        prompt: str,
        active_skills: Optional[List[str]] = None,
    ) -> DesignBrief:
        domain = cls.detect_domain(prompt)
        palette = dict(cls.DOMAIN_PALETTES.get(domain, cls.DOMAIN_PALETTES["modern_editorial"]))
        custom_colors = extract_prompt_color_palette(prompt)
        if custom_colors:
            palette.update(custom_colors)
        typo = cls.DOMAIN_TYPOGRAPHY.get(domain, cls.DOMAIN_TYPOGRAPHY["modern_editorial"])

        personalities = {
            "architecture_interior": "Refined, spatial, monolithic, serene, tactile materiality, sustainable craftsmanship",
            "veterinary_pet_care": "Compassionate, clinical, warm, friendly, reassuring, expert care",
            "legal_consulting": "Authoritative, distinguished, precise, strategic, discreet",
            "robotics_automation": "Engineered, authoritative, futuristic, high-precision, industrial innovation",
            "healthcare_medical": "Compassionate, clinical, trustworthy, patient-centric, serene",
            "real_estate": "Sophisticated, architectural, high-end, spacious, prestigious",
            "logistics_supply_chain": "Efficient, reliable, global, connected, robust",
            "travel_tourism": "Wanderlust, inspiring, luxurious, modern, breathable, vibrant",
            "culinary_restaurant": "Warm, artisanal, grounded, sensory, welcoming",
            "ecommerce_electronics": "Sleek, innovative, authoritative, high-performance, precision-engineered",
            "ecommerce_store": "Sleek, innovative, authoritative, high-performance, precision-engineered",
            "ecommerce_marketplace": "Industrial sustainability, trustworthy, circular economy, transparent, tactile materiality",
            "saas_tech": "Engineered, precise, cutting-edge, dependable, dark-mode polished",
            "automotive_luxury": "High-velocity, aerodynamic, aggressive elegance, precision",
            "fintech_commerce": "Authoritative, trustworthy, modern, crystal clear",
            "education_institution": "Scholarly, distinguished, structured, accessible",
            "creative_portfolio": "Minimalist, editorial, typography-driven, showcase",
            "modern_editorial": "Clean, contemporary, balanced, intuitive",
            "editorial_publication": "Intellectual, journalistic, investigative, long-form clarity, archival restraint",
        }

        visual_directions = {
            "architecture_interior": "Warm ivory, charcoal, and muted olive color palette. Architectural project showcase grid, monolithic hero, material inspection modal, and consultation form.",
            "veterinary_pet_care": "Deep medical teal, friendly mint, and warm amber accents. Patient care services showcase, appointment request form, and care detail modal.",
            "legal_consulting": "Authoritative navy slate, midnight slate, and prestige gold accents. Practice areas matrix, attorney profiles, and confidential consultation form.",
            "travel_tourism": "Hero showcase with expansive photography, glassmorphism destination cards, interactive category pills, and modal itinerary inspection.",
            "culinary_restaurant": "Sensory photography, warm organic tones, distinct menu grids, and accessible ordering actions.",
            "ecommerce_electronics": "Deep charcoal, crisp white, electric blue, and subtle silver accents. Modern technology cards, interactive category pills, real-time cart drawer, and modal product inspection.",
            "ecommerce_store": "Deep charcoal, crisp white, electric blue, and subtle silver accents. Modern technology cards, interactive category pills, real-time cart drawer, and modal product inspection.",
            "ecommerce_marketplace": "Warm off-white, forest green, and charcoal color palette. Material catalogue grid, price sorting, interactive quote basket, material detail modal, and supplier inquiry form.",
            "saas_tech": "Metric stat cards, interactive feature toggles, high-contrast code/preview blocks, and subtle gradient borders.",
            "automotive_luxury": "Dramatic dark contrast, high-resolution vehicle cards, spec comparison tables, and subtle hover glows.",
            "fintech_commerce": "Clean ledger cards, clear transaction workflows, accessible contrast, and zero layout shift.",
            "education_institution": "Organized faculty/course cards, calendar view, structured admission forms, and high-readability text.",
            "creative_portfolio": "Asymmetric visual grid, expansive whitespace, custom cursor interactions, and responsive media tiles.",
            "modern_editorial": "Harmonious vertical rhythm, modular card layouts, clear visual hierarchy, and polished interactive controls.",
            "editorial_publication": "Warm archival ivory newsprint canvas, serif display headlines, lead featured dispatch, article reader modal with related stories, and validated newsletter subscription.",
        }

        component_styling = {
            "card_radius": "12px" if domain in ("travel_tourism", "saas_tech") else "8px",
            "button_radius": "9999px" if domain == "travel_tourism" else "6px",
            "card_shadow": "0 4px 20px -2px rgba(0, 0, 0, 0.08)",
            "card_border": f"1px solid {palette.get('border', '#e2e8f0')}",
            "transition_speed": "0.2s ease-in-out",
        }

        image_direction = {
            "hero_aspect": "16/9",
            "aspect_ratio": "4/3",
            "object_fit": "cover",
            "border_radius": "12px 12px 0 0",
            "guideline": "High-quality, location-appropriate photography; enforce object-fit: cover and fixed aspect-ratios to prevent layout shifts.",
        }

        spacing_system = {
            "xs": "0.25rem",
            "sm": "0.5rem",
            "md": "1rem",
            "lg": "1.5rem",
            "xl": "2.5rem",
            "2xl": "4rem",
            "container_max_width": "1200px",
        }

        breakpoints = {
            "mobile_max": "768px",
            "tablet_max": "1024px",
            "desktop_min": "1025px",
        }

        brand_positionings = {
            "architecture_interior": "Independent architecture and interior design studio crafting timeless spaces with sustainable materials.",
            "veterinary_pet_care": "Comprehensive pet wellness, advanced surgical care, and compassionate veterinary services.",
            "legal_consulting": "Premier legal counsel and litigation defense delivering trusted advocacy and strategic solutions.",
            "travel_tourism": "Premier luxury and experiential travel agency showcasing world-class holiday destinations and curated travel packages.",
            "culinary_restaurant": "Artisanal gastronomy and neighborhood dining experience celebrating organic, locally sourced delicacies.",
            "ecommerce_electronics": "Cutting-edge consumer electronics brand offering premium personal technology, smartphones, laptops, audio, smartwatches, and gaming gear.",
            "ecommerce_store": "Cutting-edge consumer electronics brand offering premium personal technology, smartphones, laptops, audio, smartwatches, and gaming gear.",
            "ecommerce_marketplace": "Circular construction materials marketplace connecting builders, architects, and suppliers with high-quality reclaimed and recycled materials.",
            "saas_tech": "Next-generation developer infrastructure providing intelligent, high-throughput cloud automation.",
            "automotive_luxury": "High-performance automotive engineering delivering peerless aerodynamics and ultra-luxury performance.",
            "fintech_commerce": "Next-generation digital banking platform offering secure, borderless capital management.",
            "education_institution": "World-class educational institution fostering academic excellence and multidisciplinary innovation.",
            "creative_portfolio": "Award-winning independent design studio crafting digital products, identities, and visual systems.",
            "modern_editorial": "Sophisticated digital publication delivering incisive cultural commentary and long-form journalism.",
        }

        layout_strategies = {
            "architecture_interior": "Monolithic hero with studio manifesto, 3-column architectural project grid with category filters and live search, sustainable philosophy split-section, project detail modal, and consultation booking form.",
            "veterinary_pet_care": "Welcoming clinic hero, 3-column clinical services grid with category filters and search, doctor profiles, emergency care banner, appointment booking form, and detail modal.",
            "legal_consulting": "Prestige hero with legal practice areas matrix, landmark case results, partner profiles, client perspectives, and confidential consultation booking.",
            "travel_tourism": "Cinematic hero with integrated booking/search bar, fluid 1200px container, 3-column responsive destination card grid, 2-column curated package cards, customer review showcase, accessible enquiry form, and rich dark footer.",
            "culinary_restaurant": "Atmospheric full-width hero, two-column story layout, tabbed multi-course menu grid, table reservation form, and map/contact section.",
            "ecommerce_electronics": "Sticky brand navigation with live cart count, full-width technology hero, category filter pills, responsive 12-product grid with search and sort, feature highlights, and interactive cart/product modals.",
            "ecommerce_store": "Sticky brand navigation with live cart count, full-width technology hero, category filter pills, responsive 12-product grid with search and sort, feature highlights, and interactive cart/product modals.",
            "ecommerce_marketplace": "Industrial sustainability hero with marketplace stats, material search and category filter pills, responsive 8-item materials grid with price sorting and modal view, real-time quote basket with quantity/subtotal calculation, supplier onboarding steps, and material inquiry form.",
            "saas_tech": "Hero headline with animated code demo or product dashboard mockup, key metric highlight grid, interactive feature comparison, pricing tier cards, and FAQ accordion.",
            "automotive_luxury": "Dramatic full-screen vehicle hero, interactive model selector, technical performance specifications grid, 360-degree gallery, and bespoke consultation booking.",
            "fintech_commerce": "Trust-focused hero with security badges, interactive savings/fee calculator, feature card matrix, customer testimonial carousel, and sign-up form.",
            "education_institution": "Campus hero, program catalog grid, admissions step timeline, faculty profiles, and student inquiry form.",
            "creative_portfolio": "Asymmetric visual masonry grid, full-bleed case study cards with interactive hover previews, client logo reel, and direct project contact form.",
            "modern_editorial": "Multi-column magazine layout, lead feature article with prominent photography, curated category sections, and newsletter signup.",
        }

        navigation_strategies = {
            "travel_tourism": "Sticky top navigation with smooth scroll anchors to #destinations, #packages, #reviews, #booking.",
            "culinary_restaurant": "Sticky navigation with smooth scroll to #story, #menu, #reservations, #contact.",
            "ecommerce_marketplace": "Sticky header with brand logo, smooth scroll links to #materials, #how-it-works, #quote-basket, #sustainability, #contact, and quote basket counter badge.",
            "saas_tech": "Fixed header with product links, documentation, pricing anchor, and Sign Up / Demo CTA button.",
            "automotive_luxury": "Minimalist header with models menu, engineering highlights, and Test Drive CTA button.",
            "fintech_commerce": "Clean top bar with solutions dropdown, security overview, pricing, and Open Account button.",
            "education_institution": "Top utility bar with student portal link and main navigation for programs, admissions, and campus life.",
            "creative_portfolio": "Minimal sticky navbar with work, about, services, and Let's Talk CTA button.",
            "modern_editorial": "Top masthead with issue date, publication logo, section categories, and search trigger.",
        }

        component_languages = {
            "travel_tourism": {
                "navbar": "Fixed/sticky glassmorphism navigation (height: 64-76px) with brand logo, anchor links with hover indicators, rounded CTA button, and compact mobile hamburger toggle (<button class='mobile-menu-btn' aria-label='Toggle navigation' aria-expanded='false'><span></span><span></span><span></span></button>). Prohibit raw text 'Menu'.",
                "hero": "Expansive full-bleed photographic hero (background-size: cover; min-height: 85vh; position: relative; overflow: hidden;) with full-bleed absolute gradient overlay (position: absolute; inset: 0; z-index: 1; pointer-events: none;) and high-contrast typography in relative z-index: 2 container. Prohibit partial boxed overlay bands.",
                "card": "Modern card with fixed 4/3 photography header, badge for trip category, star rating, price per person, and interactive details CTA",
                "filter_pills": "Horizontal flex pill buttons with active status styling and smooth transition",
                "modal": "Full-screen backdrop blur modal with centered travel itinerary dialog, gallery preview, price breakdown, and booking trigger",
                "form": "Polished responsive booking enquiry form with clean labeled inputs, date selector, passenger counter, and feedback alert",
                "footer": "Rich 4-column footer with agency info, quick links, newsletter form, and copyright"
            },
            "culinary_restaurant": {
                "navbar": "Warm navigation (height: 64-76px) with logo crest, reservations CTA, and compact mobile hamburger icon toggle (aria-label='Toggle navigation'). Prohibit raw text 'Menu'.",
                "hero": "Full-bleed dark sensory food photography (min-height: 80vh; position: relative;) with full-bleed absolute gradient overlay (inset: 0; z-index: 1;) and relative z-index: 2 reservation CTA.",
                "menu_card": "Minimalist dish listing with title, dietary tags, price, and provenance description",
                "reservation_form": "Inline date/time picker, party size selector, and confirmation modal",
                "footer": "Warm stone footer with opening hours, address, and social links"
            },
            "ecommerce_marketplace": {
                "navbar": "Sticky header (height: 64-76px) with brand logo, smooth scroll links to #materials, #how-it-works, #quote-basket, #sustainability, #contact, and quote basket counter badge.",
                "hero": "Expansive hero with high-contrast headline, marketplace metrics (tons diverted, active suppliers, verified materials), and primary CTA to browse inventory.",
                "card": "Material specification card with photographic header, category badge, technical grade/specification, unit price, stock status, and add-to-quote / details triggers.",
                "quote_basket": "Interactive quote basket with itemized table, quantity adjustments, live subtotal calculation, and quote request submission.",
                "modal": "Material detail inspection modal with environmental impact specs, provenance, physical dimensions, and close controls.",
                "form": "Supplier onboarding and material quote inquiry form with instant client-side validation and demonstration feedback alert.",
                "footer": "Comprehensive 4-column footer with marketplace links, circular economy manifesto, supplier portal, and copyright."
            },
        }

        interaction_specifications = {
            "travel_tourism": {
                "filter": "Instant client-side filter updating visible destination cards by category pills and keyword search",
                "modal": "View Details opens itinerary modal with dynamic content and trap focus; closes on close-button, Escape key, or outside click",
                "booking": "Enquiry form validation for required fields with immediate success banner upon submission"
            },
            "culinary_restaurant": {
                "menu_filter": "Filter menu courses (Appetizers, Mains, Desserts, Cocktails)",
                "reservation": "Table reservation validation with guest count and date checking"
            },
            "ecommerce_marketplace": {
                "search_filter": "Instant search and category pill filtering of reclaimed materials inventory",
                "sorting": "Price and availability sorting (low-high, high-low, alphabetical)",
                "quote_basket": "Add to quote basket with quantity increment/decrement and live subtotal update",
                "modal": "Inspect material technical specifications with trap focus and Escape/backdrop close",
                "inquiry": "Submit material inquiry or supplier onboarding form with demonstration disclosure banner"
            },
        }

        asset_plans = {
            "travel_tourism": [
                "assets/images/hero/hero-wanderlust.jpg",
                "assets/images/destinations/bali.jpg",
                "assets/images/destinations/switzerland.jpg",
                "assets/images/destinations/paris.jpg",
                "assets/images/destinations/dubai.jpg",
                "assets/images/destinations/maldives.jpg",
                "assets/images/destinations/japan.jpg",
                "assets/images/packages/bali-package.jpg",
                "assets/images/packages/swiss-package.jpg",
                "assets/images/packages/paris-package.jpg",
            ],
            "culinary_restaurant": [
                "assets/images/hero/restaurant-hero.jpg",
                "assets/images/menu/artisan-dish1.jpg",
                "assets/images/menu/artisan-dish2.jpg",
            ],
            "ecommerce_marketplace": [
                "assets/images/hero/hero-materials.jpg",
                "assets/images/products/timber.jpg",
                "assets/images/products/steel.jpg",
                "assets/images/products/bricks.jpg",
                "assets/images/products/glass-aggregates.jpg",
                "assets/images/products/concrete.jpg",
                "assets/images/products/stone.jpg",
                "assets/images/products/insulation.jpg",
                "assets/images/products/fixtures.jpg",
            ],
        }

        cuisine_subtype = cls.detect_cuisine_subtype(prompt) if domain == "culinary_restaurant" else ""
        p_clean = strip_negative_constraints(prompt or "")
        p_clean_lower = p_clean.lower()
        detected_b = cls.detect_brand_name(prompt) if hasattr(cls, 'detect_brand_name') else detect_brand_name(prompt)
        if detected_b and detected_b not in ("Application", "Modern Application"):
            brand_name = detected_b
        elif "nova" in p_clean_lower:
            brand_name = "NOVA"
        elif "northstar" in p_clean_lower:
            brand_name = "NorthStar University"
        elif "wanderworld" in p_clean_lower:
            brand_name = "WanderWorld"
        elif ("saffron" in p_clean_lower or "stone" in p_clean_lower) and domain == "culinary_restaurant":
            brand_name = "Saffron & Stone"
        elif domain == "robotics_automation":
            brand_name = "ATLAS Robotics"
        else:
            brand_name = detected_b or "Application"
        pos = "Premium Contemporary Indian dining celebrating heritage clay oven tandoor cooking, dum biryani, and aromatic spices." if cuisine_subtype == "Contemporary Indian" else brand_positionings.get(domain, "High quality digital web experience.")
        vis = "Warm royal saffron and terracotta palette, rich brass and earthenware accents, evocative clay oven and spice photography, and zero fabricated credentials." if cuisine_subtype == "Contemporary Indian" else visual_directions.get(domain, "Crisp modular layout with balanced whitespace")

        return DesignBrief(
            domain=domain,
            brand_identity=brand_name,
            cuisine_subtype=cuisine_subtype,
            requested_content=["paneer tikka", "dum biryani", "tandoori specialties", "indian breads", "traditional desserts"] if cuisine_subtype == "Contemporary Indian" else [],
            purpose=f"Modern {domain.replace('_', ' ').title()} Web Experience",
            target_audience="Discerning patrons seeking authentic high-end Indian dining" if cuisine_subtype == "Contemporary Indian" else "Discerning users seeking high quality, intuitive exploration and seamless interaction",
            brand_personality="Aromatic, heritage-driven, refined, warm, sensory" if cuisine_subtype == "Contemporary Indian" else personalities.get(domain, "Modern, clean, polished"),
            visual_direction=vis,
            color_palette=palette,
            typography=typo,
            spacing_system=spacing_system,
            component_styling=component_styling,
            image_direction=image_direction,
            responsive_breakpoints=breakpoints,
            brand_positioning=brand_positionings.get(domain, "High quality digital web experience with intuitive interaction and refined visual design."),
            layout_strategy=layout_strategies.get(domain, "Structured modular layout with centered container, consistent spacing, and responsive card grids."),
            component_language=component_languages.get(domain, {
                "navbar": "Clean header (height: 64-76px) with logo, links, action button, and compact hamburger toggle (<button class='mobile-menu-btn' aria-label='Toggle navigation' aria-expanded='false'><span></span><span></span><span></span></button>). Prohibit raw text 'Menu'.",
                "hero": "Full-bleed photographic hero (background-size: cover; min-height: 85vh; position: relative; overflow: hidden;) with full-bleed absolute gradient overlay (position: absolute; inset: 0; z-index: 1;) and high-contrast typography in relative z-index: 2 container. Prohibit partial boxed overlay bands.",
                "card": "Structured cards with consistent typography, padding, and subtle shadows",
                "footer": "Standard footer with copyright and essential links",
            }),
            navigation_strategy=navigation_strategies.get(domain, "Sticky top navigation with responsive mobile menu."),
            interaction_specs=interaction_specifications.get(domain, {
                "interactive": "Clean DOM event handlers, validation on user inputs, and accessible state feedback"
            }),
            asset_plan_requirements=asset_plans.get(domain, []),
        )


@dataclass
class ContentCoverageSection:
    section_id: str
    title: str
    status: str = "NOT_STARTED"  # NOT_STARTED, IMPLEMENTED, VERIFIED
    description: str = ""
    dom_id: Optional[str] = None
    elements_found: List[str] = field(default_factory=list)


@dataclass
class ContentCoverageMap:
    """
    Tracks and preserves the complete multi-section content specification
    for rich website missions, ensuring no section is quietly dropped.
    """
    domain: str
    sections: Dict[str, ContentCoverageSection] = field(default_factory=dict)
    required_cards: List[str] = field(default_factory=list)
    required_interactions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "sections": {k: asdict(v) for k, v in self.sections.items()},
            "required_cards": self.required_cards,
            "required_interactions": self.required_interactions,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContentCoverageMap:
        cmap = cls(
            domain=data.get("domain", "general"),
            required_cards=list(data.get("required_cards", [])),
            required_interactions=list(data.get("required_interactions", [])),
        )
        for s_id, s_data in data.get("sections", {}).items():
            cmap.sections[s_id] = ContentCoverageSection(
                section_id=s_data.get("section_id", s_id),
                title=s_data.get("title", s_id),
                status=s_data.get("status", "NOT_STARTED"),
                description=s_data.get("description", ""),
                dom_id=s_data.get("dom_id"),
                elements_found=list(s_data.get("elements_found", [])),
            )
        return cmap

    @classmethod
    def from_prompt(cls, prompt: str) -> ContentCoverageMap:
        """Parse user prompt and extract all mandatory sections, cards, and interactions."""
        p_lower = prompt.lower()
        domain = DesignBriefGenerator.detect_domain(prompt)
        cmap = cls(domain=domain)

        # 1. Navigation / Header
        cmap.sections["nav"] = ContentCoverageSection(
            section_id="nav",
            title="Navigation Header",
            description="Brand logo, navigation links, and call-to-action button",
            dom_id="navbar",
        )

        # 2. Hero Section
        cmap.sections["hero"] = ContentCoverageSection(
            section_id="hero",
            title="Hero Presentation",
            description="Compelling headline, subtitle, primary CTA, and background/hero image",
            dom_id="hero",
        )

        if domain == "education_institution":
            # Academic divisions / schools
            cmap.sections["academics"] = ContentCoverageSection(
                section_id="academics",
                title="Academic Schools & Divisions",
                description="Showcase of university colleges and schools (Engineering, Arts & Sciences, Business, Medicine)",
                dom_id="academics",
            )
            # Degree programs catalog / cards
            cmap.sections["programs"] = ContentCoverageSection(
                section_id="programs",
                title="Featured Degree Programs",
                description="Interactive cards for undergraduate and graduate programs with degree level, school, and curriculum",
                dom_id="programs",
            )
            cmap.required_cards = [
                "B.S. in Computer Science & Artificial Intelligence",
                "M.S. in Biomedical Engineering",
                "Full-Time Master of Business Administration",
                "Ph.D. in Theoretical Physics",
                "B.A. in Environmental Architecture",
                "M.A. in Philosophy & Cognitive Science",
            ]
            # Search & Filter by school
            cmap.sections["filter"] = ContentCoverageSection(
                section_id="filter",
                title="Interactive Program Search & School Filter",
                description="Filter buttons/pills (All Schools, Engineering, Business, Arts & Sciences, Medicine) and keyword search",
                dom_id="filters",
            )
            cmap.required_interactions.append("category_filtering")
            cmap.required_interactions.append("search_keyword")

            # Admissions timeline & stats
            cmap.sections["admissions"] = ContentCoverageSection(
                section_id="admissions",
                title="Admissions & Financial Aid Timeline",
                description="Application deadlines, financial aid statistics, and enrollment requirements",
                dom_id="admissions",
            )

            # Faculty grid
            cmap.sections["faculty"] = ContentCoverageSection(
                section_id="faculty",
                title="Distinguished Faculty & Research Chairs",
                description="Faculty member profiles with department, title, publications, and lab affiliations",
                dom_id="faculty",
            )

            # Campus Life & Student Testimonials
            cmap.sections["campus_life"] = ContentCoverageSection(
                section_id="campus_life",
                title="Campus Life & Student Experience",
                description="Student housing, campus activities, traditions, and athletics overview",
                dom_id="campus-life",
            )

            # Testimonials / Alumni
            cmap.sections["reviews"] = ContentCoverageSection(
                section_id="reviews",
                title="Student & Alumni Voices",
                description="Testimonials and career outcomes from distinguished graduates and student researchers",
                dom_id="testimonials",
            )

            # FAQ Accordion
            cmap.sections["faq"] = ContentCoverageSection(
                section_id="faq",
                title="Admissions & Campus FAQ",
                description="Interactive accordion addressing common applicant and visitor questions",
                dom_id="faq",
            )
            cmap.required_interactions.append("faq_accordion")

            # Interactive Detail Modal
            cmap.sections["modal"] = ContentCoverageSection(
                section_id="modal",
                title="Interactive Program Detail Modal",
                description="Deep dive modal with curriculum breakdown, credit hours, faculty leads, and direct application CTA",
                dom_id="inquiry-modal",
            )
            cmap.required_interactions.append("modal_open_close")

            # Inquiry Form
            cmap.sections["booking"] = ContentCoverageSection(
                section_id="booking",
                title="Admissions Inquiry & Campus Visit Form",
                description="Validated inquiry form with Name, Email, Desired Program, and Campus Visit Date",
                dom_id="inquiry-form",
            )
            cmap.required_interactions.append("form_validation_and_submit")

        elif domain == "culinary_restaurant":
            cuisine = DesignBriefGenerator.detect_cuisine_subtype(prompt)
            is_indian = cuisine == "Contemporary Indian"
            
            # 1. Story / Heritage
            cmap.sections["story"] = ContentCoverageSection(
                section_id="story",
                title="Restaurant Introduction & Culinary Story",
                description="Contemporary Indian gastronomy, clay tandoor heritage, and artisanal spice mastery" if is_indian else "Artisanal culinary philosophy, stone oven heritage, and Mediterranean craftsmanship",
                dom_id="story",
            )
            # 2. Signature Menu & Dishes
            cmap.sections["menu"] = ContentCoverageSection(
                section_id="menu",
                title="Signature Culinary Menu & Dishes",
                description="Interactive gourmet dishes catalog with category, description, price, allergens, and pairing",
                dom_id="menu",
            )
            if is_indian:
                cmap.required_cards = [
                    "Charred Saffron Paneer Tikka",
                    "Awadhi Lamb Dum Biryani",
                    "Tandoori Spiced Wild Salmon",
                    "Smoked Cardamom Tandoori Lamb Chops",
                    "Old Delhi Butter Chicken",
                    "24-Hour Dal Makhani",
                    "Wood-Fired Truffle Kulcha",
                    "Clay Oven Garlic Coriander Naan",
                    "Kashmiri Saffron & Pistachio Kulfi",
                    "Warm Saffron Gulab Jamun",
                    "Artisanal Avocado Dahi Puri",
                    "Smoked Star Anise Old Fashioned",
                ]
            else:
                cmap.required_cards = [
                    "Saffron Seafood Tagine",
                    "Crispy Mediterranean Seabass",
                    "Wood-Fired Prime Ribeye",
                    "Heirloom Beetroot Carpaccio",
                    "Artisanal Stone Mezze Platter",
                    "Pistachio Saffron Mille-Feuille",
                    "Truffled Wild Mushroom Risotto",
                    "Charred Octopus with Romesco",
                    "Slow-Braised Lamb Shank",
                    "Spiced Fig & Goat Cheese Tart",
                    "Wood-Roasted Prawns",
                    "Dark Chocolate Cardamom Torte",
                ]
            # 3. Interactive Category Filter & Search
            cmap.sections["filter"] = ContentCoverageSection(
                section_id="filter",
                title="Interactive Menu Filter & Search",
                description="Category pills (All, Starters, Mains, Wood-Fired, Seafood, Desserts) and dish search input",
                dom_id="filters",
            )
            cmap.required_interactions.append("category_filtering")
            cmap.required_interactions.append("search_keyword")

            # 4. Executive Chef Profile
            cmap.sections["chef"] = ContentCoverageSection(
                section_id="chef",
                title="Executive Chef & Culinary Team",
                description="Chef biography, philosophy of seasonal sourcing, and heritage culinary pedigree",
                dom_id="chef",
            )

            # 5. Restaurant Ambience & Spaces
            cmap.sections["ambience"] = ContentCoverageSection(
                section_id="ambience",
                title="Dining Ambience & Architecture",
                description="Warm candlelit dining hall, open kitchen counter, and intimate courtyard spaces",
                dom_id="ambience",
            )

            # 6. Private Dining & Events
            cmap.sections["private_dining"] = ContentCoverageSection(
                section_id="private_dining",
                title="Private Dining & Celebrations",
                description="Exclusive wine cellar room, custom tasting menus, and corporate dining reservations",
                dom_id="private-dining",
            )

            # 7. Guest Reviews & Testimonials
            cmap.sections["reviews"] = ContentCoverageSection(
                section_id="reviews",
                title="Guest Testimonials & Press Reviews",
                description="Food critic reviews, Michelin guide recognition, and verified patron quotes",
                dom_id="testimonials",
            )

            # 8. Food & Venue Gallery
            cmap.sections["gallery"] = ContentCoverageSection(
                section_id="gallery",
                title="Visual Dish & Venue Gallery",
                description="Curated high-resolution photography showcasing culinary artistry and stone architecture",
                dom_id="gallery",
            )

            # 9. Dining FAQ Accordion
            cmap.sections["faq"] = ContentCoverageSection(
                section_id="faq",
                title="Dining & Reservation FAQ",
                description="Interactive accordion covering dietary requirements, dress code, parking, and cancellation policy",
                dom_id="faq",
            )
            cmap.required_interactions.append("faq_accordion")

            # 10. Dish Details / Reservation Modal
            cmap.sections["modal"] = ContentCoverageSection(
                section_id="modal",
                title="Interactive Dish & Reservation Modal",
                description="Detailed dish view with ingredients, wine pairings, and reservation modal dialog",
                dom_id="reservation-modal",
            )
            cmap.required_interactions.append("modal_open_close")

            # 11. Table Reservation Form
            cmap.sections["booking"] = ContentCoverageSection(
                section_id="booking",
                title="Table Reservation Form",
                description="Validated booking form with Name, Email, Date, Time, Party Size, and Seating Preference",
                dom_id="reservation-form",
            )
            cmap.required_interactions.append("form_validation_and_submit")

        elif domain in ("ecommerce_electronics", "ecommerce_store") or any(w in p_lower for w in ["nova", "electronics", "smartphones", "laptops", "headphones"]):
            # 1. Product Categories
            cmap.sections["categories"] = ContentCoverageSection(
                section_id="categories",
                title="Featured Electronics Categories",
                description="Showcase of hardware categories (Smartphones, Laptops, Headphones, Smartwatches, Gaming, Accessories)",
                dom_id="categories",
            )
            # 2. Products Catalog (12 products)
            cmap.sections["products"] = ContentCoverageSection(
                section_id="products",
                title="Featured Products Grid",
                description="Interactive cards for at least 12 consumer electronics products with image, category, price, and actions",
                dom_id="products",
            )
            cmap.required_cards = [
                "NOVA Apex Pro 5G",
                "NOVA Pulse Mini 5G",
                "NOVA Book Ultralight 15",
                "NOVA Studio Pro 16",
                "NOVA Sonic ANC Wireless",
                "NOVA SoundBuds Pro",
                "NOVA Chrono Precision Steel",
                "NOVA Fit Active Titanium",
                "NOVA Horizon VR Spatial Headset",
                "NOVA Reflex Mechanical Keyboard",
                "NOVA PowerMatrix 100W GaN Charger",
                "NOVA Magnetic 3-in-1 Charging Stand",
            ]
            # 3. Search, Category Filtering & Sort
            cmap.sections["filter"] = ContentCoverageSection(
                section_id="filter",
                title="Interactive Product Search, Filter & Sort",
                description="Real-time search, category filter pills, and price sorting dropdown",
                dom_id="filters",
            )
            cmap.required_interactions.append("category_filtering")
            cmap.required_interactions.append("search_keyword")
            cmap.required_interactions.append("price_sorting")

            # 4. Product Details Modal
            cmap.sections["modal"] = ContentCoverageSection(
                section_id="modal",
                title="Product Details Inspection Modal",
                description="Modal dialog with full tech specs, stock status, high-res photography, and Add to Cart trigger",
                dom_id="product-modal",
            )
            cmap.required_interactions.append("modal_open_close")

            # 5. Interactive Shopping Cart Modal / Drawer
            cmap.sections["cart"] = ContentCoverageSection(
                section_id="cart",
                title="Interactive Shopping Cart with LocalStorage",
                description="Cart modal/drawer with item list, live item counter badge, quantity adjustment, remove, subtotal, and localStorage persistence",
                dom_id="cart-modal",
            )
            cmap.required_interactions.append("cart_management")

            # 6. Contact / Demonstration Inquiries
            cmap.sections["booking"] = ContentCoverageSection(
                section_id="booking",
                title="Customer Inquiries & Support Form",
                description="Validated contact form with name, email, subject, message, and demonstration mode disclosure",
                dom_id="contact-form",
            )
            cmap.required_interactions.append("form_validation_and_submit")

        elif domain == "travel_tourism" or any(w in p_lower for w in ["wanderworld", "travel", "tourism", "vacation"]):
            # 3. Main Catalog / Cards / Destinations / Packages
            if any(w in p_lower for w in ["destinations", "destination", "cards", "places", "catalog", "showcase", "packages"]):
                cmap.sections["destinations"] = ContentCoverageSection(
                    section_id="destinations",
                    title="Featured Destinations / Catalog Cards",
                    description="Grid of cards with high-quality photography, title, category, pricing, and details button",
                    dom_id="destinations",
                )
                known_locs = ["bali", "switzerland", "paris", "dubai", "maldives", "japan", "tokyo", "rome", "iceland", "hawaii"]
                for loc in known_locs:
                    if loc in p_lower:
                        cmap.required_cards.append(loc.title())

            # 4. Search and Filter
            if any(w in p_lower for w in ["filter", "search", "category", "categories"]):
                cmap.sections["filter"] = ContentCoverageSection(
                    section_id="filter",
                    title="Interactive Search & Category Filter",
                    description="Filter buttons/pills (All, Beach, Mountain, Cultural, Luxury) and search input",
                    dom_id="filters",
                )
                cmap.required_interactions.append("category_filtering")
                cmap.required_interactions.append("search_keyword")

            # 5. Travel Packages / Specials
            if any(w in p_lower for w in ["packages", "tours", "specials", "deals", "pricing"]):
                cmap.sections["packages"] = ContentCoverageSection(
                    section_id="packages",
                    title="Curated Packages & Experiences",
                    description="Curated itineraries or package cards with duration, pricing, and booking CTA",
                    dom_id="packages",
                )

            # 6. Testimonials / Reviews
            if any(w in p_lower for w in ["review", "reviews", "testimonial", "testimonials", "ratings"]):
                cmap.sections["reviews"] = ContentCoverageSection(
                    section_id="reviews",
                    title="Customer Testimonials & Reviews",
                    description="Social proof, star ratings, customer avatar/name, and feedback quotes",
                    dom_id="reviews",
                )

            # 7. Modal Dialog
            if any(w in p_lower for w in ["modal", "dialog", "popup", "detail view", "itinerary"]):
                cmap.sections["modal"] = ContentCoverageSection(
                    section_id="modal",
                    title="Interactive Detail Modal Dialog",
                    description="Detailed inspection dialog with image, full itinerary, price, and booking trigger",
                    dom_id="modal",
                )
                cmap.required_interactions.append("modal_open_close")

            # 8. Contact / Booking Form
            if any(w in p_lower for w in ["form", "booking", "inquiry", "contact", "consultation"]):
                cmap.sections["booking"] = ContentCoverageSection(
                    section_id="booking",
                    title="Booking / Contact Inquiry Form",
                    description="Validated input fields (Name, Email, Destination, Dates) with submission feedback",
                    dom_id="booking",
                )
                cmap.required_interactions.append("form_validation_and_submit")
        else:
            # Neutral / General domain
            cmap.sections["content"] = ContentCoverageSection(
                section_id="content",
                title="Featured Showcase & Content",
                description="Primary feature presentation, cards, and interactive showcase",
                dom_id="features",
            )
            if any(w in p_lower for w in ["filter", "search"]):
                cmap.sections["filter"] = ContentCoverageSection(
                    section_id="filter",
                    title="Interactive Filter & Search",
                    description="Interactive category filter buttons and search field",
                    dom_id="filters",
                )
                cmap.required_interactions.append("category_filtering")
                cmap.required_interactions.append("search_keyword")
            if any(w in p_lower for w in ["modal", "detail", "dialog"]):
                cmap.sections["modal"] = ContentCoverageSection(
                    section_id="modal",
                    title="Detail Inspection Modal",
                    description="Interactive inspection modal dialog with full item details",
                    dom_id="modal",
                )
                cmap.required_interactions.append("modal_open_close")
            if any(w in p_lower for w in ["form", "contact", "signup", "inquiry"]):
                cmap.sections["form"] = ContentCoverageSection(
                    section_id="form",
                    title="Validated Input Form",
                    description="Interactive form with field validation and submission handling",
                    dom_id="form",
                )
                cmap.required_interactions.append("form_validation_and_submit")

        # 9. Footer
        cmap.sections["footer"] = ContentCoverageSection(
            section_id="footer",
            title="Footer Section",
            description="Company info, quick links, newsletter signup, and copyright notice",
            dom_id="footer",
        )

        return cmap

    def audit_workspace(self, workspace_root: Path | str) -> Dict[str, Any]:
        """
        Inspect HTML, CSS, and JS in workspace to verify which sections
        and interactions have been implemented and update their status.
        """
        root = Path(workspace_root).resolve()
        html_files = list(root.glob("*.html")) + list(root.glob("static/*.html"))
        js_files = list(root.glob("*.js")) + list(root.glob("static/*.js")) + list(root.glob("src/*.js"))
        css_files = list(root.glob("*.css")) + list(root.glob("static/*.css")) + list(root.glob("src/*.css"))

        if not html_files:
            return {"implemented_count": 0, "total_count": len(self.sections), "verified": False}

        html_text = ""
        for hf in html_files:
            try:
                html_text += hf.read_text(encoding="utf-8", errors="ignore") + "\n"
            except Exception:
                pass

        js_text = ""
        for jf in js_files:
            try:
                js_text += jf.read_text(encoding="utf-8", errors="ignore") + "\n"
            except Exception:
                pass

        html_lower = html_text.lower()
        js_lower = js_text.lower()

        # Audit each section
        implemented_count = 0
        for s_id, sec in self.sections.items():
            found = False
            # Check by tag or DOM ID or class
            if sec.dom_id and f'id="{sec.dom_id.lower()}' in html_lower or f"id='{sec.dom_id.lower()}" in html_lower:
                found = True
            elif f'<{s_id}' in html_lower or f'class="{s_id}' in html_lower or f'id="{s_id}' in html_lower:
                found = True
            elif s_id == "nav" and ("<nav" in html_lower or "navbar" in html_lower or "class=\"nav" in html_lower):
                found = True
            elif s_id == "hero" and ("hero" in html_lower):
                found = True
            elif s_id == "destinations" and ("destinations" in html_lower or "destination" in html_lower or "card" in html_lower):
                found = True
            elif s_id == "packages" and ("package" in html_lower or "pricing" in html_lower):
                found = True
            elif s_id == "filter" and ("filter" in html_lower or "data-category" in html_lower or "search" in html_lower):
                found = True
            elif s_id == "reviews" and ("review" in html_lower or "testimonial" in html_lower or "rating" in html_lower):
                found = True
            elif s_id == "modal" and ("modal" in html_lower or "dialog" in html_lower):
                found = True
            elif s_id == "booking" and ("<form" in html_lower or "booking" in html_lower or "contact" in html_lower):
                found = True
            elif s_id == "footer" and ("<footer" in html_lower or "footer" in html_lower):
                found = True

            if found:
                sec.status = "IMPLEMENTED"
                implemented_count += 1
            else:
                sec.status = "NOT_STARTED"

        return {
            "implemented_count": implemented_count,
            "total_count": len(self.sections),
            "all_implemented": implemented_count == len(self.sections),
        }

    def to_summary_block(self) -> str:
        lines = [
            f"=== CONTENT COVERAGE MAP ({self.domain.upper()}) ===",
            f"Sections Planned ({len(self.sections)}):",
        ]
        for s_id, sec in self.sections.items():
            mark = "[x]" if sec.status in ("IMPLEMENTED", "VERIFIED") else "[ ]"
            lines.append(f"  {mark} [{sec.status}] {sec.title}: {sec.description}")
        if self.required_cards:
            lines.append(f"Required Cards/Items: {', '.join(self.required_cards)}")
        if self.required_interactions:
            lines.append(f"Required Functional Interactions: {', '.join(self.required_interactions)}")
        lines.append("=====================================================")
        return "\n".join(lines)


detect_cuisine_subtype = DesignBriefGenerator.detect_cuisine_subtype
