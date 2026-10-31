# core/contracts/manifest.py
"""
Interface Manifest Contract for HERMES Phase 11.
Describes how the project's files connect across markup, styling, scripting,
navigation, assets, state, and API boundaries.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ElementContract:
    """Contract for a specific DOM ID element."""
    dom_id: str
    tag: str
    owning_file: str
    purpose: str = ""
    event_listeners: List[str] = field(default_factory=list)
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CssContract:
    """Contract for a CSS class or selector."""
    class_name: str
    owning_file: str
    target_elements: List[str] = field(default_factory=list)
    styles_summary: str = ""
    is_utility: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JsHookContract:
    """Contract for JavaScript DOM bindings and event hooks."""
    hook_name: str                               # e.g. "data-js='toggle-menu'" or "#search-input"
    event_type: str                              # "click", "submit", "input", "change", "DOMContentLoaded"
    handler_name: str
    owning_file: str
    target_id: Optional[str] = None
    purpose: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JsModuleContract:
    """Contract for JS modules and import/export linkages."""
    module_name: str
    file_path: str
    exports: List[str] = field(default_factory=list)
    imports: Dict[str, str] = field(default_factory=dict)  # imported_symbol -> from_source
    load_type: str = "script"                    # "script" (classic tag) or "module" (ESM)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NavLinkContract:
    """Contract for internal or external navigation anchors."""
    source_file: str
    target_href: str
    label: str = ""
    link_type: str = "internal"                  # "internal", "external", "anchor"
    is_tested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AssetContract:
    """Contract for static media, font, or image assets."""
    source_file: str
    asset_path: str
    mime_type: str = ""
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StateContract:
    """Contract for local storage or application state schemas."""
    state_key: str
    storage_type: str = "localStorage"           # "localStorage", "sessionStorage", "memory", "cookie"
    schema: Dict[str, str] = field(default_factory=dict)
    default_value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FormContract:
    """Contract for interactive forms and submission handlers."""
    form_id: str
    owning_file: str
    fields: List[str] = field(default_factory=list)
    submit_handler: Optional[str] = None
    validation_rules: Dict[str, str] = field(default_factory=dict)
    storage_target: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApiEndpointContract:
    """Contract for API routes or backend endpoints."""
    path: str
    method: str = "GET"
    request_schema: Dict[str, str] = field(default_factory=dict)
    response_schema: Dict[str, str] = field(default_factory=dict)
    owning_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InterfaceManifest:
    """
    Authoritative manifest of agreed cross-file contracts across
    IDs, classes, event hooks, routes, modules, forms, and assets.
    """
    schema_version: str = "1.0.0"
    manifest_id: str = field(default_factory=lambda: f"mnf_{uuid.uuid4().hex[:8]}")
    revision: int = 1
    mission_id: str = ""
    project_root: str = "."
    html_entrypoints: List[str] = field(default_factory=lambda: ["index.html"])
    css_tokens: Dict[str, str] = field(default_factory=dict)
    css_breakpoints: Dict[str, str] = field(default_factory=lambda: {
        "mobile": "480px",
        "tablet": "768px",
        "desktop": "1024px",
    })
    element_ids: Dict[str, ElementContract] = field(default_factory=dict)
    css_classes: Dict[str, CssContract] = field(default_factory=dict)
    js_hooks: Dict[str, JsHookContract] = field(default_factory=dict)
    js_modules: Dict[str, JsModuleContract] = field(default_factory=dict)
    navigation_links: List[NavLinkContract] = field(default_factory=list)
    asset_references: List[AssetContract] = field(default_factory=list)
    state_schemas: Dict[str, StateContract] = field(default_factory=dict)
    forms: Dict[str, FormContract] = field(default_factory=dict)
    api_endpoints: Dict[str, ApiEndpointContract] = field(default_factory=dict)
    contract_hash: str = ""

    def __post_init__(self):
        if not self.contract_hash:
            self.contract_hash = self.compute_hash()

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of interface manifest."""
        d = self.to_dict()
        d.pop("contract_hash", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "revision": self.revision,
            "mission_id": self.mission_id,
            "project_root": self.project_root,
            "html_entrypoints": list(self.html_entrypoints),
            "css_tokens": dict(self.css_tokens),
            "css_breakpoints": dict(self.css_breakpoints),
            "element_ids": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.element_ids.items()},
            "css_classes": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.css_classes.items()},
            "js_hooks": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.js_hooks.items()},
            "js_modules": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.js_modules.items()},
            "navigation_links": [l.to_dict() if hasattr(l, "to_dict") else dict(l) for l in self.navigation_links],
            "asset_references": [a.to_dict() if hasattr(a, "to_dict") else dict(a) for a in self.asset_references],
            "state_schemas": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.state_schemas.items()},
            "forms": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.forms.items()},
            "api_endpoints": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.api_endpoints.items()},
            "contract_hash": self.contract_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InterfaceManifest:
        if not data:
            return cls()
        element_ids = {
            k: ElementContract(**v) if isinstance(v, dict) else v
            for k, v in data.get("element_ids", {}).items()
        }
        css_classes = {
            k: CssContract(**v) if isinstance(v, dict) else v
            for k, v in data.get("css_classes", {}).items()
        }
        js_hooks = {
            k: JsHookContract(**v) if isinstance(v, dict) else v
            for k, v in data.get("js_hooks", {}).items()
        }
        js_modules = {
            k: JsModuleContract(**v) if isinstance(v, dict) else v
            for k, v in data.get("js_modules", {}).items()
        }
        navigation_links = [
            NavLinkContract(**item) if isinstance(item, dict) else item
            for item in data.get("navigation_links", [])
        ]
        asset_references = [
            AssetContract(**item) if isinstance(item, dict) else item
            for item in data.get("asset_references", [])
        ]
        state_schemas = {
            k: StateContract(**v) if isinstance(v, dict) else v
            for k, v in data.get("state_schemas", {}).items()
        }
        forms = {
            k: FormContract(**v) if isinstance(v, dict) else v
            for k, v in data.get("forms", {}).items()
        }
        api_endpoints = {
            k: ApiEndpointContract(**v) if isinstance(v, dict) else v
            for k, v in data.get("api_endpoints", {}).items()
        }
        return cls(
            schema_version=data.get("schema_version", "1.0.0"),
            manifest_id=data.get("manifest_id", f"mnf_{uuid.uuid4().hex[:8]}"),
            revision=data.get("revision", 1),
            mission_id=data.get("mission_id", ""),
            project_root=data.get("project_root", "."),
            html_entrypoints=data.get("html_entrypoints", ["index.html"]),
            css_tokens=data.get("css_tokens", {}),
            css_breakpoints=data.get("css_breakpoints", {"mobile": "480px", "tablet": "768px", "desktop": "1024px"}),
            element_ids=element_ids,
            css_classes=css_classes,
            js_hooks=js_hooks,
            js_modules=js_modules,
            navigation_links=navigation_links,
            asset_references=asset_references,
            state_schemas=state_schemas,
            forms=forms,
            api_endpoints=api_endpoints,
            contract_hash=data.get("contract_hash", ""),
        )
