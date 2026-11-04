# core/project_contract.py
"""
Versioned Project Contract, Layout Detection, and Canonical Path Resolution for HERMES 2.x.
Ensures multi-file consistency, canonical entrypoint resolution across root and static/ layouts,
safe path resolution rejecting directory traversal and out-of-workspace escapes,
and stale contract reconciliation across missions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class CanonicalPathResolver:
    """
    Unified Canonical Path Resolver (Phase B3).
    All artifact planners, file tools, scaffold checks, validators, recovery operations,
    and contract verifiers must use this resolver to guarantee consistent path definitions.
    """

    @staticmethod
    def normalize_slashes(path_str: str) -> str:
        """Normalize Windows backslashes to forward slashes and strip leading ./."""
        s = path_str.replace("\\", "/").strip()
        if s.startswith("./"):
            s = s[2:]
        return s

    @classmethod
    def resolve(cls, workspace_root: Path | str, path_input: Path | str) -> Path:
        """Alias for resolve_workspace_path."""
        return cls.resolve_workspace_path(workspace_root, path_input)

    @classmethod
    def resolve_workspace_path(
        cls,
        workspace_root: Path | str,
        path_input: Path | str,
        allow_symlinks_outside: bool = False,
    ) -> Path:
        """
        Safely resolve a path against the active workspace root.
        Rejects:
          - Paths that escape workspace via ../ traversal.
          - Absolute paths pointing outside workspace.
          - Symlinks resolving outside workspace (unless allow_symlinks_outside=True).
        Raises ValueError on escape; never returns an external path's basename as fallback.
        """
        ws = Path(workspace_root).resolve()
        raw_str = str(path_input).strip()
        norm_str = cls.normalize_slashes(raw_str)

        # Check for explicit traversal attempts
        parts = Path(norm_str).parts
        if ".." in parts:
            raise ValueError(f"Path traversal ('..') is strictly prohibited: {path_input}")

        p = Path(raw_str)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (ws / norm_str).resolve()

        # Workspace containment verification
        try:
            resolved.relative_to(ws)
        except ValueError:
            raise ValueError(f"Path '{path_input}' resolves outside active workspace root '{ws}'")

        return resolved

    @classmethod
    def get_workspace_relative(cls, workspace_root: Path | str, path_input: Path | str) -> str:
        """Resolve path and return forward-slash workspace-relative string."""
        resolved = cls.resolve_workspace_path(workspace_root, path_input)
        ws = Path(workspace_root).resolve()
        return cls.normalize_slashes(str(resolved.relative_to(ws)))

    @classmethod
    def is_safe_path(cls, workspace_root: Path | str, path_input: Path | str) -> bool:
        """Check if path is safely contained within workspace without raising."""
        try:
            cls.resolve_workspace_path(workspace_root, path_input)
            return True
        except (ValueError, Exception):
            return False

    @classmethod
    def resolve_canonical_alias(
        cls,
        workspace_root: Path | str,
        requested_path: str,
        contract: ProjectContract,
    ) -> str:
        """
        Map explicit canonical artifact aliases to declared canonical paths (Phase B3).
        Only maps exact entrypoint aliases (e.g. 'index.html' -> 'static/index.html' if static layout).
        Never maps arbitrary nested files sharing a basename (e.g. 'admin/index.html' remains 'admin/index.html').
        """
        norm = cls.normalize_slashes(requested_path)
        base = Path(norm).name.lower()

        # If already matching canonical relative path, return directly
        if norm in (contract.canonical_html, contract.canonical_css, contract.canonical_js):
            return norm

        # Only alias if the request was for the top-level artifact name directly
        if "/" not in norm:
            if base == "index.html" and contract.canonical_html:
                return contract.canonical_html
            if base in ("style.css", "main.css") and contract.canonical_css:
                return contract.canonical_css
            if base in ("app.js", "main.js", "index.js") and contract.canonical_js:
                return contract.canonical_js

        return norm


@dataclass
class FormFieldContract:
    field_name: str
    control_id: Optional[str] = None
    input_type: str = "text"
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
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
        )


@dataclass
class ApiEndpointContract:
    path: str
    method: str = "GET"
    request_fields: List[str] = field(default_factory=list)
    response_fields: List[str] = field(default_factory=list)
    response_status: int = 200
    content_type: str = "application/json"
    response_root_type: str = "object"  # "object", "array", "primitive", "unknown"
    envelope_properties: List[str] = field(default_factory=list)
    array_item_schema: Optional[Dict[str, Any]] = None
    responses: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ApiEndpointContract":
        if not d:
            return cls(path="")
        return cls(
            path=d.get("path", ""),
            method=d.get("method", "GET"),
            request_fields=list(d.get("request_fields", [])),
            response_fields=list(d.get("response_fields", [])),
            response_status=int(d.get("response_status", 200)),
            content_type=d.get("content_type", "application/json"),
            response_root_type=d.get("response_root_type", "object"),
            envelope_properties=list(d.get("envelope_properties", [])),
            array_item_schema=d.get("array_item_schema"),
            responses=dict(d.get("responses", {})),
            description=d.get("description", ""),
        )


@dataclass
class DeclaredInterfaces:
    """Intended application contract: what HERMES intends to build (Section 5.2)."""
    dom_ids: List[str] = field(default_factory=list)
    views: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    css_variables: List[str] = field(default_factory=list)
    api_routes: List[Dict[str, Any]] = field(default_factory=list)
    database_tables: Dict[str, List[str]] = field(default_factory=dict)
    storage_keys: Dict[str, str] = field(default_factory=dict)
    response_schemas: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
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
            response_schemas=dict(d.get("response_schemas", {})),
        )


@dataclass
class ObservedInterfaces:
    """Observed application state: what the physical generated files currently contain (Section 5.2)."""
    html_ids: List[str] = field(default_factory=list)
    html_classes: List[str] = field(default_factory=list)
    form_names: List[str] = field(default_factory=list)
    css_selectors: List[str] = field(default_factory=list)
    css_variables: List[str] = field(default_factory=list)
    js_references: List[str] = field(default_factory=list)
    backend_routes: Dict[str, List[str]] = field(default_factory=dict)
    database_tables: Dict[str, List[str]] = field(default_factory=dict)
    artifact_hashes: Dict[str, str] = field(default_factory=dict)
    response_schemas: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
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
            response_schemas=dict(d.get("response_schemas", {})),
            observed_at=float(d.get("observed_at", time.time())),
        )


@dataclass
class ProjectContract:
    """
    Authoritative, versioned contract governing application topology,
    canonical entrypoints, DOM identifiers, form fields, API routes, and database schemas (Phase B1).
    """
    version: int = 2
    mission_id: str = ""
    workspace_identity: str = ""
    app_name: str = "Application"
    app_type: str = "vanilla_web"
    project_layout: str = "root"  # "root", "static", or "custom"
    is_greenfield: bool = True
    canonical_html: str = "index.html"
    canonical_js: str = "app.js"
    canonical_css: str = "style.css"
    canonical_backend: Optional[str] = None
    package_json_entry: Optional[str] = None
    required_files: List[str] = field(default_factory=lambda: ["index.html", "style.css", "app.js"])
    required_ids: List[str] = field(default_factory=list)
    required_classes: List[str] = field(default_factory=list)
    dynamic_ids: List[str] = field(default_factory=list)
    dynamic_classes: List[str] = field(default_factory=list)
    css_custom_properties: List[str] = field(default_factory=list)
    form_fields: Dict[str, FormFieldContract] = field(default_factory=dict)
    api_endpoints: List[Dict[str, Any]] = field(default_factory=list)
    database_tables: Dict[str, List[str]] = field(default_factory=dict)
    storage_keys: Dict[str, str] = field(default_factory=dict)
    features: List[str] = field(default_factory=list)
    contract_hash: str = ""
    creation_provenance: Dict[str, Any] = field(default_factory=dict)
    migration_provenance: Optional[Dict[str, Any]] = None
    declared_interfaces: DeclaredInterfaces = field(default_factory=DeclaredInterfaces)
    observed_interfaces: ObservedInterfaces = field(default_factory=ObservedInterfaces)

    def __post_init__(self):
        if not self.contract_hash:
            self.contract_hash = self.compute_hash()

    def compute_hash(self) -> str:
        d = self.to_dict()
        d.pop("contract_hash", None)
        d.pop("migration_provenance", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "mission_id": self.mission_id,
            "workspace_identity": self.workspace_identity,
            "app_name": self.app_name,
            "app_type": self.app_type,
            "project_layout": self.project_layout,
            "is_greenfield": self.is_greenfield,
            "canonical_html": self.canonical_html,
            "canonical_js": self.canonical_js,
            "canonical_css": self.canonical_css,
            "canonical_backend": self.canonical_backend,
            "package_json_entry": self.package_json_entry,
            "required_files": list(self.required_files),
            "required_ids": list(self.required_ids),
            "required_classes": list(self.required_classes),
            "dynamic_ids": list(self.dynamic_ids),
            "dynamic_classes": list(self.dynamic_classes),
            "css_custom_properties": list(self.css_custom_properties),
            "form_fields": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.form_fields.items()},
            "api_endpoints": list(self.api_endpoints),
            "database_tables": {k: list(v) for k, v in self.database_tables.items()},
            "storage_keys": dict(self.storage_keys),
            "features": list(self.features),
            "contract_hash": self.contract_hash,
            "creation_provenance": dict(self.creation_provenance),
            "migration_provenance": dict(self.migration_provenance) if self.migration_provenance else None,
            "declared_interfaces": self.declared_interfaces.to_dict() if hasattr(self.declared_interfaces, "to_dict") else dict(self.declared_interfaces),
            "observed_interfaces": self.observed_interfaces.to_dict() if hasattr(self.observed_interfaces, "to_dict") else dict(self.observed_interfaces),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectContract:
        if not data:
            return cls()
        fields_map = {}
        for k, v in data.get("form_fields", {}).items():
            if isinstance(v, dict):
                fields_map[k] = FormFieldContract(**v)
            else:
                fields_map[k] = FormFieldContract(field_name=k)
        return cls(
            version=data.get("version", 2),
            mission_id=data.get("mission_id", ""),
            workspace_identity=data.get("workspace_identity", ""),
            app_name=data.get("app_name", "Application"),
            app_type=data.get("app_type", "vanilla_web"),
            project_layout=data.get("project_layout", "root"),
            is_greenfield=data.get("is_greenfield", True),
            canonical_html=data.get("canonical_html", "index.html"),
            canonical_js=data.get("canonical_js", "app.js"),
            canonical_css=data.get("canonical_css", "style.css"),
            canonical_backend=data.get("canonical_backend"),
            package_json_entry=data.get("package_json_entry"),
            required_files=data.get("required_files", ["index.html", "style.css", "app.js"]),
            required_ids=data.get("required_ids", []),
            required_classes=data.get("required_classes", []),
            dynamic_ids=data.get("dynamic_ids", []),
            dynamic_classes=data.get("dynamic_classes", []),
            css_custom_properties=data.get("css_custom_properties", []),
            form_fields=fields_map,
            api_endpoints=data.get("api_endpoints", []),
            database_tables=data.get("database_tables", {}),
            storage_keys=data.get("storage_keys", {}),
            features=data.get("features", []),
            contract_hash=data.get("contract_hash", ""),
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
        )

    @classmethod
    def detect_project_layout(
        cls,
        workspace_root: Path | str,
        prompt: str = "",
    ) -> Tuple[str, Dict[str, str]]:
        """
        Deterministic layout selection (Phase B2).
        Selection order:
          1. Explicit project-planner layout declaration (via prompt or config cues).
          2. Existing actual entrypoints and established project structure (static/ vs root).
          3. Existing backend static mount (e.g. app.mount('/static', ...)).
          4. Project-type conventions for genuinely new workspace.
        Returns: (layout_name, canonical_paths_dict)
        """
        ws = Path(workspace_root).resolve()
        p_lower = (prompt or "").lower()

        # Check backend files first
        backend_file = None
        has_static_mount = False
        has_public_mount = False
        for b_cand in ("main.py", "app.py", "server.py", "server.js"):
            bp = ws / b_cand
            if bp.exists() and bp.stat().st_size > 30:
                backend_file = b_cand
                try:
                    b_txt = bp.read_text(encoding="utf-8", errors="ignore")
                    if re.search(r'mount\s*\(\s*["\']/static["\']', b_txt) or 'directory="static"' in b_txt or "directory='static'" in b_txt or "express.static('static')" in b_txt or 'express.static("static")' in b_txt:
                        has_static_mount = True
                    if "express.static('public')" in b_txt or 'express.static("public")' in b_txt or "express.static(path.join(__dirname, 'public'))" in b_txt or 'express.static(path.join(__dirname, "public"))' in b_txt or re.search(r'mount\s*\(\s*["\']/public["\']', b_txt):
                        has_public_mount = True
                except Exception:
                    pass
                break

        # Also inspect prompt if file does not exist yet on disk
        if not backend_file:
            for b_cand in ("main.py", "app.py", "server.py", "server.js"):
                if b_cand in p_lower:
                    backend_file = b_cand
                    break

        # Check existing actual entrypoints on disk
        has_public_index = (ws / "public" / "index.html").exists() and (ws / "public" / "index.html").stat().st_size > 10
        has_static_index = (ws / "static" / "index.html").exists() and (ws / "static" / "index.html").stat().st_size > 10
        has_root_index = (ws / "index.html").exists() and (ws / "index.html").stat().st_size > 10

        # Handle disambiguation and layout selection prioritizing explicit backend mounts
        if has_public_mount or (has_public_index and not has_static_mount):
            selected_layout = "public"
        elif has_static_mount:
            selected_layout = "static"
        elif has_static_index and has_root_index:
            logger.info("ProjectContract: Both root and static index.html exist. Inspecting mounts and backend files to disambiguate.")
            if ("static" in p_lower and "root" not in p_lower) or backend_file:
                selected_layout = "static"
            elif "root" in p_lower and "static" not in p_lower:
                selected_layout = "root"
            else:
                selected_layout = "static" if backend_file else "root"
        elif has_public_index:
            selected_layout = "public"
        elif has_static_index:
            selected_layout = "static"
        elif has_root_index:
            selected_layout = "root"
        elif backend_file or any(k in p_lower for k in ("fastapi", "fullstack", "full-stack", "backend", "sqlite")):
            # If Express explicitly mounts public, use public, else default to static
            selected_layout = "public" if has_public_mount else "static"
        else:
            selected_layout = "root"

        # Determine canonical JS entrypoint name
        canonical_js_name = cls.determine_canonical_js(prompt, ws, layout=selected_layout)

        if selected_layout == "public":
            paths = {
                "canonical_html": "public/index.html",
                "canonical_css": "public/style.css",
                "canonical_js": f"public/{canonical_js_name}",
                "canonical_backend": backend_file,
            }
        elif selected_layout == "static":
            paths = {
                "canonical_html": "static/index.html",
                "canonical_css": "static/style.css",
                "canonical_js": f"static/{canonical_js_name}",
                "canonical_backend": backend_file,
            }
        else:
            paths = {
                "canonical_html": "index.html",
                "canonical_css": "style.css",
                "canonical_js": canonical_js_name,
                "canonical_backend": backend_file,
            }

        return selected_layout, paths

    @classmethod
    def determine_canonical_js(
        cls,
        prompt: str = "",
        workspace_root: Optional[Path | str] = None,
        layout: str = "root",
    ) -> str:
        """
        Deterministically resolve the canonical JavaScript entrypoint name:
        1. Explicit user prompt request (e.g. 'app.js' vs 'main.js')
        2. Existing index.html <script src="..."> reference (checking both static/ and root)
        3. Existing package.json 'main' field
        4. Existing file on disk in workspace
        5. Default: 'app.js'
        """
        p_lower = (prompt or "").lower()
        ws = Path(workspace_root) if workspace_root else None

        has_app_js = "app.js" in p_lower
        has_main_js = "main.js" in p_lower
        if has_app_js and not has_main_js:
            return "app.js"
        if has_main_js and not has_app_js:
            return "main.js"

        # 2. Existing index.html on disk
        if ws:
            html_candidates = [
                ws / layout / "index.html" if layout in ("public", "static") else None,
                ws / "public" / "index.html",
                ws / "static" / "index.html",
                ws / "index.html",
            ]
            for html_path in filter(None, html_candidates):
                if html_path.exists():
                    try:
                        html_txt = html_path.read_text(encoding="utf-8", errors="ignore")
                        matches = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html_txt, re.I)
                        for m in matches:
                            if not m.startswith(("http://", "https://", "//")):
                                clean = Path(m.lstrip("./")).name
                                if clean in ("app.js", "main.js", "script.js", "index.js"):
                                    return clean
                    except Exception:
                        pass

        # 3. Existing package.json 'main' (client JS only, excluding backend server files)
        if ws and (ws / "package.json").exists():
            try:
                pkg = json.loads((ws / "package.json").read_text(encoding="utf-8", errors="ignore"))
                main_val = pkg.get("main")
                if main_val and isinstance(main_val, str) and main_val.endswith(".js"):
                    clean_main = Path(main_val.lstrip("./")).name
                    if clean_main not in ("server.js", "server.py", "app.py", "main.py"):
                        return clean_main
            except Exception:
                pass

        # 4. Existing file on disk
        if ws:
            search_dirs = [ws / layout] if layout in ("public", "static") else []
            search_dirs.extend([ws / "public", ws / "static", ws])
            for sdir in search_dirs:
                if sdir.exists():
                    for cand in ("app.js", "main.js", "index.js", "script.js"):
                        if (sdir / cand).exists() and (sdir / cand).stat().st_size > 20:
                            return cand

        return "app.js" if has_app_js else ("main.js" if has_main_js else "app.js")

    @classmethod
    def create_or_load(
        cls,
        workspace_root: Path | str,
        mission_id: str = "",
        prompt: str = "",
    ) -> ProjectContract:
        """
        Create or load the persistent project contract from workspace (Phase B4).
        Performs stale contract reconciliation: archives incompatible legacy contracts
        and creates a fresh, mission-bound contract when layout or mission differs.
        """
        ws = Path(workspace_root).resolve()
        contract_file = ws / ".hermes" / "project_contract.json"
        
        layout, paths = cls.detect_project_layout(ws, prompt)

        if contract_file.exists():
            try:
                data = json.loads(contract_file.read_text(encoding="utf-8", errors="ignore"))
                existing_contract = cls.from_dict(data)

                # Check for stale contract mismatch across missions (Phase B4)
                is_stale_mission = mission_id and existing_contract.mission_id and existing_contract.mission_id != mission_id
                is_layout_incompatible = existing_contract.project_layout != layout or existing_contract.canonical_html != paths["canonical_html"]

                if is_stale_mission or is_layout_incompatible:
                    logger.info(
                        f"ProjectContract: Stale contract detected (mission={existing_contract.mission_id}, "
                        f"layout={existing_contract.project_layout}). Reconciling for current mission {mission_id}."
                    )
                    # Archive stale contract
                    cls._archive_stale_contract(ws, existing_contract)

                    # Create reconciled contract bound to active mission
                    reconciled = cls(
                        version=existing_contract.version + 1,
                        mission_id=mission_id,
                        workspace_identity=str(ws),
                        app_name=existing_contract.app_name,
                        app_type=existing_contract.app_type,
                        project_layout=layout,
                        is_greenfield=False,
                        canonical_html=paths["canonical_html"],
                        canonical_js=paths["canonical_js"],
                        canonical_css=paths["canonical_css"],
                        canonical_backend=paths.get("canonical_backend"),
                        required_files=list(dict.fromkeys([
                            paths["canonical_html"],
                            paths["canonical_css"],
                            paths["canonical_js"],
                            *( [paths["canonical_backend"]] if paths.get("canonical_backend") else [] )
                        ])),
                        required_ids=list(existing_contract.required_ids),
                        required_classes=list(existing_contract.required_classes),
                        migration_provenance={
                            "archived_mission_id": existing_contract.mission_id,
                            "archived_contract_hash": existing_contract.contract_hash,
                            "reconciled_at": time.time(),
                        }
                    )
                    reconciled.save_to_workspace(ws)
                    return reconciled
                else:
                    if mission_id and not existing_contract.mission_id:
                        existing_contract.mission_id = mission_id
                        existing_contract.save_to_workspace(ws)
                    return existing_contract
            except Exception as e:
                logger.warning(f"ProjectContract: notice reading existing contract: {e}")

        # Derive new contract
        app_name = "Application"
        for name_match in re.findall(r'(?:called|named)\s+\*?\*?([A-Za-z0-9_\-]+)\*?\*?', prompt, re.I):
            app_name = name_match
            break

        required_files = [paths["canonical_html"], paths["canonical_css"], paths["canonical_js"]]
        if paths.get("canonical_backend"):
            required_files.append(paths["canonical_backend"])

        contract = cls(
            mission_id=mission_id,
            workspace_identity=str(ws),
            app_name=app_name,
            app_type="vanilla_web" if not paths.get("canonical_backend") else "fullstack_python",
            project_layout=layout,
            is_greenfield=not any((ws / f).exists() for f in (paths["canonical_html"], "package.json", "main.py")),
            canonical_html=paths["canonical_html"],
            canonical_js=paths["canonical_js"],
            canonical_css=paths["canonical_css"],
            canonical_backend=paths.get("canonical_backend"),
            required_files=required_files,
            creation_provenance={
                "created_at": time.time(),
                "prompt_sample": prompt[:80] if prompt else "",
            }
        )
        contract.save_to_workspace(ws)
        return contract

    @classmethod
    def _archive_stale_contract(cls, workspace_root: Path, stale_contract: ProjectContract) -> None:
        """Safely archive a superseded contract preserving history (Phase B4)."""
        archive_dir = workspace_root / ".hermes" / "contracts"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        archive_name = f"archive_{stale_contract.mission_id or 'unknown'}_{ts}.json"
        try:
            (archive_dir / archive_name).write_text(json.dumps(stale_contract.to_dict(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Could not archive stale contract: {e}")


    def reconcile_observed(self, workspace_root: Path | str) -> ObservedInterfaces:
        """Harvest physical interfaces from disk without mutating declared interfaces (Section 5.2)."""
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
                js_ids = re.findall(r'getElementById\([\'"]([a-zA-Z0-9_\-]+)[\'"]\)', js_txt)
                js_qs = re.findall(r'querySelector(?:All)?\([\'"]#([a-zA-Z0-9_\-]+)[\'"]\)', js_txt)
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
        """Compare declared interfaces against observed interfaces and report discrepancies (Section 5.2)."""
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
            "missing_dom_ids": missing_ids,
            "missing_classes": missing_classes,
            "missing_routes": missing_routes,
            "unregistered_js_ids": unregistered_js_ids,
            "has_discrepancies": bool(missing_ids or missing_routes or unregistered_js_ids),
        }

    def format_for_prompt(self, turn_number: int = 1) -> str:
        """Format contract context for model prompt injection (Section 5.5)."""
        decl = self.declared_interfaces
        obs = self.observed_interfaces
        diff = self.compare_interfaces()

        if turn_number <= 1:
            # Turn 1: Initial planning & architecture contract
            lines = [
                f"=== ACTIVE PROJECT CONTRACT (v{self.version}) ===",
                f"Application: {self.app_name} ({self.app_type}) | Layout: {self.project_layout}",
                f"Canonical HTML: {self.canonical_html}",
                f"Canonical CSS:  {self.canonical_css}",
                f"Canonical JS:   {self.canonical_js}",
                f"Canonical Backend: {self.canonical_backend or 'None'}",
                f"Required Deliverables: {', '.join(self.required_files)}",
            ]
            if decl.dom_ids:
                lines.append(f"Declared DOM IDs: {', '.join(decl.dom_ids[:25])}")
            if decl.api_routes:
                routes_str = ', '.join(f"{r.get('method', 'GET')} {r.get('path')}" for r in decl.api_routes[:10])
                lines.append(f"Declared API Routes: {routes_str}")
            lines.append("Rule: You must adhere strictly to these canonical paths and declared interfaces.")
            lines.append("===========================================")
            return "\n".join(lines)
        else:
            # Subsequent turns: show observed state and outstanding discrepancies
            lines = [
                f"=== CONTRACT VERIFICATION STATUS (v{self.version}, hash: {self.contract_hash[:8]}) ===",
                f"Observed HTML IDs: {len(obs.html_ids)} | Observed Routes: {len(obs.backend_routes)}",
            ]
            if diff["has_discrepancies"]:
                lines.append("OUTSTANDING CONTRACT DISCREPANCIES:")
                if diff["missing_dom_ids"]:
                    lines.append(f"  - Missing DOM IDs in HTML: {', '.join(diff['missing_dom_ids'][:10])}")
                if diff["missing_routes"]:
                    lines.append(f"  - Missing Backend Routes: {', '.join(diff['missing_routes'][:10])}")
                if diff["unregistered_js_ids"]:
                    lines.append(f"  - JS queries missing DOM IDs: {', '.join(diff['unregistered_js_ids'][:10])}")
            else:
                lines.append("All declared and observed interfaces are coherent.")
            lines.append("===========================================================")
            return "\n".join(lines)

    def save_to_workspace(self, workspace_root: Path | str) -> Path:
        """Persist contract to .hermes/project_contract.json."""
        ws = Path(workspace_root)
        hermes_dir = ws / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        contract_path = hermes_dir / "project_contract.json"
        self.contract_hash = self.compute_hash()
        contract_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return contract_path

    @classmethod
    def extract_dom_inventory(cls, workspace_root: Path | str) -> Dict[str, Any]:
        """
        Deterministically parse canonical HTML and extract authoritative DOM inventory:
        all IDs, classes, form input names, scripts, and stylesheet links.
        Checks both static/index.html and index.html based on actual layout.
        Saves inventory to .hermes/dom_contract.json.
        """
        ws = Path(workspace_root).resolve()
        html_candidates = [
            ws / "static" / "index.html",
            ws / "index.html",
        ]
        html_path = None
        for cand in html_candidates:
            if cand.exists() and cand.stat().st_size > 20:
                html_path = cand
                break

        if not html_path or not html_path.exists():
            return {"ids": [], "classes": [], "form_names": [], "scripts": [], "stylesheets": [], "html_path": None}

        try:
            txt = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {"ids": [], "classes": [], "form_names": [], "scripts": [], "stylesheets": [], "html_path": None}

        # Extract IDs
        raw_ids = re.findall(r'\bid=["\']([a-zA-Z0-9_\-]+)["\']', txt)
        ids = sorted(list(set(raw_ids)))

        # Extract Classes
        classes_set = set()
        for cm in re.findall(r'\bclass=["\']([^"\']+)["\']', txt):
            for c in cm.split():
                if c.strip():
                    classes_set.add(c.strip())
        classes = sorted(list(classes_set))

        # Extract form field names
        raw_names = re.findall(r'\bname=["\']([a-zA-Z0-9_\-]+)["\']', txt)
        form_names = sorted(list(set(raw_names)))

        # Extract script src
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', txt, re.I)

        # Extract stylesheets
        stylesheets = []
        for m in re.findall(r'<link[^>]+(?:href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\']|rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\'])', txt, re.I):
            stylesheets.append(m[0] or m[1])

        inventory = {
            "html_path": CanonicalPathResolver.normalize_slashes(str(html_path.relative_to(ws))),
            "ids": ids,
            "classes": classes,
            "form_names": form_names,
            "scripts": scripts,
            "stylesheets": stylesheets,
            "ids_count": len(ids),
            "form_names_count": len(form_names),
        }

        # Persist
        hermes_dir = ws / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        (hermes_dir / "dom_contract.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
        return inventory
