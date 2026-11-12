# core/domain_confidence.py
"""
HERMES 2.x — Confidence-Aware Domain Classifier & Hybrid Execution Mode Router (Phase 5).

Distinguishes four explicit states:
  1. RECOGNIZED_HIGH_CONFIDENCE  -> ExecutionMode.DETERMINISTIC  (Mode 1 fast path, 0s LLM wait)
  2. RECOGNIZED_AMBIGUOUS        -> ExecutionMode.LLM_ASSISTED   (Mode 2 clarification/synthesis)
  3. UNFAMILIAR_DOMAIN           -> ExecutionMode.LLM_ASSISTED   (Mode 2 schema-validated LLM synthesis)
  4. INSUFFICIENT_INPUT          -> ExecutionMode.REJECTED       (honest insufficient-input error)

Invariants:
- Negative constraints are stripped before scoring.
- One incidental keyword NEVER drives high-confidence routing.
- Primary business purpose strictly outweighs secondary vocabulary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Set, Tuple

from core.design_intelligence import strip_negative_constraints


class DomainConfidenceCategory(str, Enum):
    RECOGNIZED_HIGH_CONFIDENCE = "RECOGNIZED_HIGH_CONFIDENCE"
    RECOGNIZED_AMBIGUOUS = "RECOGNIZED_AMBIGUOUS"
    UNFAMILIAR_DOMAIN = "UNFAMILIAR_DOMAIN"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


class HybridExecutionMode(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    REJECTED = "rejected"


@dataclass
class DomainConfidenceAssessment:
    category: DomainConfidenceCategory
    execution_mode: HybridExecutionMode
    confidence_score: float
    best_domain: str
    runner_up_domain: str
    best_score: int
    runner_up_score: int
    distinct_evidence_terms: int
    primary_purpose_matched: bool
    rationale: str
    matched_terms: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        d = asdict(self)
        d["category"] = self.category.value
        d["execution_mode"] = self.execution_mode.value
        return d


# Recognized deterministic synthesis domain profiles:
# (primary_phrases, corroborating_terms)
_DOMAIN_PROFILES: Dict[str, Tuple[List[str], List[str]]] = {
    "ecommerce_marketplace": (
        [
            "marketplace", "materials marketplace", "digital marketplace", "b2b marketplace",
            "material recovery", "circular construction", "reclaimed and recycled", "buy and sell", "verdant loop",
        ],
        [
            "quote basket", "suppliers", "vendor", "reclaimed timber", "recycled structural steel",
            "salvaged bricks", "low-carbon concrete", "catalogue", "catalog",
        ],
    ),
    "architecture_interior": (
        [
            "architecture studio", "interior design studio", "architectural studio", "architectural firm",
            "architecture firm", "architecture practice", "spatial design studio", "form & field",
            "form and field", "atelier kroma",
        ],
        [
            "blueprints", "spatial design", "passivhaus", "residence", "pavilion",
            "interior architecture", "building design",
        ],
    ),
    "veterinary_pet_care": (
        ["veterinary", "vet clinic", "pet care", "animal hospital", "veterinarian", "paws & claws", "paws and claws"],
        ["pets", "pet", "canine", "feline", "vaccination", "animal clinic", "surgery"],
    ),
    "robotics_automation": (
        ["robotics", "atlas robotics", "robotic arm", "automation company", "autonomous mobile"],
        ["robot", "robots", "cobot", "machine vision", "industrial automation", "inspection systems", "assembly automation"],
    ),
    "geospatial_intelligence": (
        [
            "geospatial", "aerial surveying", "geomatics", "drone-based terrain",
            "lidar scanning", "volumetric stockpile", "skytrace", "photogrammetry", "orthomosaic",
        ],
        ["surveying", "lidar", "drone", "terrain mapping", "stockpile", "land surveys", "topographic", "elevation"],
    ),
    "education_institution": (
        [
            "discovery museum", "science center", "children's science", "planetarium dome",
            "sparkfield", "university", "college", "northstar", "higher education", "academy",
        ],
        [
            "museum", "planetarium", "exhibits", "exhibit", "stem camps", "curriculum",
            "faculty", "admissions", "degree", "campus", "academic", "workshops",
        ],
    ),
    "culinary_restaurant": (
        [
            "restaurant", "bistro", "trattoria", "dining", "saffron & stone", "saffron and stone",
            "fine dining", "brasserie", "eatery", "culinary",
        ],
        [
            "chef", "menu", "dishes", "dish", "tasting", "cuisine", "reservation",
            "reservations", "party-size", "kitchen", "tandoori", "biryani", "pasta", "wood-fired",
        ],
    ),
    "saas_tech": (
        [
            "saas", "software as a service", "project-management", "project management",
            "workflow platform", "b2b saas", "orbit pm", "task management software", "kanban workspace",
        ],
        [
            "kanban", "sprint", "billing switcher", "monthly/annual", "pricing comparison",
            "team management", "draggable", "developer", "dashboard", "cloud",
        ],
    ),
    "editorial_publication": (
        [
            "editorial publication", "digital editorial", "journalism", "online magazine",
            "digital publication", "field journal", "newsroom", "newspaper",
        ],
        [
            "featured stories", "article", "articles", "reading-time", "newsletter",
            "contributors", "editorial author", "dispatches", "magazine", "related stories",
        ],
    ),
    "ecommerce_electronics": (
        ["consumer electronics", "electronics store", "audio electronics", "smartphones and laptops", "nova"],
        ["smartphones", "laptops", "headphones", "smartwatches", "earbuds", "gadgets", "add to cart", "warranty", "electronics", "online store"],
    ),
    "travel_tourism": (
        ["travel agency", "adventure travel", "eco-tourism", "wanderworld", "travel booking", "guided treks"],
        ["expedition", "expeditions", "safari", "vacation", "itinerary", "destinations", "packing list", "resorts"],
    ),
    "legal_consulting": (
        ["law firm", "legal services", "attorneys", "litigation practice"],
        ["attorney", "lawyer", "litigation", "counsel", "practice areas", "corporate law"],
    ),
    "astronomy_observatory": (
        ["astronomy observatory", "astrophysics observatory", "deep-sky observatory", "observatory"],
        ["telescope", "astrophysics", "interferometer", "celestial", "stargazing", "deep-sky"],
    ),
    "oceanographic_marine_research": (
        ["oceanographic institute", "marine research", "deep-sea research", "oceanography"],
        ["submersible", "benthic", "hydrophone", "oceanographic", "hadal", "marine biology"],
    ),
    "volcanology_geothermal_research": (
        ["volcanology", "geothermal observatory", "volcano observatory", "geothermal research"],
        ["caldera", "magma", "seismic", "fumarole", "geothermal", "eruption"],
    ),
}

_FILLER_TOKENS: Set[str] = {
    "build", "create", "make", "generate", "design", "develop", "website", "web", "site",
    "page", "pages", "app", "application", "portal", "platform", "modern", "premium",
    "professional", "responsive", "interactive", "clean", "nice", "good", "please",
    "with", "and", "the", "for", "from", "that", "this", "into", "using", "include",
    "including", "ensure", "clearly", "label", "sample", "data", "demo", "mode",
    "disclose", "section", "sections", "form", "validation", "search", "filters",
}


class DomainConfidenceClassifier:
    """Evaluates prompt domain confidence and selects deterministic vs LLM-assisted mode."""

    @classmethod
    def assess(cls, prompt: str) -> DomainConfidenceAssessment:
        raw = (prompt or "").strip()
        clean_p = strip_negative_constraints(raw)
        clean_lower = clean_p.lower()

        if not clean_p or len(clean_p) < 12:
            return DomainConfidenceAssessment(
                category=DomainConfidenceCategory.INSUFFICIENT_INPUT,
                execution_mode=HybridExecutionMode.REJECTED,
                confidence_score=0.0,
                best_domain="unclassified",
                runner_up_domain="none",
                best_score=0,
                runner_up_score=0,
                distinct_evidence_terms=0,
                primary_purpose_matched=False,
                rationale="Prompt is empty or too short to identify a concrete business/application purpose.",
            )

        all_words = re.findall(r"[a-zA-Z0-9&'-]{2,}", clean_lower)
        meaningful_words = [w for w in all_words if w not in _FILLER_TOKENS and len(w) >= 3]
        if len(meaningful_words) < 3 and len(all_words) < 10:
            return DomainConfidenceAssessment(
                category=DomainConfidenceCategory.INSUFFICIENT_INPUT,
                execution_mode=HybridExecutionMode.REJECTED,
                confidence_score=0.05,
                best_domain="insufficient",
                runner_up_domain="none",
                best_score=0,
                runner_up_score=0,
                distinct_evidence_terms=0,
                primary_purpose_matched=False,
                rationale=f"Insufficient domain detail (only {len(meaningful_words)} meaningful non-filler tokens).",
            )

        # Split primary business purpose statement vs full body
        sentences = re.split(r"(?<=[.!?])\s+|\n+", clean_lower)
        primary_sentences = [s.strip() for s in sentences if s.strip()][:2]
        primary_text = " ".join(primary_sentences)

        scores: Dict[str, int] = {}
        primary_hits: Dict[str, int] = {}
        distinct_terms: Dict[str, Set[str]] = {}

        for dom, (prim_kws, corr_kws) in _DOMAIN_PROFILES.items():
            s = 0
            p_cnt = 0
            matched: Set[str] = set()
            for kw in prim_kws:
                pat = r"\b" + re.escape(kw) + r"\b"
                if re.search(pat, primary_text):
                    s += 32
                    p_cnt += 1
                    matched.add(kw)
                elif re.search(pat, clean_lower):
                    # Primary term appearing only later in body has lower weight
                    s += 12
                    matched.add(kw)
            for kw in corr_kws:
                pat = r"\b" + re.escape(kw) + r"\b"
                occ_primary = len(re.findall(pat, primary_text))
                occ_body = len(re.findall(pat, clean_lower))
                if occ_primary > 0:
                    s += 8 + min(occ_primary, 2) * 3
                    matched.add(kw)
                elif occ_body > 0:
                    s += min(occ_body, 3) * 3
                    matched.add(kw)

            scores[dom] = s
            primary_hits[dom] = p_cnt
            distinct_terms[dom] = matched

        # Marketplace intent beats secondary architecture matches
        if scores.get("ecommerce_marketplace", 0) >= 32:
            scores["architecture_interior"] = 0

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_dom, best_score = ranked[0]
        runner_dom, runner_score = ranked[1] if len(ranked) > 1 else ("none", 0)

        p_matched = primary_hits.get(best_dom, 0) > 0
        n_distinct = len(distinct_terms.get(best_dom, set()))
        margin = best_score - runner_score

        # Prevent single incidental keyword from triggering deterministic fast path
        if n_distinct <= 1 and best_score < 35:
            return DomainConfidenceAssessment(
                category=DomainConfidenceCategory.UNFAMILIAR_DOMAIN,
                execution_mode=HybridExecutionMode.LLM_ASSISTED,
                confidence_score=0.2,
                best_domain="unfamiliar_custom",
                runner_up_domain=best_dom,
                best_score=best_score,
                runner_up_score=runner_score,
                distinct_evidence_terms=n_distinct,
                primary_purpose_matched=False,
                matched_terms=sorted(distinct_terms.get(best_dom, set())),
                rationale=(
                    f"Best candidate '{best_dom}' matched only {n_distinct} incidental term(s); "
                    "routing to Mode 2 LLM-assisted semantic synthesis."
                ),
            )

        # No recognized primary purpose matched in opening statement & low overall score -> Unfamiliar
        if not p_matched and best_score < 36:
            return DomainConfidenceAssessment(
                category=DomainConfidenceCategory.UNFAMILIAR_DOMAIN,
                execution_mode=HybridExecutionMode.LLM_ASSISTED,
                confidence_score=round(min(0.45, best_score / 80.0), 2),
                best_domain="unfamiliar_custom",
                runner_up_domain=best_dom if best_score > 0 else "none",
                best_score=best_score,
                runner_up_score=runner_score,
                distinct_evidence_terms=n_distinct,
                primary_purpose_matched=False,
                matched_terms=sorted(distinct_terms.get(best_dom, set())),
                rationale=(
                    f"Primary business purpose does not match any recognized deterministic profile "
                    f"(top score={best_score} on '{best_dom}', primary_match=False)."
                ),
            )

        # Ambiguous if runner-up competes closely or corroboration is thin
        if (margin < 10 and runner_score >= 20) or (not p_matched and n_distinct < 4) or best_score < 38:
            return DomainConfidenceAssessment(
                category=DomainConfidenceCategory.RECOGNIZED_AMBIGUOUS,
                execution_mode=HybridExecutionMode.LLM_ASSISTED,
                confidence_score=round(min(0.69, max(0.35, best_score / 75.0)), 2),
                best_domain=best_dom,
                runner_up_domain=runner_dom,
                best_score=best_score,
                runner_up_score=runner_score,
                distinct_evidence_terms=n_distinct,
                primary_purpose_matched=p_matched,
                matched_terms=sorted(distinct_terms.get(best_dom, set())),
                rationale=(
                    f"Recognized domain '{best_dom}' (score={best_score}) has ambiguous competition "
                    f"from '{runner_dom}' (score={runner_score}) or insufficient primary evidence."
                ),
            )

        # Strong primary business evidence with clear margin -> Mode 1 Deterministic Fast Path
        conf = round(min(0.99, 0.72 + min(0.27, (best_score - 35) / 100.0)), 2)
        return DomainConfidenceAssessment(
            category=DomainConfidenceCategory.RECOGNIZED_HIGH_CONFIDENCE,
            execution_mode=HybridExecutionMode.DETERMINISTIC,
            confidence_score=conf,
            best_domain=best_dom,
            runner_up_domain=runner_dom,
            best_score=best_score,
            runner_up_score=runner_score,
            distinct_evidence_terms=n_distinct,
            primary_purpose_matched=p_matched,
            matched_terms=sorted(distinct_terms.get(best_dom, set())),
            rationale=(
                f"High-confidence match for '{best_dom}' (score={best_score}, margin={margin}, "
                f"distinct_terms={n_distinct}); selecting Mode 1 deterministic synthesis."
            ),
        )
