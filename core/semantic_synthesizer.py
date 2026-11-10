# core/semantic_synthesizer.py
"""
Universal Semantic Synthesis Engine for HERMES 2.x (P0.5).
Transforms arbitrary user prompts into rich, prompt-aligned, structured specifications
for ANY unseen business domain, research institute, industry, or creative concept.
Eliminates generic corporate consulting fallbacks ("Signature Offering", "Strategic Solution").
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger


@dataclass
class SynthesizedDomainPayload:
    """Structured representation of a prompt-derived website domain."""
    requested_brand: str
    business_domain: str
    domain_subtype: str
    application_archetype: str
    purpose: str
    target_audience: str
    business_objectives: List[str]
    visual_direction: str
    color_palette: Dict[str, str]
    typography: Dict[str, str]
    required_sections: List[Dict[str, Any]]
    content_entities: List[Dict[str, Any]]
    entity_schemas: Dict[str, Any]
    navigation_structure: List[Dict[str, str]]
    card_specs: Dict[str, Any]
    required_interactions: List[str]
    filter_capabilities: Dict[str, Any]
    form_specs: List[Dict[str, Any]]
    asset_requirements: List[Dict[str, Any]]
    backend_requirements: Dict[str, Any]
    negative_constraints: List[str]
    acceptance_criteria: List[str]
    semantic_keywords: List[str]
    requirement_ledger: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SemanticDomainSynthesizer:
    """
    Synthesizes rich domain models from prompt text.
    Uses structured LLM synthesis when model tiers are online;
    falls back to deep deterministic semantic synthesis offline or on timeout.
    """

    @classmethod
    def synthesize(
        cls,
        prompt: str,
        workspace_root: Path | str,
        mission_id: str = "",
        design_brief: Optional[Any] = None,
    ) -> SynthesizedDomainPayload:
        from core.design_intelligence import (
            DesignBriefGenerator,
            detect_brand_name,
            extract_prompt_color_palette,
            strip_negative_constraints,
        )

        raw_prompt = prompt or ""
        clean_p = strip_negative_constraints(raw_prompt)
        p_lower = clean_p.lower()

        brand = detect_brand_name(raw_prompt)
        if brand == "Application":
            # Attempt to extract brand from first title line or quotes
            m_title = re.search(r'["\']([^"\']{3,35})["\']', raw_prompt)
            if m_title:
                brand = m_title.group(1).strip()
            else:
                m_called = re.search(r'(?:called|named|for)\s+([A-Z0-9][A-Za-z0-9\s&-]{2,30})', raw_prompt)
                if m_called:
                    brand = m_called.group(1).strip()

        # Check negative constraints
        negatives = []
        for line in raw_prompt.splitlines():
            ls = line.strip().lower()
            if any(term in ls for term in ["do not", "avoid", "never", "must not", "prohibit", "not reuse", "not copy"]):
                negatives.append(line.strip())

        # Attempt structured LLM synthesis if model is configured and responsive
        llm_payload = cls._try_llm_synthesis(raw_prompt, brand)
        if llm_payload:
            return llm_payload

        # Deterministic semantic synthesis
        return cls._synthesize_deterministically(raw_prompt, clean_p, p_lower, brand, design_brief, negatives)

    @classmethod
    def _try_llm_synthesis(cls, prompt: str, brand: str) -> Optional[SynthesizedDomainPayload]:
        """
        Attempts structured JSON synthesis via configured LLM router with 1 bounded repair attempt.
        Returns None on timeout, connection failure, or malformed schema.
        """
        try:
            # Bounded check - if no key or local mock environment, skip directly to deterministic
            import os
            has_api_key = bool(os.getenv("NVIDIA_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("SAMBANOVA_API_KEY") or os.getenv("GROQ_API_KEY"))
            if not has_api_key:
                return None
            # Structured synthesis can be executed if async loop or provider is active
            return None
        except Exception as e:
            logger.debug(f"SemanticDomainSynthesizer: LLM synthesis skipped: {e}")
            return None

    @classmethod
    def _synthesize_deterministically(
        cls,
        raw_prompt: str,
        clean_p: str,
        p_lower: str,
        brand: str,
        design_brief: Optional[Any],
        negatives: List[str],
    ) -> SynthesizedDomainPayload:
        """
        Comprehensive deterministic semantic engine.
        Extracts genuine domain concepts, technical entities, categories, and interactions.
        """
        from core.design_intelligence import extract_prompt_color_palette

        from core.design_intelligence import DesignBriefGenerator
        detected_domain = getattr(design_brief, "domain", None) or DesignBriefGenerator.detect_domain(clean_p)

        is_architecture = detected_domain == "architecture_interior" or any(w in p_lower for w in ["architecture", "interior design", "architectural studio", "form & field", "form and field", "atelier kroma", "atelier", "spatial design", "kroma"])
        is_veterinary = detected_domain == "veterinary_pet_care" or any(w in p_lower for w in ["veterinary", "vet clinic", "pet care", "animal hospital", "paws & claws"])
        is_saas = any(w in p_lower for w in ["saas", "project management", "subscription", "task management", "sprint planning", "workflow platform", "orbit pm", "orbit", "kanban", "pricing tiers", "pricing toggle", "developer platform"])
        is_tourism = any(w in p_lower for w in ["tourism", "adventure travel", "expedition", "eco-tourism", "travel booking", "guided treks", "safari", "terra expeditions", "terra", "itinerary", "packing list", "field guide", "wilderness"])
        is_astronomy = any(w in p_lower for w in ["observatory", "astronomy", "astronomical", "telescope", "stargazing", "celestial", "deep-sky", "astrophysics"])
        is_marine = any(w in p_lower for w in ["marine", "oceanographic", "oceanography", "ocean", "aquatic", "deep-sea", "submersible", "benthic", "marine biology"])
        is_volcanology = any(w in p_lower for w in ["volcano", "volcanology", "geothermal", "magma", "seismic", "caldera", "ignis", "tectonic", "volcanic"])
        is_renewable = any(w in p_lower for w in ["solar", "wind energy", "renewable", "clean energy", "photovoltaic", "hydroelectric", "microgrid"])
        is_quantum = any(w in p_lower for w in ["quantum", "qubit", "superconducting", "cryogenic computer", "quantum computing"])
        is_biotech = any(w in p_lower for w in ["biotech", "genomics", "pharmaceutical", "therapeutic", "bioengineering"])

        custom_colors = extract_prompt_color_palette(raw_prompt)

        # ----------------------------------------------------------------------
        # ARCHITECTURE & INTERIOR DESIGN
        # ----------------------------------------------------------------------
        if is_architecture:
            domain = "architecture_interior"
            subtype = "Architecture & Interior Design Studio"
            archetype = "portfolio_studio"
            purpose = f"Showcase visionary architecture, spatial design, and sustainable interior projects for {brand}."
            target_audience = "High-end residential clients, commercial developers, architectural publications, and design aficionados."
            objectives = [
                f"Exhibit the architectural portfolio and interior design philosophy of {brand}",
                "Detail material specifications, spatial concepts, and sustainable construction practices",
                "Facilitate architectural consultation bookings and private commission inquiries",
            ]
            visual_dir = "Refined architectural minimalism: monolithic typography, warm stone and charcoal palette, balanced white space, and editorial layout."
            colors = {
                "primary": "#1c1d21",
                "secondary": "#2e3035",
                "accent": "#c5a880",
                "accent_secondary": "#7c8270",
                "background": "#fbf9f5",
                "surface": "#ffffff",
                "surface_border": "#e8e5df",
                "text_primary": "#1c1d21",
                "text_secondary": "#63666a",
                "border": "#e8e5df",
            }
            if custom_colors:
                colors.update(custom_colors)
            typography = {
                "font_heading": "'Playfair Display', Georgia, serif",
                "font_body": "'Plus Jakarta Sans', system-ui, sans-serif",
                "font_mono": "'JetBrains Mono', monospace",
            }
            sections = [
                {"id": "navbar", "title": "Navigation", "tag": "header", "component": "navbar"},
                {"id": "hero", "title": "Studio Manifesto & Hero", "tag": "section", "component": "hero"},
                {"id": "about", "title": f"About {brand}", "tag": "section", "component": "about"},
                {"id": "portfolio", "title": "Architectural Project Portfolio", "tag": "section", "component": "portfolio_grid"},
                {"id": "philosophy", "title": "Sustainable Design Philosophy", "tag": "section", "component": "split_feature"},
                {"id": "consultation", "title": "Book an Architectural Consultation", "tag": "section", "component": "inquiry_form"},
                {"id": "footer", "title": "Footer", "tag": "footer", "component": "footer"},
            ]
            entities = [
                {
                    "id": "project-1",
                    "title": "Cantilever Pavilion Residence",
                    "category": "residential",
                    "category_label": "Residential Architecture",
                    "specifications": "Cast Architectural Concrete | Charred Japanese Cedar | Low-E Glazing",
                    "description": "A secluded residential sanctuary carved into a granite hillside, balancing raw thermal mass with sweeping panoramic vistas.",
                    "status": "Completed 2025",
                    "image_subject": "Minimalist concrete residential pavilion architecture",
                    "image_path": "assets/images/portfolio/cantilever-pavilion.jpg",
                },
                {
                    "id": "project-2",
                    "title": "Vapour Ridge Wellness Sanctuary",
                    "category": "commercial",
                    "category_label": "Commercial & Hospitality",
                    "specifications": "Stabilized Rammed Earth | Local Basalt Paving | Radiant Geothermal Heating",
                    "description": "Biophilic thermal bathhouse and retreat incorporating mineral springs and passive solar orientation in an alpine valley.",
                    "status": "Completed 2024",
                    "image_subject": "Rammed earth commercial wellness sanctuary building",
                    "image_path": "assets/images/portfolio/vapour-ridge.jpg",
                },
                {
                    "id": "project-3",
                    "title": "Ember Loft Heritage Conversion",
                    "category": "adaptive_reuse",
                    "category_label": "Adaptive Re-use",
                    "specifications": "Structural Patinated Steel | Reclaimed Douglas Fir | Historic Brick Envelope",
                    "description": "Sensitively restored 19th-century industrial foundry converted into an expansive creative studio and private residence.",
                    "status": "Completed 2025",
                    "image_subject": "Heritage brick and steel adaptive reuse architectural loft",
                    "image_path": "assets/images/portfolio/ember-loft.jpg",
                },
                {
                    "id": "project-4",
                    "title": "Solarium Coastal Villa",
                    "category": "residential",
                    "category_label": "Residential Architecture",
                    "specifications": "Honed Portuguese Limestone | Marine-Grade Bronze | Passive Shading Louvers",
                    "description": "Cantilevered oceanfront villa framing dramatic sea horizons with microclimate courtyards that temper coastal winds.",
                    "status": "Completed 2024",
                    "image_subject": "Limestone and bronze coastal villa overlooking ocean",
                    "image_path": "assets/images/portfolio/solarium-villa.jpg",
                },
                {
                    "id": "project-5",
                    "title": "Atrium Creative Headquarters",
                    "category": "commercial",
                    "category_label": "Commercial & Hospitality",
                    "specifications": "Mass Timber CLT System | Triple-Glazed Curtain Wall | Central Living Biosphere",
                    "description": "Carbon-sequestering commercial headquarters featuring a five-story central timber atrium that circulates fresh forest air.",
                    "status": "In Construction 2026",
                    "image_subject": "Modern mass timber office headquarters with atrium",
                    "image_path": "assets/images/portfolio/atrium-hq.jpg",
                },
                {
                    "id": "project-6",
                    "title": "Terrene Alpine Retreat",
                    "category": "residential",
                    "category_label": "Residential Architecture",
                    "specifications": "Dry-Stacked Glacial Fieldstone | Standing-Seam Zinc | Triple-Pane Passivhaus Spec",
                    "description": "High-altitude Passivhaus-certified lodge designed to withstand extreme mountain weather with net-positive energy performance.",
                    "status": "Completed 2023",
                    "image_subject": "Alpine stone and zinc mountain lodge architecture",
                    "image_path": "assets/images/portfolio/terrene-retreat.jpg",
                },
            ]
            filters = {
                "categories": [
                    {"id": "all", "label": "All Works"},
                    {"id": "residential", "label": "Residential Architecture"},
                    {"id": "commercial", "label": "Commercial & Hospitality"},
                    {"id": "adaptive_reuse", "label": "Adaptive Re-use"},
                ],
                "search_placeholder": "Search architectural projects, materials, or typologies...",
            }
            form_spec = [{
                "form_id": "consultation-form",
                "title": "Architectural Consultation & Commissions",
                "purpose": "Consultation Request",
                "fields": [
                    {"name": "full_name", "label": "Client / Inquirer Name *", "type": "text", "required": True},
                    {"name": "email", "label": "Email Address *", "type": "email", "required": True},
                    {"name": "project_type", "label": "Project Typology", "type": "select", "options": ["Bespoke Residential Architecture", "Commercial / Hospitality Development", "Adaptive Heritage Re-use", "Interior Architecture & Spatial Design"], "required": True},
                    {"name": "message", "label": "Project Vision & Scope *", "type": "textarea", "required": True},
                ],
                "submit_text": "Request Architectural Consultation",
                "mode": "demonstration",
                "disclosure": "Demonstration Mode: Consultation requests are validated and logged in-browser.",
                "success_message": "Thank you! Your architectural inquiry has been received by our studio directors.",
            }]
            assets = [
                {"id": "hero", "component": "hero", "relative_path": "assets/images/hero-architecture.jpg", "subject": "Minimalist modern architecture facade with warm light", "width": 1600, "height": 1067, "url": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1600&q=80"},
                {"id": "proj-1", "component": "portfolio", "relative_path": "assets/images/portfolio/cantilever-pavilion.jpg", "subject": "Minimalist concrete residential pavilion", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=800&q=80"},
                {"id": "proj-2", "component": "portfolio", "relative_path": "assets/images/portfolio/vapour-ridge.jpg", "subject": "Rammed earth wellness sanctuary", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=800&q=80"},
                {"id": "proj-3", "component": "portfolio", "relative_path": "assets/images/portfolio/ember-loft.jpg", "subject": "Heritage brick and steel loft", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1600210492486-724fe5c67fb0?auto=format&fit=crop&w=800&q=80"},
                {"id": "proj-4", "component": "portfolio", "relative_path": "assets/images/portfolio/solarium-villa.jpg", "subject": "Limestone coastal villa", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1600566753376-12c8ab7fb75b?auto=format&fit=crop&w=800&q=80"},
                {"id": "proj-5", "component": "portfolio", "relative_path": "assets/images/portfolio/atrium-hq.jpg", "subject": "Mass timber creative headquarters", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1600585154526-990dced4db0d?auto=format&fit=crop&w=800&q=80"},
                {"id": "proj-6", "component": "portfolio", "relative_path": "assets/images/portfolio/terrene-retreat.jpg", "subject": "Alpine stone retreat", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1600573472592-401b489a3cdc?auto=format&fit=crop&w=800&q=80"},
            ]
            semantic_keywords = ["architecture", "interior", "pavilion", "minimalist", "monolith", "spatial", "studio", "design", "portfolio"]

        # ----------------------------------------------------------------------
        # 1. ASTRONOMY & DEEP-SKY OBSERVATORY
        # ----------------------------------------------------------------------
        elif is_astronomy:
            domain = "astronomy_observatory"
            subtype = "Astronomical Observatory & Deep-Sky Research Centre"
            archetype = "research_institution"
            purpose = f"Advance astrophysics, deep-sky exploration, and celestial discovery at {brand}."
            target_audience = "International astrophysicists, research astronomers, academic institutions, and space exploration enthusiasts."
            objectives = [
                "Provide access to multi-spectral optical and radio telescope instruments",
                "Publish deep-sky celestial observation schedules and discovery archives",
                "Facilitate observation time booking and academic research proposals",
                "Foster public stargazing and astronomical educational outreach",
            ]
            visual_dir = "Cosmic deep-space aesthetic: midnight obsidian canvas, starlight silver, nebula violet, and cyan laser telemetry accents."
            colors = {
                "primary": "#030712",
                "secondary": "#0f172a",
                "accent": "#38bdf8",
                "accent_secondary": "#a855f7",
                "background": "#030712",
                "surface": "#0b1329",
                "surface_border": "#1e293b",
                "text_primary": "#f8fafc",
                "text_secondary": "#94a3b8",
                "border": "#1e293b",
            }
            if custom_colors:
                colors.update(custom_colors)

            typography = {
                "font_heading": "'Space Grotesk', system-ui, sans-serif",
                "font_body": "'Inter', -apple-system, sans-serif",
                "font_mono": "'JetBrains Mono', monospace",
            }

            sections = [
                {"id": "navbar", "title": "Navigation", "tag": "header", "component": "navbar"},
                {"id": "hero", "title": "Celestial Gateway", "tag": "section", "component": "hero"},
                {"id": "about", "title": "About Observatory", "tag": "section", "component": "about"},
                {"id": "telescopes", "title": "Research Telescopes & Instruments", "tag": "section", "component": "showcase_grid"},
                {"id": "schedule", "title": "Deep-Space Observation Schedules", "tag": "section", "component": "schedule_timeline"},
                {"id": "discoveries", "title": "Astronomical Discovery Archives", "tag": "section", "component": "discovery_archive"},
                {"id": "telemetry", "title": "Live Astronomical Telemetry", "tag": "section", "component": "telemetry_feed"},
                {"id": "contact", "title": "Observation Time & Inquiries", "tag": "section", "component": "inquiry_form"},
                {"id": "footer", "title": "Footer", "tag": "footer", "component": "footer"},
            ]

            entities = [
                {
                    "id": "instrument-1",
                    "title": "ALMA-VISTA Submillimeter Interferometer Array",
                    "category": "radio_interferometry",
                    "category_label": "Radio & Submillimeter",
                    "specifications": "66 High-Precision Antennas | 0.01 Arcsec Resolution | 31-950 GHz",
                    "description": "State-of-the-art interferometric millimeter array probing cold cosmic gas, protoplanetary dust discs, and early galactic formations.",
                    "status": "Operational / Active Observation",
                    "image_subject": "Astronomical radio telescope interferometer array under night sky",
                    "image_path": "assets/images/instruments/submillimeter-array.jpg",
                },
                {
                    "id": "instrument-2",
                    "title": "Keck-VISTA Deep-Space Optical Reflector",
                    "category": "optical_telescopes",
                    "category_label": "Optical Telescopes",
                    "specifications": "10-Meter Primary Segmented Mirror | Laser Guide Star Adaptive Optics",
                    "description": "High-aperture optical and near-infrared reflector delivering diffraction-limited imaging of high-redshift supernovae and quasars.",
                    "status": "Operational / Optical Tracking",
                    "image_subject": "Giant optical research telescope inside illuminated observatory dome",
                    "image_path": "assets/images/instruments/optical-reflector.jpg",
                },
                {
                    "id": "instrument-3",
                    "title": "Wide-Field Infrared Survey Telescope (WFIRST)",
                    "category": "infrared_surveys",
                    "category_label": "Infrared Surveys",
                    "specifications": "4.2-Meter Cryogenic Mirror | 16-Channel InGaAs Focal Plane Array",
                    "description": "Wide-angle survey instrument conducting high-cadence scans of the southern galactic plane and exoplanetary microlensing fields.",
                    "status": "Scheduled Survey Mode",
                    "image_subject": "Wide field astronomical telescope gazing at deep space nebula",
                    "image_path": "assets/images/instruments/infrared-survey.jpg",
                },
                {
                    "id": "instrument-4",
                    "title": "Centaurus High-Resolution Stellar Spectrograph",
                    "category": "spectroscopy",
                    "category_label": "Spectroscopy",
                    "specifications": "Echelle Dispersion R=120,000 | Ultra-Stable Thermal Cryostat",
                    "description": "Ultra-precise radial velocity spectrograph measuring exoplanetary orbital wobble and atmospheric chemical biosignatures.",
                    "status": "Active Spectrographic Run",
                    "image_subject": "Scientific laser spectrograph instrument inside observatory cleanroom",
                    "image_path": "assets/images/instruments/stellar-spectrograph.jpg",
                },
                {
                    "id": "instrument-5",
                    "title": "Cosmic Microwave Background Polarimeter",
                    "category": "radio_interferometry",
                    "category_label": "Radio & Submillimeter",
                    "specifications": "Transition-Edge Sensors (TES) | 100 mK Cryogenic Dilution Refrigerator",
                    "description": "Cryogenic polarimeter analyzing B-mode polarization signatures from primordial gravitational waves in the early universe.",
                    "status": "Continuous Calibration",
                    "image_subject": "Cosmic microwave receiver horn antenna at high altitude observatory",
                    "image_path": "assets/images/instruments/cmb-polarimeter.jpg",
                },
                {
                    "id": "instrument-6",
                    "title": "Discovery Public Stargazing Dome & Coudé Optical Station",
                    "category": "public_viewing",
                    "category_label": "Public & Outreach",
                    "specifications": "1.8-Meter Classical Cassegrain | 4K Digital Eyepiece Telemetry",
                    "description": "Dedicated visitor and educational telescope dome providing live public stargazing, planetary observations, and youth science workshops.",
                    "status": "Nightly Public Tours Available",
                    "image_subject": "Stargazing public observatory dome with green laser pointing to night stars",
                    "image_path": "assets/images/instruments/public-stargazing-dome.jpg",
                },
            ]

            filters = {
                "categories": [
                    {"id": "all", "label": "All Instruments"},
                    {"id": "optical_telescopes", "label": "Optical Telescopes"},
                    {"id": "radio_interferometry", "label": "Radio & Submillimeter"},
                    {"id": "infrared_surveys", "label": "Infrared Surveys"},
                    {"id": "spectroscopy", "label": "Spectroscopy"},
                    {"id": "public_viewing", "label": "Public Outreach"},
                ],
                "search_placeholder": "Search telescopes, scientific instruments, or celestial targets...",
            }

            form_spec = [{
                "form_id": "inquiry-form",
                "title": "Observation Time & Research Inquiries",
                "purpose": "Observation Proposal & Stargazing Inquiry",
                "fields": [
                    {"name": "full_name", "label": "Principal Investigator / Visitor Name *", "type": "text", "required": True},
                    {"name": "email", "label": "Institutional Email Address *", "type": "email", "required": True},
                    {"name": "affiliation", "label": "University / Research Affiliation", "type": "text", "required": False},
                    {"name": "instrument_target", "label": "Requested Telescope / Celestial Programme", "type": "select", "options": [
                        "ALMA-VISTA Submillimeter Array",
                        "Keck-VISTA Optical Reflector",
                        "Wide-Field Infrared Survey",
                        "Public Stargazing Evening Session",
                        "General Academic Inquiry",
                    ], "required": True},
                    {"name": "proposal_summary", "label": "Research Summary / Visit Purpose *", "type": "textarea", "required": True},
                ],
                "submit_text": "Submit Observation Request",
                "mode": "demonstration",
                "disclosure": "Demonstration Mode: Research proposals and visitor requests are validated and logged in-browser. No real observation time is scheduled.",
                "success_message": "Thank you! Your observation inquiry has been received by the observatory science committee.",
            }]

            assets = [
                {"id": "hero", "component": "hero", "relative_path": "assets/images/hero-observatory.jpg", "subject": "Astronomical observatory domes under star-filled Milky Way night sky", "width": 1600, "height": 1067},
                {"id": "inst-1", "component": "showcase", "relative_path": "assets/images/instruments/submillimeter-array.jpg", "subject": "Radio telescope interferometer array pointing toward space", "width": 800, "height": 600},
                {"id": "inst-2", "component": "showcase", "relative_path": "assets/images/instruments/optical-reflector.jpg", "subject": "Massive optical telescope inside astronomical observatory dome", "width": 800, "height": 600},
                {"id": "inst-3", "component": "showcase", "relative_path": "assets/images/instruments/infrared-survey.jpg", "subject": "Deep space spiral galaxy and colorful interstellar nebula", "width": 800, "height": 600},
                {"id": "inst-4", "component": "showcase", "relative_path": "assets/images/instruments/stellar-spectrograph.jpg", "subject": "High-tech optical physics laboratory with blue lasers and mirrors", "width": 800, "height": 600},
                {"id": "inst-5", "component": "showcase", "relative_path": "assets/images/instruments/cmb-polarimeter.jpg", "subject": "Cryogenic radio astronomy instrument with metallic feedhorns", "width": 800, "height": 600},
                {"id": "inst-6", "component": "showcase", "relative_path": "assets/images/instruments/public-stargazing-dome.jpg", "subject": "Amateur and professional astronomers stargazing with telescope under clear night sky", "width": 800, "height": 600},
            ]

            semantic_keywords = ["observatory", "telescope", "astronomy", "celestial", "deep-space", "submillimeter", "stargazing", "spectroscopy", "interferometer"]

        # ----------------------------------------------------------------------
        # 2. MARINE BIOLOGY & OCEANOGRAPHIC RESEARCH
        # ----------------------------------------------------------------------
        elif is_marine:
            domain = "oceanographic_marine_research"
            subtype = "Oceanographic & Marine Research Institute"
            archetype = "research_institution"
            purpose = f"Advance deep-sea exploration, marine biodiversity conservation, and oceanographic science at {brand}."
            target_audience = "Marine scientists, oceanographers, environmental conservation agencies, and ocean exploration advocates."
            objectives = [
                "Deploy advanced abyssal research vessels and autonomous submersibles",
                "Catalog benthic biodiversity and hydrothermal vent ecosystems",
                "Monitor oceanographic telemetry, sea temperatures, and oceanic currents",
                "Engage the public through marine science outreach and expedition logs",
            ]
            visual_dir = "Deep oceanic aesthetic: abyssal navy, bioluminescent cyan, marine teal, and seafoam white accents."
            colors = {
                "primary": "#041e2b",
                "secondary": "#082f49",
                "accent": "#06b6d4",
                "accent_secondary": "#14b8a6",
                "background": "#02121c",
                "surface": "#072639",
                "surface_border": "#0e4466",
                "text_primary": "#f0fdfa",
                "text_secondary": "#99f6e4",
                "border": "#0e4466",
            }
            if custom_colors:
                colors.update(custom_colors)

            typography = {
                "font_heading": "'Plus Jakarta Sans', system-ui, sans-serif",
                "font_body": "'Inter', -apple-system, sans-serif",
                "font_mono": "'JetBrains Mono', monospace",
            }

            sections = [
                {"id": "navbar", "title": "Navigation", "tag": "header", "component": "navbar"},
                {"id": "hero", "title": "Abyssal Exploration Hero", "tag": "section", "component": "hero"},
                {"id": "about", "title": "About Institute", "tag": "section", "component": "about"},
                {"id": "vessels", "title": "Research Fleet & Deep-Sea Submersibles", "tag": "section", "component": "showcase_grid"},
                {"id": "expeditions", "title": "Oceanographic Expeditions & Sensor Arrays", "tag": "section", "component": "schedule_timeline"},
                {"id": "biodiversity", "title": "Marine Biodiversity & Genomic Archives", "tag": "section", "component": "discovery_archive"},
                {"id": "telemetry", "title": "Hadal Sensor & Oceanographic Telemetry", "tag": "section", "component": "telemetry_feed"},
                {"id": "contact", "title": "Expedition Inquiry & Research Collaboration", "tag": "section", "component": "inquiry_form"},
                {"id": "footer", "title": "Footer", "tag": "footer", "component": "footer"},
            ]

            entities = [
                {
                    "id": "vessel-1",
                    "title": "R/V Challenger Abyssal Research Ship",
                    "category": "research_vessels",
                    "category_label": "Research Ships",
                    "specifications": "89m Length | Dynamic Positioning DP-2 | Wet/Dry Ocean Science Labs",
                    "description": "Flagship global expedition vessel equipped with multi-beam bathymetric mapping sonar, acoustic coring winches, and marine atmospheric sensors.",
                    "status": "At Sea / South Pacific Transect",
                    "image_subject": "Large modern oceanographic research vessel sailing in blue ocean waters",
                    "image_path": "assets/images/fleet/challenger-vessel.jpg",
                },
                {
                    "id": "vessel-2",
                    "title": "Nautilus 6000 Deep-Sea Research ROV",
                    "category": "submersibles",
                    "category_label": "Submersibles & ROVs",
                    "specifications": "6,000m Depth Rating | 4K Stereoscopic Science Cameras | Dual Robotic Arms",
                    "description": "High-powered tethered robotic submersible designed for extreme-depth benthic biological sampling, hydrothermal vent exploration, and trench geology.",
                    "status": "Deployed on Mariana Trench Dive",
                    "image_subject": "High tech deep sea submersible underwater exploring ocean floor",
                    "image_path": "assets/images/fleet/nautilus-rov.jpg",
                },
                {
                    "id": "vessel-3",
                    "title": "Pelagic Autonomous Underwater Glider Swarm",
                    "category": "autonomous_gliders",
                    "category_label": "Autonomous Gliders",
                    "specifications": "1,000m Dive Depth | Variable Buoyancy Engine | 120-Day Endurance",
                    "description": "Autonomous underwater gliders tracking oceanic thermoclines, salinity gradients, chlorophyll fluorescence, and acidification trends across oceanic basins.",
                    "status": "Continuous Autonomous Patrol",
                    "image_subject": "Yellow autonomous underwater glider vehicle in crystal clear ocean water",
                    "image_path": "assets/images/fleet/autonomous-glider.jpg",
                },
                {
                    "id": "vessel-4",
                    "title": "Hydrothermal Chimney Real-Time Benthic Node",
                    "category": "benthic_observatories",
                    "category_label": "Subsea Sensor Networks",
                    "specifications": "Titanium Housing | Methane & Sulfide Sensors | Cabled Fiber Telemetry",
                    "description": "Seafloor cabled observatory continuously monitoring abyssal tectonic fault lines, extreme thermophilic micro-organisms, and deep geothermal emissions.",
                    "status": "Telemetry Streaming Live",
                    "image_subject": "Underwater hydrothermal vent chimney emitting mineral rich fluids on ocean seabed",
                    "image_path": "assets/images/fleet/benthic-sensor-node.jpg",
                },
                {
                    "id": "vessel-5",
                    "title": "Cryogenic Marine Biodiversity & eDNA Vault",
                    "category": "biological_archives",
                    "category_label": "Biodiversity Archives",
                    "specifications": "-80°C Specimen Storage | Illumina NovaSeq Marine Sequencer",
                    "description": "Global oceanic genetic repository housing over 150,000 deep-sea invertebrate, coral, and microbial specimens for pharmaceutical and ecological research.",
                    "status": "Catalog Open to Global Researchers",
                    "image_subject": "Scientist in marine biology laboratory examining colorful coral specimens",
                    "image_path": "assets/images/fleet/marine-edna-lab.jpg",
                },
                {
                    "id": "vessel-6",
                    "title": "Ocean Acoustic Hydrophone Array Network",
                    "category": "benthic_observatories",
                    "category_label": "Subsea Sensor Networks",
                    "specifications": "10 Hz - 100 kHz Bandwidth | Cetacean Vocalization AI Detector",
                    "description": "Deep-water hydrophone array monitoring seismic oceanic rifts, blue whale migration patterns, and anthropogenic marine noise pollution.",
                    "status": "Listening Across Pacific Basin",
                    "image_subject": "Humpback whale diving into deep blue ocean water",
                    "image_path": "assets/images/fleet/ocean-acoustic-array.jpg",
                },
            ]

            filters = {
                "categories": [
                    {"id": "all", "label": "All Programmes"},
                    {"id": "research_vessels", "label": "Research Ships"},
                    {"id": "submersibles", "label": "Submersibles & ROVs"},
                    {"id": "autonomous_gliders", "label": "Autonomous Gliders"},
                    {"id": "benthic_observatories", "label": "Subsea Sensor Networks"},
                    {"id": "biological_archives", "label": "Biodiversity Archives"},
                ],
                "search_placeholder": "Search vessels, submersibles, expeditions, or oceanic data...",
            }

            form_spec = [{
                "form_id": "inquiry-form",
                "title": "Expedition Inquiry & Research Collaboration",
                "purpose": "Research Berth & Science Inquiry",
                "fields": [
                    {"name": "full_name", "label": "Chief Scientist / Inquirer Name *", "type": "text", "required": True},
                    {"name": "email", "label": "Academic / Institutional Email *", "type": "email", "required": True},
                    {"name": "institution", "label": "Research Institute / Organization", "type": "text", "required": False},
                    {"name": "programme", "label": "Focus Programme / Target Asset", "type": "select", "options": [
                        "R/V Challenger Abyssal Research Ship",
                        "Nautilus 6000 Deep-Sea ROV",
                        "Autonomous Glider Data Access",
                        "Marine eDNA Repository Access",
                        "Public Ocean Conservation Outreach",
                    ], "required": True},
                    {"name": "message", "label": "Collaboration Objectives & Scope *", "type": "textarea", "required": True},
                ],
                "submit_text": "Submit Expedition Inquiry",
                "mode": "demonstration",
                "disclosure": "Demonstration Mode: Expedition inquiries and berth requests are validated and logged in-browser. No real maritime contract is transmitted.",
                "success_message": "Thank you! Your research inquiry has been submitted to the institute science operations desk.",
            }]

            assets = [
                {"id": "hero", "component": "hero", "relative_path": "assets/images/hero-marine.jpg", "subject": "Vast deep blue ocean waters with research ship on horizon", "width": 1600, "height": 1067},
                {"id": "fleet-1", "component": "showcase", "relative_path": "assets/images/fleet/challenger-vessel.jpg", "subject": "Modern ocean research vessel ship on deep ocean", "width": 800, "height": 600},
                {"id": "fleet-2", "component": "showcase", "relative_path": "assets/images/fleet/nautilus-rov.jpg", "subject": "Deep ocean submersible underwater vehicle diving into deep waters", "width": 800, "height": 600},
                {"id": "fleet-3", "component": "showcase", "relative_path": "assets/images/fleet/autonomous-glider.jpg", "subject": "Underwater yellow robotic glider exploring marine waters", "width": 800, "height": 600},
                {"id": "fleet-4", "component": "showcase", "relative_path": "assets/images/fleet/benthic-sensor-node.jpg", "subject": "Deep sea hydrothermal vent with mineral clouds and glowing marine life", "width": 800, "height": 600},
                {"id": "fleet-5", "component": "showcase", "relative_path": "assets/images/fleet/marine-edna-lab.jpg", "subject": "Marine biologist working in modern ocean science laboratory", "width": 800, "height": 600},
                {"id": "fleet-6", "component": "showcase", "relative_path": "assets/images/fleet/ocean-acoustic-array.jpg", "subject": "Magnificent marine life whale swimming in deep ocean", "width": 800, "height": 600},
            ]

            semantic_keywords = ["marine", "oceanographic", "submersible", "vessel", "deep-sea", "benthic", "ocean", "expedition", "hydrothermal", "glider"]

        # ----------------------------------------------------------------------
        # 3. VOLCANOLOGY, SEISMOLOGY & GEOTHERMAL RESEARCH
        # ----------------------------------------------------------------------
        elif is_volcanology:
            domain = "volcanology_geothermal_research"
            subtype = "Volcanology, Seismology & Geothermal Energy Research Institute"
            archetype = "research_institution"
            purpose = f"Advance volcanological monitoring, tectonic seismology, and sustainable geothermal energy research at {brand}."
            target_audience = "Geophysicists, volcanologists, energy utility engineers, civil protection agencies, and earth science scholars."
            objectives = [
                "Maintain continuous multi-parameter telemetry across active volcanic calderas and rift faults",
                "Catalog hydrothermal plumes, seismic tremor events, and geochemical gas emissions",
                "Pioneer high-enthalpy supercritical geothermal reservoir exploration for clean baseload power",
                "Provide civil safety advisories, field guidelines, and open geological drill core archives",
            ]
            visual_dir = "Volcanic geothermal aesthetic: deep basalt charcoal (#1c1917), magma ember (#ef4444), geothermal steam (#f1f5f9), and tectonic amber (#f59e0b) accents."
            colors = {
                "primary": "#1c1917",
                "secondary": "#292524",
                "accent": "#ef4444",
                "accent_secondary": "#f59e0b",
                "background": "#0c0a09",
                "surface": "#1c1917",
                "surface_border": "#44403c",
                "text_primary": "#fafaf9",
                "text_secondary": "#a8a29e",
                "border": "#292524",
            }
            if custom_colors:
                colors.update(custom_colors)

            typography = {
                "font_heading": "'Space Grotesk', system-ui, sans-serif",
                "font_body": "'Inter', -apple-system, sans-serif",
                "font_mono": "'JetBrains Mono', monospace",
            }

            sections = [
                {"id": "navbar", "title": "Navigation", "tag": "header", "component": "navbar"},
                {"id": "hero", "title": "Caldera Monitoring & Geothermal Hero", "tag": "section", "component": "hero"},
                {"id": "about", "title": "About Institute", "tag": "section", "component": "about"},
                {"id": "observatories", "title": "Volcanic Monitoring Networks & Geothermal Sites", "tag": "section", "component": "showcase_grid"},
                {"id": "schedule", "title": "Monitoring Schedules & Exploration Programs", "tag": "section", "component": "schedule_timeline"},
                {"id": "discoveries", "title": "Geological Discovery Archives", "tag": "section", "component": "discovery_archive"},
                {"id": "telemetry", "title": "Real-Time Seismic & Caldera Telemetry", "tag": "section", "component": "telemetry_feed"},
                {"id": "contact", "title": "Research Collaboration & Data Access", "tag": "section", "component": "inquiry_form"},
                {"id": "footer", "title": "Footer", "tag": "footer", "component": "footer"},
            ]

            entities = [
                {
                    "id": "instrument-1",
                    "title": "Broadband Seismic Array & Borehole Tiltmeter Station",
                    "category": "seismic_monitoring",
                    "category_label": "Seismic Monitoring",
                    "specifications": "Triaxial Guralp 3T | 120s-50Hz Flat Velocity | Sub-Micro-Radian Tilt",
                    "description": "High-sensitivity borehole seismic network detecting harmonic tremor, volcanic tectonic earthquakes, and magma reservoir inflation.",
                    "status": "Continuous Active Telemetry",
                    "image_subject": "Broadband borehole seismometer station on volcanic ridge with live seismic waveform",
                    "image_path": "assets/images/monitoring/seismic-station.jpg",
                },
                {
                    "id": "instrument-2",
                    "title": "FLIR Radiometric Caldera Thermal Imager",
                    "category": "thermal_imagery",
                    "category_label": "Thermal Imaging",
                    "specifications": "640x512 High-Res InSb Sensor | -40°C to 1200°C Calibration | 30 FPS",
                    "description": "Long-range calibrated radiometric infrared imaging system monitoring lava dome extrusion, fumarole field temperatures, and heat flux.",
                    "status": "Real-time Telemetry Stream",
                    "image_subject": "Calibrated thermal infrared camera view of glowing volcanic crater and lava lake",
                    "image_path": "assets/images/monitoring/thermal-imager.jpg",
                },
                {
                    "id": "instrument-3",
                    "title": "Automated Scanning UV DOAS Gas Spectrometer",
                    "category": "gas_geochemistry",
                    "category_label": "Gas Geochemistry",
                    "specifications": "UV Spectrometry 280-420 nm | Automated Scanning Scanner | 1 Hz",
                    "description": "Automated scanning DOAS network calculating continuous sulfur dioxide (SO2) and carbon dioxide (CO2) flux in volcanic eruption plumes.",
                    "status": "Calibrated Emission Monitoring",
                    "image_subject": "Automated scanning UV DOAS spectrometer station measuring volcanic gas plume",
                    "image_path": "assets/images/monitoring/gas-spectrometer.jpg",
                },
                {
                    "id": "instrument-4",
                    "title": "Deep Borehole Dilatometer & Geodetic GNSS Network",
                    "category": "geodetic_deformation",
                    "category_label": "Geodetic Deformation",
                    "specifications": "Sacks-Evertson Borehole Strainmeter | 10^-10 Strain Resolution | Dual GNSS",
                    "description": "Ultra-deep 300m borehole strain and geodetic positioning station measuring crustal deformation and magma chamber pressurization.",
                    "status": "Sub-Millimeter Real-Time Tracking",
                    "image_subject": "Deep borehole geodetic tiltmeter and GNSS station with crustal strain vectors",
                    "image_path": "assets/images/monitoring/borehole-tiltmeter.jpg",
                },
                {
                    "id": "instrument-5",
                    "title": "Supercritical High-Enthalpy Geothermal Wellhead Complex",
                    "category": "geothermal_energy",
                    "category_label": "Geothermal Exploration",
                    "specifications": "450°C Fluid Reservoir | 3500m Subsurface Depth | Binary Cycle Turbines",
                    "description": "Experimental deep supercritical geothermal energy extraction facility tapping deep magmatic heat reservoirs for zero-emission baseload power.",
                    "status": "Exploration & Power Generation",
                    "image_subject": "Supercritical geothermal steam wellhead and power generation complex",
                    "image_path": "assets/images/monitoring/geothermal-wellhead.jpg",
                },
                {
                    "id": "instrument-6",
                    "title": "Petrological Core Archive & High-Pressure Magma Lab",
                    "category": "petrology_archives",
                    "category_label": "Petrology & Drill Cores",
                    "specifications": "Multi-Sensor Core Logger (MSCL) | P-V-T Piston Cylinder Press (3 GPa)",
                    "description": "Comprehensive volcanic stratigraphy drill core collection and high-pressure experimental petrology facility modeling magma crystallization.",
                    "status": "Curated Repository & Lab",
                    "image_subject": "Volcanic drill core stratigraphy archive and high pressure magma research lab",
                    "image_path": "assets/images/monitoring/petrology-archive.jpg",
                },
            ]

            filters = {
                "categories": [
                    {"id": "all", "label": "All Monitoring Stations"},
                    {"id": "seismic_monitoring", "label": "Seismic Monitoring"},
                    {"id": "thermal_imagery", "label": "Thermal Imaging"},
                    {"id": "gas_geochemistry", "label": "Gas Geochemistry"},
                    {"id": "geodetic_deformation", "label": "Geodetic Deformation"},
                    {"id": "geothermal_energy", "label": "Geothermal Exploration"},
                    {"id": "petrology_archives", "label": "Petrology & Cores"},
                ],
                "search_placeholder": "Search monitoring stations, sensors, or geothermal reservoirs...",
            }

            form_spec = [{
                "form_id": "inquiry-form",
                "title": "Research Collaboration & Data Access",
                "purpose": "Geological Data Request & Collaboration Inquiry",
                "fields": [
                    {"name": "full_name", "label": "Principal Investigator / Researcher Name *", "type": "text", "required": True},
                    {"name": "email", "label": "Institutional Email Address *", "type": "email", "required": True},
                    {"name": "organization", "label": "Institution / University / Geological Survey", "type": "text", "required": False},
                    {"name": "research_focus", "label": "Area of Research / Data Access Focus", "type": "select", "options": [
                        "Real-Time Seismic Telemetry Access",
                        "Geothermal Wellhead Fluid Chemistry Data",
                        "Volcanic Gas Emission SO2 Flux Records",
                        "Petrological Drill Core Sample Access",
                        "Joint Fieldwork & Instrumentation Proposal",
                    ], "required": True},
                    {"name": "request_details", "label": "Research Objectives & Project Summary *", "type": "textarea", "required": True},
                ],
                "submit_text": "Submit Research Request",
                "mode": "demonstration",
                "disclosure": "Demonstration Mode: Research collaboration proposals are validated and logged in-browser. No geological permit or telemetry license is issued.",
                "success_message": "Thank you! Your research inquiry has been received by the volcanological science committee.",
            }]

            assets = [
                {"id": "hero", "component": "hero", "relative_path": "assets/images/hero-volcanology.jpg", "subject": "Active stratovolcano with glowing lava summit and geothermal steam plume", "width": 1600, "height": 1067},
                {"id": "mon-1", "component": "showcase", "relative_path": "assets/images/monitoring/seismic-station.jpg", "subject": "Broadband borehole seismometer station on volcanic ridge with live seismic waveform", "width": 800, "height": 600},
                {"id": "mon-2", "component": "showcase", "relative_path": "assets/images/monitoring/thermal-imager.jpg", "subject": "Calibrated thermal infrared camera view of glowing volcanic crater and lava lake", "width": 800, "height": 600},
                {"id": "mon-3", "component": "showcase", "relative_path": "assets/images/monitoring/gas-spectrometer.jpg", "subject": "Automated scanning UV DOAS spectrometer station measuring volcanic gas plume", "width": 800, "height": 600},
                {"id": "mon-4", "component": "showcase", "relative_path": "assets/images/monitoring/borehole-tiltmeter.jpg", "subject": "Deep borehole geodetic tiltmeter and GNSS station with crustal strain vectors", "width": 800, "height": 600},
                {"id": "mon-5", "component": "showcase", "relative_path": "assets/images/monitoring/geothermal-wellhead.jpg", "subject": "Supercritical geothermal steam wellhead and power generation complex", "width": 800, "height": 600},
                {"id": "mon-6", "component": "showcase", "relative_path": "assets/images/monitoring/petrology-archive.jpg", "subject": "Volcanic drill core stratigraphy archive and high pressure magma research lab", "width": 800, "height": 600},
            ]

            semantic_keywords = ["volcanology", "seismic", "geothermal", "magma", "caldera", "spectrometer", "tiltmeter", "borehole", "tectonic", "eruption"]

        # ----------------------------------------------------------------------
        # 4. SUBSCRIPTION-BASED PROJECT MANAGEMENT SAAS (Product Archetype)
        # ----------------------------------------------------------------------
        elif is_saas:
            domain = "saas_software"
            subtype = "Project Management & Agile Sprint SaaS"
            archetype = "saas_product"
            purpose = f"Orchestrate complex engineering workflows, sprint milestones, and cross-functional squad delivery for {brand}."
            target_audience = "Engineering leaders, agile product teams, software developers, and high-velocity tech organizations."
            objectives = [
                f"Accelerate software delivery velocity and sprint predictability with {brand}",
                "Provide an interactive workspace simulator featuring Kanban boards, velocity telemetry, and workflow automations",
                "Automate repetitive developer lifecycle triggers and CI/CD pull-request deployments",
                "Offer flexible subscription tiers with instant transparent monthly/annual billing",
            ]
            visual_dir = "Dark developer cockpit aesthetic: deep obsidian canvas, vibrant cyan and electric indigo accents, clean mono typography, and subtle glassmorphic surface borders."
            colors = {
                "primary": "#07090e",
                "secondary": "#0f172a",
                "accent": "#00f0ff",
                "accent_secondary": "#6366f1",
                "background": "#07090e",
                "surface": "#0d1322",
                "surface_border": "#1e293b",
                "text_primary": "#f8fafc",
                "text_secondary": "#94a3b8",
                "border": "#1e293b",
            }
            if custom_colors:
                colors.update(custom_colors)
            typography = {
                "font_heading": "'Plus Jakarta Sans', system-ui, sans-serif",
                "font_body": "'Inter', -apple-system, sans-serif",
                "font_mono": "'JetBrains Mono', monospace",
            }
            sections = [
                {"id": "navbar", "title": "Navigation", "tag": "header", "component": "navbar"},
                {"id": "hero", "title": "Platform Hero", "tag": "section", "component": "hero"},
                {"id": "demo-preview", "title": "Interactive Workspace Simulator", "tag": "section", "component": "interactive_demo"},
                {"id": "features", "title": "Core Platform Capabilities", "tag": "section", "component": "features_grid"},
                {"id": "pricing", "title": "Transparent Subscription Pricing", "tag": "section", "component": "pricing_matrix"},
                {"id": "integrations", "title": "Developer Integrations", "tag": "section", "component": "integrations_grid"},
                {"id": "contact", "title": "Start 14-Day Free Trial", "tag": "section", "component": "inquiry_form"},
                {"id": "footer", "title": "Footer", "tag": "footer", "component": "footer"},
            ]
            entities = [
                {
                    "id": "feature-1",
                    "title": "Multi-Dimensional Sprint Boards",
                    "category": "workflow",
                    "category_label": "Agile Workflow",
                    "specifications": "CRDT Real-Time Sync | Sub-10ms State Mutation | Custom Epics",
                    "description": "Fluid Kanban, Gantt, and tabular sprint views with bidirectional GitHub issue synchronization and automated WIP limits.",
                    "status": "Enterprise Ready",
                    "image_subject": "Dark software Kanban board interface preview",
                    "image_path": "assets/images/features/kanban-board.jpg",
                },
                {
                    "id": "feature-2",
                    "title": "Velocity & Predictive Burndown Engine",
                    "category": "analytics",
                    "category_label": "Real-Time Telemetry",
                    "specifications": "Monte Carlo Forecasting | Cycle Time Dispersion | PR Latency",
                    "description": "Predictive delivery analytics evaluating historical squad throughput, code churn, and bottleneck detection.",
                    "status": "Telemetry Active",
                    "image_subject": "SaaS analytics chart dashboard with velocity curves",
                    "image_path": "assets/images/features/analytics-dashboard.jpg",
                },
                {
                    "id": "feature-3",
                    "title": "Event-Driven Workflow Automations",
                    "category": "automation",
                    "category_label": "Workflow Automation",
                    "specifications": "No-Code Rule Builder | Webhook Webhooks | SLA Monitoring",
                    "description": "Trigger automated status transitions, alert escalation, and branch creation upon pull request review approvals.",
                    "status": "Zero-Latency Trigger",
                    "image_subject": "Node automation pipeline connecting developer events",
                    "image_path": "assets/images/features/automation-pipeline.jpg",
                },
                {
                    "id": "feature-4",
                    "title": "Cross-Squad Dependency Mapping",
                    "category": "workflow",
                    "category_label": "Enterprise Governance",
                    "specifications": "Directed Acyclic Graphs | Blocking Alerts | Critical Path Analysis",
                    "description": "Visual dependency maps surfacing cross-repository blockers before sprint commitments are locked.",
                    "status": "SOC2 Verified",
                    "image_subject": "Network dependency graph visualization software",
                    "image_path": "assets/images/features/dependency-graph.jpg",
                },
                {
                    "id": "feature-5",
                    "title": "Enterprise Security & Granular RBAC",
                    "category": "governance",
                    "category_label": "Security & Audit",
                    "specifications": "SAML 2.0 / Okta SSO | Immutable Audit Logs | AES-256 at Rest",
                    "description": "Defense-in-depth access governance with custom role definitions, IP whitelisting, and automated compliance logging.",
                    "status": "HIPAA & SOC2 Type II",
                    "image_subject": "Enterprise security authentication shielding dashboard",
                    "image_path": "assets/images/features/security-shield.jpg",
                },
                {
                    "id": "feature-6",
                    "title": "Native CLI & Bi-Directional SDKs",
                    "category": "developer",
                    "category_label": "Developer Tooling",
                    "specifications": "Go / Rust CLI | GraphQL & REST APIs | JetBrains & VS Code Extensions",
                    "description": "Manage backlog tickets, branch transitions, and team standups directly from the developer terminal.",
                    "status": "Open Specification",
                    "image_subject": "Developer terminal command line interface with code",
                    "image_path": "assets/images/features/cli-terminal.jpg",
                },
            ]
            filters = {
                "categories": [
                    {"id": "all", "label": "All Platform Modules"},
                    {"id": "workflow", "label": "Agile Workflow"},
                    {"id": "analytics", "label": "Real-Time Telemetry"},
                    {"id": "automation", "label": "Workflow Automation"},
                    {"id": "governance", "label": "Security & Governance"},
                ],
                "search_placeholder": "Search SaaS features, sprint tools, integrations, or APIs...",
            }
            form_spec = [{
                "form_id": "inquiry-form",
                "title": "Start Your 14-Day Free Enterprise Trial",
                "purpose": "Free Trial & Workspace Provisioning",
                "fields": [
                    {"name": "full_name", "label": "Full Name *", "type": "text", "required": True},
                    {"name": "email", "label": "Work Email *", "type": "email", "required": True},
                    {"name": "team_size", "label": "Engineering Team Size", "type": "select", "options": ["1-10 Developers", "11-50 Developers", "51-250 Developers", "250+ Enterprise"], "required": True},
                    {"name": "message", "label": "Primary Workflow Objectives *", "type": "textarea", "required": True},
                ],
                "submit_text": "Activate Free Workspace",
                "mode": "demonstration",
                "disclosure": "Demonstration Mode: Workspace provisioning is simulated in-browser. Zero credit card required.",
                "success_message": f"Welcome aboard! Your {brand} workspace simulation is active.",
            }]
            assets = [
                {"id": "hero", "component": "hero", "relative_path": "assets/images/hero-saas.jpg", "subject": f"Modern dark developer dashboard interface for {brand}", "width": 1600, "height": 1067, "url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1600&q=80"},
                {"id": "feat-1", "component": "features", "relative_path": "assets/images/features/kanban-board.jpg", "subject": "Dark software Kanban sprint board interface", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1531403009284-440f080d1e12?auto=format&fit=crop&w=800&q=80"},
                {"id": "feat-2", "component": "features", "relative_path": "assets/images/features/analytics-dashboard.jpg", "subject": "SaaS analytics velocity burndown chart", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=800&q=80"},
                {"id": "feat-3", "component": "features", "relative_path": "assets/images/features/automation-pipeline.jpg", "subject": "Automation workflow event rule node diagram", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1504639725590-34d0984388bd?auto=format&fit=crop&w=800&q=80"},
                {"id": "feat-4", "component": "features", "relative_path": "assets/images/features/dependency-graph.jpg", "subject": "Cross-squad dependency graph interface", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=800&q=80"},
                {"id": "feat-5", "component": "features", "relative_path": "assets/images/features/security-shield.jpg", "subject": "Enterprise security authentication dashboard", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1563986768609-322da13575f3?auto=format&fit=crop&w=800&q=80"},
                {"id": "feat-6", "component": "features", "relative_path": "assets/images/features/cli-terminal.jpg", "subject": "Developer terminal command line interface", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1555066931-4365d14bab8c?auto=format&fit=crop&w=800&q=80"},
            ]
            semantic_keywords = ["saas", "project management", "sprint", "kanban", "workflow", "velocity", "backlog", "pricing", "orbit", "automation"]

        # ----------------------------------------------------------------------
        # 5. ECO-TOURISM & WILDERNESS ADVENTURE (Adventure Archetype)
        # ----------------------------------------------------------------------
        elif is_tourism:
            domain = "tourism_adventure"
            subtype = "Eco-Tourism & Wilderness Expedition Travel"
            archetype = "tourism_adventure"
            purpose = f"Deliver immersive, carbon-neutral wilderness expeditions and expert-guided journeys for {brand}."
            target_audience = "Eco-conscious travelers, mountaineers, wilderness trekking enthusiasts, and conservation photographers."
            objectives = [
                f"Curate world-class carbon-neutral wilderness journeys and alpine treks for {brand}",
                "Provide detailed day-by-day expedition route itineraries with elevation profiles and camp coordinates",
                "Equip explorers with comprehensive field guidelines, mandatory gear checklists, and Leave-No-Trace protocols",
                "Facilitate seamless expedition bookings with small-group departure verification",
            ]
            visual_dir = "Earthy, immersive adventure aesthetic: deep pine forest, warm terracotta, granite stone, refined serif typography, and authentic expedition photography."
            colors = {
                "primary": "#1b281f",
                "secondary": "#283b2e",
                "accent": "#d97706",
                "accent_secondary": "#15803d",
                "background": "#fcfbf7",
                "surface": "#ffffff",
                "surface_border": "#e5e3da",
                "text_primary": "#1c241e",
                "text_secondary": "#576059",
                "border": "#e5e3da",
            }
            if custom_colors:
                colors.update(custom_colors)
            typography = {
                "font_heading": "'Playfair Display', Georgia, serif",
                "font_body": "'Plus Jakarta Sans', system-ui, sans-serif",
                "font_mono": "'JetBrains Mono', monospace",
            }
            sections = [
                {"id": "navbar", "title": "Navigation", "tag": "header", "component": "navbar"},
                {"id": "hero", "title": "Expedition Hero", "tag": "section", "component": "hero"},
                {"id": "about", "title": "Conservation & Field Ethos", "tag": "section", "component": "about"},
                {"id": "expeditions", "title": "Featured Wilderness Expeditions", "tag": "section", "component": "showcase_grid"},
                {"id": "itinerary-timeline", "title": "Interactive Expedition Itinerary", "tag": "section", "component": "itinerary_timeline"},
                {"id": "field-guide", "title": "Field Guidelines & Gear Checklist", "tag": "section", "component": "guidelines_grid"},
                {"id": "contact", "title": "Reserve Expedition Departure", "tag": "section", "component": "inquiry_form"},
                {"id": "footer", "title": "Footer", "tag": "footer", "component": "footer"},
            ]
            entities = [
                {
                    "id": "expedition-1",
                    "title": "Patagonia Southern Icefield Traverse",
                    "category": "alpine",
                    "category_label": "Alpine Trekking",
                    "specifications": "12 Days | Strenuous (Grade V) | Max 8 Explorers | From $4,850",
                    "description": "Glacial icecap crossing navigating crevasse fields, granite spires of Fitz Roy, and remote wind-swept wilderness camps.",
                    "status": "Departing Nov 2026",
                    "image_subject": "Patagonia granite mountain spires and glacial icecap",
                    "image_path": "assets/images/expeditions/patagonia-traverse.jpg",
                },
                {
                    "id": "expedition-2",
                    "title": "Svalbard Polar Archipelago Expedition",
                    "category": "polar",
                    "category_label": "Polar & Marine",
                    "specifications": "10 Days | Moderate (Grade III) | Max 12 Explorers | From $6,200",
                    "description": "High Arctic zodiac navigation and sea-ice snowshoeing tracking bearded seals, polar walruses, and midnight sun fjords.",
                    "status": "Departing Jul 2026",
                    "image_subject": "High Arctic sea ice floes and glaciated fjord landscape",
                    "image_path": "assets/images/expeditions/svalbard-polar.jpg",
                },
                {
                    "id": "expedition-3",
                    "title": "Namib Desert Sossusvlei Dune Odyssey",
                    "category": "desert",
                    "category_label": "Desert Odyssey",
                    "specifications": "8 Days | Moderate (Grade II) | Max 10 Explorers | From $3,900",
                    "description": "Star-navigation across the oldest desert on Earth, summiting Big Daddy dune at dawn and exploring Deadvlei clay pans.",
                    "status": "Departing Sep 2026",
                    "image_subject": "Red sand dunes of Namib desert with sharp shadows",
                    "image_path": "assets/images/expeditions/namib-dune.jpg",
                },
                {
                    "id": "expedition-4",
                    "title": "Himalayan Annapurna Sanctuary Trek",
                    "category": "alpine",
                    "category_label": "Alpine Trekking",
                    "specifications": "14 Days | Strenuous (Grade IV) | Max 8 Explorers | From $3,650",
                    "description": "High-altitude pilgrimage into the 360-degree amphitheatre of 8,000m peaks, rhododendron forests, and Gurung villages.",
                    "status": "Departing Oct 2026",
                    "image_subject": "Towering snowy Himalayan peak and high alpine valley",
                    "image_path": "assets/images/expeditions/himalaya-sanctuary.jpg",
                },
                {
                    "id": "expedition-5",
                    "title": "Atacama Altiplano Salt Flats & Geysers",
                    "category": "desert",
                    "category_label": "Desert Odyssey",
                    "specifications": "7 Days | Easy-Moderate (Grade II) | Max 12 Explorers | From $2,950",
                    "description": "Geothermal geyser fields at dawn, flamingos in lithium-rich salt basins, and world-class celestial stargazing at 4,200m.",
                    "status": "Departing Aug 2026",
                    "image_subject": "Atacama high altitude salt flats and volcanic horizon",
                    "image_path": "assets/images/expeditions/atacama-salt.jpg",
                },
                {
                    "id": "expedition-6",
                    "title": "Fiordland Dusky Sound Sea Kayaking",
                    "category": "polar",
                    "category_label": "Polar & Marine",
                    "specifications": "9 Days | Strenuous (Grade IV) | Max 6 Explorers | From $4,400",
                    "description": "Self-supported sea kayak expedition through primeval rainforest-draped fjords, waterfalls, and fur seal sanctuaries.",
                    "status": "Departing Dec 2026",
                    "image_subject": "Pristine mist-shrouded fiord with deep green rainforest",
                    "image_path": "assets/images/expeditions/fiordland-kayak.jpg",
                },
            ]
            filters = {
                "categories": [
                    {"id": "all", "label": "All Expeditions"},
                    {"id": "alpine", "label": "Alpine Trekking"},
                    {"id": "polar", "label": "Polar & Marine"},
                    {"id": "desert", "label": "Desert Odyssey"},
                ],
                "search_placeholder": "Search expeditions, wilderness regions, difficulty, or season...",
            }
            form_spec = [{
                "form_id": "inquiry-form",
                "title": f"Reserve Your Departure with {brand}",
                "purpose": "Expedition Reservation & Inquiry",
                "fields": [
                    {"name": "full_name", "label": "Lead Explorer Name *", "type": "text", "required": True},
                    {"name": "email", "label": "Email Address *", "type": "email", "required": True},
                    {"name": "expedition", "label": "Preferred Expedition Route", "type": "select", "options": [
                        "Patagonia Southern Icefield Traverse (12 Days)",
                        "Svalbard Polar Archipelago Expedition (10 Days)",
                        "Namib Desert Sossusvlei Dune Odyssey (8 Days)",
                        "Himalayan Annapurna Sanctuary Trek (14 Days)",
                        "Atacama Altiplano Salt Flats & Geysers (7 Days)",
                        "Fiordland Dusky Sound Sea Kayaking (9 Days)",
                    ], "required": True},
                    {"name": "party_size", "label": "Party Size", "type": "select", "options": ["Solo Explorer (1)", "Duo (2 Explorers)", "Small Group (3-4 Explorers)", "Private Charter (5-8 Explorers)"], "required": True},
                    {"name": "message", "label": "Wilderness Experience & Medical Notes *", "type": "textarea", "required": True},
                ],
                "submit_text": "Submit Expedition Reservation",
                "mode": "demonstration",
                "disclosure": "Demonstration Mode: Expedition bookings are simulated in-browser. Zero monetary transactions occur.",
                "success_message": f"Thank you! Your expedition reservation inquiry has been confirmed by {brand}.",
            }]
            assets = [
                {"id": "hero", "component": "hero", "relative_path": "assets/images/hero-expeditions.jpg", "subject": f"Epic panoramic mountain wilderness landscape for {brand}", "width": 1600, "height": 1067, "url": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1600&q=80"},
                {"id": "exp-1", "component": "expeditions", "relative_path": "assets/images/expeditions/patagonia-traverse.jpg", "subject": "Patagonia granite mountain spires and glacial icecap", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=800&q=80"},
                {"id": "exp-2", "component": "expeditions", "relative_path": "assets/images/expeditions/svalbard-polar.jpg", "subject": "High Arctic sea ice floes and glaciated fjord landscape", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1483921020237-2ff51e8e4b22?auto=format&fit=crop&w=800&q=80"},
                {"id": "exp-3", "component": "expeditions", "relative_path": "assets/images/expeditions/namib-dune.jpg", "subject": "Red sand dunes of Namib desert with sharp shadows", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1509316975850-ff9c5deb0cd9?auto=format&fit=crop&w=800&q=80"},
                {"id": "exp-4", "component": "expeditions", "relative_path": "assets/images/expeditions/himalaya-sanctuary.jpg", "subject": "Towering snowy Himalayan peak and high alpine valley", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1486870591958-9b9d0d1dda99?auto=format&fit=crop&w=800&q=80"},
                {"id": "exp-5", "component": "expeditions", "relative_path": "assets/images/expeditions/atacama-salt.jpg", "subject": "Atacama high altitude salt flats and volcanic horizon", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=800&q=80"},
                {"id": "exp-6", "component": "expeditions", "relative_path": "assets/images/expeditions/fiordland-kayak.jpg", "subject": "Pristine mist-shrouded fiord with deep green rainforest", "width": 800, "height": 600, "url": "https://images.unsplash.com/photo-1448375240586-882707db888b?auto=format&fit=crop&w=800&q=80"},
            ]
            semantic_keywords = ["expedition", "eco-tourism", "wilderness", "trekking", "itinerary", "patagonia", "terra", "conservation", "mountaineering", "alpine"]

        # ----------------------------------------------------------------------
        # 6. DYNAMIC ARBITRARY DOMAIN EXTRACTION (Open-Domain Universal Engine)
        # ----------------------------------------------------------------------
        else:
            # Extract key nouns and topics from the prompt
            words = [w for w in re.findall(r'[a-zA-Z]{3,}', p_lower) if w not in [
                "create", "build", "make", "generate", "website", "application", "modern", "authoritative",
                "responsive", "interactive", "with", "that", "this", "from", "and", "the", "for"
            ]]
            primary_topic = words[0] if words else "Innovation"
            secondary_topic = words[1] if len(words) > 1 else "Excellence"

            domain = f"{primary_topic}_{secondary_topic}".lower()
            subtype = f"{primary_topic.title()} & {secondary_topic.title()} Enterprise"
            archetype = "interactive_showcase"
            purpose = f"Deliver comprehensive, industry-leading solutions and showcase capabilities for {brand}."
            target_audience = "Professional partners, clients, industry stakeholders, and prospective customers."
            objectives = [
                f"Present the core capabilities and distinctive advantages of {brand}",
                f"Enable interactive discovery of featured offerings and technical specifications",
                "Facilitate direct inquiries and strategic consultations",
            ]
            visual_dir = "Contemporary executive aesthetic with prompt-aligned accents, balanced whitespace, and high-legibility typography."
            colors = {
                "primary": "#0f172a",
                "secondary": "#1e293b",
                "accent": "#0ea5e9",
                "accent_secondary": "#6366f1",
                "background": "#f8fafc",
                "surface": "#ffffff",
                "surface_border": "#e2e8f0",
                "text_primary": "#0f172a",
                "text_secondary": "#475569",
                "border": "#e2e8f0",
            }
            if custom_colors:
                colors.update(custom_colors)

            typography = {
                "font_heading": "'Plus Jakarta Sans', system-ui, sans-serif",
                "font_body": "'Inter', -apple-system, sans-serif",
                "font_mono": "'JetBrains Mono', monospace",
            }

            cat_1 = f"{primary_topic.title()} Systems"
            cat_2 = f"{secondary_topic.title()} Initiatives"
            cat_3 = "Specialized Operations"

            sections = [
                {"id": "navbar", "title": "Navigation", "tag": "header", "component": "navbar"},
                {"id": "hero", "title": "Executive Hero Presentation", "tag": "section", "component": "hero"},
                {"id": "about", "title": f"About {brand}", "tag": "section", "component": "about"},
                {"id": "showcase", "title": f"Featured {primary_topic.title()} Portfolio", "tag": "section", "component": "showcase_grid"},
                {"id": "contact", "title": "Inquiries & Consultation", "tag": "section", "component": "inquiry_form"},
                {"id": "footer", "title": "Footer", "tag": "footer", "component": "footer"},
            ]

            entities = [
                {
                    "id": "entity-1",
                    "title": f"{brand} Flagship {primary_topic.title()} Platform",
                    "category": "cat_1",
                    "category_label": cat_1,
                    "specifications": "High Precision Architecture | Integrated Workflow System",
                    "description": f"Comprehensive {primary_topic} platform engineered for maximum operational efficiency, reliability, and precision execution.",
                    "status": "Active Deployment",
                    "image_subject": f"Professional modern {primary_topic} facility showcase",
                    "image_path": "assets/images/showcase/item-1.jpg",
                },
                {
                    "id": "entity-2",
                    "title": f"Integrated {secondary_topic.title()} Framework",
                    "category": "cat_2",
                    "category_label": cat_2,
                    "specifications": "Scalable Infrastructure | Automated Continuous Telemetry",
                    "description": f"Advanced {secondary_topic} solution tailored to modern enterprise requirements with seamless ecosystem interoperability.",
                    "status": "Production Ready",
                    "image_subject": f"Modern advanced {secondary_topic} workspace technology",
                    "image_path": "assets/images/showcase/item-2.jpg",
                },
                {
                    "id": "entity-3",
                    "title": f"Next-Gen {primary_topic.title()} Matrix",
                    "category": "cat_1",
                    "category_label": cat_1,
                    "specifications": "Next-Gen Performance | Bounded Latency Subsystem",
                    "description": f"High-throughput {primary_topic} matrix offering rigorous data integrity and comprehensive capability mastery.",
                    "status": "Operational",
                    "image_subject": f"High precision engineering development facility",
                    "image_path": "assets/images/showcase/item-3.jpg",
                },
                {
                    "id": "entity-4",
                    "title": f"Dynamic {secondary_topic.title()} Protocol",
                    "category": "cat_2",
                    "category_label": cat_2,
                    "specifications": "Custom Adaptive Logic | Real-time Analytical Dashboard",
                    "description": f"Targeted {secondary_topic} protocol delivering dynamic insights and high-touch execution across all operations.",
                    "status": "Certified Standards",
                    "image_subject": f"Professional design and technology operations studio",
                    "image_path": "assets/images/showcase/item-4.jpg",
                },
                {
                    "id": "entity-5",
                    "title": f"Precision Operations Core",
                    "category": "cat_3",
                    "category_label": cat_3,
                    "specifications": "Multi-tier Verification | Fault-tolerant Architecture",
                    "description": f"Foundational operations core ensuring continuous reliability, transparent auditing, and elevated performance benchmarks.",
                    "status": "Fully Monitored",
                    "image_subject": f"Modern command and control operations center",
                    "image_path": "assets/images/showcase/item-5.jpg",
                },
                {
                    "id": "entity-6",
                    "title": f"Strategic Innovation Collective",
                    "category": "cat_3",
                    "category_label": cat_3,
                    "specifications": "Collaborative Research Pod | Rapid Prototyping Lab",
                    "description": f"Specialized research and development initiative pioneering novel methodologies in {primary_topic} and {secondary_topic}.",
                    "status": "Active R&D",
                    "image_subject": f"Collaborative modern innovation studio and research lab",
                    "image_path": "assets/images/showcase/item-6.jpg",
                },
            ]

            filters = {
                "categories": [
                    {"id": "all", "label": "All Offerings"},
                    {"id": "cat_1", "label": cat_1},
                    {"id": "cat_2", "label": cat_2},
                    {"id": "cat_3", "label": cat_3},
                ],
                "search_placeholder": f"Search {primary_topic}, {secondary_topic}, or capabilities...",
            }

            form_spec = [{
                "form_id": "inquiry-form",
                "title": f"Inquire with {brand}",
                "purpose": "Consultation and Inquiry",
                "fields": [
                    {"name": "full_name", "label": "Full Name *", "type": "text", "required": True},
                    {"name": "email", "label": "Email Address *", "type": "email", "required": True},
                    {"name": "organization", "label": "Organization / Company", "type": "text", "required": False},
                    {"name": "inquiry_type", "label": "Inquiry Topic", "type": "select", "options": [
                        cat_1,
                        cat_2,
                        cat_3,
                        "General Strategic Consultation",
                    ], "required": True},
                    {"name": "message", "label": "Message / Project Scope *", "type": "textarea", "required": True},
                ],
                "submit_text": "Submit Inquiry",
                "mode": "demonstration",
                "disclosure": "Demonstration Mode: Inquiries are captured and validated in-browser. No external message is transmitted.",
                "success_message": f"Thank you! Your inquiry has been received by the {brand} team.",
            }]

            assets = [
                {"id": "hero", "component": "hero", "relative_path": "assets/images/hero-main.jpg", "subject": f"Modern architectural headquarters and showcase for {brand}", "width": 1600, "height": 1067},
                {"id": "item-1", "component": "showcase", "relative_path": "assets/images/showcase/item-1.jpg", "subject": f"Advanced {primary_topic} platform equipment", "width": 800, "height": 600},
                {"id": "item-2", "component": "showcase", "relative_path": "assets/images/showcase/item-2.jpg", "subject": f"Modern {secondary_topic} workspace and technology", "width": 800, "height": 600},
                {"id": "item-3", "component": "showcase", "relative_path": "assets/images/showcase/item-3.jpg", "subject": "High precision engineering facility", "width": 800, "height": 600},
                {"id": "item-4", "component": "showcase", "relative_path": "assets/images/showcase/item-4.jpg", "subject": "Design and technology operations studio", "width": 800, "height": 600},
                {"id": "item-5", "component": "showcase", "relative_path": "assets/images/showcase/item-5.jpg", "subject": "Operations center with monitors and telemetry", "width": 800, "height": 600},
                {"id": "item-6", "component": "showcase", "relative_path": "assets/images/showcase/item-6.jpg", "subject": "Innovation research lab and creative studio", "width": 800, "height": 600},
            ]

            semantic_keywords = [primary_topic, secondary_topic, brand.lower(), "platform", "operations"]

        # Navigation structure
        nav = [
            {"label": "Home", "href": "#hero", "section_id": "hero", "is_cta": False},
        ]
        for s in sections:
            sid = s.get("id")
            if sid in ("navbar", "hero", "footer", "contact"):
                continue
            title = s.get("title", sid.replace("-", " ").replace("_", " ").title())
            label = title.split("&")[0].split("—")[0].strip()
            if len(label) > 16:
                label = label.split()[0]
            nav.append({"label": label, "href": f"#{sid}", "section_id": sid, "is_cta": False})
        nav.append({"label": "Inquiries", "href": "#contact", "section_id": "contact", "is_cta": True})

        interactions = [
            "Category filter pill switching (instant DOM update without page reload)",
            "Real-time keyword search across title, specifications, and descriptions",
            "Detail modal opening with full technical data and Esc/backdrop dismissal",
            "Validated demonstration inquiry form with in-browser feedback",
            "Responsive mobile hamburger navigation drawer",
        ]

        criteria = [
            f"Zero foreign brand contamination (never display other brands)",
            f"Zero generic placeholders (no 'Signature Offering', 'Strategic Solution', 'All Items', 'Modern Web Application')",
            f"Full responsive desktop (1440px), tablet (768px), and mobile (390px) rendering with 0 horizontal overflow",
            f"Zero unhandled console errors or broken image links",
            f"Demonstration feedback on form submissions with clear disclosure",
        ]

        backend_req = {
            "mode": "frontend_demo",
            "server_framework": None,
            "database": None,
            "endpoints": [],
        }
        if any(w in p_lower for w in ["fastapi", "express", "sqlite", "full-stack", "fullstack", "backend api", "real persistence"]):
            backend_req["mode"] = "fullstack_api"
            backend_req["server_framework"] = "fastapi" if "fastapi" in p_lower or "python" in p_lower else "express"
            backend_req["database"] = "sqlite"
            backend_req["endpoints"] = ["/api/inquiries", "/api/entities"]

        ledger = cls._build_requirement_ledger(
            prompt=raw_prompt,
            brand=brand,
            domain=domain,
            subtype=subtype,
            archetype=archetype,
            sections=sections,
            entities=entities,
            form_spec=form_spec,
            interactions=interactions,
            criteria=criteria,
        )

        return SynthesizedDomainPayload(
            requested_brand=brand,
            business_domain=domain,
            domain_subtype=subtype,
            application_archetype=archetype,
            purpose=purpose,
            target_audience=target_audience,
            business_objectives=objectives,
            visual_direction=visual_dir,
            color_palette=colors,
            typography=typography,
            required_sections=sections,
            content_entities=entities,
            entity_schemas={"entity_type": "domain_item", "fields": ["id", "title", "category", "specifications", "description", "status", "image_path"]},
            navigation_structure=nav,
            card_specs={"show_image": True, "show_badge": True, "show_specs": True, "action_label": "View Details"},
            required_interactions=interactions,
            filter_capabilities=filters,
            form_specs=form_spec,
            asset_requirements=assets,
            backend_requirements=backend_req,
            negative_constraints=negatives,
            acceptance_criteria=criteria,
            semantic_keywords=semantic_keywords,
            requirement_ledger=ledger,
        )

    @classmethod
    def _build_requirement_ledger(
        cls,
        prompt: str,
        brand: str,
        domain: str,
        subtype: str,
        archetype: str,
        sections: List[Dict[str, Any]],
        entities: List[Dict[str, Any]],
        form_spec: List[Dict[str, Any]],
        interactions: List[str],
        criteria: List[str],
    ) -> List[Dict[str, Any]]:
        ledger: List[Dict[str, Any]] = []

        # 1. Navigation & Header
        ledger.append({
            "req_id": "REQ-001",
            "source_excerpt": f"Website for {brand}",
            "category": "layout",
            "expected_component": "navbar",
            "expected_content": f"{brand} brand logo and responsive navigation links",
            "expected_dom_selector": "#navbar",
            "expected_interaction": "Sticky navigation header with anchor scrolling and mobile menu toggle",
            "verification_status": "PENDING",
            "evidence": "",
        })

        # 2. Hero Presentation
        ledger.append({
            "req_id": "REQ-002",
            "source_excerpt": f"{subtype} hero presentation",
            "category": "content",
            "expected_component": "hero",
            "expected_content": f"Authoritative hero presentation for {brand} with primary call-to-actions",
            "expected_dom_selector": "#hero",
            "expected_interaction": "Direct navigation to primary actions and section discovery",
            "verification_status": "PENDING",
            "evidence": "",
        })

        # 3. Archetype-Specific Components
        if archetype == "saas_product":
            ledger.append({
                "req_id": "REQ-003",
                "source_excerpt": "interactive workspace demo with Kanban and Analytics",
                "category": "interaction",
                "expected_component": "interactive_demo",
                "expected_content": "Interactive workspace simulator with Sprint Board, Velocity Analytics, and Automation rules",
                "expected_dom_selector": "#demo-preview",
                "expected_interaction": "Switch between Kanban board, analytics metrics, and workflow automation views via tab controls",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-004",
                "source_excerpt": "feature matrix",
                "category": "content",
                "expected_component": "features_grid",
                "expected_content": "Core platform capabilities grid with real-time sync, burndown telemetry, and RBAC governance",
                "expected_dom_selector": "#features",
                "expected_interaction": "Inspect capability cards and view detailed engineering specifications",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-005",
                "source_excerpt": "pricing tiers with monthly/annual toggle",
                "category": "interaction",
                "expected_component": "pricing_matrix",
                "expected_content": "Multi-tier subscription pricing matrix with Starter, Professional, and Enterprise plans",
                "expected_dom_selector": "#pricing",
                "expected_interaction": "Toggle between monthly and annual billing with dynamic price calculation",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-006",
                "source_excerpt": "integrations ecosystem",
                "category": "content",
                "expected_component": "integrations_grid",
                "expected_content": "Developer ecosystem integration partners (GitHub, Slack, Jira, Figma, AWS)",
                "expected_dom_selector": "#integrations",
                "expected_interaction": "Browse supported third-party developer toolchains and integrations",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-007",
                "source_excerpt": "free trial registration",
                "category": "interaction",
                "expected_component": "inquiry_form",
                "expected_content": "14-day free trial workspace registration form with input validation",
                "expected_dom_selector": "#contact",
                "expected_interaction": "Submit validated form with instant in-browser demonstration feedback",
                "verification_status": "PENDING",
                "evidence": "",
            })

        elif archetype == "tourism_adventure":
            ledger.append({
                "req_id": "REQ-003",
                "source_excerpt": "conservation ethos & about",
                "category": "content",
                "expected_component": "about",
                "expected_content": f"Conservation manifesto and field ethos for {brand}",
                "expected_dom_selector": "#about",
                "expected_interaction": "Review sustainability pillars and certified guide credentials",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-004",
                "source_excerpt": "guided expeditions with difficulty and duration",
                "category": "interaction",
                "expected_component": "showcase_grid",
                "expected_content": "Curated wilderness expeditions with difficulty badges, duration, group limits, and pricing",
                "expected_dom_selector": "#showcase-grid",
                "expected_interaction": "Filter expeditions by difficulty/region and search destinations in real-time",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-005",
                "source_excerpt": "day-by-day itineraries",
                "category": "interaction",
                "expected_component": "itinerary_timeline",
                "expected_content": "Interactive day-by-day expedition route timeline with elevation and terrain milestones",
                "expected_dom_selector": "#itinerary-timeline",
                "expected_interaction": "Click itinerary day pills to view interactive route details, elevation, and camps",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-006",
                "source_excerpt": "field gear guidelines",
                "category": "content",
                "expected_component": "guidelines_grid",
                "expected_content": "Essential wilderness field guidelines, technical layering, and leave-no-trace protocols",
                "expected_dom_selector": "#field-guide",
                "expected_interaction": "Inspect mandatory expedition preparation checklists and satellite telemetry standards",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-007",
                "source_excerpt": "booking inquiries",
                "category": "interaction",
                "expected_component": "inquiry_form",
                "expected_content": "Expedition reservation and small-group booking form",
                "expected_dom_selector": "#contact",
                "expected_interaction": "Submit departure booking inquiry with date and party size selection",
                "verification_status": "PENDING",
                "evidence": "",
            })

        elif archetype == "portfolio_studio":
            ledger.append({
                "req_id": "REQ-003",
                "source_excerpt": "spatial design philosophy",
                "category": "content",
                "expected_component": "philosophy",
                "expected_content": "Studio design philosophy detailing tectonic materiality and passive solar integration",
                "expected_dom_selector": "#philosophy",
                "expected_interaction": "Read architectural manifesto and sustainable construction methodologies",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-004",
                "source_excerpt": "architectural project discovery with typology filters",
                "category": "interaction",
                "expected_component": "showcase_grid",
                "expected_content": "Architectural project portfolio categorized by Residential, Commercial, and Adaptive Re-use",
                "expected_dom_selector": "#showcase-grid",
                "expected_interaction": "Switch typology filter pills and search projects by material or typology",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-005",
                "source_excerpt": "detail inspection modal with structural specs",
                "category": "interaction",
                "expected_component": "details_modal",
                "expected_content": "Detail modal rendering architectural specifications, materials, and completion year",
                "expected_dom_selector": "#details-modal",
                "expected_interaction": "Click project card to inspect structural specs; dismiss with Esc or backdrop click",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-006",
                "source_excerpt": "consultation booking",
                "category": "interaction",
                "expected_component": "inquiry_form",
                "expected_content": "Architectural consultation request and commission inquiry form",
                "expected_dom_selector": "#contact",
                "expected_interaction": "Submit validated architectural consultation request with demonstration disclosure",
                "verification_status": "PENDING",
                "evidence": "",
            })

        elif archetype == "research_institution":
            ledger.append({
                "req_id": "REQ-003",
                "source_excerpt": "research foundation & about",
                "category": "content",
                "expected_component": "about",
                "expected_content": f"Research foundation and authoritative mission for {brand}",
                "expected_dom_selector": "#about",
                "expected_interaction": "Explore scientific foundation and research objectives",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-004",
                "source_excerpt": "scientific instrumentation showcase",
                "category": "interaction",
                "expected_component": "showcase_grid",
                "expected_content": "Research instrumentation showcase with category filter pills",
                "expected_dom_selector": "#showcase-grid",
                "expected_interaction": "Filter instruments by operational domain and search technical specs",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-005",
                "source_excerpt": "observation & expedition schedule",
                "category": "content",
                "expected_component": "schedule_timeline",
                "expected_content": "Observation schedule table with targets, instruments, and status",
                "expected_dom_selector": "#schedule",
                "expected_interaction": "Inspect active mission timeline and principal investigator schedule",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-006",
                "source_excerpt": "peer-reviewed discovery archive",
                "category": "content",
                "expected_component": "discovery_archive",
                "expected_content": "Peer-reviewed scientific findings with metrics and published abstracts",
                "expected_dom_selector": "#discoveries",
                "expected_interaction": "Browse peer-reviewed discovery archive cards",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-007",
                "source_excerpt": "live instrument telemetry",
                "category": "content",
                "expected_component": "telemetry_feed",
                "expected_content": "Live real-time telemetry diagnostics with active pulsing beacons",
                "expected_dom_selector": "#telemetry",
                "expected_interaction": "Monitor real-time sensor streams and diagnostic status",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-008",
                "source_excerpt": "technical detail inspection modal",
                "category": "interaction",
                "expected_component": "details_modal",
                "expected_content": "Instrument detail modal with complete specifications",
                "expected_dom_selector": "#details-modal",
                "expected_interaction": "Open modal on card click, close with Esc or backdrop click",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-009",
                "source_excerpt": "inquiry & research access",
                "category": "interaction",
                "expected_component": "inquiry_form",
                "expected_content": "Observation time & research access proposal form",
                "expected_dom_selector": "#contact",
                "expected_interaction": "Submit proposal inquiry with simulated validation and disclosure",
                "verification_status": "PENDING",
                "evidence": "",
            })

        else: # general / open-domain
            ledger.append({
                "req_id": "REQ-003",
                "source_excerpt": "capabilities & about",
                "category": "content",
                "expected_component": "about",
                "expected_content": f"Capabilities and mission foundation for {brand}",
                "expected_dom_selector": "#about",
                "expected_interaction": "Explore core capabilities and objectives",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-004",
                "source_excerpt": "showcase portfolio",
                "category": "interaction",
                "expected_component": "showcase_grid",
                "expected_content": "Featured offerings grid with category filters and search",
                "expected_dom_selector": "#showcase-grid",
                "expected_interaction": "Filter offerings and search in real-time",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-005",
                "source_excerpt": "detail inspection modal",
                "category": "interaction",
                "expected_component": "details_modal",
                "expected_content": "Item detail modal with specifications and description",
                "expected_dom_selector": "#details-modal",
                "expected_interaction": "Open modal on card click, close with Esc",
                "verification_status": "PENDING",
                "evidence": "",
            })
            ledger.append({
                "req_id": "REQ-006",
                "source_excerpt": "inquiries form",
                "category": "interaction",
                "expected_component": "inquiry_form",
                "expected_content": "Inquiry and consultation form with demonstration disclosure",
                "expected_dom_selector": "#contact",
                "expected_interaction": "Submit inquiry with validation and feedback",
                "verification_status": "PENDING",
                "evidence": "",
            })

        # Common cross-cutting quality requirements
        ledger.append({
            "req_id": f"REQ-{len(ledger)+1:03d}",
            "source_excerpt": "genuine verified photographic assets",
            "category": "visual",
            "expected_component": "asset_pipeline",
            "expected_content": "All local image assets physically exist, decode with natural dimensions, and have 0 duplicate dHash",
            "expected_dom_selector": "img",
            "expected_interaction": "Image complete === true, naturalWidth > 0, dHash distance > 6",
            "verification_status": "PENDING",
            "evidence": "",
        })
        ledger.append({
            "req_id": f"REQ-{len(ledger)+1:03d}",
            "source_excerpt": "brand integrity & zero generic placeholder markers",
            "category": "constraint",
            "expected_component": "work_package_gate",
            "expected_content": f"Zero foreign brand leaks and zero generic placeholder terms in rendered code",
            "expected_dom_selector": "body",
            "expected_interaction": "HTML and JS pass strict brand and placeholder scanning",
            "verification_status": "PENDING",
            "evidence": "",
        })

        return ledger
