# core/contracts/validator.py
"""
Contract Validator for HERMES Phase 11.
Deterministic validation of ImplementationBlueprint and InterfaceManifest.
Ensures structural soundness, dependency acyclicity, reference integrity,
and cross-contract coherence before code generation or execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from core.contracts.blueprint import ImplementationBlueprint, FilePlan
from core.contracts.manifest import InterfaceManifest
from core.contracts.rubric import QualityRubric


@dataclass
class ContractValidationResult:
    """Outcome of contract validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class ContractValidator:
    """Validates Blueprint, Manifest, and Rubric consistency."""

    @classmethod
    def validate_blueprint(cls, blueprint: ImplementationBlueprint) -> ContractValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if not blueprint.planned_files:
            errors.append("Blueprint must declare at least one planned file.")

        planned_paths = set()
        for fp in blueprint.planned_files:
            clean_p = fp.path.strip().replace("\\", "/")
            if not clean_p:
                errors.append("Planned file contains an empty path.")
                continue
            if clean_p in planned_paths:
                errors.append(f"Duplicate planned file path: '{clean_p}'")
            planned_paths.add(clean_p)

        # Check dependency DAG for cycles
        dep_graph: Dict[str, Set[str]] = {fp.path.strip().replace("\\", "/"): set(fp.dependencies) for fp in blueprint.planned_files}
        cycle = cls._detect_cycle(dep_graph)
        if cycle:
            errors.append(f"Circular dependency detected in planned files: {' -> '.join(cycle)}")

        # Check route consistency
        for r in blueprint.routes:
            rf = r.file_path.strip().replace("\\", "/")
            if rf not in planned_paths:
                errors.append(f"Route '{r.path}' targets '{rf}' which is not in planned files.")

        return ContractValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            details={"planned_file_count": len(planned_paths)},
        )

    @classmethod
    def validate_manifest(cls, manifest: InterfaceManifest) -> ContractValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        # Validate Element IDs
        id_pattern = re.compile(r"^[A-Za-z0-9_\-]+$")
        seen_ids_per_file: Dict[str, Set[str]] = {}

        for eid, ec in manifest.element_ids.items():
            target_id = ec.dom_id or eid
            if not id_pattern.match(target_id):
                errors.append(f"Invalid DOM ID syntax in manifest: '{target_id}'")
            file_key = ec.owning_file.strip().replace("\\", "/")
            if file_key not in seen_ids_per_file:
                seen_ids_per_file[file_key] = set()
            if target_id in seen_ids_per_file[file_key]:
                errors.append(f"Duplicate DOM ID '{target_id}' declared for same file '{file_key}'")
            seen_ids_per_file[file_key].add(target_id)

        # Validate Navigation links
        for nav in manifest.navigation_links:
            if nav.link_type == "internal":
                target = nav.target_href.split("#")[0].split("?")[0].lstrip("./")
                if target and target.endswith(".html") and not any(target in e for e in manifest.html_entrypoints):
                    # Check if target is in entrypoints or routes
                    warnings.append(f"Navigation link '{nav.target_href}' from '{nav.source_file}' is not declared in html_entrypoints")

        # Validate JS Hooks match declared Element IDs
        for hook_name, hook in manifest.js_hooks.items():
            if hook.target_id and hook.target_id not in manifest.element_ids:
                warnings.append(f"JS hook '{hook_name}' targets ID '{hook.target_id}' which is not in declared element_ids")

        return ContractValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            details={"element_ids_count": len(manifest.element_ids), "css_classes_count": len(manifest.css_classes)},
        )

    @classmethod
    def validate_coherence(
        cls,
        blueprint: ImplementationBlueprint,
        manifest: InterfaceManifest,
    ) -> ContractValidationResult:
        """Validate cross-contract coherence between Blueprint and InterfaceManifest."""
        errors: List[str] = []
        warnings: List[str] = []

        planned_files = {fp.path.strip().replace("\\", "/") for fp in blueprint.planned_files}

        # Check that manifest owning files exist in blueprint planned files
        for eid, ec in manifest.element_ids.items():
            f = ec.owning_file.strip().replace("\\", "/")
            if f not in planned_files:
                errors.append(f"Manifest element ID '{eid}' is assigned to '{f}' which is not in blueprint planned files.")

        for cname, cc in manifest.css_classes.items():
            f = cc.owning_file.strip().replace("\\", "/")
            if f not in planned_files:
                errors.append(f"Manifest CSS class '{cname}' is assigned to '{f}' which is not in blueprint planned files.")

        for nav in manifest.navigation_links:
            if nav.link_type == "internal":
                target = nav.target_href.split("#")[0].split("?")[0].lstrip("./")
                if target and target not in planned_files:
                    errors.append(f"Internal link '{nav.target_href}' in '{nav.source_file}' targets unplanned file '{target}'")

        return ContractValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _detect_cycle(graph: Dict[str, Set[str]]) -> Optional[List[str]]:
        """Detect circular dependencies using DFS graph traversal."""
        visited: Set[str] = set()
        stack: List[str] = []

        def dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            stack.append(node)
            for neighbor in graph.get(node, set()):
                if neighbor in stack:
                    cycle_start = stack.index(neighbor)
                    return stack[cycle_start:] + [neighbor]
                if neighbor not in visited and neighbor in graph:
                    c = dfs(neighbor)
                    if c:
                        return c
            stack.pop()
            return None

        for n in graph:
            if n not in visited:
                cycle = dfs(n)
                if cycle:
                    return cycle
        return None
