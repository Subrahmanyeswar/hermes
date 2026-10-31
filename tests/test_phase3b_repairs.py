# tests/test_phase3b_repairs.py
"""
Unit and regression tests for HERMES Phase 3B targeted repairs.
Covers:
- NVIDIA timeout classification & removal of llama-3.2 fallback
- Orchestrator multi-tier failover to Tier 2 (gpt-oss:120b-cloud)
- Workspace path canonicalization & deduplication
- Artifact quality states, stub rejection, and task-scoped verification
"""

import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from models.nvidia_client import NvidiaTimeoutError, NvidiaConnectionError, NvidiaClient
from core.workspace import canonicalize_workspace_path, MissionWorkspace, WorkspaceBoundaryError
from core.quality_verifier import QualityVerifier, ArtifactQualityState, FileQualityResult, MIN_SIZES, PLACEHOLDER_PATTERNS


# ===========================================================================
# 1-5: Timeout Classification & Attributes
# ===========================================================================

def test_nvidia_timeout_error_attributes():
    err = NvidiaTimeoutError("Connection timed out", timeout_type="CONNECT_TIMEOUT", duration=12.5)
    assert str(err) == "Connection timed out"
    assert err.timeout_type == "CONNECT_TIMEOUT"
    assert err.duration == 12.5


def test_nvidia_timeout_first_token_classification():
    err = NvidiaTimeoutError("Stream stalled before first token", timeout_type="FIRST_TOKEN_TIMEOUT", duration=35.2)
    assert err.timeout_type == "FIRST_TOKEN_TIMEOUT"
    assert err.duration > 35.0


def test_nvidia_timeout_sse_read_stall_classification():
    err = NvidiaTimeoutError("SSE stream stalled during chunk reading", timeout_type="SSE_READ_STALL", duration=40.1)
    assert err.timeout_type == "SSE_READ_STALL"
    assert err.duration == 40.1


def test_nvidia_timeout_total_generation_classification():
    err = NvidiaTimeoutError("Overall generation exceeded timeout", timeout_type="TOTAL_GENERATION_TIMEOUT", duration=120.0)
    assert err.timeout_type == "TOTAL_GENERATION_TIMEOUT"
    assert err.duration == 120.0


def test_nvidia_timeout_default_type():
    err = NvidiaTimeoutError("Generic timeout")
    assert err.timeout_type == "TOTAL_GENERATION_TIMEOUT"
    assert err.duration == 0.0


# ===========================================================================
# 6-7: No Llama-3.2 Fallback & Tier 2 Failover
# ===========================================================================

@pytest.mark.asyncio
async def test_nvidia_client_does_not_fallback_to_llama():
    client = NvidiaClient(api_key="test-key", model="z-ai/glm-5.3-flash")
    with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
        mock_http = AsyncMock()
        mock_get.return_value = mock_http
        with patch.object(client, "_generate_stream", side_effect=NvidiaTimeoutError("stalled", timeout_type="FIRST_TOKEN_TIMEOUT")):
            with pytest.raises(NvidiaTimeoutError):
                await client.generate(prompt="hello", system="system", stream=True)
    # Model lock must NEVER be changed to llama-3.2-11b-vision-instruct
    assert client.model == "z-ai/glm-5.3-flash"
    assert "llama-3.2" not in client.model


@pytest.mark.asyncio
async def test_orchestrator_generate_t1_failover_to_tier2():
    from core.orchestrator import Orchestrator
    from config.model_config import TIER2_MODEL
    from models.provider import NormalizedModelResponse

    orch = Orchestrator(mode="auto")
    mock_t1 = AsyncMock()
    mock_t1.provider = "nvidia_nim"
    mock_t1.model = "z-ai/glm-5.3-flash"
    mock_t1.generate.side_effect = NvidiaTimeoutError("Upstream NIM timeout", timeout_type="FIRST_TOKEN_TIMEOUT")

    mock_ollama = AsyncMock()
    mock_ollama.generate.return_value = NormalizedModelResponse(
        text="Tier 2 generated output",
        model=TIER2_MODEL,
        provider="ollama",
        success=True,
    )

    orch.tier1 = mock_t1
    orch.ollama = mock_ollama

    resp = await orch._generate_t1(prompt="build app", system="sys")
    assert resp.success is True
    assert resp.model == TIER2_MODEL
    assert resp.text == "Tier 2 generated output"
    mock_ollama.generate.assert_called_once()


# ===========================================================================
# 8-14: Workspace Path Canonicalization & Boundary Enforcement
# ===========================================================================

def test_canonicalize_simple_relative_path(tmp_path):
    ws = tmp_path / "my_project"
    ws.mkdir()
    res = canonicalize_workspace_path("index.html", ws)
    assert res == ws / "index.html"


def test_canonicalize_workspace_name_prefix(tmp_path):
    ws = tmp_path / "my_project"
    ws.mkdir()
    res = canonicalize_workspace_path("my_project/index.html", ws)
    assert res == ws / "index.html"


def test_canonicalize_nested_workspace_name_prefix(tmp_path):
    ws = tmp_path / "my_project"
    ws.mkdir()
    res = canonicalize_workspace_path("my_project/my_project/index.html", ws)
    assert res == ws / "index.html"


def test_canonicalize_generated_projects_prefix(tmp_path):
    ws = tmp_path / "campus_event_board"
    ws.mkdir()
    res1 = canonicalize_workspace_path("generated_projects/campus_event_board/index.html", ws)
    assert res1 == ws / "index.html"
    res2 = canonicalize_workspace_path("generated_projects/index.html", ws)
    assert res2 == ws / "index.html"


def test_canonicalize_windows_leading_slashes(tmp_path):
    ws = tmp_path / "campus_event_board"
    ws.mkdir()
    res1 = canonicalize_workspace_path("/campus_event_board/search.html", ws)
    assert res1 == ws / "search.html"
    res2 = canonicalize_workspace_path(r"\search.html", ws)
    assert res2 == ws / "search.html"


def test_canonicalize_preserves_legitimate_subdirectories(tmp_path):
    ws = tmp_path / "campus_event_board"
    ws.mkdir()
    res1 = canonicalize_workspace_path("assets/images/logo.svg", ws)
    assert res1 == ws / "assets" / "images" / "logo.svg"
    res2 = canonicalize_workspace_path("css/styles.css", ws)
    assert res2 == ws / "css" / "styles.css"
    res3 = canonicalize_workspace_path("js/app.js", ws)
    assert res3 == ws / "js" / "app.js"


def test_canonicalize_boundary_error_on_escape(tmp_path):
    ws = tmp_path / "campus_event_board"
    ws.mkdir()
    with pytest.raises(WorkspaceBoundaryError):
        canonicalize_workspace_path("../../outside.txt", ws)


# ===========================================================================
# 15-20: Artifact Quality States, Placeholder Rejection, Task-Scoped Checks
# ===========================================================================

def test_quality_verifier_missing_file(tmp_path):
    qv = QualityVerifier()
    res = qv._check_file(str(tmp_path / "nonexistent.html"))
    assert res.state == ArtifactQualityState.MISSING
    assert res.verdict == "MISSING"


def test_quality_verifier_exists_trivial_file(tmp_path):
    qv = QualityVerifier()
    tiny_file = tmp_path / "index.html"
    tiny_file.write_text("<h1>Hi</h1>", encoding="utf-8")
    res = qv._check_file(str(tiny_file))
    assert res.state == ArtifactQualityState.EXISTS
    assert res.is_trivial is True
    assert res.verdict == "SHALLOW"


def test_quality_verifier_rejection_of_placeholder_stubs(tmp_path):
    qv = QualityVerifier()
    stub_file = tmp_path / "app.js"
    stub_file.write_text("let state = {};\n// TODO: implement later\nconst events = [];", encoding="utf-8")
    res = qv._check_file(str(stub_file))
    assert res.has_placeholders is True
    assert res.verdict in ("SHALLOW", "NEEDS_IMPROVEMENT")


def test_quality_verifier_rejection_of_website_welcome_placeholder(tmp_path):
    qv = QualityVerifier()
    stub_file = tmp_path / "index.html"
    stub_file.write_text("<!DOCTYPE html><html><body>Welcome to our website!</body></html>", encoding="utf-8")
    res = qv._check_file(str(stub_file))
    assert res.has_placeholders is True


def test_quality_verifier_functional_meets_request(tmp_path):
    qv = QualityVerifier()
    full_html = tmp_path / "index.html"
    content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Campus Event Board</title>
    <link rel="stylesheet" href="css/styles.css">
</head>
<body>
    <header class="header">
        <nav class="nav"><h1>Campus Events</h1></nav>
    </header>
    <main class="main-container">
        <section class="controls">
            <input type="text" id="searchInput" placeholder="Search events..." class="search-box">
            <select id="categoryFilter" class="filter-select">
                <option value="all">All Categories</option>
            </select>
        </section>
        <section id="eventsGrid" class="events-grid"></section>
    </main>
    <script src="js/app.js"></script>
</body>
</html>"""
    full_html.write_text(content, encoding="utf-8")
    res = qv._check_file(str(full_html))
    assert res.state in (ArtifactQualityState.FUNCTIONAL, ArtifactQualityState.MEETS_REQUEST)
    assert res.verdict == "GOOD"
    assert res.has_placeholders is False


def test_quality_verifier_verify_task_scoped_scaffolding_and_html(tmp_path):
    qv = QualityVerifier()
    # Create valid HTML and CSS files in workspace
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Events</title></head><body><header><nav></nav></header><main id='events'></main></body></html>" + " " * 400,
        encoding="utf-8"
    )
    (tmp_path / "styles.css").write_text(
        "body { display: flex; } .card { border-radius: 8px; } @media (max-width: 600px) { body { flex-direction: column; } }" + " " * 200,
        encoding="utf-8"
    )
    t1_res = qv.verify_task_scoped(
        task_id="t1",
        task_title="Project Scaffolding",
        task_description="Setup base project structure and html scaffold",
        task_index=1,
        total_tasks=6,
        project_root=str(tmp_path),
    )
    assert t1_res.overall_verdict == "COMPLETE"

    t2_res = qv.verify_task_scoped(
        task_id="t2",
        task_title="HTML Layout and Markup",
        task_description="Implement semantic HTML markup for header, nav, and events container",
        task_index=2,
        total_tasks=6,
        project_root=str(tmp_path),
    )
    assert t2_res.overall_verdict == "COMPLETE"
