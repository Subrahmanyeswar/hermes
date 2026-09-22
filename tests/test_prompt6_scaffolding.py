# tests/test_prompt6_scaffolding.py
"""
Unit and integration test suite for Prompt 6 Deterministic Scaffolding Engine.
Verifies determinism, variable validation, security boundaries, and overwrite policies.
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from core.scaffold_registry import (
    ScaffoldRegistry,
    ScaffoldTemplate,
    ScaffoldFileSpec,
    scaffold_registry,
)
from core.workspace import workspace_manager, WorkspaceBoundaryError


def test_registered_templates_exist():
    """Verify that default templates are registered and have valid hashes."""
    templates = scaffold_registry.list_templates()
    template_ids = {t["id"] for t in templates}
    assert "html-blank-v1" in template_ids
    assert "web-basic-v1" in template_ids
    assert "python-basic-v1" in template_ids

    for t in templates:
        assert len(t["template_hash"]) == 64
        assert t["version"] >= 1
        assert len(t["files"]) > 0


def test_deterministic_output_reproducibility():
    """Verify that same template + same variables produces 100% bitwise identical output."""
    vars_a = {"project_name": "EduPath Mini", "title": "Interactive Learning Portal"}
    vars_b = {"project_name": "EduPath Mini", "title": "Interactive Learning Portal"}

    res1 = scaffold_registry.render("web-basic-v1", vars_a)
    res2 = scaffold_registry.render("web-basic-v1", vars_b)

    assert res1.overall_hash == res2.overall_hash
    assert res1.file_hashes == res2.file_hashes
    for fn, content in res1.files.items():
        assert content == res2.files[fn]


def test_html_blank_template_rendering():
    """Verify single-file html-blank-v1 rendering."""
    res = scaffold_registry.render("html-blank-v1", {"title": "Blank Page", "description": "Minimal layout"})
    assert res.file_count == 1
    assert "index.html" in res.files
    assert "<!DOCTYPE html>" in res.files["index.html"]
    assert "<title>Blank Page</title>" in res.files["index.html"]
    assert "Minimal layout" in res.files["index.html"]


def test_python_basic_template_rendering():
    """Verify 3-file python-basic-v1 project rendering."""
    res = scaffold_registry.render("python-basic-v1", {"project_name": "data_processor", "version": "2.1.0"})
    assert res.file_count == 3
    assert set(res.files.keys()) == {"main.py", "utils.py", "config.py"}
    assert "data_processor" in res.files["main.py"]
    assert "2.1.0" in res.files["config.py"]


def test_variable_validation_disallowed_key():
    """Verify rejection of unknown variable keys."""
    with pytest.raises(ValueError, match="is not allowed for scaffold"):
        scaffold_registry.render("html-blank-v1", {"malicious_var": "payload"})


def test_variable_validation_code_injection_prevention():
    """Verify rejection of potential code injection patterns in variables."""
    forbidden_inputs = [
        "<script>alert(1)</script>",
        "{{ execute(os.system) }}",
        "eval('import os')",
        "exec('delete')",
        "__import__('sys')",
        "../../etc/passwd",
    ]
    for bad_val in forbidden_inputs:
        with pytest.raises(ValueError, match="forbidden character sequence or potential code injection"):
            scaffold_registry.render("web-basic-v1", {"title": bad_val})


def test_workspace_write_and_overwrite_protection():
    """Verify workspace write safety, file creation, and overwrite prevention."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_manager.lock(tmpdir)
        try:
            rendered = scaffold_registry.render("web-basic-v1", {"project_name": "TestSite"})
            write_res = scaffold_registry.write_scaffold_to_workspace(rendered, target_dir=".", allow_overwrite=False)

            assert write_res["success"] is True
            assert len(write_res["files_written"]) == 3

            # Verify files exist on disk
            for fn in ["index.html", "styles.css", "app.js"]:
                p = Path(tmpdir) / fn
                assert p.exists()
                assert p.stat().st_size > 0

            # Attempting write again with allow_overwrite=False MUST raise FileExistsError
            with pytest.raises(FileExistsError, match="already exists and allow_overwrite=False"):
                scaffold_registry.write_scaffold_to_workspace(rendered, target_dir=".", allow_overwrite=False)

            # Attempting write with allow_overwrite=True succeeds
            overwrite_res = scaffold_registry.write_scaffold_to_workspace(rendered, target_dir=".", allow_overwrite=True)
            assert overwrite_res["success"] is True

        finally:
            workspace_manager.unlock()


def test_workspace_containment_violation_rejection():
    """Verify that attempting to write scaffold outside workspace root is blocked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_manager.lock(tmpdir)
        try:
            rendered = scaffold_registry.render("html-blank-v1", {"title": "Outside"})
            with pytest.raises(WorkspaceBoundaryError):
                scaffold_registry.write_scaffold_to_workspace(rendered, target_dir="../../outside", allow_overwrite=True)
        finally:
            workspace_manager.unlock()
