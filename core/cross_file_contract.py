# core/cross_file_contract.py
"""
Cross-File Contract Validation for HERMES 2.x (Prompt 13 & Final Contract-First Repair).
Validates cross-file coherence across all deliverables:
1. Route alignment (frontend fetch vs backend routes, including Node/Express and Python/FastAPI)
2. Response envelope shape alignment (backend JSON shape vs frontend consumption: object envelope vs raw array)
3. HTML asset paths (script src and link href existence)
4. Browser JavaScript module graph (script type="module", import/export consistency, no Node-CommonJS mixing)
5. Central API client contract (method existence on API client object)
6. HTML form, database enum, and request contract (direction enum casing, required request fields)
7. Jest / Supertest and server export contract (destructured app export vs request(app))
8. DOM contract alignment (HTML IDs vs JavaScript references, dynamic tracking controls)
9. CSS class alignment (HTML classes vs CSS stylesheet)
10. Database schema alignment (SQLite table/column presence vs contract)
11. Startup configuration (package.json vs backend file)
"""

from __future__ import annotations

import ast
import json
import logging
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("hermes.cross_file_contract")

# Severity Constants
SEV_PASS = "PASS"
SEV_WARNING = "WARNING"
SEV_FAIL = "FAIL"
SEV_UNVERIFIED = "UNVERIFIED"


@dataclass
class ContractDiscrepancy:
    """Fine-grained contract discrepancy metadata."""
    type: str  # BROWSER_MODULE_TYPE_MISMATCH, MISSING_IMPORTED_EXPORT, API_CLIENT_METHOD_MISSING, API_RESPONSE_SHAPE_MISMATCH, DATABASE_ENUM_CONTRACT_MISMATCH, REQUEST_FIELD_CONTRACT_MISMATCH, DOM_REFERENCE_MISMATCH, TEST_SERVER_EXPORT_MISMATCH, DOM_CONTRACT_MISMATCH, API_ROUTE_MISMATCH, DATABASE_SCHEMA_MISMATCH, BROKEN_ASSET_LINK, CSS_VARIABLE_MISMATCH
    responsible_artifact: str
    consuming_artifact: str
    mismatch: str
    confidence: str = "HIGH"  # HIGH, MEDIUM, LOW
    source_line: Optional[int] = None
    suggested_repair: Optional[str] = None
    failure_class: str = "CONTRACT_MISMATCH"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrossFileContractReport:
    """Structured report documenting cross-file contract coherence across deliverables."""
    valid: bool
    severity: str = SEV_PASS
    endpoint_mismatches: List[str] = field(default_factory=list)
    response_shape_mismatches: List[str] = field(default_factory=list)
    html_asset_mismatches: List[str] = field(default_factory=list)
    dom_id_mismatches: List[str] = field(default_factory=list)
    css_mismatches: List[str] = field(default_factory=list)
    database_mismatches: List[str] = field(default_factory=list)
    startup_mismatches: List[str] = field(default_factory=list)
    module_graph_mismatches: List[str] = field(default_factory=list)
    api_client_mismatches: List[str] = field(default_factory=list)
    form_enum_mismatches: List[str] = field(default_factory=list)
    test_export_mismatches: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    uncertainties: List[str] = field(default_factory=list)
    discrepancies: List[ContractDiscrepancy] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_issues(self) -> int:
        return (
            len(self.endpoint_mismatches) +
            len(self.response_shape_mismatches) +
            len(self.html_asset_mismatches) +
            len(self.dom_id_mismatches) +
            len(self.css_mismatches) +
            len(self.database_mismatches) +
            len(self.startup_mismatches) +
            len(self.module_graph_mismatches) +
            len(self.api_client_mismatches) +
            len(self.form_enum_mismatches) +
            len(self.test_export_mismatches)
        )

    @property
    def summary(self) -> str:
        if self.valid:
            warn_msg = f" ({len(self.warnings)} warning(s))" if self.warnings else ""
            unc_msg = f" ({len(self.uncertainties)} uncertainty notice(s))" if self.uncertainties else ""
            return f"[{self.severity}] Cross-file contracts verified and coherent{warn_msg}{unc_msg}."
        
        parts = []
        if self.module_graph_mismatches:
            parts.append(f"{len(self.module_graph_mismatches)} module graph errors")
        if self.api_client_mismatches:
            parts.append(f"{len(self.api_client_mismatches)} API client errors")
        if self.response_shape_mismatches:
            parts.append(f"{len(self.response_shape_mismatches)} response shape mismatches")
        if self.form_enum_mismatches:
            parts.append(f"{len(self.form_enum_mismatches)} form/DB enum mismatches")
        if self.test_export_mismatches:
            parts.append(f"{len(self.test_export_mismatches)} test export mismatches")
        if self.endpoint_mismatches:
            parts.append(f"{len(self.endpoint_mismatches)} route mismatches")
        if self.html_asset_mismatches:
            parts.append(f"{len(self.html_asset_mismatches)} broken asset paths")
        if self.dom_id_mismatches:
            parts.append(f"{len(self.dom_id_mismatches)} DOM ID mismatches")
        if self.database_mismatches:
            parts.append(f"{len(self.database_mismatches)} database mismatches")
        if self.startup_mismatches:
            parts.append(f"{len(self.startup_mismatches)} startup mismatches")

        return f"[{self.severity}] Cross-file contract violations detected: {self.total_issues} issue(s) ({', '.join(parts)})."


class CrossFileContractValidator:
    """Performs static cross-file contract analysis."""

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()

    def validate(self, current_phase: Optional[str] = None) -> CrossFileContractReport:
        return self.validate_workspace(self.workspace_root, current_phase=current_phase)

    def validate_all(self, current_phase: Optional[str] = None) -> Dict[str, Any]:
        report = self.validate(current_phase=current_phase)
        return {
            "valid": report.valid,
            "severity": report.severity,
            "has_hard_errors": not report.valid,
            "total_issues": report.total_issues,
            "endpoint_mismatches": report.endpoint_mismatches,
            "response_shape_mismatches": report.response_shape_mismatches,
            "html_asset_mismatches": report.html_asset_mismatches,
            "dom_id_mismatches": report.dom_id_mismatches,
            "css_mismatches": report.css_mismatches,
            "database_mismatches": report.database_mismatches,
            "startup_mismatches": report.startup_mismatches,
            "module_graph_mismatches": report.module_graph_mismatches,
            "api_client_mismatches": report.api_client_mismatches,
            "form_enum_mismatches": report.form_enum_mismatches,
            "test_export_mismatches": report.test_export_mismatches,
            "warnings": report.warnings,
            "uncertainties": report.uncertainties,
            "hard_errors": (
                report.endpoint_mismatches
                + report.response_shape_mismatches
                + report.html_asset_mismatches
                + report.dom_id_mismatches
                + report.database_mismatches
                + report.startup_mismatches
                + report.module_graph_mismatches
                + report.api_client_mismatches
                + report.form_enum_mismatches
                + report.test_export_mismatches
            ),
            "discrepancies": [d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in report.discrepancies],
            "details": report.details,
            "summary": report.summary,
        }

    @classmethod
    def validate_workspace(
        cls,
        workspace_root: Path | str,
        current_phase: Optional[str] = None,
    ) -> CrossFileContractReport:
        ws = Path(workspace_root).resolve()
        endpoint_mismatches: List[str] = []
        response_shape_mismatches: List[str] = []
        html_asset_mismatches: List[str] = []
        dom_id_mismatches: List[str] = []
        css_mismatches: List[str] = []
        database_mismatches: List[str] = []
        startup_mismatches: List[str] = []
        module_graph_mismatches: List[str] = []
        api_client_mismatches: List[str] = []
        form_enum_mismatches: List[str] = []
        test_export_mismatches: List[str] = []
        warnings: List[str] = []
        uncertainties: List[str] = []
        discrepancies: List[ContractDiscrepancy] = []
        details: Dict[str, Any] = {}

        # 1. Locate Primary Files using ProjectContract or disk layout
        from core.project_contract import ProjectContract
        contract = ProjectContract.create_or_load(ws)

        # Backend candidates (Python and Node/Express)
        be_candidates = [
            ws / contract.canonical_backend if contract.canonical_backend else None,
            ws / "server.js",
            ws / "main.py",
            ws / "app.py",
            ws / "server.py",
            ws / "app.js" if (ws / "package.json").exists() and not (ws / "index.html").exists() else None,
        ]
        be_file = next((f for f in be_candidates if f and f.exists() and f.stat().st_size > 20), None)

        # HTML entrypoint
        html_file = ws / contract.canonical_html if (ws / contract.canonical_html).exists() else (
            ws / "index.html" if (ws / "index.html").exists() else (
                ws / "static" / "index.html" if (ws / "static" / "index.html").exists() else None
            )
        )

        # CSS entrypoint
        css_file = ws / contract.canonical_css if (ws / contract.canonical_css).exists() else (
            ws / "style.css" if (ws / "style.css").exists() else (
                ws / "static" / "style.css" if (ws / "static" / "style.css").exists() else None
            )
        )

        # JavaScript entrypoint
        js_candidates = [
            ws / contract.canonical_js if contract.canonical_js else None,
            ws / "app.js",
            ws / "main.js",
            ws / "static" / "app.js",
            ws / "static" / "main.js",
            ws / "static" / "script.js",
            ws / "script.js",
        ]
        if html_file and html_file.exists():
            try:
                html_txt_s = html_file.read_text(encoding="utf-8", errors="ignore")
                for sm in re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html_txt_s, re.I):
                    if not sm.startswith(("http://", "https://", "//")):
                        js_candidates.insert(0, ws / sm.lstrip("./"))
                        js_candidates.insert(0, ws / "static" / sm.lstrip("./"))
            except Exception:
                pass
        js_file = next((f for f in js_candidates if f and f.exists() and f.stat().st_size > 20), None)

        details["canonical_html"] = str(html_file.relative_to(ws)) if html_file else None
        details["canonical_css"] = str(css_file.relative_to(ws)) if css_file else None
        details["canonical_js"] = str(js_file.relative_to(ws)) if js_file else None
        details["canonical_backend"] = str(be_file.relative_to(ws)) if be_file else None

        # 2. Extract Backend Routes & Response Envelopes
        backend_routes: Dict[str, Set[str]] = {}  # {path_pattern: set(HTTP_METHODS)}
        backend_response_shapes: Dict[Tuple[str, str], Dict[str, Any]] = {}  # {(method, path): shape_info}
        backend_required_fields: Dict[Tuple[str, str], Set[str]] = {}  # {(method, path): required_fields}
        be_content = ""

        if be_file and be_file.exists():
            be_content = be_file.read_text(encoding="utf-8", errors="ignore")
            if be_file.suffix == ".py":
                try:
                    tree = ast.parse(be_content, filename=be_file.name)
                    router_prefixes: Dict[str, str] = {}
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                            func_name = getattr(node.value.func, "id", getattr(node.value.func, "attr", ""))
                            if func_name == "APIRouter":
                                for kw in node.value.keywords:
                                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                        for tgt in node.targets:
                                            if isinstance(tgt, ast.Name):
                                                router_prefixes[tgt.id] = kw.value.value
                        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "include_router":
                            pref = ""
                            r_name = ""
                            if node.args and isinstance(node.args[0], ast.Name):
                                r_name = node.args[0].id
                            for kw in node.keywords:
                                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                    pref = kw.value.value
                            if r_name and pref:
                                router_prefixes[r_name] = pref + router_prefixes.get(r_name, "")

                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            for dec in node.decorator_list:
                                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                                    attr = dec.func.attr.upper()
                                    if attr in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                                        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                            raw_path = dec.args[0].value
                                            prefix = ""
                                            if isinstance(dec.func.value, ast.Name):
                                                prefix = router_prefixes.get(dec.func.value.id, "")
                                            full_path = (prefix.rstrip("/") + "/" + raw_path.lstrip("/")).rstrip("/") if prefix else raw_path
                                            if not full_path:
                                                full_path = "/"
                                            backend_routes.setdefault(full_path, set()).add(attr)
                                            if raw_path != full_path:
                                                backend_routes.setdefault(raw_path, set()).add(attr)

                                            # Inspect return statements for response shape
                                            norm_p = re.sub(r'\{[a-zA-Z0-9_]+\}', '{id}', full_path)
                                            for fn_node in ast.walk(node):
                                                if isinstance(fn_node, ast.Return) and fn_node.value:
                                                    if isinstance(fn_node.value, ast.Dict):
                                                        keys = [k.value for k in fn_node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                                                        backend_response_shapes[(attr, norm_p)] = {
                                                            "root_type": "object",
                                                            "envelope_properties": keys,
                                                        }
                                                    elif isinstance(fn_node.value, (ast.List, ast.ListComp)):
                                                        backend_response_shapes[(attr, norm_p)] = {
                                                            "root_type": "array",
                                                            "envelope_properties": [],
                                                        }
                except Exception as e:
                    uncertainties.append(f"Failed to fully parse {be_file.name} Python AST: {e}")

            elif be_file.suffix == ".js":
                # Node.js / Express route extraction
                route_matches = re.findall(
                    r"""(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`](.*?)(?=(?:app|router)\.(?:get|post|put|delete|patch)|$)""",
                    be_content,
                    re.DOTALL
                )
                for m, p, body in route_matches:
                    method = m.upper()
                    norm_p = re.sub(r'/:[a-zA-Z0-9_]+', '/{id}', p)
                    backend_routes.setdefault(norm_p, set()).add(method)
                    backend_routes.setdefault(p, set()).add(method)

                    # Extract res.json(...) or res.status(...).json(...) shape
                    json_calls = re.findall(r'res(?:\.status\([0-9]+\))?\.(?:json|send)\s*\(\s*(\{.*?\}|\[.*?\]|[a-zA-Z0-9_]+)\s*\)', body, re.DOTALL)
                    for jc in json_calls:
                        jc_str = jc.strip()
                        if jc_str.startswith("{") and jc_str.endswith("}"):
                            props = re.findall(r'([a-zA-Z0-9_]+)\s*:', jc_str)
                            # Also check shorthand property definitions e.g. { success: true, reference, inquiry_id }
                            # Match keys that don't have colon (e.g. shorthand identifiers)
                            tokens = [t.strip() for t in jc_str.strip("{}").split(",") if t.strip()]
                            for tok in tokens:
                                if ":" in tok:
                                    k = tok.split(":")[0].strip()
                                    if re.match(r'^[a-zA-Z0-9_]+$', k) and k not in props:
                                        props.append(k)
                                else:
                                    k = tok.strip()
                                    if re.match(r'^[a-zA-Z0-9_]+$', k) and k not in props:
                                        props.append(k)

                            backend_response_shapes[(method, norm_p)] = {
                                "root_type": "object",
                                "envelope_properties": props,
                            }
                        elif jc_str.startswith("[") and jc_str.endswith("]"):
                            backend_response_shapes[(method, norm_p)] = {
                                "root_type": "array",
                                "envelope_properties": [],
                            }
                        elif "db.all" in body or "findAll" in body:
                            backend_response_shapes[(method, norm_p)] = {
                                "root_type": "array",
                                "envelope_properties": [],
                            }
                        elif "db.get" in body or "findOne" in body:
                            backend_response_shapes[(method, norm_p)] = {
                                "root_type": "object",
                                "envelope_properties": [],
                            }

                    # Extract required request body fields
                    req_fields = set()
                    destruct_m = re.findall(r'(?:const|let|var)\s*\{([^}]+)\}\s*=\s*req\.body', body)
                    for dm in destruct_m:
                        for f_name in dm.split(","):
                            fn_clean = f_name.strip()
                            if fn_clean and re.search(rf'if\s*\(\s*!{fn_clean}\b', body):
                                req_fields.add(fn_clean)
                    direct_checks = re.findall(r'if\s*\(\s*!req\.body\.([a-zA-Z0-9_]+)\b', body)
                    for dc in direct_checks:
                        req_fields.add(dc)
                    if req_fields:
                        backend_required_fields[(method, norm_p)] = req_fields
                        backend_required_fields[(method, p)] = req_fields

            details["backend_routes_count"] = len(backend_routes)
            details["backend_routes"] = {k: list(v) for k, v in backend_routes.items()}
            details["backend_response_shapes_count"] = len(backend_response_shapes)

        # 3. Extract and Verify Frontend API Calls & Response Envelope Consumption
        check_backend = be_file is not None and current_phase not in ("scaffold_frontend", "frontend_only")

        # Discover all relevant frontend JavaScript files
        frontend_js_files: List[Path] = []
        if ws.exists():
            for f in ws.glob("**/*.js"):
                rel_parts = f.relative_to(ws).parts
                if any(p in ("node_modules", ".git", ".venv", "venv", ".hermes", ".artifacts", "tests", "test", "coverage") for p in rel_parts):
                    continue
                if be_file and f.resolve() == be_file.resolve():
                    continue
                frontend_js_files.append(f)

        if frontend_js_files and check_backend and backend_routes:
            for js_f in frontend_js_files:
                js_content = js_f.read_text(encoding="utf-8", errors="ignore")
                # Extract fetch and api calls
                raw_calls = re.findall(r"""(?:api\.(get|post|put|delete|patch)|fetch)\s*\(\s*[`'"]([^`'"]+)[`'"]""", js_content, re.I)
                template_calls = re.findall(r'(?:api\.(get|post|put|delete|patch)|fetch)\s*\(\s*`([^`]+)`', js_content, re.I)

                all_calls = set()
                for method, path in raw_calls:
                    norm_p = re.sub(r'\$\{[^}]+\}', '{id}', path)
                    all_calls.add((method.upper() if method else "GET", norm_p))

                for method, path in template_calls:
                    norm_path = re.sub(r'\$\{[^}]+\}', '{id}', path)
                    all_calls.add((method.upper() if method else "GET", norm_path))

                for method, path in all_calls:
                    if not path.startswith("/api"):
                        continue

                    norm_call_path = re.sub(r'/[0-9]+', '/{id}', path)
                    norm_call_path = re.sub(r'/[a-zA-Z0-9_\-]+(\.csv|\.json)', r' ', norm_call_path) if not norm_call_path.endswith((".csv", ".json")) else norm_call_path

                    matched = False
                    for b_route, b_methods in backend_routes.items():
                        norm_b_route = re.sub(r'\{[a-zA-Z0-9_]+\}', '{id}', b_route)
                        if norm_call_path == norm_b_route or path == b_route:
                            if method in b_methods or not method:
                                matched = True
                                break

                    if not matched:
                        path_no_query = path.split("?")[0]
                        norm_no_query = re.sub(r'/[0-9]+', '/{id}', path_no_query)
                        for b_route, b_methods in backend_routes.items():
                            norm_b_route = re.sub(r'\{[a-zA-Z0-9_]+\}', '{id}', b_route)
                            if norm_no_query == norm_b_route or path_no_query == b_route:
                                if method in b_methods or not method:
                                    matched = True
                                    break
                                else:
                                    endpoint_mismatches.append(
                                        f"HTTP method mismatch: {js_f.name} calls '{method} {path}', "
                                        f"but backend route '{b_route}' only accepts {sorted(list(b_methods))}."
                                    )
                                    matched = True
                                    break

                    if not matched:
                        if "{" in path and "}" in path and not re.search(r'\{id\}', path):
                            uncertainties.append(f"Dynamic API call in {js_f.name}: '{method} {path}' cannot be verified statically")
                        else:
                            endpoint_mismatches.append(
                                f"Frontend route mismatch: {js_f.name} calls '{method} {path}', "
                                f"but no matching backend route exists in {be_file.name if be_file else 'backend'}."
                            )

                # Response Shape Envelope Analysis
                fetch_iter = list(re.finditer(r"""(?:fetch|api\.(?:get|post|put|delete|patch))\s*\(\s*['"`]([^'"`]+)['"`]""", js_content))
                for fm in fetch_iter:
                    raw_url = fm.group(1)
                    norm_url = re.sub(r'/[0-9]+', '/{id}', raw_url)
                    norm_url = re.sub(r'/\$\{[^}]+\}', '/{id}', norm_url).split("?")[0]

                    snippet = js_content[fm.start():fm.start() + 1200]
                    req_method = "GET"
                    call_lead = js_content[max(0, fm.start()-10):fm.start()]
                    api_call_m = re.search(r'api\.(get|post|put|delete|patch)', call_lead + fm.group(0), re.I)
                    if api_call_m:
                        req_method = api_call_m.group(1).upper()
                    else:
                        method_m = re.search(r"""method\s*:\s*['"`](GET|POST|PUT|DELETE|PATCH)['"`]""", snippet, re.I)
                        if method_m:
                            req_method = method_m.group(1).upper()

                    shape = backend_response_shapes.get((req_method, norm_url)) or backend_response_shapes.get(("GET", norm_url))
                    if not shape:
                        continue

                    env_props = shape.get("envelope_properties", [])
                    root_type = shape.get("root_type", "object")

                    # Parse how response is unpacked in JavaScript
                    await_json = re.search(r'(?:const|let|var)\s+([a-zA-Z0-9_{},\s]+)\s*=\s*await\s+([a-zA-Z0-9_]+)\.json\(\)', snippet)
                    then_json = re.search(r'\.then\s*\(\s*(?:async\s*)?\s*\(?\s*([a-zA-Z0-9_{},\s]+)\s*\)?\s*=>', snippet)

                    call_prefix = js_content[max(0, fm.start()-100):fm.start()]
                    direct_assign = re.search(r'(?:const|let|var)\s+([a-zA-Z0-9_{},\s]+)\s*=\s*(?:await\s+)?$', call_prefix)

                    target_var = None
                    is_destructured = False
                    destructured_props = []

                    candidate_lhs = None
                    if await_json:
                        candidate_lhs = await_json.group(1).strip()
                    elif then_json:
                        candidate_lhs = then_json.group(1).strip()
                    elif direct_assign:
                        candidate_lhs = direct_assign.group(1).strip()

                    if candidate_lhs:
                        if candidate_lhs.startswith("{") and candidate_lhs.endswith("}"):
                            is_destructured = True
                            destructured_props = [x.strip() for x in candidate_lhs.strip("{}").split(",") if x.strip()]
                        else:
                            target_var = candidate_lhs

                    if root_type == "object" and env_props:
                        if is_destructured:
                            if not any(ep in destructured_props for ep in env_props):
                                msg = (
                                    f"API_RESPONSE_SHAPE_MISMATCH: Route '{req_method} {norm_url}' returns an Object envelope "
                                    f"with properties {env_props}, but frontend {js_f.name} destructures {destructured_props}."
                                )
                                response_shape_mismatches.append(msg)
                                discrepancies.append(
                                    ContractDiscrepancy(
                                        type="API_RESPONSE_SHAPE_MISMATCH",
                                        responsible_artifact=be_file.name if be_file else "server.js",
                                        consuming_artifact=js_f.name,
                                        mismatch=msg,
                                        confidence="HIGH",
                                        failure_class="API_RESPONSE_SHAPE_MISMATCH",
                                    )
                                )
                        elif target_var:
                            accesses_env = (
                                any(f"{target_var}.{ep}" in snippet for ep in env_props) or
                                any(f"{target_var}['{ep}']" in snippet for ep in env_props) or
                                any(f'{target_var}["{ep}"]' in snippet for ep in env_props)
                            )

                            nested_subprops = re.findall(rf'\b{target_var}\.([a-zA-Z0-9_]+)\.[a-zA-Z0-9_]+\b', snippet)
                            for nsp in nested_subprops:
                                if nsp not in env_props and nsp not in ("then", "catch", "finally", "json", "status", "ok", "message", "error"):
                                    msg = (
                                        f"API_RESPONSE_SHAPE_MISMATCH: Backend route '{req_method} {norm_url}' returns properties "
                                        f"{env_props}, but frontend {js_f.name} expects envelope object '{nsp}' (reads '{target_var}.{nsp}...'). "
                                        f"Property '{nsp}' is missing from backend response."
                                    )
                                    response_shape_mismatches.append(msg)
                                    discrepancies.append(
                                        ContractDiscrepancy(
                                            type="API_RESPONSE_SHAPE_MISMATCH",
                                            responsible_artifact=be_file.name if be_file else "server.js",
                                            consuming_artifact=js_f.name,
                                            mismatch=msg,
                                            confidence="HIGH",
                                            failure_class="API_RESPONSE_SHAPE_MISMATCH",
                                        )
                                    )

                            if not accesses_env:
                                array_ops = re.findall(rf'\b{target_var}\.(forEach|map|filter|reduce|find|findIndex|some|every|slice|length)\b', snippet)
                                for_of = re.findall(rf'for\s*\(\s*(?:const|let|var)\s+[a-zA-Z0-9_]+\s+of\s+{target_var}\b', snippet)

                                fn_call = re.search(rf'([a-zA-Z0-9_]+)\s*\(\s*{target_var}\s*\)', snippet)
                                fn_ops = []
                                if fn_call:
                                    fn_name = fn_call.group(1)
                                    fn_def = re.search(rf'function\s+{fn_name}\s*\(\s*([a-zA-Z0-9_]+)\s*\)\s*\{{(.*?)\}}', js_content, re.DOTALL)
                                    if fn_def:
                                        param = fn_def.group(1)
                                        body = fn_def.group(2)
                                        if not any(f"{param}.{ep}" in body for ep in env_props):
                                            fn_ops = re.findall(rf'\b{param}\.(forEach|map|filter|reduce|length)\b', body)

                                direct_ops = array_ops + for_of + fn_ops
                                if direct_ops:
                                    msg = (
                                        f"API_RESPONSE_SHAPE_MISMATCH: Backend route '{req_method} {norm_url}' returns an Object envelope "
                                        f"with property '{env_props[0]}' (e.g. res.json({{ {env_props[0]}: ... }})), "
                                        f"but frontend {js_f.name} treats the response as a raw Array directly on '{target_var}' (invokes '{direct_ops[0]}'). "
                                        f"Frontend must access '{target_var}.{env_props[0]}' or destructure 'const {{ {env_props[0]} }} = await ...json()'."
                                    )
                                    response_shape_mismatches.append(msg)
                                    discrepancies.append(
                                        ContractDiscrepancy(
                                            type="API_RESPONSE_SHAPE_MISMATCH",
                                            responsible_artifact=be_file.name if be_file else "server.js",
                                            consuming_artifact=js_f.name,
                                            mismatch=msg,
                                            confidence="HIGH",
                                            failure_class="API_RESPONSE_SHAPE_MISMATCH",
                                        )
                                    )

                    elif root_type == "array":
                        if target_var:
                            accessed_props = re.findall(rf'\b{target_var}\.([a-zA-Z0-9_]+)\.(forEach|map|filter)\b', snippet)
                            if accessed_props:
                                msg = (
                                    f"API_RESPONSE_SHAPE_MISMATCH: Backend route '{req_method} {norm_url}' returns a raw Array, "
                                    f"but frontend {js_f.name} accesses envelope property '{accessed_props[0][0]}'."
                                )
                                response_shape_mismatches.append(msg)
                                discrepancies.append(
                                    ContractDiscrepancy(
                                        type="API_RESPONSE_SHAPE_MISMATCH",
                                        responsible_artifact=be_file.name if be_file else "server.js",
                                        consuming_artifact=js_f.name,
                                        mismatch=msg,
                                        confidence="HIGH",
                                        failure_class="API_RESPONSE_SHAPE_MISMATCH",
                                    )
                                )


        # 4. Verify HTML Script and Stylesheet Path Resolution & Browser Module Graph (P0 Contract Gate A)
        if html_file and html_file.exists():
            html_content = html_file.read_text(encoding="utf-8", errors="ignore")
            base_html_dir = html_file.parent

            # 4a. Extract scripts and check module tags
            script_tag_matches = list(re.finditer(r'<script\b([^>]*)>(.*?)</script>', html_content, re.I | re.DOTALL))
            for st in script_tag_matches:
                attrs = st.group(1)
                src_m = re.search(r'src=["\']([^"\']+)["\']', attrs, re.I)
                if not src_m:
                    continue
                src = src_m.group(1)
                if src.startswith(("http://", "https://", "//")):
                    continue
                clean_src = src.lstrip("/")
                cands = [
                    base_html_dir / clean_src,
                    ws / clean_src,
                    ws / "static" / clean_src,
                    base_html_dir / src.lstrip("./"),
                ]
                if clean_src.startswith("static/"):
                    cands.append(ws / clean_src)
                
                target_script = next((c for c in cands if c.exists()), None)
                if not target_script:
                    html_asset_mismatches.append(
                        f"Broken script link in {html_file.name}: src='{src}' does not resolve to an existing file."
                    )
                    discrepancies.append(
                        ContractDiscrepancy(
                            type="BROKEN_ASSET_LINK",
                            responsible_artifact=html_file.name,
                            consuming_artifact="filesystem",
                            mismatch=f"Script src='{src}' does not resolve to a file",
                        )
                    )
                else:
                    # Check if target script uses ES module syntax (import/export)
                    try:
                        s_text = target_script.read_text(encoding="utf-8", errors="ignore")
                        uses_esm = bool(
                            re.search(r'\bimport\s+.*?\s+from\s+[\'"]', s_text) or
                            re.search(r'\bexport\s+(?:default|const|let|var|function|class|\{)', s_text) or
                            re.search(r'\bimport\s*\(', s_text)
                        )
                        has_module_type = bool(re.search(r'type=["\']module["\']', attrs, re.I))
                        if uses_esm and not has_module_type:
                            msg = (
                                f"BROWSER_MODULE_TYPE_MISMATCH: Script '{src}' referenced in {html_file.name} "
                                f"uses ES module syntax (import/export), but the <script> tag lacks type=\"module\". "
                                f"Browsers reject ES module syntax in classic scripts."
                            )
                            module_graph_mismatches.append(msg)
                            discrepancies.append(
                                ContractDiscrepancy(
                                    type="BROWSER_MODULE_TYPE_MISMATCH",
                                    responsible_artifact=html_file.name,
                                    consuming_artifact=src,
                                    mismatch=msg,
                                    confidence="HIGH",
                                )
                            )
                    except Exception as ex:
                        uncertainties.append(f"Notice inspecting script {target_script.name}: {ex}")

            # 4b. Extract stylesheets
            css_hrefs = re.findall(r'<link[^>]+(?:href=["\']([^"\']+\.css)["\']|rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\'])', html_content, re.I)
            for h_tup in css_hrefs:
                href = h_tup[0] or h_tup[1]
                if not href or href.startswith(("http://", "https://", "//")):
                    continue
                clean_href = href.lstrip("/")
                cands = [
                    base_html_dir / clean_href,
                    ws / clean_href,
                    ws / "static" / clean_href,
                    base_html_dir / href.lstrip("./"),
                ]
                if clean_href.startswith("static/"):
                    cands.append(ws / clean_href)
                if not any(c.exists() for c in cands):
                    html_asset_mismatches.append(
                        f"Broken stylesheet link in {html_file.name}: href='{href}' does not resolve to an existing file."
                    )
                    discrepancies.append(
                        ContractDiscrepancy(
                            type="BROKEN_ASSET_LINK",
                            responsible_artifact=html_file.name,
                            consuming_artifact="filesystem",
                            mismatch=f"Stylesheet href='{href}' does not resolve to a file",
                        )
                    )

        # 4c. Deep Browser Module Graph Verification (Import / Export consistency & Node mixing)
        module_exports_map: Dict[str, Set[str]] = {}  # {rel_path: set(exported_names)}
        all_frontend_js: Dict[str, str] = {}  # {rel_path: content}

        for js_f in frontend_js_files:
            try:
                rel_p = str(js_f.relative_to(ws)).replace("\\", "/")
                content = js_f.read_text(encoding="utf-8", errors="ignore")
                all_frontend_js[rel_p] = content

                # Extract exports
                exports = set()
                # export const/let/var/function/class Name
                named_m = re.findall(r'export\s+(?:const|let|var|function|class)\s+([a-zA-Z0-9_]+)', content)
                for nm in named_m:
                    exports.add(nm)
                # export { Name1, Name2 as Alias }
                block_m = re.findall(r'export\s*\{\s*([^}]+)\s*\}', content)
                for bm in block_m:
                    for item in bm.split(","):
                        it_clean = item.strip()
                        if " as " in it_clean:
                            exports.add(it_clean.split(" as ")[1].strip())
                        elif it_clean:
                            exports.add(it_clean)
                # export default Name
                def_m = re.findall(r'export\s+default\s+(?:class\s+|function\s+)?([a-zA-Z0-9_]+)', content)
                for dm in def_m:
                    exports.add(dm)
                exports.add("default")
                module_exports_map[rel_p] = exports

                # Check for Node.js CommonJS mixing in browser code
                has_require = bool(re.search(r'\brequire\s*\([\'"]', content))
                has_mod_exports = bool(re.search(r'\bmodule\.exports\s*=', content))
                if has_require or has_mod_exports:
                    msg = (
                        f"BROWSER_NODE_MIXING_MISMATCH: Browser module '{rel_p}' mixes Node.js CommonJS "
                        f"syntax (require/module.exports) with browser code. Browser modules must use ES module syntax."
                    )
                    module_graph_mismatches.append(msg)
                    discrepancies.append(
                        ContractDiscrepancy(
                            type="BROWSER_NODE_MIXING_MISMATCH",
                            responsible_artifact=rel_p,
                            consuming_artifact=rel_p,
                            mismatch=msg,
                            confidence="HIGH",
                        )
                    )
            except Exception as e:
                uncertainties.append(f"Notice reading module {js_f.name}: {e}")

        # Check all imports against exported symbols
        for rel_p, content in all_frontend_js.items():
            curr_dir = Path(rel_p).parent
            # import { a, b as c } from './target.js'
            import_matches = list(re.finditer(
                r'import\s+(?:(\*\s+as\s+[a-zA-Z0-9_]+)|(\{[\s\w,]*\})|([a-zA-Z0-9_]+))\s+from\s+[\'"]([^\'"]+)[\'"]',
                content
            ))
            for im in import_matches:
                named_import_grp = im.group(2)
                default_import_grp = im.group(3)
                import_path = im.group(4)

                if not (import_path.startswith(".") or import_path.endswith(".js")):
                    continue  # External package

                # Resolve target file path
                norm_tgt = str((curr_dir / import_path).as_posix())
                norm_tgt = re.sub(r'^\./', '', norm_tgt)
                norm_tgt_clean = Path(norm_tgt).as_posix()

                # Find match in module_exports_map
                matched_target = None
                for ep in module_exports_map.keys():
                    if ep == norm_tgt_clean or ep == f"{norm_tgt_clean}.js" or ep.endswith(import_path.lstrip("./")):
                        matched_target = ep
                        break

                if not matched_target:
                    target_disk = (ws / norm_tgt_clean).resolve()
                    if not target_disk.exists() and not (ws / f"{norm_tgt_clean}.js").exists():
                        msg = f"MISSING_IMPORTED_MODULE: Module '{rel_p}' imports from '{import_path}', but target file does not exist on disk."
                        module_graph_mismatches.append(msg)
                        discrepancies.append(
                            ContractDiscrepancy(
                                type="BROKEN_ASSET_LINK",
                                responsible_artifact=rel_p,
                                consuming_artifact="filesystem",
                                mismatch=msg,
                                confidence="HIGH",
                            )
                        )
                    continue

                if named_import_grp:
                    avail_exports = module_exports_map.get(matched_target, set())
                    raw_names = [n.strip() for n in named_import_grp.strip("{}").split(",") if n.strip()]
                    for r_name in raw_names:
                        orig_name = r_name.split(" as ")[0].strip()
                        if orig_name not in avail_exports and "default" not in orig_name:
                            msg = (
                                f"MISSING_IMPORTED_EXPORT: Module '{rel_p}' imports '{orig_name}' from '{matched_target}', "
                                f"but '{matched_target}' only exports {sorted(list(avail_exports)) if avail_exports else 'none'}. "
                                f"Export '{orig_name}' is missing."
                            )
                            module_graph_mismatches.append(msg)
                            discrepancies.append(
                                ContractDiscrepancy(
                                    type="MISSING_IMPORTED_EXPORT",
                                    responsible_artifact=matched_target,
                                    consuming_artifact=rel_p,
                                    mismatch=msg,
                                    confidence="HIGH",
                                )
                            )

        # 4d. Central API Client Contract Verification (P0 Contract Gate B)
        api_client_file = next((f for f in frontend_js_files if f.name in ("api.js", "client.js")), None)
        if api_client_file and api_client_file.exists():
            api_content = api_client_file.read_text(encoding="utf-8", errors="ignore")
            api_methods = {"get", "post", "put", "patch", "delete", "request"}
            # Methods on api object: e.g. api.getProducts = ... or getProducts(...) inside object
            for mm in re.findall(r'api\.([a-zA-Z0-9_]+)\s*=', api_content):
                api_methods.add(mm)
            for mm in re.findall(r'export\s+(?:async\s+)?function\s+([a-zA-Z0-9_]+)', api_content):
                api_methods.add(mm)
            for mm in re.findall(r'([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{', api_content):
                if mm not in ("constructor", "function", "if", "for", "while", "switch", "catch"):
                    api_methods.add(mm)
            for mm in re.findall(r'([a-zA-Z0-9_]+)\s*:\s*(?:async\s*)?(?:\([^)]*\)|function|\()', api_content):
                api_methods.add(mm)
            for mm in re.findall(r'([a-zA-Z0-9_]+)\s*:', api_content):
                api_methods.add(mm)

            for rel_p, content in all_frontend_js.items():
                if rel_p == str(api_client_file.relative_to(ws)).replace("\\", "/"):
                    continue
                calls = re.findall(r'\bapi\.([a-zA-Z0-9_]+)\s*\(', content)
                for call_name in calls:
                    if call_name not in api_methods and not call_name.startswith("_"):
                        msg = (
                            f"API_CLIENT_METHOD_MISSING: Frontend component '{rel_p}' invokes 'api.{call_name}()', "
                            f"but '{api_client_file.name}' does not implement or export '{call_name}'."
                        )
                        api_client_mismatches.append(msg)
                        discrepancies.append(
                            ContractDiscrepancy(
                                type="API_CLIENT_METHOD_MISSING",
                                responsible_artifact=api_client_file.name,
                                consuming_artifact=rel_p,
                                mismatch=msg,
                                confidence="HIGH",
                            )
                        )

        # 4e. Form Enum and Request Body Contract Verification (P0 Contract Gate C)
        # Check Direction Enum case-sensitivity
        if be_content:
            enum_match = re.search(r"direction\s+IN\s*\(([^)]+)\)", be_content, re.I)
            allowed_directions = set()
            if enum_match:
                allowed_directions = {d.strip(" '\"") for d in enum_match.group(1).split(",")}
            elif "direction" in be_content and ("'export'" in be_content or "'import'" in be_content):
                allowed_directions = {"export", "import", "contact"}

            if allowed_directions and html_file and html_file.exists():
                html_txt = html_file.read_text(encoding="utf-8", errors="ignore")
                # Look for select options
                select_dirs = re.findall(r'<select[^>]*name=["\']direction["\'][^>]*>(.*?)</select>', html_txt, re.I | re.DOTALL)
                for s_block in select_dirs:
                    opt_vals = re.findall(r'<option[^>]*value=["\']([^"\']+)["\']', s_block)
                    for ov in opt_vals:
                        if ov.upper() == ov and ov.lower() in allowed_directions and ov not in allowed_directions:
                            msg = (
                                f"DATABASE_ENUM_CONTRACT_MISMATCH: HTML form in {html_file.name} specifies uppercase "
                                f"option value='{ov}', but database constraint requires lowercase: {sorted(list(allowed_directions))}."
                            )
                            form_enum_mismatches.append(msg)
                            discrepancies.append(
                                ContractDiscrepancy(
                                    type="DATABASE_ENUM_CONTRACT_MISMATCH",
                                    responsible_artifact=html_file.name,
                                    consuming_artifact="database",
                                    mismatch=msg,
                                    confidence="HIGH",
                                )
                            )

            # Check Required Fields for Contact Form
            contact_req_fields = backend_required_fields.get(("POST", "/api/contact")) or backend_required_fields.get(("POST", "/api/contacts"))
            if contact_req_fields and html_file and html_file.exists():
                html_txt = html_file.read_text(encoding="utf-8", errors="ignore")
                contact_form_m = re.search(r'<form[^>]*(?:id=["\'](?:contactForm|contact-form)["\']|action=["\'][^"\']*contact)[^>]*>(.*?)</form>', html_txt, re.I | re.DOTALL)
                form_scope = contact_form_m.group(1) if contact_form_m else html_txt
                for req_f in contact_req_fields:
                    has_input = bool(re.search(rf'name=["\']{req_f}["\']', form_scope))
                    if not has_input:
                        msg = (
                            f"REQUEST_FIELD_CONTRACT_MISMATCH: Backend route 'POST /api/contact' requires body field "
                            f"'{req_f}', but HTML form in {html_file.name} has no input field with name='{req_f}'."
                        )
                        form_enum_mismatches.append(msg)
                        discrepancies.append(
                            ContractDiscrepancy(
                                type="REQUEST_FIELD_CONTRACT_MISMATCH",
                                responsible_artifact=html_file.name,
                                consuming_artifact=be_file.name if be_file else "server.js",
                                mismatch=msg,
                                confidence="HIGH",
                            )
                        )

        # 4f. Jest / Supertest Server Export Contract Verification (P0 Contract Gate D)
        test_dir_candidates = [ws / "tests", ws / "test"]
        test_files: List[Path] = []
        for td in test_dir_candidates:
            if td.exists():
                test_files.extend(list(td.glob("*.js")))
        test_files.extend(list(ws.glob("test.js")) + list(ws.glob("tests.js")))

        if be_file and be_file.suffix == ".js" and test_files:
            # Check server.js export pattern
            # module.exports = { app, db }
            server_exports_named_object = bool(re.search(r'module\.exports\s*=\s*\{\s*app\b', be_content))
            for tf in test_files:
                try:
                    t_text = tf.read_text(encoding="utf-8", errors="ignore")
                    uses_supertest = "supertest" in t_text or "request(" in t_text
                    if uses_supertest and server_exports_named_object:
                        # Check if test imports as default: const app = require('../server')
                        has_default_app_import = bool(re.search(r'const\s+app\s*=\s*require\([\'"][^\'"]*server[\'"]\)', t_text))
                        has_request_app = bool(re.search(r'request\(\s*app\s*\)', t_text))
                        if has_default_app_import and has_request_app:
                            msg = (
                                f"TEST_SERVER_EXPORT_MISMATCH: Test file '{tf.name}' imports server as single variable "
                                f"'const app = require(...)' and passes it to supertest 'request(app)', but {be_file.name} "
                                f"exports a named object: module.exports = {{ app, ... }}. Test must destructure 'const {{ app }} = require(...)'. "
                                f"Otherwise supertest fails with TypeError: app.address is not a function."
                            )
                            test_export_mismatches.append(msg)
                            discrepancies.append(
                                ContractDiscrepancy(
                                    type="TEST_SERVER_EXPORT_MISMATCH",
                                    responsible_artifact=tf.name,
                                    consuming_artifact=be_file.name,
                                    mismatch=msg,
                                    confidence="HIGH",
                                )
                            )
                except Exception as ex:
                    uncertainties.append(f"Notice reading test file {tf.name}: {ex}")

        # 5. Verify DOM ID Alignment (HTML vs JS) & Dynamic DOM Reference Verification
        if html_file and html_file.exists():
            html_content = html_file.read_text(encoding="utf-8", errors="ignore")
            defined_html_ids = set(re.findall(r'id=["\']([a-zA-Z0-9_\-]+)["\']', html_content))

            all_dynamic_js_ids = set()
            for js_f in frontend_js_files:
                js_content = js_f.read_text(encoding="utf-8", errors="ignore")
                all_dynamic_js_ids.update(re.findall(r"(?:\.id\s*=\s*|\.setAttribute\(\s*['\"]id['\"]\s*,\s*)['\"]([a-zA-Z0-9_\-]+)['\"]", js_content))
                all_dynamic_js_ids.update(re.findall(r"id=['\"]([a-zA-Z0-9_\-]+)['\"]", js_content))
            all_defined_ids = defined_html_ids | all_dynamic_js_ids

            for js_f in frontend_js_files:
                js_content = js_f.read_text(encoding="utf-8", errors="ignore")
                referenced_js_ids = set(
                    re.findall(r'getElementById\([\'\"]([a-zA-Z0-9_\-]+)[\'\"]\)', js_content)
                    + re.findall(r'querySelector\([\'\"]#([a-zA-Z0-9_\-]+)[\'\"]\)', js_content)
                )
                for js_id in referenced_js_ids:
                    # Ignore template or test IDs
                    if js_id not in all_defined_ids and not js_id.startswith("template"):
                        # Special check for required workflow IDs
                        is_critical_workflow_id = js_id in (
                            "trackShipmentBtn", "trackingInput", "trackingResultContainer",
                            "rfqForm", "inquiryForm", "catalogGrid", "productDetailsModal"
                        )
                        msg = f"DOM ID mismatch: {js_f.name} references '#{js_id}', but no element with id='{js_id}' exists in {html_file.name}."
                        dom_id_mismatches.append(msg)
                        discrepancies.append(
                            ContractDiscrepancy(
                                type="DOM_REFERENCE_MISMATCH" if is_critical_workflow_id else "DOM_CONTRACT_MISMATCH",
                                responsible_artifact=html_file.name,
                                consuming_artifact=js_f.name,
                                mismatch=msg,
                                confidence="HIGH",
                            )
                        )

        # 6. Verify CSS Classes and Variables
        if css_file and css_file.exists():
            try:
                css_text = css_file.read_text(encoding="utf-8", errors="ignore")
                defined_css_vars = set(re.findall(r'(--[a-zA-Z0-9_\-]+)\s*:', css_text))
                referenced_css_vars = set(re.findall(r'var\(([a-zA-Z0-9_\-]+)\)', css_text))
                missing_vars = referenced_css_vars - defined_css_vars
                if missing_vars:
                    warnings.append(f"Unresolved CSS variables in {css_file.name}: {sorted(list(missing_vars))}")

                if html_file and html_file.exists():
                    html_content = html_file.read_text(encoding="utf-8", errors="ignore")
                    defined_classes = set(re.findall(r'\.([a-zA-Z0-9_\-]+)[.:\s,{]', css_text))
                    UTILITY_CLASSES = frozenset({
                        "container", "card", "flex", "hidden", "btn", "col-12", "row", "active", "completed",
                        "show", "hide", "fade", "modal", "header", "footer", "nav", "text-center", "d-none",
                        "primary", "secondary", "success", "danger", "warning", "info", "dark", "light"
                    })
                    html_class_attrs = re.findall(r'class=[\'"]([^\'"]+)[\'"]', html_content)
                    for ca in html_class_attrs:
                        for c_item in ca.split():
                            c_item = c_item.strip()
                            if not c_item or c_item in UTILITY_CLASSES:
                                continue
                            if c_item not in defined_classes:
                                css_mismatches.append(
                                    f"CSS class '{c_item}' used in {html_file.name} is not defined in {css_file.name}."
                                )
                                discrepancies.append(
                                    ContractDiscrepancy(
                                        type="CSS_VARIABLE_MISMATCH",
                                        responsible_artifact=css_file.name,
                                        consuming_artifact=html_file.name,
                                        mismatch=f"CSS class '{c_item}' used in {html_file.name} not found in {css_file.name}",
                                    )
                                )
            except Exception as e:
                uncertainties.append(f"Notice inspecting CSS variables in {css_file.name}: {e}")

        # 7. Verify Database Schema Alignment
        db_files = list(ws.glob("*.db")) + list(ws.glob("*.sqlite")) + list(ws.glob("*.sqlite3"))
        if db_files:
            target_db = db_files[0]
            try:
                db_uri = f"file:{target_db.as_posix()}?mode=ro"
                try:
                    conn = sqlite3.connect(db_uri, uri=True)
                except Exception:
                    conn = sqlite3.connect(str(target_db))
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                existing_tables = set(r[0] for r in cursor.fetchall() if not r[0].startswith("sqlite_"))
                details["database_tables"] = sorted(list(existing_tables))

                if getattr(contract, "database_tables", None):
                    for exp_table, exp_cols in contract.database_tables.items():
                        if exp_table not in existing_tables:
                            database_mismatches.append(f"Expected database table '{exp_table}' missing from {target_db.name}")
                        elif exp_cols:
                            cursor.execute(f"PRAGMA table_info({exp_table});")
                            actual_cols = set(r[1] for r in cursor.fetchall())
                            for ec in exp_cols:
                                if ec not in actual_cols:
                                    database_mismatches.append(f"Column '{ec}' missing from table '{exp_table}' in {target_db.name}")
                conn.close()
            except Exception as e:
                uncertainties.append(f"Notice during read-only SQLite schema inspection of {target_db.name}: {e}")

        # 8. Verify Startup Instructions
        pkg_path = ws / "package.json"
        if pkg_path.exists():
            try:
                pkg_data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                start_cmd = pkg_data.get("scripts", {}).get("start", "")
                if start_cmd and "main.py" in start_cmd and be_file and be_file.name != "main.py":
                    startup_mismatches.append(
                        f"Startup script mismatch: package.json 'start' invokes 'main.py', but backend file is '{be_file.name}'."
                    )
            except Exception as e:
                uncertainties.append(f"Could not parse package.json for startup verification: {e}")

        # 8.5 Cross-File Test and Integration Contract Analysis (Scenarios A through I)
        test_files = []
        if (ws / "tests").exists():
            test_files.extend(list((ws / "tests").glob("*.js")) + list((ws / "tests").glob("*.ts")) + list((ws / "tests").glob("*.py")))
        if (ws / "test").exists():
            test_files.extend(list((ws / "test").glob("*.js")) + list((ws / "test").glob("*.ts")) + list((ws / "test").glob("*.py")))

        for tf in test_files:
            try:
                t_txt = tf.read_text(encoding='utf-8', errors='ignore')

                # Scenario A: Health status contract mismatch ({ status: 'healthy' } vs { status: 'ok' })
                if be_content and '/api/health' in be_content:
                    exp_status_m = re.search(r'expect\s*\(\s*res\.body\.status\s*\)\.toEqual\s*\(\s*["\']([^"\']+)["\']\s*\)', t_txt)
                    if exp_status_m:
                        expected_status = exp_status_m.group(1)
                        health_match = re.search(r"/api/health.*?res\.(?:json|send)\s*\(\s*\{([^}]+)\}\s*\)", be_content, re.DOTALL)
                        if health_match:
                            h_body = health_match.group(1)
                            actual_status_m = re.search(r'status\s*:\s*["\']([^"\']+)["\']', h_body)
                            if actual_status_m:
                                actual_status = actual_status_m.group(1)
                                if actual_status != expected_status:
                                    msg = (
                                        f"API contract mismatch: GET /api/health in {be_file.name} returns "
                                        f"status '{actual_status}', but {tf.name} expects '{expected_status}'."
                                    )
                                    response_shape_mismatches.append(msg)
                                    discrepancies.append(ContractDiscrepancy(
                                        type="API_RESPONSE_VALUE_MISMATCH",
                                        responsible_artifact=be_file.name,
                                        consuming_artifact=tf.name,
                                                                                mismatch=msg,
                                        suggested_repair=f"Align {be_file.name} or {tf.name} so both agree on status '{expected_status}'.",
                                    ))

                # Scenario B: Enquiry request payload field mismatch (companyName vs company_name, etc.)
                if be_content and ('/api/enquiries' in be_content or '/api/inquiries' in be_content):
                    test_post_enquiry = re.search(r'post\s*\(\s*["\']/api/(?:enquiries|inquiries)["\']\s*\)\s*\.send', t_txt)
                    if test_post_enquiry:
                        payload_str = t_txt
                        camel_fields = [f for f in ["companyName", "contactPerson", "productName", "destinationOrOrigin", "additionalRequirements"] if f in payload_str]
                        snake_backend = [f for f in ["company_name", "contact_person", "product", "country", "trade_direction", "requirements"] if f in be_content]
                        if camel_fields and snake_backend:
                            msg = (
                                f"Enquiry request payload mismatch: {tf.name} sends camelCase fields "
                                f"{sorted(list(set(camel_fields)))} but {be_file.name} expects snake_case fields "
                                f"{sorted(list(set(snake_backend)))}."
                            )
                            endpoint_mismatches.append(msg)
                            discrepancies.append(ContractDiscrepancy(
                                type="REQUEST_PAYLOAD_FIELD_MISMATCH",
                                responsible_artifact=tf.name,
                                consuming_artifact=be_file.name,
                                                                mismatch=msg,
                                suggested_repair="Standardize enquiry field naming between test payloads and backend request body parsing.",
                            ))

                # Scenario C: Reference format prefix mismatch (GT-ENQ- vs GTC-ENQ-)
                ref_pattern_m = re.search(r"expect\s*\(\s*res\.body\.reference\s*\)\.toMatch\s*\(\s*/\^([A-Z0-9_-]+)/", t_txt)
                if ref_pattern_m and be_content:
                    exp_prefix = ref_pattern_m.group(1)
                    actual_prefix_m = re.search(r'["\']([A-Z0-9_-]+ENQ-)["\']', be_content)
                    if actual_prefix_m:
                        actual_prefix = actual_prefix_m.group(1)
                        if actual_prefix != exp_prefix:
                            msg = (
                                f"Enquiry reference format mismatch: {be_file.name} generates '{actual_prefix}', "
                                f"but {tf.name} expects pattern '{exp_prefix}'."
                            )
                            endpoint_mismatches.append(msg)
                            discrepancies.append(ContractDiscrepancy(
                                type="REFERENCE_FORMAT_MISMATCH",
                                responsible_artifact=be_file.name,
                                consuming_artifact=tf.name,
                                                                mismatch=msg,
                                suggested_repair=f"Align enquiry reference generator in {be_file.name} to match expected prefix '{exp_prefix}'.",
                            ))

                # Scenario D: Shipment tracking reference mismatch (GT-SHP-88210 vs GTC-SHP-8821)
                test_shp_m = re.search(r"/api/shipments/([A-Z0-9_-]+)", t_txt)
                if test_shp_m and be_content:
                    test_shp_ref = test_shp_m.group(1)
                    if test_shp_ref not in be_content:
                        seed_shp_m = re.search(r'["\']([A-Z0-9_-]*SHP-[A-Z0-9_-]+)["\']', be_content)
                        seed_ref = seed_shp_m.group(1) if seed_shp_m else "unknown"
                        msg = (
                            f"Shipment tracking mismatch: {tf.name} queries tracking reference '{test_shp_ref}', "
                            f"which is not seeded or recognized in {be_file.name} (seeded '{seed_ref}')."
                        )
                        endpoint_mismatches.append(msg)
                        discrepancies.append(ContractDiscrepancy(
                            type="TRACKING_DATA_CONTRACT_MISMATCH",
                            responsible_artifact=be_file.name,
                            consuming_artifact=tf.name,
                                                        mismatch=msg,
                            suggested_repair=f"Seed '{test_shp_ref}' in database initialization or update test to query '{seed_ref}'.",
                        ))

                # Scenario E: Admin authentication credentials mismatch
                test_pwd_m = re.search(r'password\s*:\s*["\']([^"\']+)["\']', t_txt)
                if test_pwd_m and be_content and '/api/admin/login' in be_content:
                    test_pwd = test_pwd_m.group(1)
                    be_pwd_m = re.search(r'password\s*(?:===|==)\s*["\']([^"\']+)["\']', be_content)
                    if be_pwd_m:
                        be_pwd = be_pwd_m.group(1)
                        if test_pwd != be_pwd:
                            msg = (
                                f"Admin authentication mismatch: {be_file.name} checks password '{be_pwd}', "
                                f"but {tf.name} submits '{test_pwd}'."
                            )
                            endpoint_mismatches.append(msg)
                            discrepancies.append(ContractDiscrepancy(
                                type="AUTH_CREDENTIALS_MISMATCH",
                                responsible_artifact=be_file.name,
                                consuming_artifact=tf.name,
                                                                mismatch=msg,
                                suggested_repair="Synchronize admin credentials between backend authentication handler and test suite.",
                            ))

                # Scenario I: Test discovery & DB isolation
                has_sqlite_in_backend = be_content and ("sqlite" in be_content.lower() or "TEST_DB_PATH" in be_content or "GLOBALTRADE_TEST_DB_PATH" in be_content)
                lines_tf = t_txt.splitlines()
                server_req_line = -1
                db_env_line = -1
                for idx, line in enumerate(lines_tf):
                    if 'require(' in line and 'server' in line:
                        server_req_line = idx
                    if 'GLOBALTRADE_TEST_DB_PATH' in line or 'TEST_DB_PATH' in line or 'DB_PATH' in line:
                        db_env_line = idx
                if has_sqlite_in_backend and server_req_line != -1 and (db_env_line == -1 or db_env_line > server_req_line):
                    msg = (
                        f"Test database isolation warning in {tf.name}: Server module is imported "
                        f"before test database environment variable is set. May pollute demo database."
                    )
                    warnings.append(msg)
                    discrepancies.append(ContractDiscrepancy(
                        type="TEST_DB_ISOLATION_WARNING",
                        responsible_artifact=tf.name,
                        consuming_artifact=be_file.name if be_file else "server.js",
                                                mismatch=msg,
                        suggested_repair="Set process.env.TEST_DB_PATH / GLOBALTRADE_TEST_DB_PATH before require('../server').",
                    ))

            except Exception as e:
                uncertainties.append(f"Notice analyzing test file {tf.name}: {e}")

        # Scenario F: HTML and JS DOM contract mismatch (productGrid vs product-grid, etc.)
        if html_file and html_file.exists() and frontend_js_files:
            h_raw = html_file.read_text(encoding='utf-8', errors='ignore')
            for js_f in frontend_js_files:
                js_raw = js_f.read_text(encoding='utf-8', errors='ignore')
                for camel, kebab in [
                    ("productGrid", "product-grid"),
                    ("searchInput", "search-input"),
                    ("categoryFilter", "category-filter"),
                    ("tradeTypeFilter", "type-filter"),
                    ("resetFiltersBtn", "reset-filters"),
                    ("content-section", "app-section"),
                ]:
                    if (f"#{camel}" in h_raw or f'id="{camel}"' in h_raw) and (f"#{kebab}" in js_raw or f"getElementById('{kebab}')" in js_raw or f'getElementById("{kebab}")' in js_raw):
                        msg = (
                            f"DOM contract mismatch: {html_file.name} defines element with id/class '{camel}', "
                            f"but {js_f.name} queries '{kebab}'."
                        )
                        dom_id_mismatches.append(msg)
                        discrepancies.append(ContractDiscrepancy(
                            type="DOM_REFERENCE_MISMATCH",
                            responsible_artifact=js_f.name,
                            consuming_artifact=html_file.name,
                                                        mismatch=msg,
                            suggested_repair=f"Align DOM selectors: use '#{camel}' in {js_f.name} or '#{kebab}' in {html_file.name}.",
                        ))

        # Scenario G & H: Admin routes & Event property checks
        if frontend_js_files and be_content:
            for js_f in frontend_js_files:
                js_raw = js_f.read_text(encoding='utf-8', errors='ignore')
                # Scenario G: Separate enquiry/shipment endpoints vs combined dashboard
                if '/api/admin/enquiries' in js_raw and '/api/admin/enquiries' not in be_content and '/api/admin/dashboard' in be_content:
                    msg = (
                        f"Admin API contract mismatch: {js_f.name} attempts to call 'GET /api/admin/enquiries', "
                        f"but {be_file.name} only exposes combined endpoint '/api/admin/dashboard'."
                    )
                    endpoint_mismatches.append(msg)
                    discrepancies.append(ContractDiscrepancy(
                        type="ADMIN_ROUTE_CONTRACT_MISMATCH",
                        responsible_artifact=js_f.name,
                        consuming_artifact=be_file.name,
                                                mismatch=msg,
                        suggested_repair="Expose '/api/admin/enquiries' in backend or update client to use '/api/admin/dashboard'.",
                    ))

                # Scenario H: Shipment event missing required fields (event_title, event_date vs title, description)
                if '/api/admin/shipments' in js_raw or '/api/shipments' in js_raw:
                    if 'event_date' in be_content and 'event_date' not in js_raw and 'event_title' in be_content:
                        msg = (
                            f"Shipment event contract mismatch: {be_file.name} requires 'event_date' and 'event_title', "
                            f"which are not supplied by {js_f.name} event creation form."
                        )
                        endpoint_mismatches.append(msg)
                        discrepancies.append(ContractDiscrepancy(
                            type="EVENT_CONTRACT_MISMATCH",
                            responsible_artifact=js_f.name,
                            consuming_artifact=be_file.name,
                                                        mismatch=msg,
                            suggested_repair="Ensure client sends all required shipment event fields including 'event_date'.",
                        ))

        # 9. Determine Overall Gate Severity
        has_fatal = bool(
            endpoint_mismatches
            or response_shape_mismatches
            or html_asset_mismatches
            or dom_id_mismatches
            or database_mismatches
            or startup_mismatches
            or module_graph_mismatches
            or api_client_mismatches
            or form_enum_mismatches
            or test_export_mismatches
        )
        if has_fatal:
            sev = SEV_FAIL
            is_valid = False
        elif warnings:
            sev = SEV_WARNING
            is_valid = True
        elif uncertainties:
            sev = SEV_UNVERIFIED
            is_valid = True
        else:
            sev = SEV_PASS
            is_valid = True

        return CrossFileContractReport(
            valid=is_valid,
            severity=sev,
            endpoint_mismatches=endpoint_mismatches,
            response_shape_mismatches=response_shape_mismatches,
            html_asset_mismatches=html_asset_mismatches,
            dom_id_mismatches=dom_id_mismatches,
            css_mismatches=css_mismatches,
            database_mismatches=database_mismatches,
            startup_mismatches=startup_mismatches,
            module_graph_mismatches=module_graph_mismatches,
            api_client_mismatches=api_client_mismatches,
            form_enum_mismatches=form_enum_mismatches,
            test_export_mismatches=test_export_mismatches,
            warnings=warnings,
            uncertainties=uncertainties,
            discrepancies=discrepancies,
            details=details,
        )