# core/cross_file_contract.py
"""
Cross-File Contract Validation for HERMES 2.x (Prompt 13 & Final Autonomy Qualification).
Validates cross-file coherence across all deliverables:
1. Route alignment (frontend fetch vs backend routes, including Node/Express and Python/FastAPI)
2. Response envelope shape alignment (backend JSON shape vs frontend consumption: object envelope vs raw array)
3. HTML asset paths (script src and link href existence)
4. DOM contract alignment (HTML IDs vs JavaScript references)
5. CSS class alignment (HTML classes vs CSS stylesheet)
6. Database schema alignment (SQLite table/column presence vs contract)
7. Startup configuration (package.json vs backend file)
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
    type: str  # DOM_CONTRACT_MISMATCH, API_ROUTE_MISMATCH, API_RESPONSE_SHAPE_MISMATCH, DATABASE_SCHEMA_MISMATCH, BROKEN_ASSET_LINK, CSS_VARIABLE_MISMATCH
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
            len(self.startup_mismatches)
        )

    @property
    def summary(self) -> str:
        if self.valid:
            warn_msg = f" ({len(self.warnings)} warning(s))" if self.warnings else ""
            unc_msg = f" ({len(self.uncertainties)} uncertainty notice(s))" if self.uncertainties else ""
            return f"[{self.severity}] Cross-file contracts verified and coherent{warn_msg}{unc_msg}."
        return (
            f"[{self.severity}] Cross-file contract violations detected: {self.total_issues} issue(s) "
            f"({len(self.endpoint_mismatches)} route mismatches, "
            f"{len(self.response_shape_mismatches)} response shape mismatches, "
            f"{len(self.html_asset_mismatches)} broken asset paths, "
            f"{len(self.dom_id_mismatches)} DOM ID mismatches, "
            f"{len(self.database_mismatches)} database mismatches)."
        )


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
            "warnings": report.warnings,
            "uncertainties": report.uncertainties,
            "hard_errors": (
                report.endpoint_mismatches
                + report.response_shape_mismatches
                + report.html_asset_mismatches
                + report.dom_id_mismatches
                + report.database_mismatches
                + report.startup_mismatches
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
            ws / "main.py",
            ws / "app.py",
            ws / "server.py",
            ws / "server.js",
            ws / "app.js" if (ws / "package.json").exists() and not (ws / "index.html").exists() else None,
        ]
        be_file = next((f for f in be_candidates if f and f.exists() and f.stat().st_size > 20), None)

        # HTML entrypoint
        html_file = ws / contract.canonical_html if (ws / contract.canonical_html).exists() else (
            ws / "static" / "index.html" if (ws / "static" / "index.html").exists() else
            (ws / "index.html" if (ws / "index.html").exists() else None)
        )

        # CSS entrypoint
        css_file = ws / contract.canonical_css if (ws / contract.canonical_css).exists() else (
            ws / "static" / "style.css" if (ws / "static" / "style.css").exists() else
            (ws / "style.css" if (ws / "style.css").exists() else None)
        )

        # JavaScript entrypoint
        js_candidates = [
            ws / contract.canonical_js if contract.canonical_js else None,
            ws / "static" / "app.js",
            ws / "static" / "main.js",
            ws / "static" / "script.js",
            ws / "app.js",
            ws / "main.js",
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

        # 2. Extract Backend Routes & Response Envelopes (Phase C3 & 3.1)
        backend_routes: Dict[str, Set[str]] = {}  # {path_pattern: set(HTTP_METHODS)}
        backend_response_shapes: Dict[Tuple[str, str], Dict[str, Any]] = {}  # {(method, path): shape_info}

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

                    # Extract res.json(...) shape
                    json_calls = re.findall(r'res\.(?:json|send)\s*\(\s*(\{.*?\}|\[.*?\]|[a-zA-Z0-9_]+)\s*\)', body, re.DOTALL)
                    for jc in json_calls:
                        jc_str = jc.strip()
                        if jc_str.startswith("{") and jc_str.endswith("}"):
                            props = re.findall(r'([a-zA-Z0-9_]+)\s*:', jc_str)
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

            details["backend_routes_count"] = len(backend_routes)
            details["backend_routes"] = {k: list(v) for k, v in backend_routes.items()}
            details["backend_response_shapes_count"] = len(backend_response_shapes)

        # 3. Extract and Verify Frontend API Calls & Response Envelope Consumption (Section 3)
        check_backend = be_file is not None and current_phase not in ("scaffold_frontend", "frontend_only")

        if js_file and js_file.exists() and check_backend and backend_routes:
            js_content = js_file.read_text(encoding="utf-8", errors="ignore")
            # Extract fetch calls with explicit options (method: 'POST'|'PUT'|'DELETE')
            fetch_opts = re.findall(
                r"""fetch\s*\(\s*([`'"][^`'"]+[`'"]|`[^`]+`)\s*,\s*\{[^}]*?method\s*:\s*['"]([a-zA-Z]+)['"]""",
                js_content,
                re.I | re.DOTALL,
            )
            explicit_calls = {}
            for path_expr, m in fetch_opts:
                clean_p = path_expr.strip("`'\"")
                norm_p = re.sub(r'\$\{[^}]+\}', '{id}', clean_p)
                explicit_calls[norm_p] = m.upper()

            raw_calls = re.findall(r"""(?:api\.(get|post|put|delete)|fetch)\s*\(\s*[`'"]([^`'"]+)[`'"]""", js_content, re.I)
            template_calls = re.findall(r'(?:api\.(get|post|put|delete)|fetch)\s*\(\s*`([^`]+)`', js_content, re.I)

            all_calls = set()
            for method, path in raw_calls:
                norm_p = re.sub(r'\$\{[^}]+\}', '{id}', path)
                method_norm = method.upper() if method else explicit_calls.get(norm_p, "GET")
                all_calls.add((method_norm, norm_p))

            for method, path in template_calls:
                norm_path = re.sub(r'\$\{[^}]+\}', '{id}', path)
                method_norm = method.upper() if method else explicit_calls.get(norm_path, "GET")
                all_calls.add((method_norm, norm_path))

            details["frontend_api_calls_count"] = len(all_calls)

            for method, path in all_calls:
                if not path.startswith("/api"):
                    continue

                norm_call_path = re.sub(r'/[0-9]+', '/{id}', path)
                norm_call_path = re.sub(r'/[a-zA-Z0-9_\-]+(\.csv|\.json)', r'', norm_call_path) if not norm_call_path.endswith((".csv", ".json")) else norm_call_path

                matched = False
                matched_route = None
                for b_route, b_methods in backend_routes.items():
                    norm_b_route = re.sub(r'\{[a-zA-Z0-9_]+\}', '{id}', b_route)
                    if norm_call_path == norm_b_route or path == b_route:
                        if method in b_methods or not method:
                            matched = True
                            matched_route = norm_b_route
                            break

                if not matched:
                    path_no_query = path.split("?")[0]
                    norm_no_query = re.sub(r'/[0-9]+', '/{id}', path_no_query)
                    for b_route, b_methods in backend_routes.items():
                        norm_b_route = re.sub(r'\{[a-zA-Z0-9_]+\}', '{id}', b_route)
                        if norm_no_query == norm_b_route or path_no_query == b_route:
                            if method in b_methods or not method:
                                matched = True
                                matched_route = norm_b_route
                                break
                            else:
                                endpoint_mismatches.append(
                                    f"HTTP method mismatch: {js_file.name} calls '{method} {path}', "
                                    f"but backend route '{b_route}' only accepts {sorted(list(b_methods))}."
                                )
                                matched = True
                                break

                if not matched:
                    if "{" in path and "}" in path and not re.search(r'\{id\}', path):
                        uncertainties.append(f"Dynamic API call in {js_file.name}: '{method} {path}' cannot be verified statically")
                    else:
                        endpoint_mismatches.append(
                            f"Frontend route mismatch: {js_file.name} calls '{method} {path}', "
                            f"but no matching backend route exists in {be_file.name if be_file else 'backend'}."
                        )

            # 3.2 Response Shape Envelope Analysis (Section 3.2 - 3.4)
            fetch_iter = list(re.finditer(r"""(?:fetch|api\.(?:get|post|put|delete))\s*\(\s*['"`]([^'"`]+)['"`]""", js_content))
            for fm in fetch_iter:
                raw_url = fm.group(1)
                norm_url = re.sub(r'/[0-9]+', '/{id}', raw_url)
                norm_url = re.sub(r'/\$\{[^}]+\}', '/{id}', norm_url).split("?")[0]
                
                snippet = js_content[fm.start():fm.start() + 1000]
                req_method = "GET"
                method_m = re.search(r"""method\s*:\s*['"`](GET|POST|PUT|DELETE|PATCH)['"`]""", snippet, re.I)
                if method_m:
                    req_method = method_m.group(1).upper()

                shape = backend_response_shapes.get((req_method, norm_url)) or backend_response_shapes.get(("GET", norm_url))
                if not shape:
                    continue

                # Parse how response is unpacked in JavaScript
                await_json = re.search(r'(?:const|let|var)\s+([a-zA-Z0-9_{},\s]+)\s*=\s*await\s+([a-zA-Z0-9_]+)\.json\(\)', snippet)
                then_json = re.search(r'\.then\s*\(\s*(?:async\s*)?\s*\(?\s*([a-zA-Z0-9_{},\s]+)\s*\)?\s*=>', snippet)

                target_var = None
                is_destructured = False
                destructured_props = []

                if await_json:
                    lhs = await_json.group(1).strip()
                    if lhs.startswith("{") and lhs.endswith("}"):
                        is_destructured = True
                        destructured_props = [x.strip() for x in lhs.strip("{}").split(",") if x.strip()]
                    else:
                        target_var = lhs
                elif then_json:
                    lhs = then_json.group(1).strip()
                    if lhs.startswith("{") and lhs.endswith("}"):
                        is_destructured = True
                        destructured_props = [x.strip() for x in lhs.strip("{}").split(",") if x.strip()]
                    else:
                        target_var = lhs

                if shape["root_type"] == "object" and shape["envelope_properties"]:
                    env_props = shape["envelope_properties"]
                    if is_destructured:
                        if not any(ep in destructured_props for ep in env_props):
                            msg = (
                                f"API_RESPONSE_SHAPE_MISMATCH: Route '{req_method} {norm_url}' returns an Object envelope "
                                f"with properties {env_props}, but frontend {js_file.name} destructures {destructured_props}."
                            )
                            response_shape_mismatches.append(msg)
                    elif target_var:
                        # Check if target_var accesses .<env_prop>
                        accesses_env = (
                            any(f"{target_var}.{ep}" in snippet for ep in env_props) or
                            any(f"{target_var}['{ep}']" in snippet for ep in env_props) or
                            any(f'{target_var}["{ep}"]' in snippet for ep in env_props)
                        )
                        if accesses_env:
                            continue

                        # Check if target_var is directly used with array operations
                        array_ops = re.findall(rf'\b{target_var}\.(forEach|map|filter|reduce|find|findIndex|some|every|slice|length)\b', snippet)
                        for_of = re.findall(rf'for\s*\(\s*(?:const|let|var)\s+[a-zA-Z0-9_]+\s+of\s+{target_var}\b', snippet)

                        # Check if target_var is passed to a render function
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
                                f"but frontend {js_file.name} treats the response as a raw Array directly on '{target_var}' (invokes '{direct_ops[0]}'). "
                                f"Frontend must access '{target_var}.{env_props[0]}' or destructure 'const {{ {env_props[0]} }} = await ...json()'."
                            )
                            response_shape_mismatches.append(msg)

                elif shape["root_type"] == "array":
                    # Backend returns raw array, but frontend assumes object envelope
                    if target_var:
                        accessed_props = re.findall(rf'\b{target_var}\.([a-zA-Z0-9_]+)\.(forEach|map|filter)\b', snippet)
                        if accessed_props:
                            msg = (
                                f"API_RESPONSE_SHAPE_MISMATCH: Backend route '{req_method} {norm_url}' returns a raw Array, "
                                f"but frontend {js_file.name} accesses envelope property '{accessed_props[0][0]}'."
                            )
                            response_shape_mismatches.append(msg)

        # 4. Verify HTML Script and Stylesheet Path Resolution
        if html_file and html_file.exists():
            html_content = html_file.read_text(encoding="utf-8", errors="ignore")
            base_html_dir = html_file.parent

            # Extract scripts
            script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_content, re.I)
            for src in script_srcs:
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
                if not any(c.exists() for c in cands):
                    html_asset_mismatches.append(
                        f"Broken script link in {html_file.name}: src='{src}' does not resolve to an existing file."
                    )

            # Extract stylesheets
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

        # 5. Verify DOM ID Alignment (HTML vs JS)
        if html_file and html_file.exists() and js_file and js_file.exists():
            html_content = html_file.read_text(encoding="utf-8", errors="ignore")
            js_content = js_file.read_text(encoding="utf-8", errors="ignore")

            defined_html_ids = set(re.findall(r'id=["\']([a-zA-Z0-9_\-]+)["\']', html_content))
            referenced_js_ids = set(
                re.findall(r'getElementById\([\'"]([a-zA-Z0-9_\-]+)[\'"]\)', js_content)
                + re.findall(r'querySelector\([\'"]#([a-zA-Z0-9_\-]+)[\'"]\)', js_content)
            )

            details["html_ids_count"] = len(defined_html_ids)
            details["js_referenced_ids_count"] = len(referenced_js_ids)

            dynamic_js_ids = set(
                re.findall(r'(?:\.id\s*=\s*|\.setAttribute\(\s*[\'"]id[\'"]\s*,\s*)[\'"]([a-zA-Z0-9_\-]+)[\'"]', js_content)
            )
            all_defined_ids = defined_html_ids | dynamic_js_ids

            for js_id in referenced_js_ids:
                if js_id not in all_defined_ids:
                    dom_id_mismatches.append(
                        f"DOM ID mismatch: {js_file.name} references '#{js_id}', but no element with id='{js_id}' exists in {html_file.name}."
                    )
                    discrepancies.append(
                        ContractDiscrepancy(
                            type="DOM_CONTRACT_MISMATCH",
                            responsible_artifact=html_file.name,
                            consuming_artifact=js_file.name,
                            mismatch=f"Element id '{js_id}' referenced in {js_file.name} not found in {html_file.name}",
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

                # Check CSS classes used in HTML
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

        # 9. Populate structured discrepancies
        discrepancies: List[ContractDiscrepancy] = []
        html_rel = str(html_file.relative_to(ws)) if html_file else "index.html"
        js_rel = str(js_file.relative_to(ws)) if js_file else "app.js"
        css_rel = str(css_file.relative_to(ws)) if css_file else "style.css"
        be_rel = str(be_file.relative_to(ws)) if be_file else "main.py"

        for em in endpoint_mismatches:
            discrepancies.append(ContractDiscrepancy(type="API_ROUTE_MISMATCH", responsible_artifact=be_rel, consuming_artifact=js_rel, mismatch=em, confidence="HIGH"))
        for rsm in response_shape_mismatches:
            discrepancies.append(ContractDiscrepancy(type="API_RESPONSE_SHAPE_MISMATCH", responsible_artifact=be_rel, consuming_artifact=js_rel, mismatch=rsm, confidence="HIGH", failure_class="API_RESPONSE_SHAPE_MISMATCH"))
        for dm in dom_id_mismatches:
            discrepancies.append(ContractDiscrepancy(type="DOM_CONTRACT_MISMATCH", responsible_artifact=html_rel, consuming_artifact=js_rel, mismatch=dm, confidence="HIGH"))
        for am in html_asset_mismatches:
            discrepancies.append(ContractDiscrepancy(type="BROKEN_ASSET_LINK", responsible_artifact=html_rel, consuming_artifact="filesystem", mismatch=am, confidence="HIGH"))
        for dbm in database_mismatches:
            target_db_name = target_db.name if 'target_db' in locals() and target_db else "database"
            discrepancies.append(ContractDiscrepancy(type="DATABASE_SCHEMA_MISMATCH", responsible_artifact=target_db_name, consuming_artifact=be_rel, mismatch=dbm, confidence="HIGH"))

        # 10. Determine Overall Gate Severity
        has_fatal = bool(endpoint_mismatches or response_shape_mismatches or html_asset_mismatches or dom_id_mismatches or database_mismatches or startup_mismatches)
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
            warnings=warnings,
            uncertainties=uncertainties,
            discrepancies=discrepancies,
            details=details,
        )
