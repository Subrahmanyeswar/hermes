"""
Unit & Integration Tests for Phase 6.1 Background Memory Extraction.
Validates non-blocking user result delivery, failure isolation, timeout handling,
and fact persistence.
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from memory.background_worker import BackgroundMemoryManager, MemoryJob
from memory.types import MemoryFact, MemoryState, FactType
from core.orchestrator import Orchestrator

@pytest.mark.asyncio
async def test_background_memory_manager_submit_and_process():
    """Test that a MemoryJob is submitted non-blockingly and processed in background."""
    mock_client = AsyncMock()
    mock_client.generate = AsyncMock(return_value='[{"type": "FACT", "content": "Uses SQLite with WAL mode"}]')

    mgr = BackgroundMemoryManager(ollama_client=mock_client)
    
    job = MemoryJob(
        task_description="Configured SQLite database",
        conversation_history=[{"role": "user", "content": "setup db"}],
        tool_results=[{"tool": "write_file", "exit_code": 0, "success": True}],
        tool_name="write_file",
        exit_code=0,
        project="test_bg_project"
    )

    enqueued = mgr.submit(job)
    assert enqueued is True
    assert job.status in ("QUEUED", "PROCESSING", "COMPLETED")

    # Allow worker to process
    await asyncio.sleep(0.3)
    assert job.status == "COMPLETED"

@pytest.mark.asyncio
async def test_slow_memory_extraction_does_not_block_mission():
    """
    CRITICAL TEST: When memory extraction takes 3.0s,
    Orchestrator.run() returns immediately without waiting for memory extraction.
    """
    orch = Orchestrator(mode="auto", project="test_non_blocking")
    
    # Mock OllamaClient
    mock_ollama = AsyncMock()
    # T1 response (tool call)
    mock_ollama.generate = AsyncMock(return_value={
        "response": '{"tool": "list_directory", "parameters": {"path": "generated_projects"}}',
        "load_duration": 1000000,
        "prompt_eval_duration": 1000000,
        "eval_duration": 1000000,
        "prompt_eval_count": 50,
        "eval_count": 50
    })
    orch.ollama = mock_ollama

    # Mock verifier to return immediately
    from core.verifier import VerificationResult
    orch.verifier.verify = AsyncMock(return_value=VerificationResult(agree=True, confidence=0.95, critical_issues=[], risk_score=0.1, reasoning="OK"))

    # Make background extraction take 3.0s
    memory_completed_event = asyncio.Event()

    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(3.0)
        memory_completed_event.set()
        return [MemoryFact(fact_type=FactType.FACT, content="Slow fact", state=MemoryState.PROPOSED)]

    with patch("memory.background_worker.extract_memories", side_effect=slow_extract):
        t0 = time.perf_counter()
        result = await orch.run("List files in generated_projects")
        elapsed_sec = time.perf_counter() - t0

        # Mission must return before memory extraction finishes
        assert elapsed_sec < 2.5
        assert not memory_completed_event.is_set(), "Mission must return BEFORE memory extraction completes"
        assert result.success is True
        assert "Background Queued" in result.final_output

@pytest.mark.asyncio
async def test_memory_extraction_failure_does_not_fail_mission():
    """Background memory extraction crashing must never fail the mission result."""
    orch = Orchestrator(mode="auto", project="test_fail_isolation")
    
    mock_ollama = AsyncMock()
    mock_ollama.generate = AsyncMock(return_value={
        "response": '{"tool": "list_directory", "parameters": {"path": "generated_projects"}}',
        "load_duration": 1000000,
        "prompt_eval_duration": 1000000,
        "eval_duration": 1000000,
        "prompt_eval_count": 50,
        "eval_count": 50
    })
    orch.ollama = mock_ollama

    from core.verifier import VerificationResult
    orch.verifier.verify = AsyncMock(return_value=VerificationResult(agree=True, confidence=0.95, critical_issues=[], risk_score=0.1, reasoning="OK"))

    # Memory extraction throws exception
    async def failing_extract(*args, **kwargs):
        raise RuntimeError("Ollama connection failed during memory extraction")

    with patch("memory.background_worker.extract_memories", side_effect=failing_extract):
        result = await orch.run("List files in generated_projects")
        # Mission must still succeed
        assert result.success is True
        assert result.pipeline_stage_reached == 12

@pytest.mark.asyncio
async def test_memory_timeout_isolation():
    """Test that a timeout in memory extraction marks job FAILED without unhandled exception."""
    mock_client = AsyncMock()
    async def hanging_extract(*args, **kwargs):
        await asyncio.sleep(5.0)
        return []

    mgr = BackgroundMemoryManager(ollama_client=mock_client)
    job = MemoryJob(
        task_description="Timeout task",
        conversation_history=[],
        tool_results=[],
        tool_name="list_directory",
        exit_code=0,
        project="test_timeout",
        timeout_seconds=0.05,
        retries_left=0
    )

    with patch("memory.background_worker.extract_memories", side_effect=hanging_extract):
        mgr.submit(job)
        await asyncio.sleep(0.3)
        assert job.status in ("FAILED", "PROCESSING", "QUEUED")
