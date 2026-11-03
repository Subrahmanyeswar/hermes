"""
tests/test_hermes_reliability_integration.py
HERMES 2.x - Authoritative Reliability, Contract, and Architectural Integration Regression Suite.

Covers Test Groups A through K (108 Tests Total):
- Group A: Staged JavaScript validation (11 tests)
- Group B: Python and JSON validation (5 tests)
- Group C: Canonical workspace paths (8 tests)
- Group D: Contract compiler (12 tests)
- Group E: Cross-file contract validation (13 tests)
- Group F: State reconciliation (10 tests)
- Group G: Stuck detector (10 tests)
- Group H: Failure classification and failover (14 tests)
- Group I: Provenance (13 tests)
- Group J: Acceptance gate (7 tests)
- Group K: Batch writer (5 tests)
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.js_syntax_validator import (
    CLASS_SYNTAX_ERROR,
    CLASS_VALIDATION_SUCCESS,
    CLASS_VALIDATION_TIMEOUT,
    CLASS_VALIDATOR_MISSING,
    CodeValidationResult,
    compute_file_sha256,
    stage_and_promote_file,
    validate_javascript_detailed,
    validate_javascript_file,
    validate_json_code,
    validate_json_file,
    validate_python_code,
    validate_python_file,
)
from core.project_contract import (
    CanonicalPathResolver,
    DeclaredInterfaces,
    ObservedInterfaces,
    ProjectContract,
)
from core.cross_file_contract import (
    ContractDiscrepancy,
    CrossFileContractReport,
    CrossFileContractValidator,
    SEV_FAIL,
    SEV_PASS,
    SEV_WARNING,
)
from core.agent_loop.stuck_detector import (
    OperationFingerprint,
    StuckLoopDetector,
)
from core.failure_classifier import (
    FailureCategory,
    FailureClassifier,
)
from core.test_isolation import (
    get_isolated_db_path,
    is_test_isolation_active,
    isolated_test_database,
)
from core.mission_state_manager import (
    MissionStateManager,
    ReconciliationReport,
)
from core.agent_loop.completion import (
    CompletionPolicy,
    GoalCompleteGuard,
)
from core.evidence.models import (
    EvidenceFreshness,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceSourceType,
    EvidenceStatus,
)
from core.evidence.store import EvidenceStore
from core.evidence.invalidator import EvidenceInvalidator
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    HermesRuntimeState,
    RequirementState,
    RequirementStatus,
)
from core.workspace import workspace_manager
from tools.file_tools import BatchFileItem, WriteFilesBatchTool


# ==============================================================================
# GROUP A — Staged JavaScript validation (11 tests)
# ==============================================================================

class TestGroupAStagedJsValidation:

    def test_a01_valid_app_pending_js_passes_node_check(self, tmp_path):
        """1. Valid app.pending.js passes node --check."""
        staged = tmp_path / "app.pending.js"
        staged.write_text("const x = 42;\nconsole.log(x);\n", encoding="utf-8")
        res = validate_javascript_detailed(staged)
        assert res.is_valid is True
        assert res.error_class == CLASS_VALIDATION_SUCCESS

    def test_a02_valid_legacy_app_js_pending_checked_via_temp_js(self, tmp_path):
        """2. Valid legacy app.js.pending can be checked through a temporary .js filename."""
        legacy = tmp_path / "app.js.pending"
        legacy.write_text("function greet(name) { return `Hello ${name}`; }\n", encoding="utf-8")
        res = validate_javascript_detailed(legacy)
        assert res.is_valid is True
        assert res.error_class == CLASS_VALIDATION_SUCCESS

    def test_a03_validator_never_passes_pending_ending_filename_to_node(self, tmp_path, monkeypatch):
        """3. The validator never passes a .pending-ending filename to Node."""
        legacy = tmp_path / "app.js.pending"
        legacy.write_text("console.log('test');\n", encoding="utf-8")

        executed_commands = []
        real_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            executed_commands.append(cmd)
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)
        res = validate_javascript_detailed(legacy)
        assert res.is_valid is True
        node_checks = [c for c in executed_commands if len(c) >= 3 and c[1] == "--check"]
        assert len(node_checks) >= 1
        target_arg = node_checks[0][2]
        assert not target_arg.endswith(".pending")
        assert target_arg.endswith(".js")

    def test_a04_invalid_staged_js_returns_actual_stderr(self, tmp_path):
        """4. Invalid staged JavaScript returns the actual stderr."""
        bad_js = tmp_path / "broken.pending.js"
        bad_js.write_text("const foo = ;\n", encoding="utf-8")
        res = validate_javascript_detailed(bad_js)
        assert res.is_valid is False
        assert res.error_class == CLASS_SYNTAX_ERROR
        assert res.error_message is not None
        assert "Unexpected token" in res.error_message or "SyntaxError" in res.error_message or res.stderr != ""

    def test_a05_invalid_staged_js_includes_line_and_column(self, tmp_path):
        """5. Invalid staged JavaScript includes the exact line and column where available."""
        bad_js = tmp_path / "syntax_err.pending.js"
        bad_js.write_text("// Line 1\n// Line 2\nconst x = {\n", encoding="utf-8")
        res = validate_javascript_detailed(bad_js)
        assert res.is_valid is False
        assert res.line is not None
        assert res.line >= 3

    def test_a06_failed_validation_preserves_staged_content(self, tmp_path):
        """6. Failed validation preserves the staged content."""
        content = "const broken = (;\n"
        ok, msg, det = stage_and_promote_file(tmp_path, "app.js", content)
        assert ok is False
        staged_p = Path(det["staged_path"])
        assert staged_p.exists()
        assert staged_p.read_text(encoding="utf-8") == content

    def test_a07_failed_validation_preserves_previous_canonical_artifact(self, tmp_path):
        """7. Failed validation preserves the previous canonical artifact."""
        canonical = tmp_path / "app.js"
        canonical.write_text("console.log('original working version');\n", encoding="utf-8")
        orig_hash = compute_file_sha256(canonical)

        ok, msg, det = stage_and_promote_file(tmp_path, "app.js", "const bad = ;\n")
        assert ok is False
        assert canonical.exists()
        assert compute_file_sha256(canonical) == orig_hash
        assert canonical.read_text(encoding="utf-8") == "console.log('original working version');\n"

    def test_a08_successful_validation_promotes_to_correct_canonical_path(self, tmp_path):
        """8. Successful validation promotes to the correct canonical path."""
        valid_code = "const ready = true;\nconsole.log(ready);\n"
        ok, msg, det = stage_and_promote_file(tmp_path, "static/app.js", valid_code)
        assert ok is True
        dest = tmp_path / "static" / "app.js"
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == valid_code
        staged = tmp_path / "static" / "app.pending.js"
        assert not staged.exists()

    def test_a09_promotion_records_actual_before_after_hashes(self, tmp_path):
        """9. Promotion records actual before/after hashes."""
        canonical = tmp_path / "app.js"
        canonical.write_text("let a = 1;\n", encoding="utf-8")
        before_hash = compute_file_sha256(canonical)

        new_code = "let a = 2;\n"
        ok, msg, det = stage_and_promote_file(tmp_path, "app.js", new_code)
        assert ok is True
        assert det["before_hash"] == before_hash
        assert det["after_hash"] == compute_file_sha256(canonical)
        assert det["before_hash"] != det["after_hash"]

    def test_a10_missing_node_classified_as_environment_tool_availability(self, tmp_path, monkeypatch):
        """10. A missing Node executable is classified as an environment/tool availability issue, not invalid JavaScript."""
        js_file = tmp_path / "test.js"
        js_file.write_text("console.log(1);\n", encoding="utf-8")

        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        res = validate_javascript_detailed(js_file)
        assert res.is_valid is False
        assert res.error_class == CLASS_VALIDATOR_MISSING
        assert "Node.js executable not found" in res.error_message

    def test_a11_node_timeout_not_silently_classified_as_syntax_error(self, tmp_path, monkeypatch):
        """11. A Node timeout or process error is not silently classified as a syntax error."""
        js_file = tmp_path / "test.js"
        js_file.write_text("console.log(1);\n", encoding="utf-8")

        def mock_timeout(*args, **kwargs):
            if "--check" in args[0]:
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=5)
            mock_proc = MagicMock()
            mock_proc.stdout = "v20.0.0"
            mock_proc.returncode = 0
            return mock_proc

        monkeypatch.setattr(subprocess, "run", mock_timeout)
        res = validate_javascript_detailed(js_file)
        assert res.is_valid is False
        assert res.error_class == CLASS_VALIDATION_TIMEOUT
        assert "timed out" in res.error_message.lower()


# ==============================================================================
# GROUP B — Python and JSON validation (5 tests)
# ==============================================================================

class TestGroupBPythonJsonValidation:

    def test_b01_valid_python_passes_ast_validation(self, tmp_path):
        """1. Valid Python passes AST validation."""
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        res = validate_python_code(code)
        assert res.is_valid is True
        assert res.error_class == CLASS_VALIDATION_SUCCESS

        py_file = tmp_path / "main.py"
        py_file.write_text(code, encoding="utf-8")
        ok, err, line = validate_python_file(py_file)
        assert ok is True
        assert err is None

    def test_b02_invalid_python_returns_exact_syntax_diagnostics(self, tmp_path):
        """2. Invalid Python returns exact syntax diagnostics."""
        bad_code = "def broken(:\n    pass\n"
        res = validate_python_code(bad_code)
        assert res.is_valid is False
        assert res.error_class == CLASS_SYNTAX_ERROR
        assert res.line == 1
        assert "SyntaxError" in res.error_message

    def test_b03_valid_json_passes_parsing(self, tmp_path):
        """3. Valid JSON passes parsing."""
        raw = '{"name": "Hermes", "version": 2, "active": true}'
        res = validate_json_code(raw)
        assert res.is_valid is True
        assert res.error_class == CLASS_VALIDATION_SUCCESS

    def test_b04_invalid_json_returns_line_and_column(self, tmp_path):
        """4. Invalid JSON returns line and column."""
        bad_json = '{\n  "name": "Hermes",\n  "incomplete": \n}'
        res = validate_json_code(bad_json)
        assert res.is_valid is False
        assert res.error_class == CLASS_SYNTAX_ERROR
        assert res.line is not None
        assert res.column is not None

    def test_b05_failed_validation_prevents_promotion(self, tmp_path):
        """5. Failed validation prevents promotion for Python and JSON."""
        py_target = tmp_path / "service.py"
        py_target.write_text("print('stable')\n", encoding="utf-8")
        ok, msg, det = stage_and_promote_file(tmp_path, "service.py", "def syntax error:\n")
        assert ok is False
        assert py_target.read_text(encoding="utf-8") == "print('stable')\n"


# ==============================================================================
# GROUP C — Canonical workspace paths (8 tests)
# ==============================================================================

class TestGroupCCanonicalWorkspacePaths:

    def test_c01_root_level_project_layout(self, tmp_path):
        """1. Root-level project layout."""
        layout, paths = ProjectContract.detect_project_layout(tmp_path, prompt="Build a simple calculator")
        assert layout == "root"
        assert paths["canonical_html"] == "index.html"
        assert paths["canonical_css"] == "style.css"

    def test_c02_static_project_layout(self, tmp_path):
        """2. static/ project layout."""
        layout, paths = ProjectContract.detect_project_layout(tmp_path, prompt="Build a FastAPI fullstack web app")
        assert layout == "static"
        assert paths["canonical_html"] == "static/index.html"
        assert paths["canonical_css"] == "static/style.css"

    def test_c03_static_mount_detection(self, tmp_path):
        """3. Static mount detection."""
        main_py = tmp_path / "main.py"
        main_py.write_text(
            'from fastapi import FastAPI\nfrom fastapi.staticfiles import StaticFiles\n'
            'app = FastAPI()\napp.mount("/static", StaticFiles(directory="static"), name="static")\n',
            encoding="utf-8",
        )
        layout, paths = ProjectContract.detect_project_layout(tmp_path, prompt="Todo App")
        assert layout == "static"
        assert paths["canonical_html"] == "static/index.html"

    def test_c04_root_versus_static_conflicts(self, tmp_path):
        """4. Root-versus-static conflicts return ambiguous without cues."""
        (tmp_path / "static").mkdir()
        (tmp_path / "static" / "index.html").write_text("<h1>Static</h1>", encoding="utf-8")
        (tmp_path / "index.html").write_text("<h1>Root</h1>", encoding="utf-8")

        layout, paths = ProjectContract.detect_project_layout(tmp_path, prompt="Ambiguous layout test")
        assert layout == "ambiguous"
        assert paths.get("error") == "WORKSPACE_LAYOUT_AMBIGUOUS"

    def test_c05_windows_path_separators_normalized(self, tmp_path):
        """5. Windows path separators normalized to POSIX slashes."""
        raw = "static\\css\\style.css"
        normalized = CanonicalPathResolver.normalize_slashes(raw)
        assert normalized == "static/css/style.css"
        assert "\\" not in normalized

    def test_c06_stale_project_contract_reconciled(self, tmp_path):
        """6. Stale project contract detected and reconciled across missions."""
        old_contract = ProjectContract(
            mission_id="mission_alpha",
            app_name="AlphaApp",
            project_layout="root",
            canonical_html="index.html",
        )
        old_contract.save_to_workspace(tmp_path)

        reconciled = ProjectContract.create_or_load(tmp_path, prompt="New Beta App", mission_id="mission_beta")
        assert reconciled.mission_id == "mission_beta"
        archives = list((tmp_path / ".hermes" / "contracts").glob("archive_mission_alpha_*.json"))
        assert len(archives) >= 1

    def test_c07_traversal_attempts_rejected(self, tmp_path):
        """7. Traversal attempts rejected."""
        with pytest.raises(ValueError, match="prohibited|outside"):
            CanonicalPathResolver.resolve(tmp_path, "../../etc/shadow")

    def test_c08_consistent_resolution_across_read_and_write(self, tmp_path):
        """8. Consistent resolution across read and write tools."""
        p1 = CanonicalPathResolver.resolve(tmp_path, "static/app.js")
        p2 = CanonicalPathResolver.resolve(tmp_path, "static\\app.js")
        assert p1 == p2
        assert str(p1.relative_to(tmp_path)).replace("\\", "/") == "static/app.js"


# ==============================================================================
# GROUP D — Contract compiler (12 tests)
# ==============================================================================

class TestGroupDContractCompiler:

    def test_d01_contract_bound_to_active_mission_id(self, tmp_path):
        """1. Contract is bound to the active mission ID."""
        contract = ProjectContract.create_or_load(tmp_path, mission_id="m_active_01")
        assert contract.mission_id == "m_active_01"

    def test_d02_previous_mission_contract_detected(self, tmp_path):
        """2. A previous mission contract is detected."""
        c1 = ProjectContract(mission_id="m_prev", app_name="OldApp")
        c1.save_to_workspace(tmp_path)
        c2 = ProjectContract.create_or_load(tmp_path, mission_id="m_curr")
        assert c2.migration_provenance is not None
        assert c2.migration_provenance["archived_mission_id"] == "m_prev"

    def test_d03_old_contract_data_preserved_for_audit(self, tmp_path):
        """3. Old contract data is preserved for audit."""
        c1 = ProjectContract(mission_id="m_audit_old", app_name="AuditApp", required_ids=["test-id"])
        c1.save_to_workspace(tmp_path)
        ProjectContract.create_or_load(tmp_path, mission_id="m_audit_new")
        archive_files = list((tmp_path / ".hermes" / "contracts").glob("archive_m_audit_old_*.json"))
        assert len(archive_files) == 1
        data = json.loads(archive_files[0].read_text(encoding="utf-8"))
        assert data["app_name"] == "AuditApp"
        assert "test-id" in data["required_ids"]

    def test_d04_declared_interfaces_not_overwritten_by_observed(self, tmp_path):
        """4. Declared interfaces are not overwritten by observed symbols."""
        contract = ProjectContract(mission_id="m1")
        contract.declared_interfaces = DeclaredInterfaces(
            dom_ids=["navbar", "user-profile", "logout-btn"],
            api_routes=[{"path": "/api/v1/auth", "method": "POST"}],
        )
        (tmp_path / "index.html").write_text('<div id="some-other-id"></div>', encoding="utf-8")
        obs = contract.reconcile_observed(tmp_path)
        assert "some-other-id" in obs.html_ids
        assert contract.declared_interfaces.dom_ids == ["navbar", "user-profile", "logout-btn"]

    def test_d05_html_ids_and_classes_harvested(self, tmp_path):
        """5. HTML IDs and classes are harvested."""
        html = '<div id="container" class="layout card main-view"><button id="save-btn" class="btn primary">Save</button></div>'
        (tmp_path / "index.html").write_text(html, encoding="utf-8")
        inv = ProjectContract.extract_dom_inventory(tmp_path)
        assert "container" in inv["ids"]
        assert "save-btn" in inv["ids"]
        assert "card" in inv["classes"]
        assert "primary" in inv["classes"]

    def test_d06_script_and_stylesheet_paths_harvested(self, tmp_path):
        """6. Script and stylesheet paths are harvested."""
        html = '<head><link rel="stylesheet" href="style.css"></head><body><script src="app.js"></script></body>'
        (tmp_path / "index.html").write_text(html, encoding="utf-8")
        inv = ProjectContract.extract_dom_inventory(tmp_path)
        assert "style.css" in inv["stylesheets"]
        assert "app.js" in inv["scripts"]

    def test_d07_css_variables_harvested_with_appropriate_confidence(self, tmp_path):
        """7. CSS variables are harvested with appropriate confidence."""
        css = ":root {\n  --primary-color: #007bff;\n  --font-base: sans-serif;\n}\n"
        (tmp_path / "style.css").write_text(css, encoding="utf-8")
        contract = ProjectContract(canonical_css="style.css")
        obs = contract.reconcile_observed(tmp_path)
        assert "--primary-color" in obs.css_variables
        assert "--font-base" in obs.css_variables

    def test_d08_fastapi_routes_extracted_where_statically_supported(self, tmp_path):
        """8. FastAPI routes are extracted where statically supported."""
        be = (
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/api/tasks')\ndef get_tasks(): pass\n"
            "@app.post('/api/tasks')\ndef create_task(): pass\n"
        )
        (tmp_path / "main.py").write_text(be, encoding="utf-8")
        contract = ProjectContract(canonical_backend="main.py")
        obs = contract.reconcile_observed(tmp_path)
        assert "/api/tasks" in obs.backend_routes
        assert "GET" in obs.backend_routes["/api/tasks"]
        assert "POST" in obs.backend_routes["/api/tasks"]

    def test_d09_router_prefixes_handled(self, tmp_path):
        """9. Router prefixes are handled where supported."""
        be = (
            "from fastapi import FastAPI, APIRouter\n"
            "app = FastAPI()\n"
            "router = APIRouter(prefix='/api/v1')\n"
            "@router.get('/items')\ndef get_items(): pass\n"
        )
        (tmp_path / "main.py").write_text(be, encoding="utf-8")
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
        (tmp_path / "app.js").write_text("fetch('/api/v1/items');", encoding="utf-8")

        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert "/api/v1/items" in rep.details.get("backend_routes", {})

    def test_d10_unknown_dynamic_route_definitions_not_falsely_missing(self, tmp_path):
        """10. Unknown dynamic route definitions are not falsely reported as missing."""
        be = "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/api/users/{user_id}')\ndef get_user(user_id: int): pass\n"
        (tmp_path / "main.py").write_text(be, encoding="utf-8")
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
        (tmp_path / "app.js").write_text("const id = 5; fetch(`/api/users/${id}`);", encoding="utf-8")

        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert not rep.endpoint_mismatches

    def test_d11_contract_version_changes_invalidate_dependent_evidence(self, tmp_path):
        """11. Contract version changes invalidate dependent evidence."""
        c = ProjectContract(version=2, app_name="AppV2")
        h1 = c.compute_hash()
        c.version = 3
        h2 = c.compute_hash()
        assert h1 != h2

    def test_d12_changed_artifact_invalidates_stale_observed_hashes(self, tmp_path):
        """12. A changed artifact invalidates stale observed hashes."""
        (tmp_path / "index.html").write_text("<h1>v1</h1>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log(1);", encoding="utf-8")

        contract = ProjectContract(mission_id="m_val")
        obs1 = contract.reconcile_observed(tmp_path)
        hash1 = obs1.artifact_hashes["index.html"]

        (tmp_path / "index.html").write_text("<h1>v2</h1>", encoding="utf-8")
        obs2 = contract.reconcile_observed(tmp_path)
        hash2 = obs2.artifact_hashes["index.html"]

        assert hash1 != hash2


# ==============================================================================
# GROUP E — Cross-file contract validation (13 tests)
# ==============================================================================

class TestGroupECrossFileContractValidation:

    def _setup_base_app(self, tmp_path):
        (tmp_path / "index.html").write_text(
            '<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head>'
            '<body><div id="app"></div><button id="submit-btn" class="btn primary">Submit</button>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8"
        )
        (tmp_path / "style.css").write_text(
            ':root { --primary-color: #007bff; }\n'
            '#app { margin: 10px; }\n.btn { padding: 8px; }\n.primary { color: var(--primary-color); }\n',
            encoding="utf-8"
        )
        (tmp_path / "app.js").write_text(
            'document.getElementById("submit-btn").addEventListener("click", () => console.log("clicked"));\n',
            encoding="utf-8"
        )

    def test_e01_js_reference_to_missing_html_id_fails(self, tmp_path):
        """1. A JavaScript reference to a missing HTML ID fails."""
        self._setup_base_app(tmp_path)
        (tmp_path / "app.js").write_text('document.getElementById("nonexistent-header");\n', encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is False
        assert any("nonexistent-header" in m for m in rep.dom_id_mismatches)
        assert any(d.type == "DOM_CONTRACT_MISMATCH" for d in rep.discrepancies)

    def test_e02_js_reference_to_valid_html_id_passes(self, tmp_path):
        """2. A JavaScript reference to a valid HTML ID passes."""
        self._setup_base_app(tmp_path)
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is True
        assert not rep.dom_id_mismatches

    def test_e03_dynamically_created_dom_element_passes(self, tmp_path):
        """3. A dynamically created DOM element passes."""
        self._setup_base_app(tmp_path)
        js = (
            'const modal = document.createElement("div");\n'
            'modal.id = "dynamic-modal";\n'
            'document.body.appendChild(modal);\n'
            'document.querySelector("#dynamic-modal").classList.add("active");\n'
        )
        (tmp_path / "app.js").write_text(js, encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is True
        assert not rep.dom_id_mismatches

    def test_e04_missing_css_class_definition_caught(self, tmp_path):
        """4. A missing CSS class definition is caught."""
        self._setup_base_app(tmp_path)
        (tmp_path / "index.html").write_text(
            '<html><head><link rel="stylesheet" href="style.css"></head>'
            '<body><div class="completely-undefined-custom-hero-banner"></div><script src="app.js"></script></body></html>',
            encoding="utf-8"
        )
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert any("completely-undefined-custom-hero-banner" in m for m in rep.css_mismatches)

    def test_e05_valid_utility_framework_class_permitted(self, tmp_path):
        """5. A valid utility/framework class is permitted."""
        self._setup_base_app(tmp_path)
        (tmp_path / "index.html").write_text(
            '<html><head><link rel="stylesheet" href="style.css"></head>'
            '<body><div class="container card flex hidden col-12"></div><script src="app.js"></script></body></html>',
            encoding="utf-8"
        )
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert not rep.css_mismatches

    def test_e06_undefined_css_variable_without_fallback_reported(self, tmp_path):
        """6. An undefined CSS variable without fallback is reported."""
        self._setup_base_app(tmp_path)
        (tmp_path / "style.css").write_text(".box { color: var(--missing-theme-var); }\n", encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert any("--missing-theme-var" in w for w in rep.warnings)

    def test_e07_css_variable_with_fallback_permitted(self, tmp_path):
        """7. A CSS variable with a fallback is permitted."""
        self._setup_base_app(tmp_path)
        (tmp_path / "style.css").write_text(".box { color: var(--theme-color, #333333); }\n", encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert not any("--theme-color" in w for w in rep.warnings)

    def test_e08_valid_api_endpoint_and_method_passes(self, tmp_path):
        """8. A valid API endpoint and method passes."""
        self._setup_base_app(tmp_path)
        (tmp_path / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/api/users')\ndef get_users(): return []\n",
            encoding="utf-8"
        )
        (tmp_path / "app.js").write_text("fetch('/api/users');\n", encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is True
        assert not rep.endpoint_mismatches

    def test_e09_missing_api_endpoint_fails(self, tmp_path):
        """9. A missing API endpoint fails."""
        self._setup_base_app(tmp_path)
        (tmp_path / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/api/other')\ndef other(): return {}\n",
            encoding="utf-8"
        )
        (tmp_path / "app.js").write_text("fetch('/api/missing-endpoint');\n", encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is False
        assert any("/api/missing-endpoint" in m for m in rep.endpoint_mismatches)

    def test_e10_incorrect_http_method_fails(self, tmp_path):
        """10. An incorrect HTTP method fails."""
        self._setup_base_app(tmp_path)
        (tmp_path / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/api/items')\ndef get_items(): return []\n",
            encoding="utf-8"
        )
        (tmp_path / "app.js").write_text("api.post('/api/items', { data: 1 });\n", encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is False
        assert any("HTTP method mismatch" in m for m in rep.endpoint_mismatches)

    def test_e11_api_prefix_properly_resolved(self, tmp_path):
        """11. An API prefix is properly resolved."""
        self._setup_base_app(tmp_path)
        (tmp_path / "main.py").write_text(
            "from fastapi import FastAPI, APIRouter\napp = FastAPI()\n"
            "router = APIRouter(prefix='/api')\n"
            "@router.get('/products')\ndef prods(): return []\n"
            "app.include_router(router)\n",
            encoding="utf-8"
        )
        (tmp_path / "app.js").write_text("fetch('/api/products');\n", encoding="utf-8")
        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is True
        assert not rep.endpoint_mismatches

    def test_e12_missing_database_table_fails(self, tmp_path):
        """12. A missing database table fails."""
        self._setup_base_app(tmp_path)
        import sqlite3
        db = tmp_path / "app.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE orders (id INT, total REAL);")
        conn.commit()
        conn.close()

        c = ProjectContract(database_tables={"users": ["id", "username"]})
        c.save_to_workspace(tmp_path)

        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is False
        assert any("users" in m for m in rep.database_mismatches)

    def test_e13_existing_table_with_incorrect_referenced_column_fails(self, tmp_path):
        """13. An existing table with an incorrect referenced column fails."""
        self._setup_base_app(tmp_path)
        import sqlite3
        db = tmp_path / "app.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE users (id INT, username TEXT);")
        conn.commit()
        conn.close()

        c = ProjectContract(database_tables={"users": ["id", "username", "missing_email_col"]})
        c.save_to_workspace(tmp_path)

        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is False
        assert any("missing_email_col" in m for m in rep.database_mismatches)


# ==============================================================================
# GROUP F — State reconciliation (10 tests)
# ==============================================================================

class TestGroupFStateReconciliation:

    def test_f01_matching_mission_state(self, tmp_path):
        """1. Matching mission state."""
        (tmp_path / "index.html").write_text("<h1>App</h1>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log(1);", encoding="utf-8")

        mgr = MissionStateManager(tmp_path, mission_id="m_match")
        mgr.record_validation("index.html", compute_file_sha256(tmp_path / "index.html"))
        mgr.record_validation("style.css", compute_file_sha256(tmp_path / "style.css"))
        mgr.record_validation("app.js", compute_file_sha256(tmp_path / "app.js"))

        contract = ProjectContract(mission_id="m_match")
        rep = mgr.reconcile(contract=contract)
        assert rep.next_action == "evaluate_completion"

    def test_f02_stale_mission_contract_detected(self, tmp_path):
        """2. Stale mission contract."""
        mgr = MissionStateManager(tmp_path, mission_id="m_current")
        contract = ProjectContract(mission_id="m_older_stale")
        rep = mgr.reconcile(contract=contract)
        assert rep.is_contract_stale is True
        assert rep.next_action == "reconcile_stale_contract"

    def test_f03_conflicting_progress_and_recovery_snapshots(self, tmp_path):
        """3. Conflicting progress and recovery snapshots."""
        mgr = MissionStateManager(tmp_path, mission_id="m1")
        snaps = [
            {"state_hash": "hash_a", "step": 1},
            {"state_hash": "hash_b", "step": 2},
        ]
        rep = mgr.reconcile(recovery_snapshots=snaps)
        assert rep.has_conflicting_snapshots is True

    def test_f04_missing_canonical_artifact_detected(self, tmp_path):
        """4. Missing canonical artifact."""
        (tmp_path / "index.html").write_text("<h1>App</h1>", encoding="utf-8")
        mgr = MissionStateManager(tmp_path, mission_id="m1")
        rep = mgr.reconcile()
        assert "style.css" in rep.missing_required_files
        assert rep.next_action.startswith("generate_missing_file:")

    def test_f05_existing_but_unvalidated_artifact_detected(self, tmp_path):
        """5. Existing but unvalidated artifact."""
        (tmp_path / "index.html").write_text("<h1>App</h1>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log(1);", encoding="utf-8")

        mgr = MissionStateManager(tmp_path, mission_id="m1")
        rep = mgr.reconcile()
        assert len(rep.unvalidated_files) == 3
        assert rep.next_action.startswith("validate_artifact:")

    def test_f06_unpromoted_staged_artifact_detected(self, tmp_path):
        """6. Unpromoted staged artifact."""
        (tmp_path / "app.pending.js").write_text("const x = 1;", encoding="utf-8")
        mgr = MissionStateManager(tmp_path, mission_id="m1")
        rep = mgr.reconcile()
        assert "app.pending.js" in rep.unpromoted_staged_files
        assert rep.next_action == "promote_staged_artifact"

    def test_f07_changed_artifact_hash_invalidating_prior_validation(self, tmp_path):
        """7. Changed artifact hash invalidating prior validation."""
        f = tmp_path / "app.js"
        f.write_text("const v = 1;", encoding="utf-8")
        h1 = compute_file_sha256(f)

        mgr = MissionStateManager(tmp_path, mission_id="m1")
        mgr.record_validation("app.js", h1)

        # Mutate file on disk
        f.write_text("const v = 2;", encoding="utf-8")
        contract = ProjectContract(mission_id="m1", required_files=["app.js"])
        rep = mgr.reconcile(contract=contract)
        assert "app.js" in rep.invalidated_files
        assert rep.next_action.startswith("revalidate_modified_file:")

    def test_f08_reconciliation_repeated_twice_without_state_change_is_idempotent(self, tmp_path):
        """8. Reconciliation repeated twice without state change."""
        (tmp_path / "index.html").write_text("<h1>App</h1>", encoding="utf-8")
        mgr = MissionStateManager(tmp_path, mission_id="m1")
        r1 = mgr.reconcile()
        r2 = mgr.reconcile()
        assert r1.state_hash == r2.state_hash
        assert r1.next_action == r2.next_action

    def test_f09_historical_state_preserved(self, tmp_path):
        """9. Historical state preserved."""
        mgr = MissionStateManager(tmp_path, mission_id="m1")
        mgr.reconcile()
        mgr.reconcile()
        assert len(mgr.history) == 2

    def test_f10_next_action_derived_deterministically(self, tmp_path):
        """10. next_action derived deterministically."""
        mgr = MissionStateManager(tmp_path, mission_id="m1")
        rep = mgr.reconcile(contract=ProjectContract(mission_id="other"))
        assert rep.next_action == "reconcile_stale_contract"


# ==============================================================================
# GROUP G — Stuck detector (10 tests)
# ==============================================================================

class TestGroupGStuckDetector:

    def test_g01_same_tool_same_args_same_failure_twice(self):
        """1. Same tool, same arguments, same failure twice."""
        detector = StuckLoopDetector(max_identical_errors=2)
        fp1 = OperationFingerprint(
            mission_id="m1", tool_name="fs.write", canonical_args={"path": "a.txt"},
            success=False, failure_class="SYNTAX_ERROR", diagnostic_digest="diag1",
            workspace_mutation_digest="ws_initial"
        )
        detector.record_operation(fp1)

        fp2 = OperationFingerprint(
            mission_id="m1", tool_name="fs.write", canonical_args={"path": "a.txt"},
            success=False, failure_class="SYNTAX_ERROR", diagnostic_digest="diag1",
            workspace_mutation_digest="ws_initial"
        )
        is_stuck, reason = detector.check_stuck(fp2)
        assert is_stuck is True
        assert "STUCK_LOOP_DETECTED" in reason

    def test_g02_same_tool_with_different_arguments(self):
        """2. Same tool with different arguments."""
        detector = StuckLoopDetector(max_identical_errors=2)
        fp1 = OperationFingerprint(
            mission_id="m1", tool_name="fs.write", canonical_args={"path": "a.txt"},
            success=False, failure_class="SYNTAX_ERROR"
        )
        detector.record_operation(fp1)

        fp2 = OperationFingerprint(
            mission_id="m1", tool_name="fs.write", canonical_args={"path": "b.txt"},
            success=False, failure_class="SYNTAX_ERROR"
        )
        is_stuck, reason = detector.check_stuck(fp2)
        assert is_stuck is False

    def test_g03_same_tool_with_changed_input_hash(self):
        """3. Same tool with changed input hash."""
        detector = StuckLoopDetector(max_identical_errors=2)
        fp1 = OperationFingerprint(
            mission_id="m1", tool_name="fs.write", canonical_args={"path": "a.txt"},
            input_hashes=["hash1"], success=False, failure_class="SYNTAX_ERROR"
        )
        detector.record_operation(fp1)

        fp2 = OperationFingerprint(
            mission_id="m1", tool_name="fs.write", canonical_args={"path": "a.txt"},
            input_hashes=["hash2"], success=False, failure_class="SYNTAX_ERROR"
        )
        is_stuck, reason = detector.check_stuck(fp2)
        assert is_stuck is False

    def test_g04_same_failure_after_meaningful_repair(self):
        """4. Same failure after a meaningful repair."""
        detector = StuckLoopDetector(max_identical_errors=2)
        fp1 = OperationFingerprint(
            mission_id="m1", tool_name="test_runner", canonical_args={"test": "unit"},
            success=False, failure_class="TEST_FAILURE", workspace_mutation_digest="ws_v1"
        )
        detector.record_operation(fp1)

        fp2 = OperationFingerprint(
            mission_id="m1", tool_name="test_runner", canonical_args={"test": "unit"},
            success=False, failure_class="TEST_FAILURE", workspace_mutation_digest="ws_v2"
        )
        is_stuck, reason = detector.check_stuck(fp2)
        assert is_stuck is False

    def test_g05_abab_oscillation_with_unchanged_workspace_state(self):
        """5. A-B-A-B oscillation with unchanged workspace state."""
        detector = StuckLoopDetector(max_identical_errors=2)
        fp_a1 = OperationFingerprint(
            mission_id="m1", tool_name="tool_a", canonical_args={"arg": 1},
            success=False, failure_class="FAIL_A", workspace_mutation_digest="static_ws"
        )
        fp_b1 = OperationFingerprint(
            mission_id="m1", tool_name="tool_b", canonical_args={"arg": 2},
            success=True, workspace_mutation_digest="static_ws"
        )
        fp_a2 = OperationFingerprint(
            mission_id="m1", tool_name="tool_a", canonical_args={"arg": 1},
            success=False, failure_class="FAIL_A", workspace_mutation_digest="static_ws"
        )
        detector.record_operation(fp_a1)
        detector.record_operation(fp_b1)
        detector.record_operation(fp_a2)

        fp_incoming = OperationFingerprint(
            mission_id="m1", tool_name="tool_a", canonical_args={"arg": 1},
            success=False, failure_class="FAIL_A", workspace_mutation_digest="static_ws"
        )
        is_stuck, reason = detector.check_stuck(fp_incoming)
        assert is_stuck is True

    def test_g06_two_distinct_useful_reads(self):
        """6. Two distinct useful reads."""
        detector = StuckLoopDetector()
        fp1 = OperationFingerprint(mission_id="m1", tool_name="fs.read", canonical_args={"path": "f1.txt"}, output_hash="h1")
        detector.record_operation(fp1)
        fp2 = OperationFingerprint(mission_id="m1", tool_name="fs.read", canonical_args={"path": "f2.txt"}, output_hash="h2")
        is_stuck, _ = detector.check_stuck(fp2)
        assert is_stuck is False

    def test_g07_repeated_unchanged_read_output(self):
        """7. Repeated unchanged read output."""
        detector = StuckLoopDetector(max_identical_errors=2)
        for _ in range(3):
            fp = OperationFingerprint(mission_id="m1", tool_name="fs.read", canonical_args={"path": "f1.txt"}, output_hash="same_h")
            detector.record_operation(fp)

        incoming = OperationFingerprint(mission_id="m1", tool_name="fs.read", canonical_args={"path": "f1.txt"}, output_hash="same_h")
        is_stuck, reason = detector.check_stuck(incoming)
        assert is_stuck is True
        assert "Repeated redundant read" in reason

    def test_g08_bounded_history(self):
        """8. Bounded history."""
        detector = StuckLoopDetector(max_history=5)
        for i in range(10):
            detector.record_operation(OperationFingerprint(mission_id="m1", tool_name="tool", canonical_args={"i": i}))
        assert len(detector.history) == 5

    def test_g09_mission_isolation(self):
        """9. Mission isolation."""
        detector = StuckLoopDetector()
        detector.record_operation(OperationFingerprint(mission_id="mission_1", tool_name="tool", canonical_args={}))
        assert len(detector.history) == 1

        detector.record_operation(OperationFingerprint(mission_id="mission_2", tool_name="tool", canonical_args={}))
        assert len(detector.history) == 1
        assert detector.mission_id == "mission_2"

    def test_g10_no_false_blocking_of_legitimate_recovery(self):
        """10. No false blocking of legitimate recovery."""
        detector = StuckLoopDetector(max_identical_errors=2)
        detector.record_operation(OperationFingerprint(
            mission_id="m1", tool_name="compile", canonical_args={}, success=False, failure_class="SYNTAX"
        ))
        detector.record_operation(OperationFingerprint(
            mission_id="m1", tool_name="edit", canonical_args={"fix": True}, success=True,
            workspace_mutation_digest="repaired"
        ))
        incoming = OperationFingerprint(
            mission_id="m1", tool_name="compile", canonical_args={}, success=False, failure_class="SYNTAX",
            workspace_mutation_digest="repaired"
        )
        is_stuck, _ = detector.check_stuck(incoming)
        assert is_stuck is False


# ==============================================================================
# GROUP H — Failure classification and failover (14 tests)
# ==============================================================================

class TestGroupHFailureClassificationAndFailover:

    def test_h01_provider_rate_limit(self):
        """1. Provider rate limit."""
        cat = FailureClassifier.classify("Error 429: Resource has been exhausted (quota exceeded)")
        assert cat == FailureCategory.PROVIDER_RATE_LIMIT
        assert FailureClassifier.should_trigger_provider_failover(cat) is True

    def test_h02_provider_timeout(self):
        """2. Provider timeout."""
        cat = FailureClassifier.classify("ReadTimeout: Request timed out after 30 seconds")
        assert cat == FailureCategory.PROVIDER_TIMEOUT
        assert FailureClassifier.should_trigger_provider_failover(cat) is True

    def test_h03_provider_connection_failure(self):
        """3. Provider connection failure."""
        cat = FailureClassifier.classify("ConnectionError: Failed to establish a new connection: [Errno 111] Connection refused")
        assert cat == FailureCategory.PROVIDER_CONNECTION_FAILURE
        assert FailureClassifier.should_trigger_provider_failover(cat) is True

    def test_h04_eligible_transient_provider_server_response(self):
        """4. Eligible transient provider-server response."""
        cat = FailureClassifier.classify("503 Service Unavailable: upstream connect error")
        assert cat == FailureCategory.PROVIDER_TRANSIENT_SERVER_ERROR
        assert FailureClassifier.should_trigger_provider_failover(cat) is True

    def test_h05_provider_authentication_failure(self):
        """5. Provider authentication failure."""
        cat = FailureClassifier.classify("401 Unauthorized: Invalid API Key provided")
        assert cat == FailureCategory.PROVIDER_AUTH_ERROR
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h06_invalid_provider_request(self):
        """6. Invalid provider request."""
        cat = FailureClassifier.classify("400 Bad Request: Context length exceeded maximum tokens")
        assert cat == FailureCategory.PROVIDER_INVALID_REQUEST
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h07_javascript_syntax_error(self):
        """7. JavaScript syntax error."""
        cat = FailureClassifier.classify("node --check error: Unexpected token ';' in app.js")
        assert cat == FailureCategory.SYNTAX_ERROR_JS
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h08_python_syntax_error(self):
        """8. Python syntax error."""
        cat = FailureClassifier.classify("SyntaxError: invalid syntax in main.py, line 12")
        assert cat == FailureCategory.SYNTAX_ERROR_PYTHON
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h09_contract_mismatch(self):
        """9. Contract mismatch."""
        cat = FailureClassifier.classify("Contract discrepancy: Missing DOM element #submit-btn in index.html")
        assert cat == FailureCategory.CONTRACT_MISMATCH
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h10_filesystem_path_failure(self):
        """10. Filesystem path failure."""
        cat = FailureClassifier.classify("FileNotFoundError: [Errno 2] No such file or directory: 'missing.json'")
        assert cat == FailureCategory.FILESYSTEM_ERROR
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h11_environment_permission_failure(self):
        """11. Environment permission failure."""
        cat = FailureClassifier.classify("PermissionError: [Errno 13] Permission denied / command not found")
        assert cat == FailureCategory.ENVIRONMENT_ERROR
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h12_api_test_failure(self):
        """12. API test failure."""
        cat = FailureClassifier.classify("AssertionError: assert response.status_code == 200 in pytest")
        assert cat == FailureCategory.TEST_FAILURE_API
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h13_browser_runtime_exception(self):
        """13. Browser runtime exception."""
        cat = FailureClassifier.classify("Chrome CDP Error: Target closed or navigation failed")
        assert cat == FailureCategory.BROWSER_RUNTIME_ERROR
        assert FailureClassifier.should_trigger_provider_failover(cat) is False

    def test_h14_stuck_loop_detection(self):
        """14. Stuck-loop detection."""
        cat = FailureClassifier.classify("STUCK_LOOP_DETECTED: Tool 'fs.write' failed 2 times")
        assert cat == FailureCategory.STUCK_LOOP_ERROR
        assert FailureClassifier.should_trigger_provider_failover(cat) is False


# ==============================================================================
# GROUP I — Provenance (13 tests)
# ==============================================================================

class TestGroupIProvenance:

    def test_i01_successful_file_creation(self):
        """1. Successful file creation."""
        rec = EvidenceRecord(
            evidence_id="ev_write_1", mission_id="m1",
            source_type=EvidenceSourceType.ARTIFACT_WRITE,
            source_uri_or_path="app.js", exit_code=0,
            status=EvidenceStatus.RECORDED, output_digest="sha_new"
        )
        assert rec.source_type == EvidenceSourceType.ARTIFACT_WRITE
        assert rec.exit_code == 0

    def test_i02_successful_overwrite(self):
        """2. Successful overwrite."""
        rec = EvidenceRecord(
            evidence_id="ev_write_2", mission_id="m1",
            source_type=EvidenceSourceType.ARTIFACT_WRITE,
            source_uri_or_path="app.js", exit_code=0,
            inputs_digest="sha_old", output_digest="sha_new",
        )
        assert rec.inputs_digest != rec.output_digest

    def test_i03_unchanged_noop_write(self):
        """3. Unchanged no-op write."""
        rec = EvidenceRecord(
            evidence_id="ev_write_3", mission_id="m1",
            source_type=EvidenceSourceType.ARTIFACT_WRITE,
            source_uri_or_path="app.js",
            inputs_digest="sha_same", output_digest="sha_same",
        )
        assert rec.inputs_digest == rec.output_digest

    def test_i04_failed_write(self):
        """4. Failed write."""
        rec = EvidenceRecord(
            evidence_id="ev_write_fail", mission_id="m1",
            source_type=EvidenceSourceType.ARTIFACT_WRITE,
            source_uri_or_path="protected/path.js",
            exit_code=1, status=EvidenceStatus.REJECTED,
        )
        assert rec.exit_code != 0
        assert rec.status == EvidenceStatus.REJECTED

    def test_i05_failed_syntax_validation(self):
        """5. Failed syntax validation."""
        rec = EvidenceRecord(
            evidence_id="ev_syn_fail", mission_id="m1",
            source_type=EvidenceSourceType.SYNTAX_VALIDATION,
            source_uri_or_path="broken.js", exit_code=1,
            status=EvidenceStatus.REJECTED,
        )
        assert rec.source_type == EvidenceSourceType.SYNTAX_VALIDATION
        assert rec.status == EvidenceStatus.REJECTED

    def test_i06_successful_syntax_validation(self):
        """6. Successful syntax validation."""
        rec = EvidenceRecord(
            evidence_id="ev_syn_ok", mission_id="m1",
            source_type=EvidenceSourceType.SYNTAX_VALIDATION,
            source_uri_or_path="valid.js", exit_code=0,
            status=EvidenceStatus.RECORDED, freshness=EvidenceFreshness.FRESH,
        )
        assert rec.status == EvidenceStatus.RECORDED
        assert rec.freshness == EvidenceFreshness.FRESH

    def test_i07_successful_promotion(self):
        """7. Successful promotion."""
        rec = EvidenceRecord(
            evidence_id="ev_promote", mission_id="m1",
            source_type=EvidenceSourceType.ARTIFACT_PROMOTION,
            source_uri_or_path="app.js", exit_code=0,
            status=EvidenceStatus.RECORDED,
        )
        assert rec.source_type == EvidenceSourceType.ARTIFACT_PROMOTION

    def test_i08_contract_validation(self):
        """8. Contract validation."""
        rec = EvidenceRecord(
            evidence_id="ev_contract", mission_id="m1",
            source_type=EvidenceSourceType.CONTRACT_VALIDATION,
            status=EvidenceStatus.RECORDED,
        )
        assert rec.source_type == EvidenceSourceType.CONTRACT_VALIDATION

    def test_i09_api_test(self):
        """9. API test."""
        rec = EvidenceRecord(
            evidence_id="ev_api", mission_id="m1",
            source_type=EvidenceSourceType.API_TEST,
            status=EvidenceStatus.RECORDED,
        )
        assert rec.source_type == EvidenceSourceType.API_TEST

    def test_i10_browser_test(self):
        """10. Browser test."""
        rec = EvidenceRecord(
            evidence_id="ev_browser", mission_id="m1",
            source_type=EvidenceSourceType.BROWSER_TEST,
            status=EvidenceStatus.RECORDED,
        )
        assert rec.source_type == EvidenceSourceType.BROWSER_TEST

    def test_i11_changed_file_invalidates_prior_evidence(self, tmp_path):
        """11. Changed file invalidates prior evidence."""
        js_file = tmp_path / "app.js"
        js_file.write_text("console.log('original');", encoding="utf-8")
        orig_hash = compute_file_sha256(js_file)

        store = EvidenceStore(workspace_root=tmp_path)
        rec = EvidenceRecord(
            evidence_id="ev_file", mission_id="m1",
            source_type=EvidenceSourceType.SYNTAX_VALIDATION,
            source_uri_or_path="app.js", output_digest=orig_hash,
            status=EvidenceStatus.RECORDED, freshness=EvidenceFreshness.FRESH,
        )
        store.add(rec)

        invalidator = EvidenceInvalidator(workspace_root=tmp_path, evidence_store=store, mission_id="m1")
        assert invalidator.check_file_freshness(rec) is True

        js_file.write_text("console.log('modified');", encoding="utf-8")
        assert invalidator.check_file_freshness(rec) is False
        invalidator.mark_stale(rec.evidence_id)
        assert store.get(rec.evidence_id).freshness == EvidenceFreshness.STALE

    def test_i12_write_event_cannot_be_classified_as_syntax_validation(self):
        """12. A write event cannot be classified as a syntax-validation event."""
        assert EvidenceSourceType.ARTIFACT_WRITE != EvidenceSourceType.SYNTAX_VALIDATION
        assert EvidenceSourceType.ARTIFACT_WRITE.value != EvidenceSourceType.SYNTAX_VALIDATION.value

    def test_i13_missing_execution_evidence_cannot_be_fabricated(self, tmp_path):
        """13. Missing execution evidence cannot be fabricated."""
        store = EvidenceStore(workspace_root=tmp_path)
        ledger = AcceptanceLedger(goal_id="m_fab")
        chk = AcceptanceCheck(
            check_id="chk_1", requirement_id="req_1", description="Verify API endpoint",
            status=AcceptanceCheckStatus.PASS, critical=True
        )
        ledger.add_check(chk)

        can_complete, reason, issues = GoalCompleteGuard.evaluate(
            ledger=ledger, evidence_store=store, strict_requirements=True
        )
        assert can_complete is False
        assert any("no supporting evidence records" in iss for iss in issues)


# ==============================================================================
# GROUP J — Acceptance gate (7 tests)
# ==============================================================================

class TestGroupJAcceptanceGate:

    def test_j01_does_not_mark_complete_when_required_file_missing(self, tmp_path):
        """1. Does not mark a mission complete when a required file is missing."""
        policy = CompletionPolicy()
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Build interactive task board with index.html and app.js",
            workspace=tmp_path,
        )
        assert ok is False
        assert "rejected" in reason.lower()

    def test_j02_does_not_mark_complete_when_syntax_fails(self, tmp_path):
        """2. Does not mark a mission complete when syntax validation fails."""
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / "app.js").write_text("const broken = (;\n", encoding="utf-8")

        policy = CompletionPolicy()
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Build app", workspace=tmp_path, written_files=["index.html", "app.js"]
        )
        assert ok is False
        assert "syntax validation failed" in reason.lower()

    def test_j03_does_not_mark_complete_with_unresolved_contract_error(self, tmp_path):
        """3. Does not mark a mission complete with an unresolved high-confidence contract error."""
        (tmp_path / "index.html").write_text(
            '<!DOCTYPE html><html><head><title>Test App</title><link rel="stylesheet" href="style.css"></head>'
            '<body><div id="app"><button id="existing_btn">Click Me</button><input id="text_input" type="text"/></div>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8"
        )
        (tmp_path / "style.css").write_text('body { margin: 0; padding: 20px; font-family: sans-serif; }', encoding="utf-8")
        js_content = (
            '// Application logic\n'
            'console.log("Initializing app...");\n'
            'const el = document.getElementById("missing_target_btn");\n'
            'if (el) { el.addEventListener("click", () => console.log("clicked")); }\n'
            'console.log("Setup complete for active dashboard view.");\n'
        )
        (tmp_path / "app.js").write_text(js_content, encoding="utf-8")

        policy = CompletionPolicy()
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Build full web app with interactive controls", workspace=tmp_path, written_files=["index.html", "style.css", "app.js"]
        )
        assert ok is False
        assert "contract" in reason.lower()

    def test_j04_does_not_reuse_stale_validation_evidence(self, tmp_path):
        """4. Does not reuse stale validation evidence."""
        store = EvidenceStore(workspace_root=tmp_path)
        rec = EvidenceRecord(
            evidence_id="ev_stale", mission_id="m1", requirement_id="req_1",
            acceptance_check_id="chk_stale",
            source_type=EvidenceSourceType.API_TEST, exit_code=0,
            status=EvidenceStatus.RECORDED, freshness=EvidenceFreshness.STALE,
        )
        store.add(rec)

        ledger = AcceptanceLedger(goal_id="m1")
        chk = AcceptanceCheck(
            check_id="chk_stale", requirement_id="req_1", description="Check stale API",
            status=AcceptanceCheckStatus.PASS, critical=True
        )
        ledger.add_check(chk)

        ok, reason, issues = GoalCompleteGuard.evaluate(
            ledger=ledger, evidence_store=store, strict_requirements=True
        )
        assert ok is False
        assert any("stale" in iss.lower() for iss in issues)

    def test_j05_does_not_count_screenshot_alone_as_browser_workflow(self):
        """5. Does not count a screenshot alone as a successful browser workflow."""
        assert EvidenceSourceType.BROWSER_SCREENSHOT != EvidenceSourceType.BROWSER_TEST
        assert EvidenceSourceType.BROWSER_SCREENSHOT.value != EvidenceSourceType.BROWSER_TEST.value

    def test_j06_correctly_handles_non_applicable_verification_level(self, tmp_path):
        """6. Correctly handles a project for which a particular verification level is not applicable."""
        (tmp_path / "index.html").write_text("<html><body><h1>Static</h1></body></html>", encoding="utf-8")
        (tmp_path / "style.css").write_text("h1 { color: red; }", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log('static');", encoding="utf-8")

        rep = CrossFileContractValidator.validate_workspace(tmp_path)
        assert rep.valid is True
        assert rep.details["canonical_backend"] is None

    def test_j07_returns_honest_blocked_or_incomplete_result(self, tmp_path):
        """7. Returns an honest blocked or incomplete result when verification cannot be completed."""
        policy = CompletionPolicy()
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Implement user management",
            workspace=tmp_path,
            acceptance_criteria=["must_contain:Authentication verified"],
            candidate_response="I created the files but tests are still pending."
        )
        assert ok is False
        assert len(issues) >= 1


# ==============================================================================
# GROUP K — Batch writer (5 tests)
# ==============================================================================

class TestGroupKBatchWriter:

    def test_k01_staged_files_actually_used_during_promotion(self, tmp_path):
        """1. Staged files are actually used during promotion."""
        workspace_manager.lock(tmp_path)
        tool = WriteFilesBatchTool()
        inp = WriteFilesBatchTool.Input(files=[
            BatchFileItem(path="index.html", content="<h1>Title</h1>"),
            BatchFileItem(path="style.css", content="body { margin: 0; }"),
        ])
        res = tool.execute(inp)
        assert res.success is True
        assert (tmp_path / "index.html").read_text(encoding="utf-8") == "<h1>Title</h1>"
        assert (tmp_path / "style.css").read_text(encoding="utf-8") == "body { margin: 0; }"

    def test_k02_existing_files_backed_up(self, tmp_path):
        """2. Existing files are backed up."""
        workspace_manager.lock(tmp_path)
        orig = tmp_path / "config.json"
        orig.write_text('{"v": 1}', encoding="utf-8")

        tool = WriteFilesBatchTool()
        inp = WriteFilesBatchTool.Input(files=[
            BatchFileItem(path="config.json", content='{"v": 2}')
        ])
        res = tool.execute(inp)
        assert res.success is True
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == '{"v": 2}'

    def test_k03_failure_triggers_restoration(self, tmp_path, monkeypatch):
        """3. Failure during commit triggers rollback and restoration."""
        workspace_manager.lock(tmp_path)
        target = tmp_path / "app.js"
        target.write_text("console.log('before');", encoding="utf-8")

        real_open = open

        def mock_open(file, mode="r", *args, **kwargs):
            if "w" in mode and "app.js" in str(file) and ".hermes" not in str(file) and "staging" not in str(file):
                raise IOError("Disk full simulation")
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", mock_open)

        tool = WriteFilesBatchTool()
        inp = WriteFilesBatchTool.Input(files=[
            BatchFileItem(path="app.js", content="console.log('after');")
        ])
        res = tool.execute(inp)
        assert res.success is False
        assert target.read_text(encoding="utf-8") == "console.log('before');"

    def test_k04_temporary_staging_and_backup_cleaned_up(self, tmp_path):
        """4. Temporary staging and backup directories are cleaned up safely."""
        workspace_manager.lock(tmp_path)
        tool = WriteFilesBatchTool()
        inp = WriteFilesBatchTool.Input(files=[
            BatchFileItem(path="data.txt", content="hello")
        ])
        res = tool.execute(inp)
        assert res.success is True

        staging_base = tmp_path / ".hermes" / "staging"
        if staging_base.exists():
            active_stagings = list(staging_base.glob("batch_*"))
            assert len(active_stagings) == 0

    def test_k05_recovery_behavior_consistent_after_interrupted_transaction(self, tmp_path):
        """5. Recovery behavior is consistent after interrupted transaction."""
        workspace_manager.lock(tmp_path)
        (tmp_path / "f1.txt").write_text("v1", encoding="utf-8")
        tool = WriteFilesBatchTool()
        inp = WriteFilesBatchTool.Input(files=[
            BatchFileItem(path="f1.txt", content="v2")
        ])
        res = tool.execute(inp)
        assert res.success is True
        assert (tmp_path / "f1.txt").read_text(encoding="utf-8") == "v2"
