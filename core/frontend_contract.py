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
            "Modal & Form Contract: #booking-modal dialog with #modal-close button and backdrop click dismissal. .book-now-btn opens modal with selected package details. #booking-form validates inputs and displays confirmation feedback with clear demo mode notice.",
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
        """Generate initial contract before implementation starts."""
        task_lower = task.lower()
        if "wanderworld" in task_lower:
            app_name = "WanderWorld"
        elif "aether" in task_lower:
            app_name = "Aether Orbital"
        elif len(task) < 40 and not any(k in task_lower for k in ("create ", "build ", "make ", "generate ")):
            app_name = task
        else:
            app_name = "Application"

        # Determine architecture
        arch = ArchitectureContract(
            project_type="vanilla_web",
            technology_stack=["html5", "css3", "javascript"],
            entrypoint="index.html",
            authoritative_script="app.js",
            authoritative_style="style.css",
        )

        # Standard components
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

        # DOM and State
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

        # CSS tokens from design brief if available
        tokens = {
            "--primary-color": "#2563eb",
            "--secondary-color": "#0f172a",
            "--accent-color": "#f59e0b",
            "--bg-color": "#f8fafc",
            "--card-bg": "#ffffff",
            "--text-primary": "#1e293b",
            "--text-secondary": "#64748b",
            "--font-main": "system-ui, -apple-system, sans-serif",
            "--radius-sm": "0.375rem",
            "--radius-md": "0.5rem",
            "--radius-lg": "1rem",
            "--shadow-md": "0 4px 6px -1px rgb(0 0 0 / 0.1)",
        }
        if design_brief and hasattr(design_brief, "color_palette"):
            pal = getattr(design_brief, "color_palette", {})
            if "primary" in pal: tokens["--primary-color"] = pal["primary"]
            if "background" in pal: tokens["--bg-color"] = pal["background"]
            if "text" in pal: tokens["--text-primary"] = pal["text"]
            if "accent" in pal: tokens["--accent-color"] = pal["accent"]

        css = CssContract(
            design_tokens=tokens,
            layout_strategy="responsive_grid_flex",
            component_selectors=[
                ".navbar", ".hero", ".card", ".destination-card", ".package-card",
                ".grid", ".cards-grid", ".modal", ".form-control", ".btn",
            ],
            responsive_breakpoints=["768px", "1024px"],
        )

        # JS Contract
        js = JavaScriptContract(
            authoritative_entrypoint="app.js",
            secondary_modules=[],
            state_management="vanilla_store",
            rendering_functions=["renderDestinations", "renderPackages", "openModal", "closeModal", "filterCards"],
        )

        # Assets
        assets = [
            AssetContractItem(intended_component="hero", relative_path="assets/hero.jpg", alt_text="Cinematic travel landscape"),
            AssetContractItem(intended_component="destination-bali", relative_path="assets/dest_bali.jpg", alt_text="Tropical beaches of Bali"),
            AssetContractItem(intended_component="destination-paris", relative_path="assets/dest_paris.jpg", alt_text="Historic architecture of Paris"),
            AssetContractItem(intended_component="destination-tokyo", relative_path="assets/dest_tokyo.jpg", alt_text="Modern city of Tokyo"),
            AssetContractItem(intended_component="destination-swiss", relative_path="assets/dest_swiss.jpg", alt_text="Snow-capped Swiss Alps"),
        ]

        return FrontendImplementationContract(
            version=1,
            mission_id=mission_id,
            app_name=app_name,
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
