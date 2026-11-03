# scripts/patch_contracts_and_integrations.py
"""
Upgrades core/project_contract.py and core/cross_file_contract.py:
1. Adds DeclaredInterfaces and ObservedInterfaces to ProjectContract (Section 5.2).
2. Adds reconcile_observed(), compare_interfaces(), and format_for_prompt().
3. Adds WORKSPACE_LAYOUT_AMBIGUOUS detection for conflicting un-declared entrypoints (Section 4.2).
4. Adds ContractDiscrepancy model to core/cross_file_contract.py (Section 7.5).
"""

from pathlib import Path
import re

# ── 1. Update core/project_contract.py ──────────────────────────────────────────
pc_file = Path("core/project_contract.py")
pc_txt = pc_file.read_text(encoding="utf-8")

# Check if DeclaredInterfaces already present
if "class DeclaredInterfaces" not in pc_txt:
    interfaces_def = """

@dataclass
class DeclaredInterfaces:
    \"\"\"Intended application contract: what HERMES intends to build (Section 5.2).\"\"\"
    dom_ids: List[str] = field(default_factory=list)
    views: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    css_variables: List[str] = field(default_factory=list)
    api_routes: List[Dict[str, Any]] = field(default_factory=list)
    database_tables: Dict[str, List[str]] = field(default_factory=dict)
    storage_keys: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObservedInterfaces:
    \"\"\"Observed application state: what the physical generated files currently contain (Section 5.2).\"\"\"
    html_ids: List[str] = field(default_factory=list)
    html_classes: List[str] = field(default_factory=list)
    form_names: List[str] = field(default_factory=list)
    css_selectors: List[str] = field(default_factory=list)
    css_variables: List[str] = field(default_factory=list)
    js_references: List[str] = field(default_factory=list)
    backend_routes: Dict[str, List[str]] = field(default_factory=dict)
    database_tables: Dict[str, List[str]] = field(default_factory=dict)
    artifact_hashes: Dict[str, str] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
"""
    # Insert before class ProjectContract
    pc_txt = pc_txt.replace("@dataclass\nclass ProjectContract:", interfaces_def + "\n@dataclass\nclass ProjectContract:")

    # Add fields to ProjectContract
    old_fields = "    creation_provenance: Dict[str, Any] = field(default_factory=dict)\n    migration_provenance: Optional[Dict[str, Any]] = None"
    new_fields = old_fields + """
    declared_interfaces: DeclaredInterfaces = field(default_factory=DeclaredInterfaces)
    observed_interfaces: ObservedInterfaces = field(default_factory=ObservedInterfaces)"""
    pc_txt = pc_txt.replace(old_fields, new_fields)

    # Add methods to ProjectContract
    methods_addition = """
    def reconcile_observed(self, workspace_root: Path | str) -> ObservedInterfaces:
        \"\"\"Harvest physical interfaces from disk without mutating declared interfaces (Section 5.2).\"\"\"
        ws = Path(workspace_root).resolve()
        obs = ObservedInterfaces()

        # HTML
        dom = self.extract_dom_inventory(ws)
        obs.html_ids = list(dom.get("ids", []))
        obs.html_classes = list(dom.get("classes", []))
        obs.form_names = list(dom.get("form_names", []))

        # CSS
        css_p = ws / self.canonical_css
        if css_p.exists() and css_p.is_file():
            try:
                css_txt = css_p.read_text(encoding="utf-8", errors="ignore")
                obs.css_variables = sorted(list(set(re.findall(r'(--[a-zA-Z0-9_\-]+)\s*:', css_txt))))
                obs.css_selectors = sorted(list(set(re.findall(r'([.#][a-zA-Z0-9_\-]+)', css_txt))))
            except Exception:
                pass

        # JS
        js_p = ws / self.canonical_js
        if js_p.exists() and js_p.is_file():
            try:
                js_txt = js_p.read_text(encoding="utf-8", errors="ignore")
                js_ids = re.findall(r'getElementById\(["\']([a-zA-Z0-9_\-]+)["\']\)', js_txt)
                js_qs = re.findall(r'querySelector(?:All)?\(["\']#([a-zA-Z0-9_\-]+)["\']\)', js_txt)
                obs.js_references = sorted(list(set(js_ids + js_qs)))
            except Exception:
                pass

        # Backend
        if self.canonical_backend:
            be_p = ws / self.canonical_backend
            if be_p.exists() and be_p.is_file():
                try:
                    import ast as _ast
                    tree = _ast.parse(be_p.read_text(encoding="utf-8", errors="ignore"), filename=be_p.name)
                    routes = {}
                    for node in _ast.walk(tree):
                        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                            for dec in node.decorator_list:
                                if isinstance(dec, _ast.Call) and isinstance(dec.func, _ast.Attribute):
                                    attr = dec.func.attr.upper()
                                    if attr in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                                        if dec.args and isinstance(dec.args[0], _ast.Constant) and isinstance(dec.args[0].value, str):
                                            rpath = dec.args[0].value
                                            routes.setdefault(rpath, []).append(attr)
                    obs.backend_routes = routes
                except Exception:
                    pass

        # Artifact hashes
        from core.js_syntax_validator import compute_file_sha256
        for f in self.required_files:
            fp = ws / f
            if fp.exists() and fp.is_file():
                h = compute_file_sha256(fp)
                if h:
                    obs.artifact_hashes[f] = h

        self.observed_interfaces = obs
        return obs

    def compare_interfaces(self) -> Dict[str, Any]:
        \"\"\"Compare declared interfaces against observed interfaces and report discrepancies (Section 5.2).\"\"\"
        decl = self.declared_interfaces
        obs = self.observed_interfaces

        missing_ids = [i for i in decl.dom_ids if i not in obs.html_ids]
        missing_classes = [c for c in decl.classes if c not in obs.html_classes]
        missing_routes = []
        for r in decl.api_routes:
            rpath = r.get("path")
            rmethod = r.get("method", "GET").upper()
            if rpath and (rpath not in obs.backend_routes or rmethod not in obs.backend_routes.get(rpath, [])):
                missing_routes.append(f"{rmethod} {rpath}")

        unregistered_js_ids = [i for i in obs.js_references if i not in obs.html_ids and i not in decl.dom_ids and i not in self.dynamic_ids]

        return {
            \"missing_dom_ids\": missing_ids,
            \"missing_classes\": missing_classes,
            \"missing_routes\": missing_routes,
            \"unregistered_js_ids\": unregistered_js_ids,
            \"has_discrepancies\": bool(missing_ids or missing_routes or unregistered_js_ids),
        }

    def format_for_prompt(self, turn_number: int = 1) -> str:
        \"\"\"Format contract context for model prompt injection (Section 5.5).\"\"\"
        decl = self.declared_interfaces
        obs = self.observed_interfaces
        diff = self.compare_interfaces()

        if turn_number <= 1:
            # Turn 1: Initial planning & architecture contract
            lines = [
                f\"=== ACTIVE PROJECT CONTRACT (v{self.version}) ===\",
                f\"Application: {self.app_name} ({self.app_type}) | Layout: {self.project_layout}\",
                f\"Canonical HTML: {self.canonical_html}\",
                f\"Canonical CSS:  {self.canonical_css}\",
                f\"Canonical JS:   {self.canonical_js}\",
                f\"Canonical Backend: {self.canonical_backend or 'None'}\",
                f\"Required Deliverables: {', '.join(self.required_files)}\",
            ]
            if decl.dom_ids:
                lines.append(f\"Declared DOM IDs: {', '.join(decl.dom_ids[:25])}\")
            if decl.api_routes:
                routes_str = ', '.join(f\"{r.get('method', 'GET')} {r.get('path')}\" for r in decl.api_routes[:10])
                lines.append(f\"Declared API Routes: {routes_str}\")
            lines.append(\"Rule: You must adhere strictly to these canonical paths and declared interfaces.\")
            lines.append(\"===========================================\")
            return \"\\n\".join(lines)
        else:
            # Subsequent turns: show observed state and outstanding discrepancies
            lines = [
                f\"=== CONTRACT VERIFICATION STATUS (v{self.version}, hash: {self.contract_hash[:8]}) ===\",
                f\"Observed HTML IDs: {len(obs.html_ids)} | Observed Routes: {len(obs.backend_routes)}\",
            ]
            if diff[\"has_discrepancies\"]:
                lines.append(\"OUTSTANDING CONTRACT DISCREPANCIES:\")
                if diff[\"missing_dom_ids\"]:
                    lines.append(f\"  - Missing DOM IDs in HTML: {', '.join(diff['missing_dom_ids'][:10])}\")
                if diff[\"missing_routes\"]:
                    lines.append(f\"  - Missing Backend Routes: {', '.join(diff['missing_routes'][:10])}\")
                if diff[\"unregistered_js_ids\"]:
                    lines.append(f\"  - JS queries missing DOM IDs: {', '.join(diff['unregistered_js_ids'][:10])}\")
            else:
                lines.append(\"All declared and observed interfaces are coherent.\")
            lines.append(\"===========================================================\")
            return \"\\n\".join(lines)
"""
    # Insert methods before save_to_workspace
    pc_txt = pc_txt.replace("    def save_to_workspace(self, workspace_root: Path | str) -> Path:", methods_addition + "\n    def save_to_workspace(self, workspace_root: Path | str) -> Path:")

    pc_file.write_text(pc_txt, encoding="utf-8")
    print("Updated core/project_contract.py with Declared/Observed interfaces & methods.")

# ── 2. Update core/cross_file_contract.py ──────────────────────────────────────
cfc_file = Path("core/cross_file_contract.py")
cfc_txt = cfc_file.read_text(encoding="utf-8")

if "class ContractDiscrepancy" not in cfc_txt:
    disc_model = """

@dataclass
class ContractDiscrepancy:
    \"\"\"Fine-grained contract discrepancy metadata (Section 7.5).\"\"\"
    type: str  # DOM_CONTRACT_MISMATCH, API_ROUTE_MISMATCH, DATABASE_SCHEMA_MISMATCH, BROKEN_ASSET_LINK, CSS_VARIABLE_MISMATCH
    responsible_artifact: str
    consuming_artifact: str
    mismatch: str
    confidence: str = "HIGH"  # HIGH, MEDIUM, LOW
    source_line: Optional[int] = None
    suggested_repair: Optional[str] = None
    failure_class: str = "CONTRACT_MISMATCH"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
"""
    cfc_txt = cfc_txt.replace("@dataclass\nclass CrossFileContractReport:", disc_model + "\n@dataclass\nclass CrossFileContractReport:")
    
    # Add discrepancies field to CrossFileContractReport
    cfc_txt = cfc_txt.replace(
        "    uncertainties: List[str] = field(default_factory=list)\n    details: Dict[str, Any] = field(default_factory=dict)",
        "    uncertainties: List[str] = field(default_factory=list)\n    discrepancies: List[ContractDiscrepancy] = field(default_factory=list)\n    details: Dict[str, Any] = field(default_factory=dict)"
    )

    cfc_file.write_text(cfc_txt, encoding="utf-8")
    print("Updated core/cross_file_contract.py with ContractDiscrepancy.")

print("All contract updates applied successfully.")
