# core/contracts/blueprint.py
"""
Implementation Blueprint Contract for HERMES Phase 11.
Describes what the project must contain, its architecture, file responsibilities,
and verifiable acceptance requirements.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class FilePlan:
    """Planned file specification within the blueprint."""
    path: str
    purpose: str
    role: str = "component"                      # "entrypoint", "style", "logic", "component", "config", "test"
    dependencies: List[str] = field(default_factory=list)
    ordered_sections: List[str] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    min_lines: int = 10
    target_exports: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ComponentSpec:
    """Component architecture specification."""
    name: str
    role: str
    file_path: str
    parent_component: Optional[str] = None
    child_components: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    state_bindings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RouteSpec:
    """Planned navigation page or route specification."""
    path: str
    title: str
    file_path: str
    nav_label: str = ""
    is_entrypoint: bool = False
    query_params: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DataModelSpec:
    """Planned data schema specification."""
    name: str
    fields: Dict[str, str]                       # field_name -> type_desc
    storage_key: Optional[str] = None
    storage_type: str = "memory"                 # "localStorage", "sessionStorage", "sqlite", "memory"
    validation_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ImplementationBlueprint:
    """
    Authoritative specification of project intent and structure.
    """
    schema_version: str = "1.0.0"
    blueprint_id: str = field(default_factory=lambda: f"bp_{uuid.uuid4().hex[:8]}")
    revision: int = 1
    mission_id: str = ""
    project_type: str = "vanilla_web"            # "vanilla_web", "python_cli", "multi_page_web", "dashboard", "api"
    delivery_mode: str = "file_system"           # "file_system", "served", "static"
    user_requirements: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    design_brief: Dict[str, Any] = field(default_factory=dict)
    planned_files: List[FilePlan] = field(default_factory=list)
    component_tree: List[ComponentSpec] = field(default_factory=list)
    routes: List[RouteSpec] = field(default_factory=list)
    data_models: List[DataModelSpec] = field(default_factory=list)
    complexity_profile: str = "SIMPLE"           # "TRIVIAL", "SIMPLE", "MEDIUM", "COMPLEX", "LARGE"
    quality_targets: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = self.compute_hash()

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of blueprint contents."""
        d = self.to_dict()
        d.pop("content_hash", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "blueprint_id": self.blueprint_id,
            "revision": self.revision,
            "mission_id": self.mission_id,
            "project_type": self.project_type,
            "delivery_mode": self.delivery_mode,
            "user_requirements": list(self.user_requirements),
            "acceptance_criteria": list(self.acceptance_criteria),
            "design_brief": dict(self.design_brief),
            "planned_files": [f.to_dict() if hasattr(f, "to_dict") else dict(f) for f in self.planned_files],
            "component_tree": [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in self.component_tree],
            "routes": [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in self.routes],
            "data_models": [m.to_dict() if hasattr(m, "to_dict") else dict(m) for m in self.data_models],
            "complexity_profile": self.complexity_profile,
            "quality_targets": dict(self.quality_targets),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ImplementationBlueprint:
        if not data:
            return cls()
        planned_files = [
            FilePlan(**item) if isinstance(item, dict) else item
            for item in data.get("planned_files", [])
        ]
        component_tree = [
            ComponentSpec(**item) if isinstance(item, dict) else item
            for item in data.get("component_tree", [])
        ]
        routes = [
            RouteSpec(**item) if isinstance(item, dict) else item
            for item in data.get("routes", [])
        ]
        data_models = [
            DataModelSpec(**item) if isinstance(item, dict) else item
            for item in data.get("data_models", [])
        ]
        return cls(
            schema_version=data.get("schema_version", "1.0.0"),
            blueprint_id=data.get("blueprint_id", f"bp_{uuid.uuid4().hex[:8]}"),
            revision=data.get("revision", 1),
            mission_id=data.get("mission_id", ""),
            project_type=data.get("project_type", "vanilla_web"),
            delivery_mode=data.get("delivery_mode", "file_system"),
            user_requirements=data.get("user_requirements", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
            design_brief=data.get("design_brief", {}),
            planned_files=planned_files,
            component_tree=component_tree,
            routes=routes,
            data_models=data_models,
            complexity_profile=data.get("complexity_profile", "SIMPLE"),
            quality_targets=data.get("quality_targets", {}),
            content_hash=data.get("content_hash", ""),
        )
