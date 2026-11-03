import re
from pathlib import Path

contract_path = Path("core/project_contract.py")
content = contract_path.read_text(encoding="utf-8")

# 1. Add from_dict to DeclaredInterfaces
decl_target = '''    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)'''

decl_replacement = '''    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DeclaredInterfaces":
        if not d:
            return cls()
        return cls(
            dom_ids=list(d.get("dom_ids", [])),
            views=list(d.get("views", [])),
            classes=list(d.get("classes", [])),
            css_variables=list(d.get("css_variables", [])),
            api_routes=list(d.get("api_routes", [])),
            database_tables=dict(d.get("database_tables", {})),
            storage_keys=dict(d.get("storage_keys", {})),
        )'''

assert decl_target in content, "Could not find decl_target"
content = content.replace(decl_target, decl_replacement, 1)

# 2. Add from_dict to ObservedInterfaces
obs_target = '''    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)'''

# Find the second occurrence for ObservedInterfaces
first_idx = content.find(obs_target)
second_idx = content.find(obs_target, first_idx + len(decl_replacement))
assert second_idx != -1, "Could not find second to_dict for ObservedInterfaces"

obs_replacement = '''    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ObservedInterfaces":
        if not d:
            return cls()
        return cls(
            html_ids=list(d.get("html_ids", [])),
            html_classes=list(d.get("html_classes", [])),
            form_names=list(d.get("form_names", [])),
            css_selectors=list(d.get("css_selectors", [])),
            css_variables=list(d.get("css_variables", [])),
            js_references=list(d.get("js_references", [])),
            backend_routes=dict(d.get("backend_routes", {})),
            database_tables=dict(d.get("database_tables", {})),
            artifact_hashes=dict(d.get("artifact_hashes", {})),
            observed_at=float(d.get("observed_at", time.time())),
        )'''

content = content[:second_idx] + obs_replacement + content[second_idx + len(obs_target):]

# 3. Update to_dict and from_dict in ProjectContract
proj_to_dict_target = '''            "creation_provenance": dict(self.creation_provenance),
            "migration_provenance": dict(self.migration_provenance) if self.migration_provenance else None,
        }'''

proj_to_dict_replacement = '''            "creation_provenance": dict(self.creation_provenance),
            "migration_provenance": dict(self.migration_provenance) if self.migration_provenance else None,
            "declared_interfaces": self.declared_interfaces.to_dict() if hasattr(self.declared_interfaces, "to_dict") else dict(self.declared_interfaces),
            "observed_interfaces": self.observed_interfaces.to_dict() if hasattr(self.observed_interfaces, "to_dict") else dict(self.observed_interfaces),
        }'''

assert proj_to_dict_target in content, "Could not find proj_to_dict_target"
content = content.replace(proj_to_dict_target, proj_to_dict_replacement, 1)

proj_from_dict_target = '''            contract_hash=data.get("contract_hash", ""),
            creation_provenance=data.get("creation_provenance", {}),
            migration_provenance=data.get("migration_provenance"),
        )'''

proj_from_dict_replacement = '''            contract_hash=data.get("contract_hash", ""),
            creation_provenance=data.get("creation_provenance", {}),
            migration_provenance=data.get("migration_provenance"),
            declared_interfaces=DeclaredInterfaces.from_dict(data.get("declared_interfaces", {})) if "declared_interfaces" in data else DeclaredInterfaces(
                dom_ids=list(data.get("required_ids", [])),
                classes=list(data.get("required_classes", [])),
                css_variables=list(data.get("css_custom_properties", [])),
                api_routes=list(data.get("api_endpoints", [])),
                database_tables=dict(data.get("database_tables", {})),
                storage_keys=dict(data.get("storage_keys", {})),
            ),
            observed_interfaces=ObservedInterfaces.from_dict(data.get("observed_interfaces", {})) if "observed_interfaces" in data else ObservedInterfaces(),
        )'''

assert proj_from_dict_target in content, "Could not find proj_from_dict_target"
content = content.replace(proj_from_dict_target, proj_from_dict_replacement, 1)

# 4. Fix regex syntax error in reconcile_observed
reconcile_bad = """                js_ids = re.findall(r'getElementById\\(["']([a-zA-Z0-9_\\-]+)["']\\)', js_txt)
                js_qs = re.findall(r'querySelector(?:All)?\\(["']#([a-zA-Z0-9_\\-]+)["']\\)', js_txt)"""

reconcile_good = """                js_ids = re.findall(r'getElementById\\([\\'"]([a-zA-Z0-9_\\-]+)[\\'"]\\)', js_txt)
                js_qs = re.findall(r'querySelector(?:All)?\\([\\'"]#([a-zA-Z0-9_\\-]+)[\\'"]\\)', js_txt)"""

assert reconcile_bad in content, "Could not find reconcile_bad"
content = content.replace(reconcile_bad, reconcile_good, 1)

# 5. Ambiguous layout detection
ambig_target = '''        # Handle ambiguity without creating duplicates
        if has_static_index and has_root_index:
            logger.info("ProjectContract: Both root and static index.html exist. Inspecting mounts to disambiguate.")
            if has_static_mount or backend_file:
                selected_layout = "static"
            else:
                selected_layout = "root"'''

ambig_replacement = '''        # Handle ambiguity without creating duplicates
        if has_static_index and has_root_index:
            logger.info("ProjectContract: Both root and static index.html exist. Inspecting mounts to disambiguate.")
            if has_static_mount or ("static" in p_lower and "root" not in p_lower):
                selected_layout = "static"
            elif "root" in p_lower and "static" not in p_lower:
                selected_layout = "root"
            elif backend_file and has_static_mount:
                selected_layout = "static"
            elif not has_static_mount and not ("static" in p_lower or "root" in p_lower):
                # Return ambiguous error layout to prevent split-brain writes (Section 5.1)
                canonical_js_name = cls.determine_canonical_js(prompt, ws, layout="root")
                return "ambiguous", {
                    "error": "WORKSPACE_LAYOUT_AMBIGUOUS",
                    "message": "Both root and static index.html exist without mount or prompt cues to disambiguate.",
                    "canonical_html": "index.html",
                    "canonical_css": "style.css",
                    "canonical_js": canonical_js_name,
                }
            else:
                selected_layout = "static" if (has_static_mount or backend_file) else "root"'''

assert ambig_target in content, "Could not find ambig_target"
content = content.replace(ambig_target, ambig_replacement, 1)

contract_path.write_text(content, encoding="utf-8")
print("Successfully patched core/project_contract.py")
