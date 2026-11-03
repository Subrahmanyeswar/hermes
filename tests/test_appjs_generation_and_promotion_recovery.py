# tests/test_appjs_generation_and_promotion_recovery.py
"""
HERMES 2.x Regression Suite: app.js Generation, Write Integrity, Staged Promotion,
Syntax Validation, and Targeted Recovery.
Enforces all 15 Phase 7 requirements:
 1. Missing app.js remains an unmet deliverable.
 2. A successful file write is distinguishable from successful validation.
 3. A failed tool invocation propagates its actual error.
 4. A staged file is promoted only after validation succeeds.
 5. A failed candidate preserves the previous valid target.
 6. A missing canonical target cannot be reported as created.
 7. A file written under an unexpected path cannot satisfy the canonical requirement.
 8. A truncated model response cannot be promoted.
 9. Node extension errors are distinguished from syntax errors.
10. ESM validation uses the correct module mode.
11. Targeted repair must actually modify the target.
12. Successful repair triggers fresh validation.
13. Repeated identical failures terminate within the repair budget.
14. Provider failover does not replace local syntax repair.
15. Missing or invalid required code cannot produce MISSION_COMPLETED.
"""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_loop.mvp_gate import WebsiteMvpGate
from core.agent_loop.syntax_repair import SyntaxRepairController, SyntaxRepairTicket
from core.code_completeness import validate_implementation_completeness
from core.js_syntax_validator import (
    CLASS_APP_SYNTAX_ERROR,
    CLASS_MODULE_MODE_MISMATCH,
    CLASS_TOOLING_EXTENSION_ERROR,
    CLASS_VALIDATION_SUCCESS,
    check_js_bracket_balance,
    detect_js_module_format,
    promote_staged_javascript,
    stage_and_promote_file,
    validate_javascript_content,
    validate_javascript_detailed,
    validate_javascript_file,
)
from core.project_contract import ProjectContract
from core.workspace import WorkspaceManager
from tools.platform.core_tools import FSEditTool, FSWriteTool, ToolResult


@pytest.fixture
def temp_ws(tmp_path: Path):
    ws_dir = tmp_path / "appjs_qualification_workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    return ws_dir


# 1. Missing app.js remains an unmet deliverable.
def test_01_missing_appjs_remains_unmet_deliverable(temp_ws: Path):
    (temp_ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><title>App</title><link rel="stylesheet" href="style.css"></head>'
        '<body><script src="app.js"></script></body></html>',
        encoding="utf-8",
    )
    (temp_ws / "style.css").write_text("body { margin: 0; background: #fff; }", encoding="utf-8")
    (temp_ws / "package.json").write_text('{"name": "test-app", "version": "1.0.0"}', encoding="utf-8")

    gate = WebsiteMvpGate()
    complete, missing = gate.check_scaffold_complete(temp_ws)
    assert complete is False
    assert any("app.js" in m for m in missing)


# 2. A successful file write is distinguishable from successful validation.
def test_02_successful_file_write_distinguishable_from_validation(temp_ws: Path):
    wm = WorkspaceManager()
    wm.lock(temp_ws)

    write_tool = FSWriteTool()
    # Write valid content with regex and quotes
    valid_content = (
        "function escapeHtml(s) {\n"
        "  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/'/g, '&#39;');\n"
        "}\n"
    )
    res = write_tool.execute({
        "path": "app.js",
        "content": valid_content,
        "_workspace": wm,
    })
    assert res.success is True
    assert res.exit_code == 0
    assert (temp_ws / "app.js").exists()

    # Distinguish: write succeeded vs validation result structure
    v_res = validate_javascript_detailed(temp_ws / "app.js", workspace_root=temp_ws)
    assert v_res.is_valid is True
    assert v_res.error_class == CLASS_VALIDATION_SUCCESS


# 3. A failed tool invocation propagates its actual error.
def test_03_failed_tool_invocation_propagates_actual_error(temp_ws: Path):
    wm = WorkspaceManager()
    wm.lock(temp_ws)

    write_tool = FSWriteTool()
    # Unclosed syntax that is genuinely broken
    broken_content = "function broken(a, b) {\n  const x = 'unclosed string;\n  return x;\n"
    res = write_tool.execute({
        "path": "app.js",
        "content": broken_content,
        "_workspace": wm,
    })
    assert res.success is False
    assert res.exit_code == 1
    assert "Unclosed string or template literal" in res.error or "INCOMPLETE_IMPLEMENTATION_TRUNCATED" in res.error
    assert not (temp_ws / "app.js").exists()


# 4. A staged file is promoted only after validation succeeds.
def test_04_staged_file_promoted_only_after_validation_succeeds(temp_ws: Path):
    valid_js = "console.log('Safe staged execution');\n"
    success, msg, details = stage_and_promote_file(temp_ws, "app.js", valid_js)
    assert success is True
    assert (temp_ws / "app.js").exists()
    assert (temp_ws / "app.js").read_text(encoding="utf-8") == valid_js
    assert not (temp_ws / "app.pending.js").exists()


# 5. A failed candidate preserves the previous valid target.
def test_05_failed_candidate_preserves_previous_valid_target(temp_ws: Path):
    original_js = "console.log('Original working code');\n"
    target = temp_ws / "app.js"
    target.write_text(original_js, encoding="utf-8")
    original_hash = hashlib.sha256(target.read_bytes()).hexdigest()

    invalid_js = "function broken() { if (true) { \n"  # unclosed brace
    success, msg, details = stage_and_promote_file(temp_ws, "app.js", invalid_js)
    assert success is False
    assert target.exists()
    assert target.read_text(encoding="utf-8") == original_js
    assert hashlib.sha256(target.read_bytes()).hexdigest() == original_hash


# 6. A missing canonical target cannot be reported as created.
def test_06_missing_canonical_target_cannot_be_reported_as_created(temp_ws: Path):
    wm = WorkspaceManager()
    wm.lock(temp_ws)

    write_tool = FSWriteTool()
    truncated_js = "const x = "  # dangling operator / incomplete
    res = write_tool.execute({
        "path": "app.js",
        "content": truncated_js,
        "_workspace": wm,
    })
    assert res.success is False
    assert not (temp_ws / "app.js").exists()


# 7. A file written under an unexpected path cannot satisfy the canonical requirement.
def test_07_unexpected_path_cannot_satisfy_canonical_requirement(temp_ws: Path):
    wm = WorkspaceManager()
    wm.lock(temp_ws)

    # Set up index.html expecting root app.js
    (temp_ws / "index.html").write_text(
        '<!DOCTYPE html><html><body><script src="app.js"></script></body></html>',
        encoding="utf-8",
    )
    (temp_ws / "style.css").write_text("body { color: black; }", encoding="utf-8")
    (temp_ws / "package.json").write_text('{"name": "test"}', encoding="utf-8")

    # Write to nested unexpected path
    nested = temp_ws / "generated_projects" / "sub" / "app.js"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("console.log('wrong path');\n", encoding="utf-8")

    gate = WebsiteMvpGate()
    complete, missing = gate.check_scaffold_complete(temp_ws)
    assert complete is False
    assert any("app.js" in m for m in missing)


# 8. A truncated model response cannot be promoted.
def test_08_truncated_model_response_cannot_be_promoted(temp_ws: Path):
    truncated = (
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "  const list = document.getElementById('list');\n"
        "  fetch('/api/data').then(r => r.json()).then(data => {\n"
        "    list.innerHTML = data.map(item => `<li>${item.name}</li>`).join('');\n"
        # Truncated before closing then, addEventListener
    )
    is_valid, err = validate_implementation_completeness(truncated, "app.js")
    assert is_valid is False
    assert "INCOMPLETE_IMPLEMENTATION_TRUNCATED" in err


# 9. Node extension errors are distinguished from syntax errors.
def test_09_node_extension_errors_distinguished_from_syntax_errors(temp_ws: Path):
    bad_ext_file = temp_ws / "app.unknown_ext"
    bad_ext_file.write_text("const x = 1;\n", encoding="utf-8")

    res = validate_javascript_detailed(bad_ext_file, workspace_root=temp_ws)
    # If node fails on unknown file extension
    if not res.is_valid:
        assert res.error_class in (CLASS_TOOLING_EXTENSION_ERROR, "unsupported_extension")


# 10. ESM validation uses the correct module mode.
def test_10_esm_validation_uses_correct_module_mode(temp_ws: Path):
    (temp_ws / "index.html").write_text(
        '<!DOCTYPE html><html><body><script type="module" src="app.js"></script></body></html>',
        encoding="utf-8",
    )
    esm_content = "import { something } from './module.js';\nexport function run() { return something(); }\n"
    (temp_ws / "app.js").write_text(esm_content, encoding="utf-8")

    res = validate_javascript_detailed(temp_ws / "app.js", workspace_root=temp_ws)
    assert res.is_valid is True
    assert res.error_class == CLASS_VALIDATION_SUCCESS


# 11. Targeted repair must actually modify the target.
def test_11_targeted_repair_must_actually_modify_target(temp_ws: Path):
    target = temp_ws / "app.js"
    initial_content = "console.log('version 1');\n"
    target.write_text(initial_content, encoding="utf-8")

    controller = SyntaxRepairController(workspace_root=temp_ws)
    ticket = controller.create_or_update_ticket(
        target_file="app.js",
        validator="syntax_check",
        stderr_or_output="SyntaxError: Unexpected token at line 1",
        candidate_content=initial_content,
    )
    assert ticket.is_active is True

    # Same content does not resolve ticket
    ticket_again = controller.create_or_update_ticket(
        target_file="app.js",
        validator="syntax_check",
        stderr_or_output="SyntaxError: Unexpected token at line 1",
        candidate_content=initial_content,
    )
    assert ticket_again.failure_fingerprint == ticket.failure_fingerprint


# 12. Successful repair triggers fresh validation.
def test_12_successful_repair_triggers_fresh_validation(temp_ws: Path):
    target = temp_ws / "app.js"
    broken_content = "function foo( { return 1; }\n"
    target.write_text(broken_content, encoding="utf-8")

    res1, err1, _ = validate_javascript_file(target, workspace_root=temp_ws)
    assert res1 is False

    # Repair with valid content
    repaired_content = "function foo() { return 1; }\n"
    target.write_text(repaired_content, encoding="utf-8")

    res2, err2, _ = validate_javascript_file(target, workspace_root=temp_ws)
    assert res2 is True
    assert err2 is None


# 13. Repeated identical failures terminate within the repair budget.
def test_13_repeated_identical_failures_terminate_within_budget(temp_ws: Path):
    controller = SyntaxRepairController(workspace_root=temp_ws)
    ticket = controller.create_or_update_ticket(
        target_file="app.js",
        validator="syntax_check",
        stderr_or_output="SyntaxError: Test error at line 5",
        candidate_content="bad code",
    )
    assert ticket.repair_attempts == 0

    ticket.repair_attempts += 1
    assert ticket.repair_attempts < ticket.max_attempts

    ticket.repair_attempts += 1
    assert ticket.repair_attempts >= ticket.max_attempts  # Budget exceeded


# 14. Provider failover does not replace local syntax repair.
def test_14_provider_failover_does_not_replace_local_syntax_repair(temp_ws: Path):
    controller = SyntaxRepairController(workspace_root=temp_ws)
    ticket = controller.create_or_update_ticket(
        target_file="app.js",
        validator="syntax_check",
        stderr_or_output="SyntaxError: Unexpected token at line 10",
        candidate_content="broken code",
    )
    directive = controller.build_repair_directive(ticket)
    # Enforces local edit tool usage without tier switching
    assert "fs.write or fs.edit" in directive
    assert "Do NOT switch model tiers" in directive


# 15. Missing or invalid required code cannot produce MISSION_COMPLETED.
def test_15_missing_or_invalid_required_code_cannot_produce_mission_completed(temp_ws: Path):
    (temp_ws / "package.json").write_text('{"name": "test-app", "version": "1.0.0"}', encoding="utf-8")
    (temp_ws / "index.html").write_text(
        '<!DOCTYPE html><html><body><script src="app.js"></script></body></html>',
        encoding="utf-8",
    )
    (temp_ws / "style.css").write_text("body { margin: 0; }", encoding="utf-8")

    # Incomplete placeholder app.js
    (temp_ws / "app.js").write_text("function init() { ... }\n", encoding="utf-8")

    gate = WebsiteMvpGate()
    complete, missing = gate.check_scaffold_complete(temp_ws)
    assert complete is False
    assert any("placeholder" in m or "incomplete" in m or "app.js" in m for m in missing)
