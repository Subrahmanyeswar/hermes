# tests/test_phase5_contract_creation.py
"""
HERMES Phase 5 Acceptance Test Suite: Scenario A — Contract Creation.

Verifies that:
1. A valid mission prompt produces a durable, machine-verifiable implementation contract.
2. The contract encompasses ImplementationBlueprint, InterfaceManifest, and QualityRubric.
3. Contracts are structurally sound and pass ContractValidator coherence verification.
4. Deterministic content hashing ensures contract integrity and version immutability.
"""

import pytest
from core.contracts.builder import ContractBuilder
from core.contracts.blueprint import ImplementationBlueprint
from core.contracts.manifest import InterfaceManifest
from core.contracts.rubric import QualityRubric
from core.contracts.validator import ContractValidator


def test_scenario_a_web_contract_derivation():
    """
    Scenario A.1: Valid web mission prompt produces a cohesive, verifiable contract bundle.
    """
    mission_id = "msn_campus_events_001"
    prompt = "Build a campus event board with search, category filtering, and an event creation form."

    blueprint, manifest, rubric = ContractBuilder.derive_contracts_for_mission(
        mission_id=mission_id,
        prompt=prompt,
        project_type="vanilla_web",
    )

    # 1. Blueprint assertions
    assert blueprint.mission_id == mission_id
    assert blueprint.project_type == "vanilla_web"
    planned_file_paths = [f.path for f in blueprint.planned_files]
    assert "index.html" in planned_file_paths
    assert "styles.css" in planned_file_paths
    assert "app.js" in planned_file_paths
    assert len(blueprint.acceptance_criteria) > 0
    assert blueprint.content_hash != ""

    # 2. Interface Manifest assertions
    assert manifest.mission_id == mission_id
    assert "index.html" in manifest.html_entrypoints
    assert "eventList" in manifest.element_ids
    assert "searchInput" in manifest.element_ids
    assert "categoryFilter" in manifest.element_ids
    assert "eventForm" in manifest.forms
    assert "#searchInput" in manifest.js_hooks
    assert "container" in manifest.css_classes
    assert "mobile" in manifest.css_breakpoints
    assert manifest.contract_hash != ""

    # 3. Quality Rubric assertions
    assert rubric.mission_id == mission_id
    assert rubric.task_type == "vanilla_web"
    req_ids = [r.req_id for r in rubric.hard_requirements]
    assert "REQ-FILES" in req_ids
    assert "REQ-DOM-ALIGNMENT" in req_ids
    assert "REQ-SYNTAX" in req_ids
    assert "no_todo_comments" in rubric.anti_placeholder_rules

    # 4. Cross-Contract Coherence Validation
    coherence = ContractValidator.validate_coherence(blueprint, manifest)
    assert coherence.valid is True, f"Contract coherence failed: {coherence.errors}"


def test_scenario_a_contract_serialization_integrity():
    """
    Scenario A.2: Contract serializes to dict and reconstructs identically with stable hashes.
    """
    prompt = "Create a todo tracker application with input form, add button, and dynamic task list."
    blueprint, manifest, rubric = ContractBuilder.derive_contracts_for_mission(
        mission_id="msn_todo_002",
        prompt=prompt,
        project_type="vanilla_web",
    )

    # Round trip Blueprint
    bp_dict = blueprint.to_dict()
    bp_reconstructed = ImplementationBlueprint.from_dict(bp_dict)
    assert bp_reconstructed.content_hash == blueprint.content_hash
    assert len(bp_reconstructed.planned_files) == len(blueprint.planned_files)

    # Round trip Manifest
    im_dict = manifest.to_dict()
    im_reconstructed = InterfaceManifest.from_dict(im_dict)
    assert im_reconstructed.contract_hash == manifest.contract_hash
    assert "todoForm" in im_reconstructed.forms
    assert "todoInput" in im_reconstructed.element_ids

    # Round trip Rubric
    rb_dict = rubric.to_dict()
    rb_reconstructed = QualityRubric.from_dict(rb_dict)
    assert rb_reconstructed.rubric_hash == rubric.rubric_hash


def test_scenario_a_python_contract_derivation():
    """
    Scenario A.3: Python mission prompt derives python-specific contracts.
    """
    mission_id = "msn_py_cli_003"
    prompt = "Build a python data processor script to parse CSV files and report summaries."

    blueprint, manifest, rubric = ContractBuilder.derive_contracts_for_mission(
        mission_id=mission_id,
        prompt=prompt,
        project_type="python_project",
    )

    assert blueprint.project_type == "python_project"
    assert any(f.path == "main.py" for f in blueprint.planned_files)
    assert rubric.task_type == "python_project"
    assert any(r.req_id == "REQ-PY-SYNTAX" for r in rubric.hard_requirements)
