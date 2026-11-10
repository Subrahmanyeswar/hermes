# core/frontend_contract.py
"""
Shared Project Implementation Contract for HERMES 2.x (Phase 3).
Defines authoritative, machine-readable specifications across HTML, CSS,
JavaScript, DOM structures, state models, assets, and build commands.
Persisted as a canonical project artifact in .hermes/frontend_contract.json.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


@dataclass
class ArchitectureContract:
    """Project-level architectural boundaries and entrypoint configuration."""
    project_type: str = "vanilla_web"  # "vanilla_web", "react", "static_site", "fullstack"
    technology_stack: List[str] = field(default_factory=lambda: ["html5", "css3", "javascript"])
    entrypoint: str = "index.html"
    authoritative_script: str = "app.js"
    authoritative_style: str = "style.css"
    file_ownership: Dict[str, str] = field(default_factory=lambda: {
        "index.html": "markup_structure",
        "style.css": "visual_styling",
        "app.js": "interactive_logic",
    })
    dependencies: Dict[str, str] = field(default_factory=dict)
    runtime_requirements: List[str] = field(default_factory=lambda: ["modern_browser"])
    build_command: Optional[str] = None
    test_command: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArchitectureContract:
        return cls(
            project_type=data.get("project_type", "vanilla_web"),
            technology_stack=list(data.get("technology_stack", ["html5", "css3", "javascript"])),
            entrypoint=data.get("entrypoint", "index.html"),
            authoritative_script=data.get("authoritative_script", "app.js"),
            authoritative_style=data.get("authoritative_style", "style.css"),
            file_ownership=dict(data.get("file_ownership", {})),
            dependencies=dict(data.get("dependencies", {})),
            runtime_requirements=list(data.get("runtime_requirements", ["modern_browser"])),
            build_command=data.get("build_command"),
            test_command=data.get("test_command"),
        )


@dataclass
class ComponentContract:
    """Structural component hierarchy and rendering ownership."""
    id: str
    name: str
    tag: str = "section"
    required_classes: List[str] = field(default_factory=list)
    hierarchy: str = "root"  # "root", "child", "overlay"
    rendering_ownership: str = "static"  # "static", "dynamic", "template"
    render_target_id: Optional[str] = None
    is_modal: bool = False
    is_form: bool = False
    data_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ComponentContract:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            tag=data.get("tag", "section"),
            required_classes=list(data.get("required_classes", [])),
            hierarchy=data.get("hierarchy", "root"),
            rendering_ownership=data.get("rendering_ownership", "static"),
            render_target_id=data.get("render_target_id"),
            is_modal=bool(data.get("is_modal", False)),
            is_form=bool(data.get("is_form", False)),
            data_sources=list(data.get("data_sources", [])),
        )


@dataclass
class DomAndStateContract:
    """Authoritative DOM selectors, dynamic elements, event wiring, and interactions."""
    required_static_ids: List[str] = field(default_factory=list)
    required_static_classes: List[str] = field(default_factory=list)
    dynamic_ids: List[str] = field(default_factory=list)
    dynamic_classes: List[str] = field(default_factory=list)
    optional_selectors: List[str] = field(default_factory=list)
    data_attributes: List[str] = field(default_factory=list)
    event_handlers: List[Dict[str, Any]] = field(default_factory=list)
    interactions: List[Dict[str, Any]] = field(default_factory=list)
    state_transitions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DomAndStateContract:
        return cls(
            required_static_ids=list(data.get("required_static_ids", [])),
            required_static_classes=list(data.get("required_static_classes", [])),
            dynamic_ids=list(data.get("dynamic_ids", [])),
            dynamic_classes=list(data.get("dynamic_classes", [])),
            optional_selectors=list(data.get("optional_selectors", [])),
            data_attributes=list(data.get("data_attributes", [])),
            event_handlers=list(data.get("event_handlers", [])),
            interactions=list(data.get("interactions", [])),
            state_transitions=dict(data.get("state_transitions", {})),
        )


@dataclass
class CssContract:
    """Authoritative styling rules, design tokens, layout strategies, and responsive rules."""
    design_tokens: Dict[str, str] = field(default_factory=dict)
    layout_strategy: str = "responsive_flex_grid"
    typography: Dict[str, str] = field(default_factory=dict)
    component_selectors: List[str] = field(default_factory=list)
    responsive_breakpoints: List[str] = field(default_factory=lambda: ["768px", "1024px"])
    visual_states: List[str] = field(default_factory=lambda: [":hover", ":focus-visible", ".active", ".open", ".hidden"])
    interaction_states: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CssContract:
        return cls(
            design_tokens=dict(data.get("design_tokens", {})),
            layout_strategy=data.get("layout_strategy", "responsive_flex_grid"),
            typography=dict(data.get("typography", {})),
            component_selectors=list(data.get("component_selectors", [])),
            responsive_breakpoints=list(data.get("responsive_breakpoints", ["768px", "1024px"])),
            visual_states=list(data.get("visual_states", [":hover", ":focus-visible", ".active", ".open", ".hidden"])),
            interaction_states=list(data.get("interaction_states", [])),
        )


@dataclass
class JavaScriptContract:
    """Script entrypoint, modular structure, state store, and functional handlers."""
    authoritative_entrypoint: str = "app.js"
    secondary_modules: List[str] = field(default_factory=list)
    module_imports: List[str] = field(default_factory=list)
    state_management: str = "vanilla_store"
    rendering_functions: List[str] = field(default_factory=list)
    event_delegation: List[Dict[str, Any]] = field(default_factory=list)
    search_filter_behavior: Dict[str, Any] = field(default_factory=dict)
    modal_behavior: Dict[str, Any] = field(default_factory=dict)
    form_behavior: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JavaScriptContract:
        return cls(
            authoritative_entrypoint=data.get("authoritative_entrypoint", "app.js"),
            secondary_modules=list(data.get("secondary_modules", [])),
            module_imports=list(data.get("module_imports", [])),
            state_management=data.get("state_management", "vanilla_store"),
            rendering_functions=list(data.get("rendering_functions", [])),
            event_delegation=list(data.get("event_delegation", [])),
            search_filter_behavior=dict(data.get("search_filter_behavior", {})),
            modal_behavior=dict(data.get("modal_behavior", {})),
            form_behavior=dict(data.get("form_behavior", {})),
        )


@dataclass
class AssetContractItem:
    """Photographic and graphical asset requirements."""
    intended_component: str
    relative_path: str
    alt_text: str
    verification_state: str = "pending"  # "pending", "verified", "missing"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AssetContractItem:
        return cls(
            intended_component=data.get("intended_component", ""),
            relative_path=data.get("relative_path", ""),
            alt_text=data.get("alt_text", ""),
            verification_state=data.get("verification_state", "pending"),
        )


@dataclass
class FrontendImplementationContract:
    """
    Authoritative machine-readable project implementation contract (Phase 3).
    Ensures that HTML, CSS, JavaScript, assets, and DOM relationships remain
    strictly aligned and coherent across all generation turns and model failovers.
    """
    version: int = 1
    mission_id: str = ""
    app_name: str = "Application"
    architecture: ArchitectureContract = field(default_factory=ArchitectureContract)
    components: List[ComponentContract] = field(default_factory=list)
    dom_and_state: DomAndStateContract = field(default_factory=DomAndStateContract)
    css: CssContract = field(default_factory=CssContract)
    javascript: JavaScriptContract = field(default_factory=JavaScriptContract)
    assets: List[AssetContractItem] = field(default_factory=list)
    business_domain: str = ""
    cuisine_subtype: str = ""
    brand_positioning: str = ""
    target_audience: str = ""
    requested_content: List[str] = field(default_factory=list)
    requested_visual_direction: str = ""
    contract_hash: str = ""

    def __post_init__(self):
        if not self.contract_hash:
            self.contract_hash = self.compute_hash()

    def compute_hash(self) -> str:
        """Compute stable SHA-256 fingerprint excluding volatile fields."""
        d = self.to_dict()
        d.pop("contract_hash", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "mission_id": self.mission_id,
            "app_name": self.app_name,
            "architecture": self.architecture.to_dict(),
            "components": [c.to_dict() for c in self.components],
            "dom_and_state": self.dom_and_state.to_dict(),
            "css": self.css.to_dict(),
            "javascript": self.javascript.to_dict(),
            "assets": [a.to_dict() for a in self.assets],
            "business_domain": self.business_domain,
            "cuisine_subtype": self.cuisine_subtype,
            "brand_positioning": self.brand_positioning,
            "target_audience": self.target_audience,
            "requested_content": self.requested_content,
            "requested_visual_direction": self.requested_visual_direction,
            "contract_hash": self.contract_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FrontendImplementationContract:
        return cls(
            version=int(data.get("version", 1)),
            mission_id=data.get("mission_id", ""),
            app_name=data.get("app_name", "Application"),
            architecture=ArchitectureContract.from_dict(data.get("architecture", {})),
            components=[ComponentContract.from_dict(c) for c in data.get("components", [])],
            dom_and_state=DomAndStateContract.from_dict(data.get("dom_and_state", {})),
            css=CssContract.from_dict(data.get("css", {})),
            javascript=JavaScriptContract.from_dict(data.get("javascript", {})),
            assets=[AssetContractItem.from_dict(a) for a in data.get("assets", [])],
            business_domain=data.get("business_domain", ""),
            cuisine_subtype=data.get("cuisine_subtype", ""),
            brand_positioning=data.get("brand_positioning", ""),
            target_audience=data.get("target_audience", ""),
            requested_content=list(data.get("requested_content", [])),
            requested_visual_direction=data.get("requested_visual_direction", ""),
            contract_hash=data.get("contract_hash", ""),
        )

    def save_to_workspace(self, workspace_root: Path | str) -> Path:
        """Persist contract to .hermes/frontend_contract.json."""
        ws = Path(workspace_root).resolve()
        hermes_dir = ws / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        contract_path = hermes_dir / "frontend_contract.json"
        self.contract_hash = self.compute_hash()
        contract_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        logger.info(f"FrontendImplementationContract: saved v{self.version} hash={self.contract_hash} to {contract_path}")
        return contract_path

    @classmethod
    def load_from_workspace(cls, workspace_root: Path | str) -> Optional[FrontendImplementationContract]:
        """Load contract from .hermes/frontend_contract.json if it exists."""
        ws = Path(workspace_root).resolve()
        contract_path = ws / ".hermes" / "frontend_contract.json"
        if not contract_path.exists():
            return None
        try:
            data = json.loads(contract_path.read_text(encoding="utf-8", errors="ignore"))
            return cls.from_dict(data)
        except Exception as e:
            logger.warning(f"FrontendImplementationContract: error loading from {contract_path}: {e}")
            return None

    def update_version(self) -> None:
        """Increment contract version and update hash upon intentional revision."""
        self.version += 1
        self.contract_hash = self.compute_hash()

    def to_compact_directive(self) -> str:
        """
        Render a concise prompt directive communicating the contract to code generation calls.
        """
        lines = [
            f"=== FRONTEND IMPLEMENTATION CONTRACT (v{self.version}) ===",
            f"Entrypoint: {self.architecture.entrypoint} | Style: {self.architecture.authoritative_style} | Script: {self.architecture.authoritative_script}",
            f"Authoritative Script Entrypoint: '{self.architecture.authoritative_script}' (MUST NOT create duplicate or conflicting entrypoints e.g. main.js). Link only {self.architecture.authoritative_script} in index.html.",
            "Canonical DOM Selectors: Search input must have id='search-input' (DO NOT query #search). Dynamic grids are #destinations-grid and #packages-grid.",
            "Dynamic Data Model: In app.js, populate #destinations-grid with 6 destinations (Bali, Switzerland, Paris, Dubai, Maldives, Japan) and #packages-grid with 6 travel packages.",
            "Filtering Taxonomy: Filter categories must use ['all', 'beach', 'mountain', 'city', 'cultural', 'luxury']. Filter buttons must have data-category matching these.",
            "Modal & Form Contract: #booking-modal dialog (or #destination-modal) with close button (#modal-close-btn or #modal-close), backdrop click dismissal, Escape key dismissal, and body scroll lock/unlock. .book-now-btn opens modal with package details. #booking-form validates inputs and displays confirmation feedback with clear demo mode notice.",
            "Component Class Unification: Use unified classes across HTML, CSS, and JS: cards use (.card, .destination-card, .package-card), image containers use (.card-image, .card-img, .package-image-wrap) with object-fit: cover, card content uses (.card-content, .card-body). Package cards must include (.package-meta, .duration, .price, .highlights). Testimonials must use (.testimonial-card, .testimonial-header, .avatar, .testimonial-text).",
            "Filter & Navigation Contract: Filter controls use (.filter-container, .search-box, .filter-buttons) aligned in CSS. Header height must be 64-76px. Mobile nav button must be a styled hamburger icon (<button class='mobile-menu-btn' id='mobile-menu-btn' aria-label='Toggle navigation' aria-expanded='false'><span></span><span></span><span></span></button> or SVG), NEVER raw 'Menu' text. Mobile nav must implement (.nav-links.active or #nav-menu.active) visible styling with solid/blur dropdown drawer, aria-expanded toggle, Escape key dismiss, and close on link click. Every nav link (<a href='#...'>) MUST link to an existing section id (e.g. #destinations, #packages, #why-us, #about, #reviews, #booking).",
            "Hero Visual Architecture Contract: .hero MUST have full-bleed background photography (background-size: cover; background-position: center; min-height: 85vh; position: relative; overflow: hidden;) and a FULL-HERO gradient overlay spanning the ENTIRE hero via 'position: absolute; inset: 0; z-index: 1; pointer-events: none;' (or .hero::before). Text and buttons MUST be inside a container with 'position: relative; z-index: 2;' for high contrast. STRICTLY PROHIBIT partial-height boxed overlay bands (.hero-overlay with padding/relative pos) leaving raw photo exposed above or below. Fluid typography: h1 font-size: clamp(2rem, 5vw, 3.5rem); p font-size: clamp(1rem, 2.5vw, 1.25rem);",
            "Destination Actions & Normalization: Destination details action scrollToPackages(dest) must filter packages for that destination and scroll to #packages. Opening a package pre-selects the destination in the booking form with lowercase normalized value (e.g. destSelect.value = dest.toLowerCase().split(' ')[0]).",
            "Safe DOM Operations: Always check elements exist before adding listeners or reading properties (e.g. if (el) el.addEventListener(...)). Zero uncaught null reference exceptions.",
            "Asset Provenance: Use verified local photography provisioned in assets/images/ (hero, 6 destinations, 6 packages, testimonials). Never use external remote placeholder URLs.",
        ]

        if self.dom_and_state.required_static_ids:
            lines.append(f"Required Static IDs: {', '.join(self.dom_and_state.required_static_ids[:15])}")

        if self.dom_and_state.dynamic_ids:
            lines.append(f"Dynamic Render Target IDs: {', '.join(self.dom_and_state.dynamic_ids)}")
            lines.append("CRITICAL: Dynamic render targets MUST be child containers (e.g. #destinations-grid), NEVER overwrite parent <section> tags!")

        if self.css.design_tokens:
            token_sample = ", ".join(f"{k}: {v}" for k, v in list(self.css.design_tokens.items())[:6])
            lines.append(f"Design Tokens (:root): {token_sample}")

        lines.append(
            "Interactions: Search and filters must execute real client-side filtering updating DOM; "
            "Forms must validate and execute advertised actions. Console logging is STRICTLY REJECTED as a substitute for features."
        )
        lines.append("==========================================================")
        return "\n".join(lines)


class FrontendContractBuilder:
    """
    Constructs an initial authoritative contract from task description and design brief,
    or reconciles it with existing HTML markup.
    """

    @classmethod
    def build_initial_contract(
        cls,
        task: str,
        mission_id: str = "",
        design_brief: Optional[Any] = None,
    ) -> FrontendImplementationContract:
        """Generate initial contract dynamically derived from the specific mission domain and task."""
        from core.design_intelligence import DesignBriefGenerator, strip_negative_constraints
        task_clean = strip_negative_constraints(task or "")
        task_clean_lower = task_clean.lower()
        task_lower = task_clean_lower
        domain = getattr(design_brief, "domain", None) or DesignBriefGenerator.detect_domain(task)

        # Architecture defaults
        arch = ArchitectureContract(
            project_type="vanilla_web",
            technology_stack=["html5", "css3", "javascript"],
            entrypoint="index.html",
            authoritative_script="app.js",
            authoritative_style="style.css",
        )

        # ------------------------------------------------------------------
        # ------------------------------------------------------------------
        from core.design_intelligence import detect_brand_name
        detected_brand = detect_brand_name(task)

        # ------------------------------------------------------------------
        # 0. ROBOTICS & INDUSTRIAL AUTOMATION DOMAIN (e.g. ATLAS Robotics)
        # ------------------------------------------------------------------
        if domain == "robotics_automation" or any(w in task_clean_lower for w in ["robotics", "robot", "industrial automation", "autonomous mobile"]):
            app_name = detected_brand if detected_brand != "Application" else "ATLAS Robotics"
            brand_pos = "Global robotics and industrial automation engineering company delivering autonomous mobile robots, multi-axis robotic arms, AI machine vision, and intelligent assembly automation."
            target_aud = "Enterprise manufacturing directors, automation engineers, logistics executives, and plant operations managers."
            req_content = ["industrial robotic arms", "autonomous mobile robots", "ai vision systems", "collaborative robots", "precision assembly automation", "autonomous inspection systems", "consultation enquiry"]
            req_vis = "Deep graphite, midnight navy, electric cyan, and subtle precision lime accents. High-tech engineering aesthetic with crisp hierarchy, dynamic solution cards, product catalog, and consultation modal."

            components = [
                ComponentContract(id="navbar", name="Navigation Header", tag="header", required_classes=["site-header", "navbar"]),
                ComponentContract(id="hero", name="Robotics Hero Presentation", tag="section", required_classes=["hero", "hero-content"]),
                ComponentContract(id="about", name="Company Overview & Philosophy", tag="section", required_classes=["container", "about-section"]),
                ComponentContract(
                    id="solutions",
                    name="Robotics Solutions & Capabilities",
                    tag="section",
                    required_classes=["solutions-section"],
                    rendering_ownership="dynamic",
                    render_target_id="solutions-grid",
                    data_sources=["solutions_data"],
                ),
                ComponentContract(
                    id="products",
                    name="Robotics Product Catalogue",
                    tag="section",
                    required_classes=["products-section"],
                    rendering_ownership="dynamic",
                    render_target_id="products-grid",
                    data_sources=["products_data"],
                ),
                ComponentContract(id="applications", name="Industry Applications", tag="section", required_classes=["container", "applications-section"]),
                ComponentContract(id="research", name="Research & Innovation", tag="section", required_classes=["container", "research-section"]),
                ComponentContract(id="projects", name="Featured Engineering Projects", tag="section", required_classes=["container", "projects-section"]),
                ComponentContract(id="why-us", name="Why Choose ATLAS", tag="section", required_classes=["container", "why-section"]),
                ComponentContract(id="testimonials", name="Customer Perspectives", tag="section", required_classes=["container", "testimonials-section"]),
                ComponentContract(id="contact", name="Consultation & Inquiries", tag="section", required_classes=["container", "contact-section"]),
                ComponentContract(id="consultation-form", name="Consultation Request Form", tag="form", required_classes=["consultation-form"], is_form=True),
                ComponentContract(id="product-modal", name="Product Details Inspection Modal", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
                ComponentContract(id="footer", name="Site Footer", tag="footer", required_classes=["site-footer"]),
            ]

            dom_state = DomAndStateContract(
                required_static_ids=[
                    "navbar", "hero", "about", "solutions", "solutions-grid",
                    "products", "products-grid", "product-search", "category-filters",
                    "applications", "research", "projects", "why-us", "testimonials",
                    "contact", "consultation-form", "product-modal", "modal-close", "mobile-menu-btn",
                ],
                required_static_classes=[
                    "site-header", "hero", "solution-card", "product-card",
                    "filter-pill", "modal-overlay", "site-footer", "btn-primary",
                ],
                dynamic_ids=["solutions-grid", "products-grid"],
                dynamic_classes=["active", "open", "hidden"],
                optional_selectors=[".spec-row", ".status-badge", ".tech-pill"],
                data_attributes=["data-category", "data-product-id", "data-solution-id"],
                event_handlers=[
                    {"target": "#product-search", "event": "input", "action": "filterProducts"},
                    {"target": ".filter-pill", "event": "click", "action": "filterByCategory"},
                    {"target": ".btn-details", "event": "click", "action": "openProductModal"},
                    {"target": "#modal-close", "event": "click", "action": "closeProductModal"},
                    {"target": "#consultation-form", "event": "submit", "action": "submitConsultation"},
                ],
                interactions=[
                    {
                        "trigger": "Filter pill click",
                        "expected_state_change": "Filters product catalogue by category",
                        "expected_result": "Displays matching robotics product cards",
                    },
                    {
                        "trigger": "Search input typing",
                        "expected_state_change": "Filters products in real-time by title or capability",
                        "expected_result": "Dynamic DOM update matching query",
                    },
                    {
                        "trigger": "View Details button click",
                        "expected_state_change": "Opens product modal with full engineering specs",
                        "expected_result": "Modal dialog rendered visible",
                    },
                    {
                        "trigger": "Consultation form submit",
                        "expected_state_change": "Validates inputs and displays demonstration confirmation",
                        "expected_result": "Validation feedback presented to user",
                    },
                ],
            )

            tokens = {
                "--primary-color": "#00d2ff",
                "--secondary-color": "#162032",
                "--accent-color": "#10b981",
                "--bg-main": "#0b0f17",
                "--bg-surface": "#131b28",
                "--text-primary": "#f8fafc",
                "--text-muted": "#94a3b8",
                "--border-color": "#243248",
            }
            if design_brief and getattr(design_brief, "color_palette", None):
                for k, v in getattr(design_brief, "color_palette", {}).items():
                    token_k = f"--{k.replace('_', '-')}" if not k.startswith("--") else k
                    tokens[token_k] = v

            css = CssContract(
                design_tokens=tokens,
                layout_strategy="responsive_grid_flex",
                component_selectors=[
                    ".site-header", ".hero", ".solution-card", ".product-card",
                    ".filter-pill", ".modal-dialog", ".site-footer", ".consultation-form"
                ],
                responsive_breakpoints=["768px", "1024px"],
            )

            js = JavaScriptContract(
                authoritative_entrypoint="app.js",
                secondary_modules=[],
                state_management="vanilla_store",
                rendering_functions=[
                    "renderSolutions", "renderProducts", "filterByCategory", "searchProducts",
                    "openProductModal", "closeProductModal", "handleConsultationSubmit"
                ],
            )

            assets = [
                AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-robotics.jpg", alt_text="High-tech industrial robotics automation laboratory"),
                AssetContractItem(intended_component="solutions_grid", relative_path="assets/images/solutions/sol-arms.jpg", alt_text="High-precision articulated industrial robotic arm"),
                AssetContractItem(intended_component="solutions_grid", relative_path="assets/images/solutions/sol-amr.jpg", alt_text="Autonomous mobile robot navigating warehouse"),
                AssetContractItem(intended_component="solutions_grid", relative_path="assets/images/solutions/sol-vision.jpg", alt_text="AI machine vision inspection sensor system"),
                AssetContractItem(intended_component="solutions_grid", relative_path="assets/images/solutions/sol-cobot.jpg", alt_text="Collaborative robot cobot operating alongside technician"),
                AssetContractItem(intended_component="solutions_grid", relative_path="assets/images/solutions/sol-assembly.jpg", alt_text="Precision micro-component robotic assembly cell"),
                AssetContractItem(intended_component="solutions_grid", relative_path="assets/images/solutions/sol-inspection.jpg", alt_text="Autonomous quality assurance scanning cell"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/atlas-apex-6.jpg", alt_text="ATLAS Apex-6 6-axis articulated industrial robotic arm"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/atlas-strider-amr.jpg", alt_text="ATLAS Strider AMR-1000 autonomous mobile robot"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/atlas-optiscan.jpg", alt_text="ATLAS OptiScan AI neural machine vision head"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/atlas-nexus-7.jpg", alt_text="ATLAS Nexus-7 7-axis precision collaborative cobot"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/atlas-microassembler.jpg", alt_text="ATLAS MicroAssembler Pro high-speed micro-component assembly cell"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/atlas-sentinel.jpg", alt_text="ATLAS Sentinel automated 360-degree quality assurance scanner"),
            ]

            return FrontendImplementationContract(
                version=2,
                mission_id=mission_id,
                app_name=app_name,
                business_domain="robotics_automation",
                brand_positioning=brand_pos,
                target_audience=target_aud,
                requested_content=req_content,
                requested_visual_direction=req_vis,
                components=components,
                dom_and_state=dom_state,
                css=css,
                javascript=js,
                assets=assets,
            )

        # ------------------------------------------------------------------
        # 0. E-COMMERCE / CONSUMER ELECTRONICS DOMAIN (e.g. NOVA)
        # ------------------------------------------------------------------
        if (domain in ("ecommerce_electronics", "ecommerce_store") and not any(w in task_clean_lower for w in ["robotics", "robot", "hospital", "logistics", "real estate"])) or ("nova" in task_clean_lower and any(w in task_clean_lower for w in ["smartphones", "laptops", "headphones", "electronics"])):
            app_name = "NOVA"
            brand_pos = "Premium consumer electronics brand delivering cutting-edge personal computing, mobile, audio, and gaming technology."
            target_aud = "Discerning tech enthusiasts, professionals, and gamers seeking precision-engineered devices."
            req_content = ["smartphones", "laptops", "headphones", "smartwatches", "gaming", "accessories", "shopping cart"]
            req_vis = "Deep charcoal, clean white, electric blue, and subtle silver accents. Modern cards, live cart count, and modal product inspection."

            components = [
                ComponentContract(id="navbar", name="Navigation Header & Cart", tag="header", required_classes=["site-header", "navbar"]),
                ComponentContract(id="hero", name="Technology Hero Presentation", tag="section", required_classes=["hero", "hero-content"]),
                ComponentContract(id="categories", name="Featured Hardware Categories", tag="section", required_classes=["categories-section"]),
                ComponentContract(
                    id="products",
                    name="Product Catalog & Interactive Grid",
                    tag="section",
                    required_classes=["products-section"],
                    rendering_ownership="dynamic",
                    render_target_id="products-grid",
                    data_sources=["products_data"],
                ),
                ComponentContract(id="features", name="Value Propositions & Warranty", tag="section", required_classes=["container", "features-section"]),
                ComponentContract(id="about", name="Engineering Philosophy & Heritage", tag="section", required_classes=["container", "about-section"]),
                ComponentContract(id="product-modal", name="Product Details Inspection Modal", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
                ComponentContract(id="cart-modal", name="Interactive Shopping Cart Modal", tag="div", required_classes=["modal-overlay", "cart-modal"], is_modal=True),
                ComponentContract(id="checkout-modal", name="Demonstration Checkout Modal", tag="div", required_classes=["modal-overlay"], is_modal=True),
                ComponentContract(id="contact", name="Customer Inquiries & Support", tag="section", required_classes=["container", "contact-section"]),
                ComponentContract(id="contact-form", name="Customer Support Form", tag="form", required_classes=["contact-form"], is_form=True),
                ComponentContract(id="footer", name="Site Footer", tag="footer", required_classes=["site-footer"]),
            ]

            dom_state = DomAndStateContract(
                required_static_ids=[
                    "navbar", "hero", "categories", "products", "products-grid", "filters",
                    "features", "about", "product-modal", "cart-modal", "checkout-modal",
                    "contact", "contact-form", "footer", "cart-btn", "cart-count"
                ],
                required_static_classes=[
                    "site-header", "hero", "product-card", "category-btn",
                    "modal-overlay", "site-footer", "cart-modal"
                ],
                dynamic_ids=["products-grid", "cart-items", "cart-subtotal", "cart-count"],
                dynamic_classes=["active", "open", "hidden"],
                optional_selectors=[".badge", ".price", ".rating", ".cart-badge"],
                data_attributes=["data-category", "data-product-id", "data-price"],
                event_handlers=[
                    {"target": "#product-search", "event": "input", "action": "searchProducts"},
                    {"target": ".category-btn", "event": "click", "action": "filterByCategory"},
                    {"target": "#price-sort", "event": "change", "action": "sortProducts"},
                    {"target": "#cart-btn", "event": "click", "action": "openCartModal"},
                    {"target": ".cart-close", "event": "click", "action": "closeCartModal"},
                    {"target": "#contact-form", "event": "submit", "action": "submit_contact"},
                ],
                interactions=[
                    {
                        "trigger": "Add to Cart button click",
                        "expected_state_change": "Appends product to cart state and increments badge count",
                        "expected_result": "Cart item added with live subtotal update",
                    },
                    {
                        "trigger": "Category button click",
                        "expected_state_change": "Filters visible products by selected electronics category",
                        "expected_result": "Displays matching electronic product cards",
                    },
                    {
                        "trigger": "Search input typing",
                        "expected_state_change": "Filters products in real time by name, category, or description",
                        "expected_result": "Dynamic DOM update matching query",
                    },
                ],
            )

            tokens = {
                "--primary-color": "#0284c7",
                "--primary-light": "#38bdf8",
                "--secondary-color": "#0f172a",
                "--accent-blue": "#0ea5e9",
                "--bg-dark": "#0b0f17",
                "--bg-card": "#131b2e",
                "--bg-surface": "#1e293b",
                "--text-primary": "#f8fafc",
                "--text-secondary": "#94a3b8",
                "--border-color": "#334155",
                "--radius-md": "8px",
                "--shadow-md": "0 4px 20px -2px rgba(0, 0, 0, 0.25)",
            }
            if design_brief and hasattr(design_brief, "color_palette"):
                for k, v in getattr(design_brief, "color_palette", {}).items():
                    tokens[f"--{k}"] = v

            css = CssContract(
                design_tokens=tokens,
                layout_strategy="responsive_grid_flex",
                component_selectors=[
                    ".site-header", ".hero", ".product-card", ".products-grid",
                    ".category-btn", ".modal-dialog", ".site-footer", ".cart-modal"
                ],
                responsive_breakpoints=["768px", "1024px"],
            )

            js = JavaScriptContract(
                authoritative_entrypoint="app.js",
                secondary_modules=[],
                state_management="vanilla_store",
                rendering_functions=[
                    "renderProducts", "filterByCategory", "searchProducts", "sortProducts",
                    "openProductModal", "closeProductModal", "openCartModal", "closeCartModal",
                    "addToCart", "updateCartQuantity", "removeFromCart", "calculateSubtotal"
                ],
            )

            assets = [
                AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-electronics.jpg", alt_text="Premium consumer electronics workspace showcasing cutting-edge devices"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-apex-pro.jpg", alt_text="NOVA Apex Pro 5G flagship smartphone with titanium frame"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-pulse-mini.jpg", alt_text="NOVA Pulse Mini 5G compact smartphone with OLED display"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-book-15.jpg", alt_text="NOVA Book Ultralight 15 inch laptop with CNC aluminum chassis"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-studio-16.jpg", alt_text="NOVA Studio Pro 16 creator laptop with discrete graphics"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-sonic-anc.jpg", alt_text="NOVA Sonic active noise cancelling wireless over-ear headphones"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-soundbuds-pro.jpg", alt_text="NOVA SoundBuds Pro spatial audio wireless earbuds"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-chrono-steel.jpg", alt_text="NOVA Chrono Precision stainless steel smart wristwatch"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-fit-active.jpg", alt_text="NOVA Fit Active titanium sport smartwatch with biometric sensors"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-horizon-vr.jpg", alt_text="NOVA Horizon VR spatial computing gaming headset"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-reflex-keyboard.jpg", alt_text="NOVA Reflex mechanical gaming keyboard with RGB backlighting"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-gan-charger.jpg", alt_text="NOVA PowerMatrix 100W GaN fast charger with braided cable"),
                AssetContractItem(intended_component="products_grid", relative_path="assets/images/products/nova-magnetic-stand.jpg", alt_text="NOVA Magnetic 3-in-1 wireless fast charging stand"),
            ]

            return FrontendImplementationContract(
                version=2,
                mission_id=mission_id,
                app_name=app_name,
                business_domain="ecommerce_electronics",
                brand_positioning=brand_pos,
                target_audience=target_aud,
                requested_content=req_content,
                requested_visual_direction=req_vis,
                components=components,
                dom_and_state=dom_state,
                css=css,
                javascript=js,
                assets=assets,
            )

        # 1. EDUCATION / UNIVERSITY DOMAIN
        # ------------------------------------------------------------------
        if domain == "education_institution" or any(w in task_lower for w in ["northstar", "university", "college", "academic", "degree"]):
            app_name = "NorthStar University" if "northstar" in task_lower else "University Portal"
            components = [
                ComponentContract(id="navbar", name="Navigation Header", tag="header", required_classes=["site-header", "navbar"]),
                ComponentContract(id="hero", name="Campus Hero Presentation", tag="section", required_classes=["hero", "hero-content"]),
                ComponentContract(id="about", name="About & Heritage", tag="section", required_classes=["container"]),
                ComponentContract(
                    id="academics",
                    name="Academic Schools & Degree Programs",
                    tag="section",
                    required_classes=["academics-section"],
                    rendering_ownership="dynamic",
                    render_target_id="programs-grid",
                    data_sources=["programs_data"],
                ),
                ComponentContract(id="admissions", name="Admissions Process", tag="section", required_classes=["admissions-section"]),
                ComponentContract(
                    id="faculty",
                    name="Distinguished Faculty",
                    tag="section",
                    required_classes=["container"],
                    rendering_ownership="dynamic",
                    render_target_id="faculty-grid",
                    data_sources=["faculty_data"],
                ),
                ComponentContract(id="campus-life", name="Campus Life & Housing", tag="section", required_classes=["container"]),
                ComponentContract(id="research", name="Research Centers", tag="section", required_classes=["container"]),
                ComponentContract(id="events", name="Events Calendar", tag="section", required_classes=["container"]),
                ComponentContract(id="faq", name="FAQ Accordion", tag="section", required_classes=["faq-section"]),
                ComponentContract(id="inquiry-modal", name="Information Request Modal", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
                ComponentContract(id="inquiry-form", name="Admissions Inquiry Form", tag="form", required_classes=["inquiry-form"], is_form=True),
                ComponentContract(id="footer", name="University Footer", tag="footer", required_classes=["site-footer"]),
            ]

            dom_state = DomAndStateContract(
                required_static_ids=[
                    "navbar", "hero", "search-input", "filter-buttons", "programs-grid",
                    "faculty-grid", "faq-accordion", "inquiry-modal", "inquiry-form",
                    "modal-close", "mobile-menu-btn",
                ],
                required_static_classes=[
                    "site-header", "hero", "program-card", "timeline-card",
                    "filter-pill", "modal-overlay", "site-footer",
                ],
                dynamic_ids=["programs-grid", "faculty-grid", "events-list"],
                dynamic_classes=["active", "open", "hidden"],
                optional_selectors=[".stats-ribbon", ".badge", ".timeline-step"],
                data_attributes=["data-category", "data-program-id", "data-degree"],
                event_handlers=[
                    {"target": "#search-input", "event": "input", "action": "filter_programs"},
                    {"target": ".filter-pill", "event": "click", "action": "filter_by_school"},
                    {"target": "#btn-request-info", "event": "click", "action": "open_inquiry_modal"},
                    {"target": "#modal-close", "event": "click", "action": "close_inquiry_modal"},
                    {"target": "#inquiry-form", "event": "submit", "action": "submit_inquiry"},
                    {"target": ".faq-question", "event": "click", "action": "toggle_accordion"},
                ],
                interactions=[
                    {
                        "trigger": "Filter pill click",
                        "expected_state_change": "Filters academic programs by selected school",
                        "expected_result": "Displays matching program cards",
                    },
                    {
                        "trigger": "Search input typing",
                        "expected_state_change": "Filters programs in real time by title or keyword",
                        "expected_result": "Dynamic DOM update matching query",
                    },
                    {
                        "trigger": "FAQ question toggle",
                        "expected_state_change": "Expands or collapses targeted FAQ answer",
                        "expected_result": "Accordion panel revealed",
                    },
                    {
                        "trigger": "Inquiry form submit",
                        "expected_state_change": "Validates inputs and displays confirmation alert",
                        "expected_result": "Inquiry recorded with student notification",
                    },
                ],
            )

            tokens = {
                "--primary-color": "#0b2545",
                "--primary-light": "#134074",
                "--royal-blue": "#1d4ed8",
                "--accent-gold": "#d4af37",
                "--bg-main": "#f8fafc",
                "--bg-surface": "#ffffff",
                "--text-primary": "#0f172a",
                "--text-secondary": "#475569",
                "--font-heading": "'Plus Jakarta Sans', system-ui, sans-serif",
                "--font-body": "'Inter', system-ui, sans-serif",
                "--border-color": "#e2e8f0",
                "--radius-md": "10px",
                "--shadow-md": "0 4px 12px rgba(11, 37, 69, 0.08)",
            }
            if design_brief and hasattr(design_brief, "color_palette"):
                for k, v in getattr(design_brief, "color_palette", {}).items():
                    tokens[f"--{k}"] = v

            css = CssContract(
                design_tokens=tokens,
                layout_strategy="responsive_grid_flex",
                component_selectors=[
                    ".site-header", ".hero", ".program-card", ".cards-grid",
                    ".filter-pill", ".timeline-card", ".modal-dialog", ".site-footer",
                ],
                responsive_breakpoints=["768px", "1024px"],
            )

            js = JavaScriptContract(
                authoritative_entrypoint="app.js",
                secondary_modules=[],
                state_management="vanilla_store",
                rendering_functions=["renderPrograms", "renderFaculty", "applyFilter", "openModal", "closeModal"],
            )

            assets = [
                AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-campus.jpg", alt_text="Historic collegiate campus quadrangle"),
                AssetContractItem(intended_component="engineering", relative_path="assets/images/academics/engineering.jpg", alt_text="Engineering robotics laboratory"),
                AssetContractItem(intended_component="arts", relative_path="assets/images/academics/arts-sciences.jpg", alt_text="Humanities reading room"),
                AssetContractItem(intended_component="business", relative_path="assets/images/academics/business.jpg", alt_text="Business leadership amphitheater"),
                AssetContractItem(intended_component="faculty", relative_path="assets/images/faculty/dr-mitchell.jpg", alt_text="Distinguished faculty researcher"),
            ]

            return FrontendImplementationContract(
                version=1,
                mission_id=mission_id,
                app_name="NorthStar University",
                business_domain="education_institution",
                cuisine_subtype="",
                brand_positioning="Premier collegiate institution fostering academic excellence and global leadership.",
                target_audience="Prospective students, faculty, alumni, and researchers",
                requested_content=["academic programs", "faculty directory", "campus life", "admissions inquiry"],
                requested_visual_direction="Historic collegiate navy and gold, academic typography, campus photography",
                architecture=arch,
                components=components,
                dom_and_state=dom_state,
                css=css,
                javascript=js,
                assets=assets,
            )

        # ------------------------------------------------------------------
        # 2. CULINARY / RESTAURANT DOMAIN
        # ------------------------------------------------------------------
        if domain == "culinary_restaurant":
            from core.design_intelligence import DesignBriefGenerator, strip_negative_constraints
            cuisine = getattr(design_brief, "cuisine_subtype", "") or DesignBriefGenerator.detect_cuisine_subtype(task)
            is_indian = cuisine == "Contemporary Indian"
            app_name = "Saffron & Stone" if any(w in task_lower for w in ["saffron", "stone"]) else ("Contemporary Indian Kitchen" if is_indian else "Artisanal Restaurant & Bar")
            brand_pos = "Premium Contemporary Indian dining celebrating heritage clay oven tandoor cooking, dum biryani, and aromatic spices." if is_indian else "Artisanal Mediterranean hearth dining."
            target_aud = "Discerning patrons seeking authentic high-end Indian dining" if is_indian else "Discerning culinary enthusiasts"
            req_content = ["paneer tikka", "dum biryani", "tandoori specialities", "indian breads", "traditional desserts"] if is_indian else ["tagine", "seabass", "ribeye", "mezze"]
            req_vis = "Warm royal saffron and terracotta palette, rich brass accents, evocative clay oven photography, zero fabricated credentials." if is_indian else "Warm terracotta, saffron amber, exposed stone."
            components = [
                ComponentContract(id="navbar", name="Restaurant Header & Navigation", tag="header", required_classes=["site-header", "navbar"]),
                ComponentContract(id="hero", name="Atmospheric Culinary Hero", tag="section", required_classes=["hero", "hero-content"]),
                ComponentContract(id="story", name="Culinary Philosophy & Heritage", tag="section", required_classes=["container", "story-section"]),
                ComponentContract(
                    id="menu",
                    name="Signature Menu & Dishes",
                    tag="section",
                    required_classes=["menu-section"],
                    rendering_ownership="dynamic",
                    render_target_id="menu-grid",
                    data_sources=["menu_data"],
                ),
                ComponentContract(id="chef", name="Executive Chef Profile", tag="section", required_classes=["container", "chef-section"]),
                ComponentContract(id="ambience", name="Dining Ambience & Spaces", tag="section", required_classes=["container"]),
                ComponentContract(id="private-dining", name="Private Dining & Events", tag="section", required_classes=["container"]),
                ComponentContract(id="gallery", name="Culinary & Architectural Gallery", tag="section", required_classes=["container", "gallery-section"]),
                ComponentContract(id="reviews", name="Critic & Guest Reviews", tag="section", required_classes=["container", "reviews-section"]),
                ComponentContract(id="faq", name="Dining FAQ Accordion", tag="section", required_classes=["faq-section"]),
                ComponentContract(id="dish-modal", name="Dish Inspection Dialog", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
                ComponentContract(id="reservation-modal", name="Table Reservation Dialog", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
                ComponentContract(id="reservation-form", name="Table Reservation Form", tag="form", required_classes=["reservation-form"], is_form=True),
                ComponentContract(id="footer", name="Restaurant Footer", tag="footer", required_classes=["site-footer"]),
            ]

            dom_state = DomAndStateContract(
                required_static_ids=[
                    "navbar", "hero", "search-input", "filter-buttons", "menu-grid",
                    "dish-modal", "reservation-modal", "reservation-form",
                    "modal-close", "mobile-menu-btn", "faq-accordion",
                ],
                required_static_classes=[
                    "site-header", "hero", "menu-card", "filter-pill",
                    "modal-overlay", "site-footer",
                ],
                dynamic_ids=["menu-grid", "gallery-grid"],
                dynamic_classes=["active", "open", "hidden"],
                data_attributes=["data-category", "data-dish-id", "data-price"],
                event_handlers=[
                    {"target": "#search-input", "event": "input", "action": "filter_dishes"},
                    {"target": ".filter-pill", "event": "click", "action": "filter_by_category"},
                    {"target": "#btn-book-table", "event": "click", "action": "open_reservation_modal"},
                    {"target": "#modal-close", "event": "click", "action": "close_modal"},
                    {"target": "#reservation-form", "event": "submit", "action": "submit_reservation"},
                    {"target": ".faq-question", "event": "click", "action": "toggle_accordion"},
                ],
                interactions=[
                    {
                        "trigger": "Filter pill click",
                        "expected_state_change": "Filters menu items by selected culinary course",
                        "expected_result": "Displays matching dish cards",
                    },
                    {
                        "trigger": "Search input typing",
                        "expected_state_change": "Searches dishes in real time by name or ingredient",
                        "expected_result": "Live DOM update of menu grid",
                    },
                    {
                        "trigger": "Dish card click",
                        "expected_state_change": "Opens dish modal with tasting notes and wine pairing",
                        "expected_result": "Modal dialog opens",
                    },
                    {
                        "trigger": "Reservation form submit",
                        "expected_state_change": "Validates reservation inputs and displays booking confirmation",
                        "expected_result": "Reservation confirmation displayed",
                    },
                ],
            )

            tokens = {
                "--primary-color": "#8b3a1a",
                "--primary-light": "#b85328",
                "--accent-gold": "#e5982e",
                "--bg-dark": "#141210",
                "--bg-surface": "#faf7f2",
                "--text-light": "#f5f2eb",
                "--text-dark": "#1a1714",
                "--text-muted": "#78716c",
                "--font-heading": "'Playfair Display', Georgia, serif",
                "--font-body": "'Plus Jakarta Sans', system-ui, sans-serif",
                "--border-color": "#e7e2da",
                "--radius-md": "8px",
                "--shadow-md": "0 4px 16px rgba(20, 18, 16, 0.08)",
            }
            if design_brief and hasattr(design_brief, "color_palette"):
                for k, v in getattr(design_brief, "color_palette", {}).items():
                    tokens[f"--{k}"] = v

            css = CssContract(
                design_tokens=tokens,
                layout_strategy="responsive_grid_flex",
                component_selectors=[
                    ".site-header", ".hero", ".menu-card", ".filter-pill",
                    ".modal-dialog", ".site-footer",
                ],
                responsive_breakpoints=["768px", "1024px"],
            )

            js = JavaScriptContract(
                authoritative_entrypoint="app.js",
                secondary_modules=[],
                state_management="vanilla_store",
                rendering_functions=["renderMenu", "openModal", "closeModal", "applyFilter", "submitReservation"],
            )

            assets = [
                AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-culinary.jpg", alt_text="Atmospheric candlelit dining room at Saffron and Stone"),
                AssetContractItem(intended_component="chef", relative_path="assets/images/chef/chef-marco.jpg", alt_text="Executive Chef Marco Valenti plating signature dish"),
                AssetContractItem(intended_component="ambience", relative_path="assets/images/ambience/dining-room.jpg", alt_text="Handcrafted stone walls and warm lighting"),
                AssetContractItem(intended_component="dish_tagine", relative_path="assets/images/dishes/tagine.jpg", alt_text="Signature saffron seafood tagine"),
                AssetContractItem(intended_component="dish_seabass", relative_path="assets/images/dishes/seabass.jpg", alt_text="Pan-seared Mediterranean seabass"),
            ]

            return FrontendImplementationContract(
                version=1,
                mission_id=mission_id,
                app_name=app_name,
                business_domain="culinary_restaurant",
                cuisine_subtype=cuisine,
                brand_positioning=brand_pos,
                target_audience=target_aud,
                requested_content=req_content,
                requested_visual_direction=req_vis,
                architecture=arch,
                components=components,
                dom_and_state=dom_state,
                css=css,
                javascript=js,
                assets=assets,
            )

        # ------------------------------------------------------------------
        # 3. TRAVEL / WANDERWORLD DOMAIN
        # ------------------------------------------------------------------
        if ("wanderworld" in task_lower) or ("destinations-grid" in task_lower):
            app_name = "WanderWorld"
            components = [
                ComponentContract(id="navbar", name="Navigation Bar", tag="nav", required_classes=["navbar", "nav-container"]),
                ComponentContract(id="hero", name="Hero Section", tag="section", required_classes=["hero", "hero-content"]),
                ComponentContract(
                    id="destinations",
                    name="Destinations Section",
                    tag="section",
                    required_classes=["destinations-section"],
                    rendering_ownership="dynamic",
                    render_target_id="destinations-grid",
                    data_sources=["destinations_data"],
                ),
                ComponentContract(
                    id="packages",
                    name="Travel Packages",
                    tag="section",
                    required_classes=["packages-section"],
                    rendering_ownership="dynamic",
                    render_target_id="packages-grid",
                    data_sources=["packages_data"],
                ),
                ComponentContract(id="booking-modal", name="Booking Modal", tag="div", required_classes=["modal", "modal-dialog"], is_modal=True),
                ComponentContract(id="booking-form", name="Booking Form", tag="form", required_classes=["booking-form", "form-control"], is_form=True),
                ComponentContract(id="footer", name="Site Footer", tag="footer", required_classes=["site-footer"]),
            ]

            dom_state = DomAndStateContract(
                required_static_ids=[
                    "navbar", "hero", "search-input", "filter-buttons",
                    "destinations-grid", "packages-grid", "booking-modal",
                    "booking-form", "modal-close", "mobile-menu-btn",
                ],
                required_static_classes=[
                    "navbar", "hero", "card", "destination-card", "package-card",
                    "filter-btn", "modal", "booking-form", "site-footer",
                ],
                dynamic_ids=["destinations-grid", "packages-grid", "modal-content-body"],
                dynamic_classes=["active", "open", "hidden", "filtered-out", "selected"],
                optional_selectors=[".dark-theme", "#theme-toggle", ".badge-popular"],
                data_attributes=["data-category", "data-destination-id", "data-price"],
                event_handlers=[
                    {"target": "#search-input", "event": "input", "action": "filter_destinations"},
                    {"target": ".filter-btn", "event": "click", "action": "filter_by_category"},
                    {"target": ".book-now-btn", "event": "click", "action": "open_booking_modal"},
                    {"target": "#modal-close", "event": "click", "action": "close_modal"},
                    {"target": "#booking-form", "event": "submit", "action": "handle_booking_submission"},
                ],
                interactions=[
                    {
                        "trigger": "Filter button click",
                        "expected_state_change": "Sets active filter; filters visible cards by category",
                        "expected_result": "Non-matching cards hidden or removed; matching cards displayed",
                    },
                    {
                        "trigger": "Search input typing",
                        "expected_state_change": "Filters visible items by matching title or description text",
                        "expected_result": "Real-time DOM update matching search query",
                    },
                    {
                        "trigger": "Book now button click",
                        "expected_state_change": "Populates modal with selected package details and adds .open class",
                        "expected_result": "Modal overlay displayed over viewport",
                    },
                    {
                        "trigger": "Modal close button or backdrop click",
                        "expected_state_change": "Removes .open class and resets modal",
                        "expected_result": "Modal overlay dismissed",
                    },
                    {
                        "trigger": "Booking form submit",
                        "expected_state_change": "Validates required fields and renders confirmation feedback",
                        "expected_result": "Displays confirmation notification without fake network claim",
                    },
                ],
            )

            tokens = {
                "--primary-color": "#0b1d33",
                "--primary-light": "#163256",
                "--ocean-teal": "#0d7a82",
                "--gold-accent": "#d4af37",
                "--bg-main": "#f8fafc",
                "--card-bg": "#ffffff",
                "--text-primary": "#0f172a",
                "--text-secondary": "#475569",
                "--border-color": "#e2e8f0",
                "--radius-sm": "6px",
                "--radius-md": "12px",
                "--shadow-md": "0 4px 12px rgba(11, 29, 51, 0.08)",
            }
            if design_brief and hasattr(design_brief, "color_palette"):
                for k, v in getattr(design_brief, "color_palette", {}).items():
                    tokens[f"--{k}"] = v

            css = CssContract(
                design_tokens=tokens,
                layout_strategy="responsive_grid_flex",
                component_selectors=[
                    ".navbar", ".hero", ".card", ".destination-card", ".package-card",
                    ".grid", ".cards-grid", ".modal", ".form-control", ".btn",
                ],
                responsive_breakpoints=["768px", "1024px"],
            )

            js = JavaScriptContract(
                authoritative_entrypoint="app.js",
                secondary_modules=[],
                state_management="vanilla_store",
                rendering_functions=["renderDestinations", "renderPackages", "openModal", "closeModal", "filterCards"],
            )

            assets = [
                AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-wanderlust.jpg", alt_text="Cinematic tropical ocean and white sand beach"),
                AssetContractItem(intended_component="destination-bali", relative_path="assets/images/destinations/bali.jpg", alt_text="Water temple in Bali"),
                AssetContractItem(intended_component="destination-paris", relative_path="assets/images/destinations/paris.jpg", alt_text="Eiffel Tower in Paris"),
                AssetContractItem(intended_component="destination-dubai", relative_path="assets/images/destinations/dubai.jpg", alt_text="Dubai skyline"),
                AssetContractItem(intended_component="destination-swiss", relative_path="assets/images/destinations/switzerland.jpg", alt_text="Snow-capped Swiss Alps"),
            ]

            return FrontendImplementationContract(
                version=1,
                mission_id=mission_id,
                app_name="WanderWorld",
                business_domain="travel_tourism",
                cuisine_subtype="",
                brand_positioning="Curated luxury eco-travel and extraordinary adventure expeditions.",
                target_audience="Adventurous luxury travelers and culture seekers",
                requested_content=["destinations", "travel packages", "interactive filters", "booking modal"],
                requested_visual_direction="Vibrant azure ocean gradients, panoramic landscapes, clean card grid",
                architecture=arch,
                components=components,
                dom_and_state=dom_state,
                css=css,
                javascript=js,
                assets=assets,
            )

        # ------------------------------------------------------------------
        # 3. ARCHITECTURE & INTERIOR DESIGN STUDIO DOMAIN (e.g. FORM & FIELD)
        # ------------------------------------------------------------------
        if ("form & field" in task_clean_lower) or ("form and field" in task_clean_lower):
            app_name = detected_brand if detected_brand != "Application" else "FORM & FIELD"
            brand_pos = "Independent architecture and interior design studio crafting timeless spaces with sustainable materials, monolithic form, and serene spatial balance."
            target_aud = "Discerning residential and commercial clients, developers, and architectural enthusiasts."
            req_content = ["architectural portfolio", "sustainable design philosophy", "project details modal", "consultation enquiry"]
            req_vis = "Warm ivory, charcoal, and muted olive color palette. Monolithic typography, expansive architectural photography, tactile materiality."

            components = [
                ComponentContract(id="navbar", name="Studio Navigation Header", tag="header", required_classes=["site-header", "navbar"]),
                ComponentContract(id="hero", name="Architectural Hero Statement", tag="section", required_classes=["hero", "hero-content"]),
                ComponentContract(id="philosophy", name="Sustainable Design Philosophy", tag="section", required_classes=["container", "about-section"]),
                ComponentContract(
                    id="portfolio",
                    name="Curated Project Portfolio",
                    tag="section",
                    required_classes=["portfolio-section"],
                    rendering_ownership="dynamic",
                    render_target_id="portfolio-grid",
                    data_sources=["projects_data"],
                ),
                ComponentContract(id="services", name="Studio Disciplines & Services", tag="section", required_classes=["container", "services-section"]),
                ComponentContract(id="contact", name="Consultation & Inquiries", tag="section", required_classes=["container", "contact-section"]),
                ComponentContract(id="consultation-form", name="Consultation Request Form", tag="form", required_classes=["consultation-form"], is_form=True),
                ComponentContract(id="project-modal", name="Project Inspection Modal", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
                ComponentContract(id="footer", name="Studio Footer", tag="footer", required_classes=["site-footer"]),
            ]

            dom_state = DomAndStateContract(
                required_static_ids=[
                    "navbar", "hero", "philosophy", "portfolio", "portfolio-grid",
                    "project-search", "category-filters", "services",
                    "contact", "consultation-form", "project-modal", "modal-close", "mobile-menu-btn",
                ],
                required_static_classes=[
                    "site-header", "hero", "project-card", "filter-pill",
                    "modal-overlay", "site-footer", "btn-primary",
                ],
                dynamic_ids=["portfolio-grid"],
                dynamic_classes=["active", "open", "hidden"],
                data_attributes=["data-category", "data-project-id"],
                event_handlers=[
                    {"target": "#project-search", "event": "input", "action": "filterProjects"},
                    {"target": ".filter-pill", "event": "click", "action": "filterByCategory"},
                    {"target": ".btn-project-details", "event": "click", "action": "openProjectModal"},
                    {"target": "#modal-close", "event": "click", "action": "closeProjectModal"},
                    {"target": "#consultation-form", "event": "submit", "action": "submitConsultation"},
                ],
                interactions=[
                    {
                        "trigger": "Category filter pill click",
                        "expected_state_change": "Filters portfolio projects by category",
                        "expected_result": "Displays matching architectural project cards",
                    },
                    {
                        "trigger": "Search input typing",
                        "expected_state_change": "Searches projects in real time by name, material, or location",
                        "expected_result": "Live DOM update of portfolio grid",
                    },
                    {
                        "trigger": "Project card click",
                        "expected_state_change": "Opens project modal with specifications and materials",
                        "expected_result": "Modal dialog opens with focus trapped",
                    },
                    {
                        "trigger": "Consultation form submit",
                        "expected_state_change": "Validates inputs and displays demonstration confirmation",
                        "expected_result": "Feedback message displayed without misleading claims",
                    },
                ],
            )

            tokens = {
                "--primary-color": "#1c1d21",
                "--secondary-color": "#556b2f",
                "--accent-color": "#8c7b65",
                "--bg-main": "#fbf9f5",
                "--bg-card": "#ffffff",
                "--text-primary": "#1c1d21",
                "--text-secondary": "#6b7280",
                "--border-color": "#e5e2da",
                "--radius-sm": "4px",
                "--radius-md": "8px",
                "--radius-lg": "12px",
                "--shadow-card": "0 4px 20px -2px rgba(28, 29, 33, 0.06)",
            }
            if design_brief and hasattr(design_brief, "color_palette"):
                for k, v in getattr(design_brief, "color_palette", {}).items():
                    tokens[f"--{k}"] = v

            css = CssContract(
                design_tokens=tokens,
                layout_strategy="responsive_grid_flex",
                component_selectors=[
                    ".site-header", ".navbar", ".hero", ".project-card", ".portfolio-grid",
                    ".filter-pill", ".modal-overlay", ".site-footer", ".consultation-form",
                ],
                responsive_breakpoints=["768px", "1024px"],
            )

            js = JavaScriptContract(
                authoritative_entrypoint="app.js",
                secondary_modules=[],
                state_management="vanilla_store",
                rendering_functions=["renderProjects", "openProjectModal", "closeProjectModal", "filterProjects", "submitConsultation"],
            )

            assets = [
                AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-architecture.jpg", alt_text="Monolithic modern architecture studio facade"),
                AssetContractItem(intended_component="project-1", relative_path="assets/images/projects/pavilion.jpg", alt_text="The Monolith Pavilion"),
                AssetContractItem(intended_component="project-2", relative_path="assets/images/projects/sanctuary.jpg", alt_text="Highland Minimalist Sanctuary"),
                AssetContractItem(intended_component="project-3", relative_path="assets/images/projects/villa.jpg", alt_text="Olive Grove Villa"),
                AssetContractItem(intended_component="project-4", relative_path="assets/images/projects/loft.jpg", alt_text="Obsidian Urban Loft"),
                AssetContractItem(intended_component="project-5", relative_path="assets/images/projects/gallery.jpg", alt_text="Kyoto Timber Gallery"),
                AssetContractItem(intended_component="project-6", relative_path="assets/images/projects/eco-residence.jpg", alt_text="Dune Eco-Residence"),
            ]

            return FrontendImplementationContract(
                version=1,
                mission_id=mission_id,
                app_name=app_name,
                business_domain="architecture_interior",
                cuisine_subtype="",
                brand_positioning=brand_pos,
                target_audience=target_aud,
                requested_content=req_content,
                requested_visual_direction=req_vis,
                architecture=arch,
                components=components,
                dom_and_state=dom_state,
                css=css,
                javascript=js,
                assets=assets,
            )

        # ------------------------------------------------------------------
        # 4. VETERINARY & PET CARE CLINIC DOMAIN
        # ------------------------------------------------------------------
        if ("paws & claws" in task_clean_lower) or ("paws and claws" in task_clean_lower):
            app_name = detected_brand if detected_brand != "Application" else "Paws & Claws Veterinary Clinic"
            brand_pos = "Comprehensive pet wellness, advanced surgical care, and compassionate veterinary services."
            target_aud = "Pet owners, animal lovers, and companion caregivers."
            req_content = ["clinical services", "wellness plans", "pet care modal", "appointment booking"]
            req_vis = "Clinical teal, friendly mint, and warm amber accents. Compassionate, welcoming, modern healthcare aesthetic."

            components = [
                ComponentContract(id="navbar", name="Clinic Navigation Header", tag="header", required_classes=["site-header", "navbar"]),
                ComponentContract(id="hero", name="Compassionate Care Hero", tag="section", required_classes=["hero", "hero-content"]),
                ComponentContract(id="about", name="Our Medical Philosophy & Team", tag="section", required_classes=["container", "about-section"]),
                ComponentContract(
                    id="services",
                    name="Veterinary Services & Specialties",
                    tag="section",
                    required_classes=["services-section"],
                    rendering_ownership="dynamic",
                    render_target_id="services-grid",
                    data_sources=["services_data"],
                ),
                ComponentContract(id="contact", name="Appointments & Inquiries", tag="section", required_classes=["container", "contact-section"]),
                ComponentContract(id="appointment-form", name="Appointment Booking Form", tag="form", required_classes=["appointment-form"], is_form=True),
                ComponentContract(id="care-modal", name="Service Detail Inspection Modal", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
                ComponentContract(id="footer", name="Clinic Footer", tag="footer", required_classes=["site-footer"]),
            ]

            dom_state = DomAndStateContract(
                required_static_ids=[
                    "navbar", "hero", "about", "services", "services-grid",
                    "service-search", "category-filters",
                    "contact", "appointment-form", "care-modal", "modal-close", "mobile-menu-btn",
                ],
                required_static_classes=[
                    "site-header", "hero", "service-card", "filter-pill",
                    "modal-overlay", "site-footer", "btn-primary",
                ],
                dynamic_ids=["services-grid"],
                dynamic_classes=["active", "open", "hidden"],
                data_attributes=["data-category", "data-service-id"],
                event_handlers=[
                    {"target": "#service-search", "event": "input", "action": "filterServices"},
                    {"target": ".filter-pill", "event": "click", "action": "filterByCategory"},
                    {"target": ".btn-service-details", "event": "click", "action": "openCareModal"},
                    {"target": "#modal-close", "event": "click", "action": "closeCareModal"},
                    {"target": "#appointment-form", "event": "submit", "action": "submitAppointment"},
                ],
            )

            tokens = {
                "--primary-color": "#0f766e",
                "--secondary-color": "#14b8a6",
                "--accent-color": "#f59e0b",
                "--bg-main": "#f0fdfa",
                "--bg-card": "#ffffff",
                "--text-primary": "#134e4a",
                "--text-secondary": "#475569",
                "--border-color": "#ccfbf1",
                "--radius-sm": "6px",
                "--radius-md": "10px",
                "--radius-lg": "16px",
                "--shadow-card": "0 4px 15px rgba(15, 118, 110, 0.08)",
            }
            if design_brief and hasattr(design_brief, "color_palette"):
                for k, v in getattr(design_brief, "color_palette", {}).items():
                    tokens[f"--{k}"] = v

            css = CssContract(
                design_tokens=tokens,
                layout_strategy="responsive_grid_flex",
                component_selectors=[
                    ".site-header", ".navbar", ".hero", ".service-card", ".services-grid",
                    ".filter-pill", ".modal-overlay", ".site-footer", ".appointment-form",
                ],
                responsive_breakpoints=["768px", "1024px"],
            )

            js = JavaScriptContract(
                authoritative_entrypoint="app.js",
                rendering_functions=["renderServices", "openCareModal", "closeCareModal", "filterServices", "submitAppointment"],
            )

            assets = [
                AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-vet.jpg", alt_text="Compassionate veterinarian with happy pet"),
                AssetContractItem(intended_component="service-1", relative_path="assets/images/services/wellness.jpg", alt_text="Preventive Pet Wellness"),
                AssetContractItem(intended_component="service-2", relative_path="assets/images/services/surgery.jpg", alt_text="Advanced Veterinary Surgery"),
                AssetContractItem(intended_component="service-3", relative_path="assets/images/services/dental.jpg", alt_text="Pet Dental Healthcare"),
            ]

            return FrontendImplementationContract(
                version=1,
                mission_id=mission_id,
                app_name=app_name,
                business_domain="veterinary_pet_care",
                cuisine_subtype="",
                brand_positioning=brand_pos,
                target_audience=target_aud,
                requested_content=req_content,
                requested_visual_direction=req_vis,
                architecture=arch,
                components=components,
                dom_and_state=dom_state,
                css=css,
                javascript=js,
                assets=assets,
            )

        # ------------------------------------------------------------------
        # 5. UNIVERSAL PROMPT-DERIVED DOMAIN (Any Unseen / Future Industry)
        # ------------------------------------------------------------------
        if detected_brand != "Application":
            app_name = detected_brand
        elif len(task.strip().split()) <= 4 and not any(w in task.lower() for w in ["build", "create", "website", "generate"]):
            app_name = task.strip()
        else:
            app_name = domain.replace("_", " ").title() if domain != "modern_editorial" else "Modern Web Studio"
        business_domain = domain if domain != "modern_editorial" else "general"

        tokens = {
            "--primary-color": "#1e293b",
            "--secondary-color": "#334155",
            "--accent-color": "#2563eb",
            "--bg-main": "#f8fafc",
            "--bg-card": "#ffffff",
            "--text-primary": "#0f172a",
            "--text-secondary": "#475569",
            "--border-color": "#e2e8f0",
            "--radius-sm": "6px",
            "--radius-md": "10px",
            "--radius-lg": "14px",
            "--shadow-card": "0 4px 15px rgba(0, 0, 0, 0.06)",
        }
        if design_brief and hasattr(design_brief, "color_palette"):
            for k, v in getattr(design_brief, "color_palette", {}).items():
                tokens[f"--{k}"] = v

        components = [
            ComponentContract(id="navbar", name="Navigation Bar", tag="header", required_classes=["site-header", "navbar"]),
            ComponentContract(id="hero", name="Hero Section", tag="section", required_classes=["hero", "hero-content"]),
            ComponentContract(
                id="showcase",
                name="Domain Showcase Grid",
                tag="section",
                required_classes=["showcase-section"],
                rendering_ownership="dynamic",
                render_target_id="showcase-grid",
                data_sources=["showcase_data"],
            ),
            ComponentContract(id="about", name="About & Core Values", tag="section", required_classes=["container", "about-section"]),
            ComponentContract(id="contact", name="Inquiries & Booking", tag="section", required_classes=["container", "contact-section"]),
            ComponentContract(id="inquiry-form", name="Inquiry Form", tag="form", required_classes=["inquiry-form"], is_form=True),
            ComponentContract(id="details-modal", name="Inspection Modal", tag="div", required_classes=["modal-overlay", "modal-dialog"], is_modal=True),
            ComponentContract(id="footer", name="Site Footer", tag="footer", required_classes=["site-footer"]),
        ]

        dom_state = DomAndStateContract(
            required_static_ids=[
                "navbar", "hero", "showcase", "showcase-grid",
                "showcase-search", "category-filters",
                "about", "contact", "inquiry-form", "details-modal", "modal-close", "mobile-menu-btn",
            ],
            required_static_classes=["site-header", "hero", "showcase-card", "filter-pill", "modal-overlay", "site-footer", "btn-primary"],
            dynamic_ids=["showcase-grid"],
            dynamic_classes=["active", "open", "hidden"],
            data_attributes=["data-category", "data-item-id"],
            event_handlers=[
                {"target": "#showcase-search", "event": "input", "action": "filterItems"},
                {"target": ".filter-pill", "event": "click", "action": "filterByCategory"},
                {"target": ".btn-details", "event": "click", "action": "openModal"},
                {"target": "#modal-close", "event": "click", "action": "closeModal"},
                {"target": "#inquiry-form", "event": "submit", "action": "submitInquiry"},
            ],
        )

        css = CssContract(
            design_tokens=tokens,
            layout_strategy="responsive_grid_flex",
            component_selectors=[".site-header", ".navbar", ".hero", ".showcase-card", ".showcase-grid", ".filter-pill", ".modal-overlay", ".site-footer"],
            responsive_breakpoints=["768px", "1024px"],
        )

        js = JavaScriptContract(
            authoritative_entrypoint="app.js",
            rendering_functions=["renderShowcase", "openModal", "closeModal", "filterItems", "submitInquiry"],
        )

        assets = [
            AssetContractItem(intended_component="hero", relative_path="assets/images/hero/hero-main.jpg", alt_text=f"Cinematic imagery representing {app_name}"),
        ]

        return FrontendImplementationContract(
            version=1,
            mission_id=mission_id,
            app_name=app_name,
            business_domain=business_domain,
            cuisine_subtype="",
            brand_positioning=f"Authoritative web presence for {app_name}.",
            target_audience="General audience and prospective clients",
            requested_content=["hero showcase", "interactive catalog", "detail modal", "validated enquiry form"],
            requested_visual_direction="Balanced layout, prompt-aligned color palette, responsive design",
            architecture=arch,
            components=components,
            dom_and_state=dom_state,
            css=css,
            javascript=js,
            assets=assets,
        )

    @classmethod
    def reconcile_from_html(
        cls,
        contract: FrontendImplementationContract,
        html_text: str,
    ) -> FrontendImplementationContract:
        """
        Reconcile contract with actual HTML markup generated on disk.
        Extracts actual IDs, classes, script references, and forms,
        updating the contract version while preserving architecture invariants.
        """
        import re

        # Extract IDs
        found_ids = set(re.findall(r'\bid=["\']([a-zA-Z0-9_\-]+)["\']', html_text))
        if found_ids:
            contract.dom_and_state.required_static_ids = sorted(list(set(contract.dom_and_state.required_static_ids) | found_ids))

        # Extract script sources
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_text, re.I)
        if scripts:
            # Set the first non-vendor script as authoritative
            local_scripts = [s for s in scripts if not s.startswith("http")]
            if local_scripts:
                contract.architecture.authoritative_script = local_scripts[0]
                contract.javascript.authoritative_entrypoint = local_scripts[0]
                if len(local_scripts) > 1:
                    contract.javascript.secondary_modules = local_scripts[1:]

        # Extract classes
        classes_set = set()
        for cm in re.findall(r'\bclass=["\']([^"\']+)["\']', html_text):
            for c in cm.split():
                if c.strip():
                    classes_set.add(c.strip())
        if classes_set:
            contract.dom_and_state.required_static_classes = sorted(list(classes_set))

        contract.update_version()
        return contract


build_initial_contract = FrontendContractBuilder.build_initial_contract
