# tests/test_phase11_contracts.py
"""
Unit and Regression Tests for HERMES Phase 11 Versioned Contracts (Stage 11.1).
Tests ImplementationBlueprint, InterfaceManifest, QualityRubric,
ContractValidator, schema migration, and checkpoint backward compatibility.
"""

import json
import pytest

from core.contracts.blueprint import (
    ImplementationBlueprint,
    FilePlan,
    ComponentSpec,
    RouteSpec,
    DataModelSpec,
)
from core.contracts.manifest import (
    InterfaceManifest,
    ElementContract,
    CssContract,
    JsHookContract,
    JsModuleContract,
    NavLinkContract,
    StateContract,
    FormContract,
)
from core.contracts.rubric import (
    QualityRubric,
    RubricRequirement,
    QualityDimension,
)
from core.contracts.validator import ContractValidator
from core.runtime_state.models import HermesRuntimeState
from core.persistence.serializer import serialize_runtime_state, deserialize_runtime_state


def test_blueprint_serialization_round_trip():
    """Verify that ImplementationBlueprint serializes to dict and reconstructs identically."""
    bp = ImplementationBlueprint(
        blueprint_id="bp_test_001",
        mission_id="m_123",
        project_type="multi_page_web",
        delivery_mode="file_system",
        user_requirements=["Create home page", "Create about page"],
        acceptance_criteria=["All links work", "Responsive layout"],
        planned_files=[
            FilePlan(
                path="index.html",
                purpose="Home entrypoint",
                role="entrypoint",
                dependencies=["styles.css", "app.js"],
                features=["hero", "navigation"],
                min_lines=30,
            ),
            FilePlan(
                path="about.html",
                purpose="About page",
                role="component",
                dependencies=["styles.css"],
                features=["bio", "navigation"],
                min_lines=20,
            ),
            FilePlan(
                path="styles.css",
                purpose="Shared styles",
                role="style",
                dependencies=[],
                min_lines=40,
            ),
            FilePlan(
                path="app.js",
                purpose="Interactive logic",
                role="logic",
                dependencies=["index.html"],
                min_lines=25,
            ),
        ],
        routes=[
            RouteSpec(path="/", title="Home", file_path="index.html", is_entrypoint=True),
            RouteSpec(path="/about.html", title="About", file_path="about.html"),
        ],
        data_models=[
            DataModelSpec(
                name="UserProfile",
                fields={"username": "string", "theme": "string"},
                storage_key="user_pref",
                storage_type="localStorage",
            )
        ],
        complexity_profile="MEDIUM",
    )

    d = bp.to_dict()
    assert d["blueprint_id"] == "bp_test_001"
    assert len(d["planned_files"]) == 4
    assert len(d["routes"]) == 2
    assert d["content_hash"]

    # Reconstruct from dict
    bp_reconstructed = ImplementationBlueprint.from_dict(d)
    assert bp_reconstructed.blueprint_id == bp.blueprint_id
    assert bp_reconstructed.project_type == bp.project_type
    assert len(bp_reconstructed.planned_files) == 4
    assert bp_reconstructed.planned_files[0].path == "index.html"
    assert bp_reconstructed.routes[1].title == "About"
    assert bp_reconstructed.content_hash == bp.content_hash


def test_interface_manifest_serialization_round_trip():
    """Verify that InterfaceManifest serializes to dict and reconstructs identically."""
    manifest = InterfaceManifest(
        manifest_id="mnf_test_001",
        mission_id="m_123",
        html_entrypoints=["index.html"],
        css_tokens={"--primary": "#2563eb", "--bg": "#ffffff"},
        css_breakpoints={"mobile": "480px", "desktop": "1024px"},
        element_ids={
            "app-header": ElementContract(dom_id="app-header", tag="header", owning_file="index.html", purpose="Site banner"),
            "search-input": ElementContract(dom_id="search-input", tag="input", owning_file="index.html", purpose="Filter query", event_listeners=["input"]),
        },
        css_classes={
            "btn-primary": CssContract(class_name="btn-primary", owning_file="styles.css", target_elements=["button", "a"]),
        },
        js_hooks={
            "search_filter": JsHookContract(hook_name="#search-input", event_type="input", handler_name="handleSearch", owning_file="app.js", target_id="search-input"),
        },
        navigation_links=[
            NavLinkContract(source_file="index.html", target_href="about.html", label="About Us", link_type="internal"),
        ],
        state_schemas={
            "todos": StateContract(state_key="todos", storage_type="localStorage", schema={"id": "string", "title": "string"}),
        },
        forms={
            "task-form": FormContract(form_id="task-form", owning_file="index.html", fields=["task-title", "task-desc"], submit_handler="addTask"),
        },
    )

    d = manifest.to_dict()
    assert d["manifest_id"] == "mnf_test_001"
    assert "app-header" in d["element_ids"]
    assert "btn-primary" in d["css_classes"]
    assert d["contract_hash"]

    manifest_rec = InterfaceManifest.from_dict(d)
    assert manifest_rec.manifest_id == manifest.manifest_id
    assert manifest_rec.element_ids["search-input"].tag == "input"
    assert manifest_rec.css_tokens["--primary"] == "#2563eb"
    assert len(manifest_rec.navigation_links) == 1
    assert manifest_rec.contract_hash == manifest.contract_hash


def test_quality_rubric_serialization_round_trip():
    """Verify that QualityRubric serializes to dict and reconstructs identically."""
    rubric = QualityRubric(
        rubric_id="rbc_test_001",
        mission_id="m_123",
        task_type="dashboard",
        complexity_profile="MEDIUM",
        hard_requirements=[
            RubricRequirement(req_id="hr_1", title="HTML Semantic Tags", description="Valid head and body", passed=True),
            RubricRequirement(req_id="hr_2", title="Zero Dead Links", description="All internal links resolve", passed=False),
        ],
        quality_dimensions={
            "visual_depth": QualityDimension(dimension_name="visual_depth", weight=1.5, score=0.85, passed=True),
            "responsive_layout": QualityDimension(dimension_name="responsive_layout", weight=1.2, score=0.90, passed=True),
        },
        anti_placeholder_rules=["no_todo_comments", "no_lorem_ipsum"],
        expected_loc_bounds={"index.html": {"min": 50, "max": 800}},
        evaluation_verdict="PASS",
    )

    d = rubric.to_dict()
    assert d["rubric_id"] == "rbc_test_001"
    assert len(d["hard_requirements"]) == 2
    assert "visual_depth" in d["quality_dimensions"]

    rubric_rec = QualityRubric.from_dict(d)
    assert rubric_rec.rubric_id == rubric.rubric_id
    assert rubric_rec.hard_requirements[0].title == "HTML Semantic Tags"
    assert rubric_rec.quality_dimensions["visual_depth"].score == 0.85
    assert rubric_rec.rubric_hash == rubric.rubric_hash


def test_contract_validator_happy_path():
    """Verify that valid Blueprint, Manifest, and Coherence checks pass cleanly."""
    bp = ImplementationBlueprint(
        planned_files=[
            FilePlan(path="index.html", purpose="Entrypoint", dependencies=["styles.css"]),
            FilePlan(path="styles.css", purpose="Styles", dependencies=[]),
        ]
    )
    manifest = InterfaceManifest(
        html_entrypoints=["index.html"],
        element_ids={
            "main-title": ElementContract(dom_id="main-title", tag="h1", owning_file="index.html"),
        },
        css_classes={
            "hero": CssContract(class_name="hero", owning_file="styles.css"),
        },
    )

    bp_res = ContractValidator.validate_blueprint(bp)
    assert bp_res.valid
    assert not bp_res.errors

    mf_res = ContractValidator.validate_manifest(manifest)
    assert mf_res.valid
    assert not mf_res.errors

    coh_res = ContractValidator.validate_coherence(bp, manifest)
    assert coh_res.valid
    assert not coh_res.errors


def test_contract_validator_detects_circular_dependency():
    """Verify that circular dependencies between planned files are caught."""
    bp = ImplementationBlueprint(
        planned_files=[
            FilePlan(path="a.js", purpose="Module A", dependencies=["b.js"]),
            FilePlan(path="b.js", purpose="Module B", dependencies=["c.js"]),
            FilePlan(path="c.js", purpose="Module C", dependencies=["a.js"]),
        ]
    )
    res = ContractValidator.validate_blueprint(bp)
    assert not res.valid
    assert any("Circular dependency" in err for err in res.errors)


def test_contract_validator_detects_duplicate_element_ids():
    """Verify that duplicate DOM IDs declared in the same file are rejected."""
    manifest = InterfaceManifest(
        element_ids={
            "search-btn": ElementContract(dom_id="search-btn", tag="button", owning_file="index.html"),
        }
    )
    # Simulate duplicate entry attempt with duplicate element id
    manifest.element_ids["search-btn-dup"] = ElementContract(dom_id="search-btn", tag="a", owning_file="index.html")

    res = ContractValidator.validate_manifest(manifest)
    assert not res.valid
    assert any("Duplicate DOM ID 'search-btn'" in err for err in res.errors)


def test_contract_validator_detects_unplanned_file_in_manifest():
    """Verify that manifest references to unplanned files are flagged in coherence check."""
    bp = ImplementationBlueprint(
        planned_files=[
            FilePlan(path="index.html", purpose="Entrypoint"),
        ]
    )
    manifest = InterfaceManifest(
        element_ids={
            "footer": ElementContract(dom_id="footer", tag="footer", owning_file="missing.html"),
        },
        navigation_links=[
            NavLinkContract(source_file="index.html", target_href="unplanned_page.html", link_type="internal"),
        ],
    )

    coh_res = ContractValidator.validate_coherence(bp, manifest)
    assert not coh_res.valid
    assert any("missing.html" in err for err in coh_res.errors)
    assert any("unplanned_page.html" in err for err in coh_res.errors)


def test_backward_compatibility_with_older_checkpoints():
    """
    CRITICAL SAFETY CONTRACT:
    Ensure that older checkpoints (without Phase 11 blueprint/manifest/rubric fields)
    deserialize safely without KeyError, raising, or data loss.
    """
    # Create a baseline HermesRuntimeState and serialize it
    state = HermesRuntimeState.create_empty(mission_id="m_old_chk", session_id="sess_old")
    state_dict, _ = serialize_runtime_state(state)

    # Intentionally strip Phase 11 fields as would exist in pre-Phase 11 checkpoints
    state_dict.pop("blueprint", None)
    state_dict.pop("interface_manifest", None)
    state_dict.pop("quality_rubric", None)

    # Must deserialize cleanly
    recovered = deserialize_runtime_state(state_dict)
    assert recovered.mission.mission_id == "m_old_chk"
    assert recovered.blueprint is None
    assert recovered.interface_manifest is None
    assert recovered.quality_rubric is None


def test_full_state_round_trip_preserves_contracts():
    """Verify that serializing and deserializing HermesRuntimeState preserves Phase 11 contracts."""
    state = HermesRuntimeState.create_empty(mission_id="m_contracts", session_id="sess_contracts")
    bp = ImplementationBlueprint(
        mission_id="m_contracts",
        project_type="dashboard",
        planned_files=[FilePlan(path="index.html", purpose="UI")],
    )
    manifest = InterfaceManifest(
        mission_id="m_contracts",
        element_ids={"chart": ElementContract(dom_id="chart", tag="div", owning_file="index.html")},
    )
    rubric = QualityRubric(
        mission_id="m_contracts",
        task_type="dashboard",
        evaluation_verdict="PASS",
    )

    state.blueprint = bp
    state.interface_manifest = manifest
    state.quality_rubric = rubric

    serialized_dict, state_hash = serialize_runtime_state(state)
    assert "blueprint" in serialized_dict
    assert "interface_manifest" in serialized_dict
    assert "quality_rubric" in serialized_dict
    assert state_hash

    # Deserialize
    recovered = deserialize_runtime_state(serialized_dict)
    assert recovered.blueprint is not None
    assert recovered.blueprint.project_type == "dashboard"
    assert recovered.blueprint.planned_files[0].path == "index.html"
    assert recovered.interface_manifest is not None
    assert "chart" in recovered.interface_manifest.element_ids
    assert recovered.quality_rubric is not None
    assert recovered.quality_rubric.evaluation_verdict == "PASS"

    # Second serialization round trip produces identical hash
    reserialized_dict, reserialized_hash = serialize_runtime_state(recovered)
    assert reserialized_hash == state_hash
