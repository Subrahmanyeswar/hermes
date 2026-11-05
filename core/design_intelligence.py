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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DesignBrief:
        return cls(
            domain=data.get("domain", "modern_editorial"),
            purpose=data.get("purpose", "Web Application"),
            target_audience=data.get("target_audience", "General Public"),
            brand_personality=data.get("brand_personality", "Clean, modern, professional"),
            visual_direction=data.get("visual_direction", "Modern layout with crisp hierarchy"),
            color_palette=dict(data.get("color_palette", {})),
            typography=dict(data.get("typography", {})),
            spacing_system=dict(data.get("spacing_system", {})),
            component_styling=dict(data.get("component_styling", {})),
            image_direction=dict(data.get("image_direction", {})),
            responsive_breakpoints=dict(data.get("responsive_breakpoints", {})),
        )

    def to_compact_directive(self) -> str:
        """
        Produce a compact 10-15 line actionable design directive
        suitable for model context injection during Phase B and Phase C.
        """
        colors_str = ", ".join(f"{k}: {v}" for k, v in list(self.color_palette.items())[:5])
        typo_str = f"Headings: {self.typography.get('heading_font', 'sans-serif')} | Body: {self.typography.get('body_font', 'sans-serif')}"
        cards_str = f"Radius: {self.component_styling.get('card_radius', '8px')} | Shadow: {self.component_styling.get('card_shadow', 'subtle')} | Border: {self.component_styling.get('card_border', '1px solid')}"
        img_str = f"Object-fit: {self.image_direction.get('object_fit', 'cover')} | Aspect: {self.image_direction.get('aspect_ratio', '16/9')}"
        
        lines = [
            "=== AUTHORITATIVE DESIGN BRIEF & UI/UX SPECIFICATION ===",
            f"Domain & Personality: {self.domain.upper()} -- {self.brand_personality}",
            f"Visual Direction: {self.visual_direction}",
            f"Color Palette: {colors_str}",
            f"Typography: {typo_str}",
            f"Card & Component Styling: {cards_str}",
            f"Image Direction: {img_str} (Use relevant section-specific photography; NO full-page oversized images)",
            f"Spacing & Layout: Container max-width: {self.spacing_system.get('container_max_width', '1200px')} | Gap: {self.spacing_system.get('md', '1.5rem')}",
            f"Responsive: Mobile breakpoint: {self.responsive_breakpoints.get('mobile_max', '768px')} | Zero horizontal overflow (overflow-x: hidden)",
            "STRICT PROHIBITIONS: No unstyled browser links, no raw buttons, no missing container classes, no overwriting <section> roots during dynamic JS render.",
            "=======================================================",
        ]
        return "\n".join(lines)


class DesignBriefGenerator:
    """
    Synthesizes domain-tailored design briefs based on user prompt analysis
    and active skill instructions (taste-design, design-engineering, design-system).
    """

    DOMAIN_PALETTES = {
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
    }

    DOMAIN_TYPOGRAPHY = {
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
    }

    @classmethod
    def detect_domain(cls, prompt: str) -> str:
        p_lower = (prompt or "").lower()
        if any(w in p_lower for w in ["wanderworld", "travel", "tourism", "vacation", "destinations", "destination", "resort", "safari", "tour", "explore", "packages", "airline", "flight"]):
            return "travel_tourism"
        if any(w in p_lower for w in ["cafe", "coffee", "restaurant", "dining", "roaster", "bakery", "bistro", "menu", "culinary", "food"]):
            return "culinary_restaurant"
        if any(w in p_lower for w in ["saas", "dashboard", "analytics", "developer", "cloud", "api", "ai engine", "infrastructure"]):
            return "saas_tech"
        if any(w in p_lower for w in ["car", "automotive", "hypercar", "dealership", "vehicle", "race", "motor"]):
            return "automotive_luxury"
        if any(w in p_lower for w in ["fintech", "banking", "finance", "crypto", "trading", "investment", "commerce", "store"]):
            return "fintech_commerce"
        if any(w in p_lower for w in ["university", "college", "school", "academy", "curriculum", "courses", "education"]):
            return "education_institution"
        if any(w in p_lower for w in ["portfolio", "agency", "photographer", "creative studio", "designer showcase"]):
            return "creative_portfolio"
        return "modern_editorial"

    @classmethod
    def generate_brief(
        cls,
        prompt: str,
        active_skills: Optional[List[str]] = None,
    ) -> DesignBrief:
        domain = cls.detect_domain(prompt)
        palette = cls.DOMAIN_PALETTES.get(domain, cls.DOMAIN_PALETTES["modern_editorial"])
        typo = cls.DOMAIN_TYPOGRAPHY.get(domain, cls.DOMAIN_TYPOGRAPHY["modern_editorial"])

        personalities = {
            "travel_tourism": "Wanderlust, inspiring, luxurious, modern, breathable, vibrant",
            "culinary_restaurant": "Warm, artisanal, grounded, sensory, welcoming",
            "saas_tech": "Engineered, precise, cutting-edge, dependable, dark-mode polished",
            "automotive_luxury": "High-velocity, aerodynamic, aggressive elegance, precision",
            "fintech_commerce": "Authoritative, trustworthy, modern, crystal clear",
            "education_institution": "Scholarly, distinguished, structured, accessible",
            "creative_portfolio": "Minimalist, editorial, typography-driven, showcase",
            "modern_editorial": "Clean, contemporary, balanced, intuitive",
        }

        visual_directions = {
            "travel_tourism": "Hero showcase with expansive photography, glassmorphism destination cards, interactive category pills, and modal itinerary inspection.",
            "culinary_restaurant": "Sensory photography, warm organic tones, distinct menu grids, and accessible ordering actions.",
            "saas_tech": "Metric stat cards, interactive feature toggles, high-contrast code/preview blocks, and subtle gradient borders.",
            "automotive_luxury": "Dramatic dark contrast, high-resolution vehicle cards, spec comparison tables, and subtle hover glows.",
            "fintech_commerce": "Clean ledger cards, clear transaction workflows, accessible contrast, and zero layout shift.",
            "education_institution": "Organized faculty/course cards, calendar view, structured admission forms, and high-readability text.",
            "creative_portfolio": "Asymmetric visual grid, expansive whitespace, custom cursor interactions, and responsive media tiles.",
            "modern_editorial": "Harmonious vertical rhythm, modular card layouts, clear visual hierarchy, and polished interactive controls.",
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

        return DesignBrief(
            domain=domain,
            purpose=f"Modern {domain.replace('_', ' ').title()} Web Experience",
            target_audience="Discerning users seeking high quality, intuitive exploration and seamless interaction",
            brand_personality=personalities.get(domain, "Modern, clean, polished"),
            visual_direction=visual_directions.get(domain, "Crisp modular layout with balanced whitespace"),
            color_palette=palette,
            typography=typo,
            spacing_system=spacing_system,
            component_styling=component_styling,
            image_direction=image_direction,
            responsive_breakpoints=breakpoints,
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

        # 3. Main Catalog / Cards / Destinations / Packages
        if any(w in p_lower for w in ["destinations", "destination", "cards", "places", "catalog", "showcase", "packages"]):
            cmap.sections["destinations"] = ContentCoverageSection(
                section_id="destinations",
                title="Featured Destinations / Catalog Cards",
                description="Grid of cards with high-quality photography, title, category, pricing, and details button",
                dom_id="destinations",
            )
            # Detect specific destinations if requested
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
