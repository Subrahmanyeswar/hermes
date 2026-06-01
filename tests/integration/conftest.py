# tests/integration/conftest.py
# Shared fixtures for all HERMES integration tests.
# Every test gets:
#   - A fresh SQLite database (no state leakage between tests)
#   - A fresh memory directory (no cross-test memory contamination)
#   - A fresh session logger
#   - A real Orchestrator pointed at the temp database
#   - Automatic skip if Ollama is not running
import asyncio
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── Session-scoped Ollama availability check ──────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def ollama_available(event_loop):
    """
    Check once per session if Ollama is running and required models are present.
    All integration tests are skipped if Ollama is unavailable.
    """
    from models.ollama_client import OllamaClient

    async def check():
        client = OllamaClient()
        if not await client.is_running():
            return False, "Ollama is not running"
        models = await client.list_models()
        if not any("qwen2.5-coder" in m for m in models):
            return False, "qwen2.5-coder:7b not found — run: ollama pull qwen2.5-coder:7b"
        if not any("mistral" in m for m in models):
            return False, "mistral:7b-instruct-q4_K_M not found — run: ollama pull mistral:7b-instruct-q4_K_M"
        return True, "OK"

    available, reason = event_loop.run_until_complete(check())
    return available, reason


@pytest.fixture(autouse=True)
def skip_if_ollama_unavailable(ollama_available):
    """Auto-applied to every integration test — skips if Ollama is not running."""
    available, reason = ollama_available
    if not available:
        pytest.skip(f"Ollama unavailable: {reason}")


# ── Per-test isolated environment ─────────────────────────────────────

@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """
    Create a completely isolated environment for one integration test.
    Returns a dict with all paths and the configured orchestrator.
    """
    from pathlib import Path

    # ── Directory structure ───────────────────────────────────────────
    db_path      = tmp_path / "tasks.db"
    memory_dir   = tmp_path / "memory"
    sessions_dir = tmp_path / "sessions"
    generated_dir = tmp_path / "generated_projects"
    skills_dir   = Path("skills")   # Real skills directory — read only

    memory_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    # ── Patch all database and file paths ─────────────────────────────
    monkeypatch.setattr("kairos.db.DB_PATH", db_path)
    monkeypatch.setattr("kairos.task_queue.DB_PATH", db_path)
    monkeypatch.setattr("core.orchestrator.DB_PATH", db_path)
    monkeypatch.setattr("memory.store.LAYER2_BASE_DIR", memory_dir)
    monkeypatch.setattr("memory.session_logger.SESSION_LOG_DIR", sessions_dir)
    monkeypatch.setattr("utils.logging.SESSION_LOG_DIR", sessions_dir)

    # ── Initialise database ───────────────────────────────────────────
    from kairos.db import init_db
    init_db(db_path=db_path)

    # ── Create MEMORY.md in tmp_path ──────────────────────────────────
    memory_md = tmp_path / "MEMORY.md"
    memory_md.write_text(
        "# HERMES MEMORY INDEX\n"
        "## Project: integration_test\n"
        "## Last Updated: 2026-01-01 00:00\n\n"
    )

    def mock_get_memory_path(project="default"):
        return memory_md

    monkeypatch.setattr("memory.store.get_memory_path", mock_get_memory_path)

    # ── Patch KairosDaemon so it never actually starts ────────────────
    # CRITICAL: must use monkeypatch, NOT a context manager with block,
    # because the context manager exits before the test runs.
    from unittest.mock import MagicMock, AsyncMock

    mock_kairos = MagicMock()
    mock_kairos.start = AsyncMock()
    mock_kairos.stop  = AsyncMock()
    mock_kairos.is_running = False
    mock_kairos.get_stats = MagicMock(return_value={
        "is_running": False, "loop_count": 0,
        "stuck_tasks_detected": 0, "tasks_retried": 0,
        "consolidations_run": 0, "total_api_cost": 0.0,
        "pending_tasks": 0,
    })

    monkeypatch.setattr("core.orchestrator.KairosDaemon", MagicMock(return_value=mock_kairos))

    # ── Build the orchestrator ────────────────────────────────────────
    from core.orchestrator import Orchestrator
    orch = Orchestrator(mode="auto", project="integration_test")

    yield {
        "tmp_path":     tmp_path,
        "db_path":      db_path,
        "memory_md":    memory_md,
        "sessions_dir": sessions_dir,
        "generated_dir":generated_dir,
        "skills_dir":   skills_dir,
        "orchestrator": orch,
    }
    # monkeypatch automatically undoes all patches after the test



# ── Result validation helpers ─────────────────────────────────────────

def assert_pipeline_reached_stage(result, min_stage: int):
    """Assert that the pipeline progressed at least to a given stage."""
    assert result.pipeline_stage_reached >= min_stage, (
        f"Pipeline only reached stage {result.pipeline_stage_reached}, "
        f"expected at least stage {min_stage}. "
        f"Error: {result.error}"
    )


def assert_result_has_trace_id(result):
    """Assert that the result has a valid 8-char trace_id."""
    assert hasattr(result, "trace_id"), "Result missing trace_id field"
    assert result.trace_id and len(result.trace_id) == 8, (
        f"trace_id has wrong format: {result.trace_id!r}"
    )


def assert_output_is_not_empty(result):
    """Assert that final_output contains something meaningful."""
    assert result.final_output and len(result.final_output.strip()) > 0, (
        f"final_output is empty. tool={result.tool_name} error={result.error}"
    )
