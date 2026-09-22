# tests/test_prompt6_website_fast_path.py
"""
Unit and integration test suite for Prompt 6 Website Fast Path Engine.
Verifies classification precision, false-positive protection, safe fallback,
Prompt 5 write_files_batch composition, and benchmark isolation.
"""

import pytest
import tempfile
from pathlib import Path

from core.website_fast_path import (
    WebsiteFastPathClassifier,
    WebsiteFastPathCoordinator,
    FastPathDecisionRecord,
)
from core.workspace import workspace_manager


def test_blank_html_fast_path_eligible():
    """Verify clean blank HTML request qualifies for Category A (fully deterministic)."""
    dec = WebsiteFastPathClassifier.evaluate("Create a blank HTML5 page with title 'Demo'")
    assert dec.fast_path_candidate is True
    assert dec.file_count == 1
    assert dec.target_files == ["index.html"]
    assert dec.template_id == "html-blank-v1"
    assert dec.model_required is False
    assert dec.batch_eligible is True


def test_standard_three_file_website_eligible():
    """Verify standard 3-file website qualifies for fast path."""
    dec = WebsiteFastPathClassifier.evaluate("Create a website with index.html, styles.css, and app.js for EduPath Mini")
    assert dec.fast_path_candidate is True
    assert dec.file_count == 3
    assert set(dec.target_files) == {"index.html", "styles.css", "app.js"}
    assert dec.template_id == "web-basic-v1"
    assert dec.batch_eligible is True


def test_rejection_of_four_plus_files():
    """Verify rejection when requested files exceed the <=3 bound."""
    dec = WebsiteFastPathClassifier.evaluate("Create index.html, styles.css, app.js, and extra.js")
    assert dec.fast_path_candidate is False
    assert "exceeds_max_files_bound" in dec.reason


def test_rejection_of_framework_react_nextjs():
    """Verify rejection of modern frontend frameworks."""
    for kw in ["React", "Vue", "Next.js", "Svelte", "Angular"]:
        dec = WebsiteFastPathClassifier.evaluate(f"Build a {kw} single page application")
        assert dec.fast_path_candidate is False
        assert "disqualified_by_framework_keyword" in dec.reason


def test_rejection_of_backend_and_database():
    """Verify rejection of backend, API, and database workloads."""
    for prompt in [
        "Create a website with Flask backend and sqlite database",
        "Build a REST API endpoint for user profile",
        "Make a landing page with Express node backend",
    ]:
        dec = WebsiteFastPathClassifier.evaluate(prompt)
        assert dec.fast_path_candidate is False
        assert "disqualified_by_backend_keyword" in dec.reason


def test_rejection_of_auth_and_security():
    """Verify rejection of authentication, login, and password requests."""
    for prompt in [
        "Create a website with user login and authentication",
        "Build a portal with password reset and jwt session",
    ]:
        dec = WebsiteFastPathClassifier.evaluate(prompt)
        assert dec.fast_path_candidate is False
        assert "disqualified_by_security_auth_keyword" in dec.reason


def test_rejection_of_existing_repo_modifications():
    """Verify rejection of modifications, edits, or bug fixes."""
    for prompt in [
        "Modify the existing index.html to fix styling bugs",
        "Refactor styles.css in our website",
        "Update the landing page header",
    ]:
        dec = WebsiteFastPathClassifier.evaluate(prompt)
        assert dec.fast_path_candidate is False
        assert "disqualified_by_modification_keyword" in dec.reason


def test_benchmark_isolation_unconditional():
    """Verify that execution_mode='benchmark' unconditionally disables fast path."""
    dec = WebsiteFastPathClassifier.evaluate(
        "Create a website with index.html, styles.css, and app.js",
        execution_mode="benchmark"
    )
    assert dec.fast_path_candidate is False
    assert "benchmark_mode_isolation" in dec.reason
    assert dec.batch_eligible is False


def test_coordinator_category_a_execution():
    """Verify Category A (fully deterministic, 0 model calls) writes files correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_manager.lock(tmpdir)
        try:
            dec = WebsiteFastPathClassifier.evaluate("Create a blank HTML5 page with title 'Portal'")
            res = WebsiteFastPathCoordinator.execute_fast_path(dec, workspace_dir=tmpdir)

            assert res["success"] is True
            assert res["category"] == "A_fully_deterministic"
            assert res["model_calls"] == 0
            assert res["tool_calls"] == 1
            assert (Path(tmpdir) / "index.html").exists()
        finally:
            workspace_manager.unlock()


def test_coordinator_category_b_execution_with_batch():
    """Verify Category B (scaffold + 1 model call) composes with write_files_batch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_manager.lock(tmpdir)
        try:
            dec = WebsiteFastPathClassifier.evaluate("Create an interactive website with index.html, styles.css, app.js")
            assert dec.model_required is True

            # Mock single model call returning customized content based on scaffold
            def mock_model_generator(scaffolded_files):
                custom = {}
                for fn, content in scaffolded_files.items():
                    custom[fn] = content + f"\n<!-- Customized for {fn} -->"
                return custom

            res = WebsiteFastPathCoordinator.execute_fast_path(
                dec,
                dynamic_content_generator=mock_model_generator,
                workspace_dir=tmpdir
            )

            assert res["success"] is True
            assert res["category"] == "B_scaffold_plus_model_batch"
            assert res["model_calls"] == 1
            assert res["tool_calls"] == 1

            for fn in ["index.html", "styles.css", "app.js"]:
                p = Path(tmpdir) / fn
                assert p.exists()
                assert f"Customized for {fn}" in p.read_text(encoding="utf-8")
        finally:
            workspace_manager.unlock()
