import re
from pathlib import Path

p = Path("core/cross_file_contract.py")
content = p.read_text(encoding="utf-8").replace('\r\n', '\n')

# Let's inspect CrossFileContractValidator class definition
target_validator_class = '''class CrossFileContractValidator:
    """Performs static cross-file contract analysis (Phase C)."""

    @classmethod
    def validate_workspace(
        cls,
        workspace_root: Path | str,
        current_phase: Optional[str] = None,
    ) -> CrossFileContractReport:'''

replacement_validator_class = '''class CrossFileContractValidator:
    """Performs static cross-file contract analysis (Phase C)."""

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
            "hard_errors": report.endpoint_mismatches + report.html_asset_mismatches + report.dom_id_mismatches + report.database_mismatches + report.startup_mismatches,
            "warnings": report.warnings,
            "discrepancies": [d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in report.discrepancies],
            "summary": report.summary,
        }

    @classmethod
    def validate_workspace(
        cls,
        workspace_root: Path | str,
        current_phase: Optional[str] = None,
    ) -> CrossFileContractReport:'''

assert target_validator_class in content, "Could not find target_validator_class"
content = content.replace(target_validator_class, replacement_validator_class, 1)

# Now router prefix and route extraction
route_extraction_target = '''        # 2. Extract Backend Routes via Python AST (Phase C3)
        backend_routes: Dict[str, Set[str]] = {}  # {path_pattern: set(HTTP_METHODS)}
        if be_file and be_file.exists():
            try:
                tree = ast.parse(be_file.read_text(encoding="utf-8", errors="ignore"), filename=be_file.name)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for dec in node.decorator_list:
                            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                                attr = dec.func.attr.upper()
                                if attr in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                                    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                        route_path = dec.args[0].value
                                        backend_routes.setdefault(route_path, set()).add(attr)
            except Exception as e:
                uncertainties.append(f"Failed to fully parse {be_file.name} AST for route contracts: {e}")'''

route_extraction_replacement = '''        # 2. Extract Backend Routes via Python AST (Phase C3)
        backend_routes: Dict[str, Set[str]] = {}  # {path_pattern: set(HTTP_METHODS)}
        if be_file and be_file.exists():
            try:
                tree = ast.parse(be_file.read_text(encoding="utf-8", errors="ignore"), filename=be_file.name)
                # Detect APIRouter prefixes and include_router calls
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
            except Exception as e:
                uncertainties.append(f"Failed to fully parse {be_file.name} AST for route contracts: {e}")'''

assert route_extraction_target in content, "Could not find route_extraction_target"
content = content.replace(route_extraction_target, route_extraction_replacement, 1)

# Now frontend api call check to detect method mismatches
call_check_target = r'''                if not matched:
                    path_no_query = path.split("?")[0]
                    norm_no_query = re.sub(r'/[0-9]+', '/{id}', path_no_query)
                    for b_route, b_methods in backend_routes.items():
                        norm_b_route = re.sub(r'\{[a-zA-Z0-9_]+\}', '{id}', b_route)
                        if norm_no_query == norm_b_route:
                            matched = True
                            break

                if not matched:
                    # Check if dynamic expression
                    if "{" in path and "}" in path and not re.search(r'\{id\}', path):
                        uncertainties.append(f"Dynamic API call in {js_file.name}: '{method} {path}' cannot be verified statically")
                    else:
                        endpoint_mismatches.append(
                            f"Frontend route mismatch: {js_file.name} calls '{method} {path}', "
                            f"but no matching FastAPI route exists in {be_file.name if be_file else 'backend'}."
                        )'''

call_check_replacement = r'''                if not matched:
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
                                    f"HTTP method mismatch: {js_file.name} calls '{method} {path}', "
                                    f"but FastAPI route '{b_route}' only accepts {sorted(list(b_methods))}."
                                )
                                matched = True
                                break

                if not matched:
                    # Check if dynamic expression
                    if "{" in path and "}" in path and not re.search(r'\{id\}', path):
                        uncertainties.append(f"Dynamic API call in {js_file.name}: '{method} {path}' cannot be verified statically")
                    else:
                        endpoint_mismatches.append(
                            f"Frontend route mismatch: {js_file.name} calls '{method} {path}', "
                            f"but no matching FastAPI route exists in {be_file.name if be_file else 'backend'}."
                        )'''

assert call_check_target in content, "Could not find call_check_target"
content = content.replace(call_check_target, call_check_replacement, 1)

# Now dynamic DOM creation check in JS
js_dom_target = r'''            # 5. Check JS DOM queries against HTML IDs (Phase C1)
            if js_file and js_file.exists() and html_ids:
                js_content = js_file.read_text(encoding="utf-8", errors="ignore")
                geb_ids = set(re.findall(r'getElementById\(["\']([a-zA-Z0-9_\-]+)["\']\)', js_content))
                qs_ids = set(re.findall(r'querySelector(?:All)?\(["\']#([a-zA-Z0-9_\-]+)["\']\)', js_content))
                queried_ids = geb_ids.union(qs_ids)

                # Declared dynamic IDs from contract
                declared_dynamic_ids = set(getattr(contract, "dynamic_ids", []))

                for qid in queried_ids:
                    if qid in declared_dynamic_ids:
                        continue
                    if qid not in html_ids:
                        # Check if defined in template strings or innerHTML in JS
                        if f'id="{qid}"' not in js_content and f"id='{qid}'" not in js_content and f"id=`{qid}`" not in js_content:
                            # If it looks like a dynamic interpolation, flag as uncertainty rather than hard fail
                            if "${" in qid:
                                uncertainties.append(f"Dynamic DOM ID query '#{qid}' in {js_file.name} cannot be verified statically")
                            else:
                                dom_id_mismatches.append(
                                    f"DOM ID mismatch: {js_file.name} queries '#{qid}', "
                                    f"but element #{qid} is missing from {html_file.name} and declared templates."
                                )'''

js_dom_replacement = r'''            # 5. Check JS DOM queries against HTML IDs (Phase C1)
            if js_file and js_file.exists() and html_ids:
                js_content = js_file.read_text(encoding="utf-8", errors="ignore")
                geb_ids = set(re.findall(r'getElementById\(["\']([a-zA-Z0-9_\-]+)["\']\)', js_content))
                qs_ids = set(re.findall(r'querySelector(?:All)?\(["\']#([a-zA-Z0-9_\-]+)["\']\)', js_content))
                queried_ids = geb_ids.union(qs_ids)

                # Dynamically created elements in JS (e.g. createElement, .id = "...", innerHTML)
                dynamic_js_ids = set(re.findall(r'\.id\s*=\s*["\']([a-zA-Z0-9_\-]+)["\']', js_content))
                dynamic_js_ids.update(re.findall(r'id=["\']([a-zA-Z0-9_\-]+)["\']', js_content))

                # Declared dynamic IDs from contract
                declared_dynamic_ids = set(getattr(contract, "dynamic_ids", [])).union(dynamic_js_ids)

                for qid in queried_ids:
                    if qid in declared_dynamic_ids:
                        continue
                    if qid not in html_ids:
                        # Check if defined in template strings or innerHTML in JS
                        if f'id="{qid}"' not in js_content and f"id='{qid}'" not in js_content and f"id=`{qid}`" not in js_content:
                            # If it looks like a dynamic interpolation, flag as uncertainty rather than hard fail
                            if "${" in qid:
                                uncertainties.append(f"Dynamic DOM ID query '#{qid}' in {js_file.name} cannot be verified statically")
                            else:
                                dom_id_mismatches.append(
                                    f"DOM ID mismatch: {js_file.name} queries '#{qid}', "
                                    f"but element #{qid} is missing from {html_file.name} and declared templates."
                                )'''

assert js_dom_target in content, "Could not find js_dom_target"
content = content.replace(js_dom_target, js_dom_replacement, 1)

# Populate discrepancies and CSS classes verification
final_block_target = '''        # 9. Determine Overall Gate Severity (Phase C6)
        has_fatal = bool(endpoint_mismatches or html_asset_mismatches or dom_id_mismatches or database_mismatches or startup_mismatches)
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
            html_asset_mismatches=html_asset_mismatches,
            dom_id_mismatches=dom_id_mismatches,
            css_mismatches=css_mismatches,
            database_mismatches=database_mismatches,
            startup_mismatches=startup_mismatches,
            warnings=warnings,
            uncertainties=uncertainties,
            details=details,
        )'''

final_block_replacement = '''        # 8b. CSS Classes verification (HTML classes vs CSS selectors)
        if html_file and html_file.exists() and css_file and css_file.exists():
            try:
                css_txt = css_file.read_text(encoding="utf-8", errors="ignore")
                defined_css_classes = set(re.findall(r'\.([a-zA-Z0-9_\-]+)', css_txt))
                html_txt = html_file.read_text(encoding="utf-8", errors="ignore")
                html_classes = set()
                for cm in re.findall(r'class=["\']([^"\']+)["\']', html_txt):
                    for c in cm.split():
                        if c.strip():
                            html_classes.add(c.strip())

                VALID_UTILITY_CLASSES = {
                    "container", "card", "btn", "btn-primary", "btn-secondary", "flex", "grid",
                    "row", "col", "hidden", "active", "modal", "header", "footer", "nav",
                    "title", "content", "app", "form-group", "badge", "text-center", "dark", "light"
                }
                for hc in html_classes:
                    if hc in defined_css_classes or hc in VALID_UTILITY_CLASSES:
                        continue
                    if any(hc.startswith(pre) for pre in ("col-", "row-", "text-", "bg-", "p-", "m-", "d-", "align-", "justify-")):
                        continue
                    css_mismatches.append(f"CSS class '{hc}' used in {html_file.name} is not defined in {css_file.name}")
            except Exception as e:
                uncertainties.append(f"Notice inspecting CSS classes: {e}")

        # 9. Populate structured discrepancies
        discrepancies: List[ContractDiscrepancy] = []
        html_rel = str(html_file.relative_to(ws)) if html_file else "index.html"
        js_rel = str(js_file.relative_to(ws)) if js_file else "app.js"
        css_rel = str(css_file.relative_to(ws)) if css_file else "style.css"
        be_rel = str(be_file.relative_to(ws)) if be_file else "main.py"

        for em in endpoint_mismatches:
            discrepancies.append(ContractDiscrepancy(type="API_ROUTE_MISMATCH", responsible_artifact=be_rel, consuming_artifact=js_rel, mismatch=em, confidence="HIGH"))
        for dm in dom_id_mismatches:
            discrepancies.append(ContractDiscrepancy(type="DOM_CONTRACT_MISMATCH", responsible_artifact=html_rel, consuming_artifact=js_rel, mismatch=dm, confidence="HIGH"))
        for am in html_asset_mismatches:
            discrepancies.append(ContractDiscrepancy(type="BROKEN_ASSET_LINK", responsible_artifact=html_rel, consuming_artifact="filesystem", mismatch=am, confidence="HIGH"))
        for dbm in database_mismatches:
            target_db_name = target_db.name if 'target_db' in locals() and target_db else "database"
            discrepancies.append(ContractDiscrepancy(type="DATABASE_SCHEMA_MISMATCH", responsible_artifact=target_db_name, consuming_artifact=be_rel, mismatch=dbm, confidence="HIGH"))
        for cm in css_mismatches:
            discrepancies.append(ContractDiscrepancy(type="CSS_MISMATCH", responsible_artifact=css_rel, consuming_artifact=html_rel, mismatch=cm, confidence="HIGH"))

        # 10. Determine Overall Gate Severity (Phase C6)
        has_fatal = bool(endpoint_mismatches or html_asset_mismatches or dom_id_mismatches or database_mismatches or startup_mismatches or css_mismatches)
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
            html_asset_mismatches=html_asset_mismatches,
            dom_id_mismatches=dom_id_mismatches,
            css_mismatches=css_mismatches,
            database_mismatches=database_mismatches,
            startup_mismatches=startup_mismatches,
            warnings=warnings,
            uncertainties=uncertainties,
            discrepancies=discrepancies,
            details=details,
        )'''

assert final_block_target in content, "Could not find final_block_target"
content = content.replace(final_block_target, final_block_replacement, 1)

p.write_text(content, encoding="utf-8")
print("Successfully patched core/cross_file_contract.py")
