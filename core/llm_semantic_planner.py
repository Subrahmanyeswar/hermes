# core/llm_semantic_planner.py
"""
HERMES 2.x — Mode 2: LLM-Assisted Semantic Planner & Strict Schema Validator (Phase 5).

Synthesizes structured website specifications (JSON) for genuinely unfamiliar or
ambiguous domains within a strict 25-second LogicalOperationBudget, using live
ProviderAvailabilityRegistry state and non-cyclic multi-tier failover.

Does NOT ask the LLM to generate large raw HTML documents; validates the returned
structured JSON strictly against a Pydantic schema and factual-honesty rules before
converting it to SynthesizedDomainPayload for deterministic rendering.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from config.model_config import (
    TIER1_PROVIDER,
    TIER1_MODEL,
    TIER2_PROVIDER,
    TIER2_MODEL,
    TIER3_PROVIDER,
    TIER3_MODEL,
    TIER3_BASE_URL,
    TIER4_PROVIDER,
    TIER4_MODEL,
    NVIDIA_API_KEY,
    GEMINI_API_KEY,
    SAMBANOVA_API_KEY,
)
from core.provider_registry import get_provider_registry, ProviderAvailabilityState
from core.runtime_failover import (
    LogicalOperationBudget,
    ProviderAttemptRecord,
    classify_runtime_error,
    global_attempt_ledger,
    global_failover_coordinator,
)


ALLOWED_ARCHETYPES = {
    "interactive_showcase",
    "marketplace",
    "saas_product",
    "portfolio_studio",
    "editorial_publication",
    "culinary_restaurant",
    "tourism_adventure",
    "research_institution",
}

_BANNED_PLACEHOLDERS = (
    "signature offering",
    "strategic solution",
    "modern web application",
    "lorem ipsum",
    "acme corp",
    "company xyz",
    "placeholder",
)

_UNVERIFIED_CLAIM_TOKENS = (
    "soc2",
    "soc 2",
    "hipaa",
    "iso 27001",
    "iso27001",
    "michelin",
    "99.99%",
    "google reviews",
    "yelp",
)


class LLMSynthesisBlockedError(RuntimeError):
    """Raised when Mode 2 LLM synthesis is required but all eligible providers fail or block."""

    def __init__(
        self,
        message: str,
        *,
        attempts: Optional[List[Dict[str, Any]]] = None,
        registry_snapshot: Optional[Dict[str, Any]] = None,
        total_duration_ms: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts or []
        self.registry_snapshot = registry_snapshot or {}
        self.total_duration_ms = total_duration_ms


class StructuredEntitySpec(BaseModel):
    id: str = Field(default="item-1", min_length=1, max_length=60)
    title: str = Field(..., min_length=3, max_length=120)
    category: str = Field(..., min_length=2, max_length=60)
    category_label: str = Field(default="", max_length=60)
    specifications: str = Field(..., min_length=4, max_length=240)
    description: str = Field(..., min_length=12, max_length=600)
    status: str = Field(default="Illustrative Offering", min_length=2, max_length=60)
    price_display: Optional[str] = Field(default=None, max_length=60)
    image_subject: str = Field(..., min_length=4, max_length=160)


class StructuredSectionSpec(BaseModel):
    id: str = Field(..., min_length=2, max_length=40)
    title: str = Field(..., min_length=2, max_length=80)
    component: str = Field(..., min_length=2, max_length=40)


class StructuredFilterCategory(BaseModel):
    id: str = Field(..., min_length=2, max_length=40)
    label: str = Field(..., min_length=2, max_length=50)


class StructuredFormFieldSpec(BaseModel):
    name: str = Field(..., min_length=2, max_length=40)
    label: str = Field(..., min_length=2, max_length=80)
    type: str = Field(default="text")
    required: bool = True
    options: Optional[List[str]] = None

    @field_validator("type")
    @classmethod
    def check_field_type(cls, v: str) -> str:
        allowed = {"text", "email", "date", "number", "select", "textarea", "tel"}
        return v if v in allowed else "text"


class StructuredFormSpec(BaseModel):
    title: str = Field(..., min_length=4, max_length=100)
    purpose: str = Field(..., min_length=4, max_length=120)
    fields: List[StructuredFormFieldSpec] = Field(..., min_length=2, max_length=8)
    submit_text: str = Field(default="Submit Demo Inquiry", min_length=3, max_length=50)
    disclosure: str = Field(..., min_length=15, max_length=300)
    success_message: str = Field(..., min_length=10, max_length=240)


def _default_sections() -> List[StructuredSectionSpec]:
    return [
        StructuredSectionSpec(id="navbar", title="Navigation", component="navbar"),
        StructuredSectionSpec(id="hero", title="Hero", component="hero"),
        StructuredSectionSpec(id="about", title="Studio Overview", component="about"),
        StructuredSectionSpec(id="showcase", title="Curated Offerings", component="showcase_grid"),
        StructuredSectionSpec(id="contact", title="Consultation Inquiry", component="inquiry_form"),
        StructuredSectionSpec(id="footer", title="Footer", component="footer"),
    ]


def _default_form_spec() -> StructuredFormSpec:
    return StructuredFormSpec(
        title="Consultation & Commission Inquiry",
        purpose="Capture client inquiries (Demonstration Mode)",
        fields=[
            StructuredFormFieldSpec(name="full_name", label="Full Name *", type="text", required=True),
            StructuredFormFieldSpec(name="email", label="Email Address *", type="email", required=True),
            StructuredFormFieldSpec(
                name="inquiry_topic",
                label="Area of Interest *",
                type="select",
                required=True,
                options=["Custom Commission", "Consultation", "Technical Service"],
            ),
            StructuredFormFieldSpec(name="message", label="Inquiry Notes *", type="textarea", required=True),
        ],
        submit_text="Validate Demo Inquiry",
        disclosure="Demonstration Mode: In-browser validation only; no external booking or submission occurs.",
        success_message="Demonstration inquiry validated locally.",
    )


class StructuredSemanticWebsiteSpec(BaseModel):
    brand: str = Field(..., min_length=2, max_length=80)
    business_domain: str = Field(..., min_length=3, max_length=60)
    domain_subtype: str = Field(..., min_length=4, max_length=100)
    application_archetype: str = Field(default="interactive_showcase")
    target_audience: str = Field(..., min_length=8, max_length=250)
    purpose: str = Field(..., min_length=15, max_length=500)
    business_objectives: List[str] = Field(..., min_length=3, max_length=5)
    navigation_labels: List[str] = Field(default_factory=lambda: ["Home", "Studio", "Offerings", "Inquiries"])
    required_sections: List[StructuredSectionSpec] = Field(default_factory=_default_sections)
    canonical_entities: List[StructuredEntitySpec] = Field(..., min_length=4, max_length=10)
    filter_categories: List[StructuredFilterCategory] = Field(..., min_length=2, max_length=6)
    important_functionality: List[str] = Field(default_factory=lambda: ["Category filter", "Keyword search", "Detail inspection modal", "Demo inquiry form"])
    user_interactions: List[str] = Field(default_factory=lambda: ["Filter offerings by category", "Search offerings", "Inspect details modal", "Submit demonstration form"])
    form_spec: StructuredFormSpec = Field(default_factory=_default_form_spec)
    visual_direction: str = Field(..., min_length=10, max_length=400)
    hero_image_query: str = Field(default="", max_length=120)
    color_palette: Dict[str, str] = Field(default_factory=dict)
    asset_search_keywords: List[str] = Field(default_factory=list)
    data_and_factual_constraints: List[str] = Field(default_factory=lambda: ["All offerings shown as illustrative examples.", "No unverified claims or external transactions."])

    @field_validator("application_archetype")
    @classmethod
    def check_archetype(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        return clean if clean in ALLOWED_ARCHETYPES else "interactive_showcase"

    @field_validator("color_palette")
    @classmethod
    def check_palette(cls, v: Dict[str, str]) -> Dict[str, str]:
        defaults = {
            "primary": "#0f172a",
            "secondary": "#1e293b",
            "accent": "#0ea5e9",
            "accent_secondary": "#f59e0b",
            "background": "#f8fafc",
            "surface": "#ffffff",
            "surface_border": "#e2e8f0",
            "text_primary": "#0f172a",
            "text_secondary": "#475569",
            "border": "#e2e8f0",
        }
        out = dict(defaults)
        for k, val in (v or {}).items():
            if isinstance(val, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", val.strip()):
                out[k] = val.strip()
        if out["background"].lower() == out["text_primary"].lower():
            out["text_primary"] = "#0f172a" if out["background"].lower().startswith("#f") else "#f8fafc"
        return out


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Strip <think> blocks and markdown fences, then parse a JSON object cleanly."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text or "", flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No valid JSON object boundaries found in LLM output")
    candidate = cleaned[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        sanitized = re.sub(r",\s*([}\]])", r"\1", candidate)
        return json.loads(sanitized)


def validate_structured_semantic_spec(
    raw_text_or_dict: str | Dict[str, Any],
    user_prompt: str,
    expected_brand: str = "",
) -> StructuredSemanticWebsiteSpec:
    """Strictly parse and validate structured LLM semantic spec against schema & safety rules."""
    data = _extract_json_object(raw_text_or_dict) if isinstance(raw_text_or_dict, str) else dict(raw_text_or_dict)
    accent_hex = data.get("accent_hex")
    pal = dict(data.get("color_palette") or {})
    if isinstance(accent_hex, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", accent_hex.strip()):
        pal.setdefault("accent", accent_hex.strip())
    data["color_palette"] = pal
    spec = StructuredSemanticWebsiteSpec(**data)

    # Preserve deterministic non-generic brand when detected reliably from prompt
    if expected_brand and expected_brand not in ("Application", "Modern Web Application"):
        if expected_brand.lower() not in spec.brand.lower() and spec.brand.lower() not in expected_brand.lower():
            spec.brand = expected_brand

    prompt_lower = (user_prompt or "").lower()
    serialized_lower = json.dumps(spec.model_dump()).lower()

    for placeholder in _BANNED_PLACEHOLDERS:
        if placeholder in serialized_lower:
            raise ValueError(f"Rejected response containing placeholder text: '{placeholder}'")

    for claim in _UNVERIFIED_CLAIM_TOKENS:
        if claim in serialized_lower and claim not in prompt_lower:
            raise ValueError(f"Rejected response introducing unverified claim not in prompt: '{claim}'")

    # Ensure disclosure explicitly communicates demo/sample nature
    if not any(k in spec.form_spec.disclosure.lower() for k in ("demo", "demonstration", "sample", "illustrative", "in-browser", "no live")):
        spec.form_spec.disclosure = (
            spec.form_spec.disclosure.rstrip(".")
            + " (Demonstration Mode: Inputs are validated in-browser only; no external booking or transaction occurs.)"
        )

    # Ensure category integrity & hydrate compact optional defaults deterministically
    valid_cats = {c.id for c in spec.filter_categories if c.id != "all"}
    if not valid_cats:
        valid_cats = {ent.category for ent in spec.canonical_entities}
        spec.filter_categories = [
            StructuredFilterCategory(id=cid, label=cid.replace("_", " ").title())
            for cid in sorted(valid_cats)[:4]
        ]
    cat_labels = {c.id: c.label for c in spec.filter_categories}
    for idx, ent in enumerate(spec.canonical_entities, 1):
        if not ent.id or ent.id == "item-1":
            ent.id = f"item-{idx}"
        if ent.category not in valid_cats:
            ent.category = spec.filter_categories[0].id
        if not ent.category_label:
            ent.category_label = cat_labels.get(ent.category, ent.category.replace("_", " ").title())

    if len(spec.asset_search_keywords) < 4:
        spec.asset_search_keywords = [spec.domain_subtype] + [ent.image_subject for ent in spec.canonical_entities]

    # Normalize snake_case subtype if model emitted underscores
    if "_" in (spec.domain_subtype or ""):
        spec.domain_subtype = spec.domain_subtype.replace("_", " ").strip().title()

    # Tailor inquiry select options to actual filter categories when default options were kept
    for f in spec.form_spec.fields:
        if f.type == "select" and f.options == ["Custom Commission", "Consultation", "Technical Service"]:
            f.options = [c.label for c in spec.filter_categories[:4]]

    return spec


class LLMSemanticPlanner:
    """
    Executes Mode 2 structured semantic planning via healthy routable tiers under a
    single 25-second LogicalOperationBudget.
    """

    SYSTEM_PROMPT = (
        "Output ONLY a compact valid JSON object representing a business website spec. "
        "No markdown, no explanation, no HTML/CSS/JS. Never invent awards or certifications (SOC2, HIPAA, ISO, Michelin)."
    )

    @classmethod
    def _build_user_prompt(cls, user_prompt: str, detected_brand: str, feedback: str = "") -> str:
        compact_example = {
            "brand": detected_brand or "Brand Name",
            "business_domain": "snake_case_domain",
            "domain_subtype": "Short Readable Specialty Subtitle",
            "application_archetype": "interactive_showcase",
            "target_audience": "Primary audience sentence",
            "purpose": "1-2 sentence mission summary",
            "business_objectives": ["Objective 1", "Objective 2", "Objective 3"],
            "visual_direction": "Colors and aesthetic direction",
            "hero_image_query": "2-4 word concrete hero photograph subject",
            "accent_hex": "#b45309",
            "filter_categories": [
                {"id": "slug_a", "label": "Category A"},
                {"id": "slug_b", "label": "Category B"},
                {"id": "slug_c", "label": "Category C"},
            ],
            "canonical_entities": [
                {"title": "Item 1", "category": "slug_a", "specifications": "Spec A | Spec B", "description": "8-word factual summary.", "image_subject": "2-3 word photo query"},
                {"title": "Item 2", "category": "slug_a", "specifications": "Spec A | Spec B", "description": "8-word factual summary.", "image_subject": "2-3 word photo query"},
                {"title": "Item 3", "category": "slug_b", "specifications": "Spec A | Spec B", "description": "8-word factual summary.", "image_subject": "2-3 word photo query"},
                {"title": "Item 4", "category": "slug_c", "specifications": "Spec A | Spec B", "description": "8-word factual summary.", "image_subject": "2-3 word photo query"},
            ],
        }
        repair_note = f" FIX:{feedback}" if feedback else ""
        return (
            f"Request: {user_prompt}\n"
            f"Output valid single-line JSON matching this exact structure (replace EVERY placeholder value with genuine domain-specific content matching the prompt; MUST contain 4 to 6 items in canonical_entities, 3 real filter_categories with domain slugs, concise <=10-word descriptions, Demonstration Mode):"
            f"\n{json.dumps(compact_example, separators=(',', ':'))}{repair_note}"
        )

    @classmethod
    def _build_client_for_tier(cls, tier: int, timeout: float):
        if tier == 1 and TIER1_PROVIDER == "nvidia_nim":
            from models.nvidia_client import NvidiaClient
            return NvidiaClient(timeout_seconds=int(max(1, round(timeout)))), TIER1_PROVIDER, TIER1_MODEL
        if tier == 2 and TIER2_PROVIDER == "gemini":
            from models.gemini_client import GeminiClient
            return GeminiClient(model=TIER2_MODEL, timeout_seconds=timeout, tier=2), TIER2_PROVIDER, TIER2_MODEL
        if tier == 3 and TIER3_PROVIDER == "sambanova":
            from models.common_adapter import CommonProviderAdapter
            return CommonProviderAdapter(
                provider_name=TIER3_PROVIDER,
                model_name=TIER3_MODEL,
                base_url=TIER3_BASE_URL,
                api_key=SAMBANOVA_API_KEY,
                tier=3,
                timeout_seconds=timeout,
            ), TIER3_PROVIDER, TIER3_MODEL
        if tier == 4 and TIER4_PROVIDER == "ollama":
            from models.ollama_client import OllamaClient
            return OllamaClient(timeout_seconds=int(timeout)), TIER4_PROVIDER, TIER4_MODEL
        from models.common_adapter import get_provider_adapter
        prov_map = {1: (TIER1_PROVIDER, TIER1_MODEL), 2: (TIER2_PROVIDER, TIER2_MODEL), 3: (TIER3_PROVIDER, TIER3_MODEL)}
        p, m = prov_map.get(tier, (TIER1_PROVIDER, TIER1_MODEL))
        return get_provider_adapter(p, m, tier=tier), p, m

    @classmethod
    async def synthesize_async(
        cls,
        user_prompt: str,
        workspace_root: Any,
        mission_id: str = "",
        detected_brand: str = "",
        total_budget_seconds: float = 25.0,
        event_callback: Optional[Any] = None,
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Execute bounded LLM-assisted semantic planning across routable tiers.
        Returns: (SynthesizedDomainPayload, telemetry_metadata_dict)
        Raises LLMSynthesisBlockedError if every eligible tier fails or rejects.
        """
        from core.design_intelligence import detect_brand_name, strip_negative_constraints

        brand = detected_brand or detect_brand_name(user_prompt)
        registry = get_provider_registry()
        budget = LogicalOperationBudget(
            operation_id=f"op_sem_{uuid.uuid4().hex[:8]}",
            mission_id=mission_id,
            turn_id="semantic_plan",
            total_budget=min(float(total_budget_seconds), 25.0),
        )
        op_t0 = budget.start_time

        excluded = global_failover_coordinator.get_mission_excluded_tiers(mission_id) if mission_id else set()
        routable_tiers = [t for t in registry.get_routable_tiers() if t not in excluded]

        # Preflight check credential presence & unreachable local daemon cleanly
        filtered_tiers: List[int] = []
        for t in routable_tiers:
            e = registry.get(t)
            if e and e.provider in ("nvidia_nim", "gemini", "sambanova") and not e.has_credentials:
                continue
            if e and e.provider == "ollama" and e.state == ProviderAvailabilityState.DEGRADED and "unreachable" in (e.last_error or "").lower():
                continue
            filtered_tiers.append(t)

        if not filtered_tiers:
            raise LLMSynthesisBlockedError(
                "Mode 2 LLM-assisted semantic planning blocked: zero routable LLM providers are currently available.",
                attempts=[],
                registry_snapshot={k: v.to_dict() for k, v in registry.get_all().items()},
                total_duration_ms=round((time.monotonic() - op_t0) * 1000.0, 2),
            )

        # Prefer verified healthy/authenticated tiers first, then configured, then degraded fallbacks
        def _tier_sort_key(t: int) -> Tuple[int, int]:
            st = registry.get(t).state if registry.get(t) else ProviderAvailabilityState.CONFIGURED
            rank = {
                ProviderAvailabilityState.HEALTHY: 0,
                ProviderAvailabilityState.AUTHENTICATED: 1,
                ProviderAvailabilityState.CONFIGURED: 2,
                ProviderAvailabilityState.DEGRADED: 3,
                ProviderAvailabilityState.COOLDOWN: 4,
            }.get(st, 5)
            return (rank, t)

        filtered_tiers.sort(key=_tier_sort_key)

        attempts_summary: List[Dict[str, Any]] = []
        repair_feedback = ""

        for idx, tier in enumerate(filtered_tiers):
            if not budget.has_budget(2.0):
                break
            downstream_healthy = sum(
                1
                for dt in filtered_tiers[idx + 1 :]
                if (registry.get(dt) and registry.get(dt).state in (ProviderAvailabilityState.HEALTHY, ProviderAvailabilityState.AUTHENTICATED, ProviderAvailabilityState.CONFIGURED))
            )
            remaining_after = downstream_healthy if (idx + 1 < len(filtered_tiers)) else 0
            attempt_cap = budget.compute_attempt_timeout(remaining_tiers_count=remaining_after, default_cap=22.5)
            cur_entry = registry.get(tier)
            if cur_entry and cur_entry.state == ProviderAvailabilityState.DEGRADED:
                attempt_cap = min(attempt_cap, 8.0)

            client, prov_name, mod_name = cls._build_client_for_tier(tier, timeout=attempt_cap)
            prompt_text = cls._build_user_prompt(user_prompt, brand, feedback=repair_feedback)

            if event_callback:
                try:
                    await event_callback("model_requested", {
                        "tier": tier,
                        "provider": prov_name,
                        "model": mod_name,
                        "operation_id": budget.operation_id,
                    })
                except Exception:
                    pass

            att_t0 = time.monotonic()
            att_start_wall = time.time()
            try:
                gen_kwargs: Dict[str, Any] = {
                    "model": mod_name,
                    "prompt": prompt_text,
                    "system": cls.SYSTEM_PROMPT,
                    "temperature": 0.0,
                    "max_tokens": 1800,
                    "timeout_seconds": attempt_cap,
                }
                if prov_name == "nvidia_nim":
                    gen_kwargs["stream"] = True
                    gen_kwargs["chat_template_kwargs"] = {"enable_thinking": False}
                    gen_kwargs["allow_internal_retry"] = False
                elif prov_name == "gemini":
                    gen_kwargs["stream"] = False
                    gen_kwargs["reasoning_effort"] = "low"
                    gen_kwargs["allow_internal_retry"] = False

                resp = await asyncio.wait_for(client.generate(**gen_kwargs), timeout=attempt_cap)
                dur_ms = (time.monotonic() - att_t0) * 1000.0
                timings = getattr(resp, "raw_timing_metadata", {}) or {}
                ttfb = timings.get("ttfb_ms", getattr(resp, "ttfb_ms", None))
                ttft_r = timings.get("ttft_reasoning_ms", getattr(resp, "ttft_reasoning_ms", None))
                ttft_c = timings.get("ttft_content_ms", getattr(resp, "ttft_content_ms", None))
                ttft_u = timings.get("ttft_usable_ms") or ttft_c

                if not getattr(resp, "success", False) or not (getattr(resp, "text", "") or "").strip():
                    raise RuntimeError(getattr(resp, "error", None) or f"{prov_name} returned empty output")

                validated_spec = validate_structured_semantic_spec(
                    resp.text,
                    user_prompt=user_prompt,
                    expected_brand=brand,
                )

                total_op_ms = (time.monotonic() - op_t0) * 1000.0
                rec = ProviderAttemptRecord(
                    operation_id=budget.operation_id,
                    mission_id=mission_id or "semantic_plan",
                    turn_id="semantic_plan",
                    provider=prov_name,
                    model=mod_name,
                    tier=tier,
                    attempt_number=idx + 1,
                    start_time=att_start_wall,
                    end_time=time.time(),
                    duration_ms=dur_ms,
                    success=True,
                    ttft_ms=ttft_u,
                    ttfb_ms=ttfb,
                    ttft_reasoning_ms=ttft_r,
                    ttft_content_ms=ttft_c,
                    ttft_usable_ms=ttft_u,
                    availability_state="HEALTHY",
                )
                global_attempt_ledger.record_attempt(rec)
                registry.record_outcome(
                    tier,
                    success=True,
                    ttfb_ms=ttfb,
                    ttft_reasoning_ms=ttft_r,
                    ttft_content_ms=ttft_c,
                    ttft_usable_ms=ttft_u,
                    latency_ms=dur_ms,
                    served_model=getattr(resp, "served_model", None) or mod_name,
                )
                attempts_summary.append(rec.to_dict())

                if event_callback:
                    try:
                        await event_callback("model_completed", {
                            "tier": tier,
                            "provider": prov_name,
                            "model": mod_name,
                            "latency": round(dur_ms / 1000.0, 3),
                            "duration_ms": int(dur_ms),
                            "ttfb_ms": ttfb,
                            "ttft_reasoning_ms": ttft_r,
                            "ttft_content_ms": ttft_c,
                            "ttft_usable_ms": ttft_u,
                        })
                    except Exception:
                        pass

                payload = cls.to_domain_payload(validated_spec, user_prompt=user_prompt)
                telemetry = {
                    "provider": prov_name,
                    "model": mod_name,
                    "tier": tier,
                    "operation_id": budget.operation_id,
                    "ttfb_ms": ttfb,
                    "ttft_reasoning_ms": ttft_r,
                    "ttft_content_ms": ttft_c,
                    "ttft_usable_ms": ttft_u,
                    "response_completion_ms": round(dur_ms, 2),
                    "total_operation_ms": round(total_op_ms, 2),
                    "within_25s_budget": total_op_ms <= 25000.0,
                    "attempts": attempts_summary,
                }
                return payload, telemetry

            except Exception as exc:
                dur_ms = (time.monotonic() - att_t0) * 1000.0
                err_cls, is_transient, _ = classify_runtime_error(exc=exc, response_text=str(exc))
                err_msg = f"{type(exc).__name__}: {exc}"
                logger.warning(f"Mode 2 tier {tier} ({prov_name}/{mod_name}) failed in {dur_ms:.0f}ms: {err_msg[:220]}")
                sc = 402 if "402" in str(exc) else (503 if "503" in str(exc) else (404 if "not found" in str(exc).lower() else None))
                registry.record_outcome(tier, success=False, status_code=sc, error=err_msg, latency_ms=dur_ms)
                reg_state = registry.get(tier).state.value if registry.get(tier) else None

                next_prov = None
                if idx + 1 < len(filtered_tiers):
                    ne = registry.get(filtered_tiers[idx + 1])
                    next_prov = ne.provider if ne else None

                rec = ProviderAttemptRecord(
                    operation_id=budget.operation_id,
                    mission_id=mission_id or "semantic_plan",
                    turn_id="semantic_plan",
                    provider=prov_name,
                    model=mod_name,
                    tier=tier,
                    attempt_number=idx + 1,
                    start_time=att_start_wall,
                    end_time=time.time(),
                    duration_ms=dur_ms,
                    success=False,
                    availability_state=reg_state,
                    error_classification=err_cls.value,
                    http_status=sc,
                    next_selected_provider=next_prov,
                    error_message=err_msg[:300],
                )
                global_attempt_ledger.record_attempt(rec)
                attempts_summary.append(rec.to_dict())

                if mission_id:
                    global_failover_coordinator.exclude_tier_for_mission(
                        mission_id, tier, permanent=not is_transient
                    )
                if next_prov and event_callback:
                    try:
                        await event_callback("tier_failover_started", {
                            "from_tier": tier,
                            "from_provider": prov_name,
                            "to_tier": filtered_tiers[idx + 1],
                            "to_provider": next_prov,
                            "error": err_msg[:200],
                        })
                    except Exception:
                        pass
                # Feed schema/validation errors into next tier prompt concisely
                if "validation" in err_msg.lower() or "json" in err_msg.lower() or "rejected" in err_msg.lower():
                    repair_feedback = str(exc)[:200]
            finally:
                if hasattr(client, "aclose"):
                    try:
                        await client.aclose()
                    except Exception:
                        pass
                elif hasattr(client, "close"):
                    try:
                        await client.close()
                    except Exception:
                        pass

        total_dur_ms = round((time.monotonic() - op_t0) * 1000.0, 2)
        raise LLMSynthesisBlockedError(
            f"Mode 2 LLM-assisted semantic planning exhausted {len(attempts_summary)} provider attempt(s) in {total_dur_ms:.0f}ms without a valid structured specification.",
            attempts=attempts_summary,
            registry_snapshot={str(k): v.to_dict() for k, v in registry.get_all().items()},
            total_duration_ms=total_dur_ms,
        )

    @classmethod
    def to_domain_payload(cls, spec: StructuredSemanticWebsiteSpec, user_prompt: str) -> Any:
        """Convert a validated StructuredSemanticWebsiteSpec to SynthesizedDomainPayload."""
        from core.semantic_synthesizer import SemanticDomainSynthesizer, SynthesizedDomainPayload

        sections = [s.model_dump() for s in spec.required_sections]
        section_ids = {s["id"] for s in sections}
        if "hero" not in section_ids:
            sections.insert(1, {"id": "hero", "title": "Hero", "tag": "section", "component": "hero"})
        if "about" not in section_ids and spec.application_archetype == "interactive_showcase":
            sections.insert(2, {"id": "about", "title": f"About {spec.brand}", "tag": "section", "component": "about"})
        if "showcase" not in section_ids:
            sections.append({"id": "showcase", "title": "Offerings Showcase", "tag": "section", "component": "showcase_grid"})
        if "contact" not in section_ids:
            sections.append({"id": "contact", "title": spec.form_spec.title, "tag": "section", "component": "inquiry_form"})

        for s in sections:
            s.setdefault("tag", "header" if s["id"] == "navbar" else ("footer" if s["id"] == "footer" else "section"))

        # Navigation anchors tied strictly to existing sections
        nav = [{"label": "Home", "href": "#hero", "section_id": "hero", "is_cta": False}]
        for s in sections:
            sid = s["id"]
            if sid in ("navbar", "hero", "footer", "contact"):
                continue
            label = s["title"].split("&")[0].split("—")[0].strip()
            if len(label) > 16:
                label = label.split()[0]
            nav.append({"label": label, "href": f"#{sid}", "section_id": sid, "is_cta": False})
        nav.append({"label": "Inquiries", "href": "#contact", "section_id": "contact", "is_cta": True})

        entities: List[Dict[str, Any]] = []
        assets: List[Dict[str, Any]] = []

        hero_kw = (
            spec.hero_image_query
            or (spec.canonical_entities[0].image_subject if spec.canonical_entities else "")
            or spec.asset_search_keywords[0]
            or spec.domain_subtype
        )
        assets.append({
            "id": "hero",
            "component": "hero",
            "relative_path": "assets/images/hero-main.jpg",
            "subject": hero_kw,
            "search_query": hero_kw,
            "width": 1600,
            "height": 1067,
        })

        for idx, ent in enumerate(spec.canonical_entities, 1):
            rel_img = f"assets/images/showcase/item-{idx}.jpg"
            kw = spec.asset_search_keywords[idx] if idx < len(spec.asset_search_keywords) else ent.image_subject
            ent_dict = ent.model_dump()
            ent_dict["image_path"] = rel_img
            entities.append(ent_dict)
            assets.append({
                "id": f"item-{idx}",
                "component": "showcase",
                "relative_path": rel_img,
                "subject": ent.image_subject,
                "search_query": kw,
                "width": 800,
                "height": 600,
            })

        cat_list = [{"id": "all", "label": "All Offerings"}] + [c.model_dump() for c in spec.filter_categories]
        filters = {
            "categories": cat_list,
            "search_placeholder": f"Search {spec.brand} offerings, specs, or categories...",
        }

        form_dict = spec.form_spec.model_dump()
        form_dict["form_id"] = "inquiry-form"
        form_dict["mode"] = "demonstration"
        form_specs = [form_dict]

        typography = {
            "font_heading": "'Playfair Display', Georgia, serif"
            if spec.application_archetype in ("culinary_restaurant", "editorial_publication", "portfolio_studio")
            else "'Plus Jakarta Sans', system-ui, -apple-system, sans-serif",
            "font_body": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
            "font_mono": "'JetBrains Mono', monospace",
        }

        ledger = SemanticDomainSynthesizer._build_requirement_ledger(
            prompt=user_prompt,
            brand=spec.brand,
            domain=spec.business_domain,
            subtype=spec.domain_subtype,
            archetype=spec.application_archetype,
            sections=sections,
            entities=entities,
            form_spec=form_specs,
            interactions=spec.user_interactions,
            criteria=spec.data_and_factual_constraints,
        )

        return SynthesizedDomainPayload(
            requested_brand=spec.brand,
            business_domain=spec.business_domain,
            domain_subtype=spec.domain_subtype,
            application_archetype=spec.application_archetype,
            purpose=spec.purpose,
            target_audience=spec.target_audience,
            business_objectives=spec.business_objectives,
            visual_direction=spec.visual_direction,
            color_palette=spec.color_palette,
            typography=typography,
            required_sections=sections,
            content_entities=entities,
            entity_schemas={"entity_type": "domain_item", "fields": ["id", "title", "category", "specifications", "description", "status", "image_path"]},
            navigation_structure=nav,
            card_specs={"show_image": True, "show_badge": True, "show_specs": True, "action_label": "View Details"},
            required_interactions=spec.user_interactions,
            filter_capabilities=filters,
            form_specs=form_specs,
            asset_requirements=assets,
            backend_requirements={"mode": "frontend_demo", "server_framework": None, "database": None, "endpoints": []},
            negative_constraints=[],
            acceptance_criteria=spec.data_and_factual_constraints,
            semantic_keywords=[spec.brand.lower(), spec.business_domain] + spec.asset_search_keywords[:5],
            requirement_ledger=ledger,
        )
