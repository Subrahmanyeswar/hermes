"""
HERMES — Failure Mode Test Suite
Tests every error path in the orchestrator in complete isolation.
Every test uses mocked Ollama/Claude — no real API calls.
Every test verifies that the session produces a clean result, never crashes.

Critical invariant: orchestrator.run() must ALWAYS return an OrchestratorResult.
It must NEVER raise an exception to the caller under any circumstances.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from core.orchestrator import Orchestrator, OrchestratorResult
from core.verifier import VerificationResult
from models.ollama_client import OllamaTimeoutError, OllamaConnectionError
from models.claude_client import Tier3Response
from tools.base import BaseTool, ToolResult
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────
# Dummy Tool for Mocking
# ──────────────────────────────────────────────────────────────────────

class DummyTool(BaseTool):
    name = "list_dir"
    description = "List files in a directory"
    risk_score = 0.1
    blocked_in = []
    
    class Input(BaseModel):
        DirectoryPath: str = Field(default=".", description="Path to list")
        
    def execute(self, tool_input: Input) -> ToolResult:
        return ToolResult(success=True, exit_code=0, output="success output", error="")


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db(tmp_path, monkeypatch):
    """Redirect all SQLite operations to a temp database."""
    from kairos.db import init_db
    test_db = tmp_path / "test.db"
    init_db(db_path=test_db)
    monkeypatch.setattr("core.orchestrator.DB_PATH", test_db)
    monkeypatch.setattr("kairos.task_queue.DB_PATH", test_db)
    return test_db

@pytest.fixture
def orch(mock_db):
    """Create an Orchestrator with all heavy components mocked."""
    with patch("core.orchestrator.OllamaClient") as mock_ollama, \
         patch("core.orchestrator.ClaudeClient") as mock_claude, \
         patch("core.orchestrator.Tier2Verifier") as mock_verifier:
        
        o = Orchestrator(mode="auto")
        o.ollama = mock_ollama.return_value
        o.claude = mock_claude.return_value
        o.claude.get_cost_summary = MagicMock(return_value={"total_spent": 0.0})
        o.verifier = mock_verifier.return_value
        yield o


# ──────────────────────────────────────────────────────────────────────
# 1. JSON Parse Failure tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestJSONParseFailure:
    async def test_json_parse_failure_retry_success(self, orch):
        """Tier 1 fails to parse first time, but succeeds on V2 retry."""
        orch.ollama.generate = AsyncMock(side_effect=[
            "not valid json at all",
            '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "retrying with v2 worked", "explanation": "successful fallback"}'
        ])
        orch.verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=True, confidence=0.9, critical_issues=[], risk_score=0.1, reasoning="looks good"
        ))
        
        with patch("core.orchestrator.get_tool", return_value=DummyTool):
            result = await orch.run("test json parse retry success")
            assert isinstance(result, OrchestratorResult)
            assert result.success is True
            assert orch.ollama.generate.call_count >= 2

    async def test_json_parse_failure_both_attempts_fail(self, orch):
        """Tier 1 fails to parse twice, resulting in failure."""
        orch.ollama.generate = AsyncMock(side_effect=[
            "bad json 1",
            "bad json 2"
        ])
        
        result = await orch.run("test json parse both fail")
        assert isinstance(result, OrchestratorResult)
        assert result.success is False
        assert "invalid JSON" in result.error


# ──────────────────────────────────────────────────────────────────────
# 2. Tool Not Found tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestToolNotFound:
    async def test_tool_not_found_retry_success(self, orch):
        """T1 returns an unknown tool, but on retry T1 returns a valid tool."""
        orch.ollama.generate = AsyncMock(side_effect=[
            '{"tool": "invalid_tool_xyz", "parameters": {}, "reasoning": "oops", "explanation": "trying custom"}',
            '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "done", "explanation": "ok"}'
        ])
        orch.verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=True, confidence=0.9, critical_issues=[], risk_score=0.1, reasoning="looks good"
        ))
        
        with patch("core.orchestrator.get_tool", side_effect=[None, DummyTool]):
            result = await orch.run("test tool not found retry success")
            assert isinstance(result, OrchestratorResult)
            assert result.success is True
            assert result.tool_name == "list_dir"
            assert orch.ollama.generate.call_count >= 2

    async def test_tool_not_found_both_attempts_fail(self, orch):
        """T1 returns unknown tool twice, resulting in failure."""
        orch.ollama.generate = AsyncMock(return_value=
            '{"tool": "nonexistent_tool_forever", "parameters": {}, "reasoning": "oops", "explanation": "still try"}'
        )
        
        with patch("core.orchestrator.get_tool", return_value=None):
            result = await orch.run("test tool not found both fail")
            assert isinstance(result, OrchestratorResult)
            assert result.success is False
            assert "unknown tool" in result.error.lower()


# ──────────────────────────────────────────────────────────────────────
# 3. Tool Execution Failure tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestToolExecutionFailure:
    async def test_tool_execution_failure_succeeds_on_retry(self, orch):
        """Tool fails on first execute call, but succeeds on retry."""
        with patch.object(DummyTool, 'execute') as mock_exec:
            mock_exec.side_effect = [
                ToolResult(success=False, exit_code=1, output="error output", error="permission denied"),
                ToolResult(success=True, exit_code=0, output="happy path", error="")
            ]
            
            with patch("core.orchestrator.get_tool", return_value=DummyTool):
                orch.ollama.generate = AsyncMock(return_value=
                    '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "done", "explanation": "ok"}'
                )
                orch.verifier.verify = AsyncMock(return_value=VerificationResult(
                    agree=True, confidence=0.9, critical_issues=[], risk_score=0.1, reasoning="looks good"
                ))
                
                result = await orch.run("test tool execution failure retry success")
                assert isinstance(result, OrchestratorResult)
                assert result.success is True
                assert mock_exec.call_count == 2
                assert orch.ollama.generate.call_count >= 2

    async def test_tool_execution_failure_max_retries_exceeded(self, orch):
        """Tool fails 4 times consecutively (original + 3 retries), resulting in final failure."""
        with patch.object(DummyTool, 'execute') as mock_exec:
            mock_exec.return_value = ToolResult(success=False, exit_code=2, output="still error", error="fatal error")
            
            with patch("core.orchestrator.get_tool", return_value=DummyTool):
                orch.ollama.generate = AsyncMock(return_value=
                    '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "done", "explanation": "ok"}'
                )
                
                result = await orch.run("test tool execution failure max retries")
                assert isinstance(result, OrchestratorResult)
                assert result.success is False
                assert "FAILED" in result.final_output
                assert "failed 3 times" in result.error or "FAILED" in result.final_output


# ──────────────────────────────────────────────────────────────────────
# 4. Ollama Timeout tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestOllamaTimeout:
    async def test_ollama_timeout_tier1_generation(self, orch):
        """Ollama times out during Stage 4 generation, raising OllamaTimeoutError."""
        orch.ollama.generate = AsyncMock(side_effect=OllamaTimeoutError("Request timed out"))
        
        result = await orch.run("test timeout generation")
        assert isinstance(result, OrchestratorResult)
        assert result.success is False
        assert "TIMEOUT" in result.final_output
        assert "timeout" in result.error.lower()

    async def test_ollama_timeout_tier2_verification(self, orch):
        """Ollama times out during Stage 7 verification, raising OllamaTimeoutError."""
        orch.ollama.generate = AsyncMock(return_value=
            '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "done", "explanation": "ok"}'
        )
        orch.verifier.verify = AsyncMock(side_effect=OllamaTimeoutError("Verification timeout"))
        
        with patch("core.orchestrator.get_tool", return_value=DummyTool):
            result = await orch.run("test timeout verification")
            assert isinstance(result, OrchestratorResult)
            assert result.success is True
            # Verifier timed out, but pipeline completed successfully using a synthetic agree=True verification!
            assert result.pipeline_stage_reached == 12


# ──────────────────────────────────────────────────────────────────────
# 5. Tier 3 API Failure tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTier3ApiFailure:
    async def test_tier3_api_failure_non_success_response(self, orch):
        """Tier 3 API call returns success=False."""
        orch.ollama.generate = AsyncMock(return_value=
            '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "done", "explanation": "ok"}'
        )
        orch.verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=False, confidence=0.8, critical_issues=["issue"], risk_score=0.2, reasoning="disagree"
        ))
        orch.claude.arbitrate = AsyncMock(return_value=Tier3Response(
            content="", input_tokens=0, output_tokens=0, cost_usd=0.0,
            model="claude-sonnet-4-6", latency_seconds=0.0, success=False, error="Claude API Down"
        ))
        
        with patch("core.orchestrator.get_tool", return_value=DummyTool):
            result = await orch.run("test tier3 non-success")
            assert isinstance(result, OrchestratorResult)
            assert result.tier3_was_called is True
            assert "[UNVERIFIED]" in result.final_output

    async def test_tier3_api_failure_raised_exception(self, orch):
        """Tier 3 API raises an unexpected exception."""
        orch.ollama.generate = AsyncMock(return_value=
            '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "done", "explanation": "ok"}'
        )
        orch.verifier.verify = MagicMock(return_value=VerificationResult(
            agree=False, confidence=0.8, critical_issues=["issue"], risk_score=0.2, reasoning="disagree"
        ))
        orch.claude.arbitrate = AsyncMock(side_effect=Exception("Claude Connection Failure"))
        
        with patch("core.orchestrator.get_tool", return_value=DummyTool):
            result = await orch.run("test tier3 exception")
            assert isinstance(result, OrchestratorResult)
            assert result.tier3_was_called is True
            assert "[UNVERIFIED]" in result.final_output


# ──────────────────────────────────────────────────────────────────────
# 6. Memory Parse Error tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMemoryParseError:
    async def test_memory_parse_error_fallback(self, orch):
        """read_context_for_prompt raises a memory parse exception, fallback to empty string."""
        orch.ollama.generate = AsyncMock(return_value=
            '{"tool": "list_dir", "parameters": {"DirectoryPath": "."}, "reasoning": "done", "explanation": "ok"}'
        )
        orch.verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=True, confidence=0.9, critical_issues=[], risk_score=0.1, reasoning="looks good"
        ))
        
        with patch("core.orchestrator.get_tool", return_value=DummyTool), \
             patch("core.orchestrator.read_context_for_prompt", side_effect=Exception("Memory parse error: invalid YAML")):
            
            result = await orch.run("test memory parse error fallback")
            assert isinstance(result, OrchestratorResult)
            assert result.success is True
            assert result.pipeline_stage_reached == 12


# ──────────────────────────────────────────────────────────────────────
# 7. Robustness / Crash Safety tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRobustness:
    async def test_total_component_failure(self, orch):
        """All components fail completely, raising exceptions, but run() never raises."""
        orch.ollama.generate = AsyncMock(side_effect=OllamaConnectionError("Ollama down"))
        orch.verifier.verify = AsyncMock(side_effect=OllamaConnectionError("Ollama down"))
        orch.claude.arbitrate = AsyncMock(side_effect=Exception("Claude API down"))
        
        try:
            result = await orch.run("any request at all")
            assert isinstance(result, OrchestratorResult)
            assert result.success is False
        except Exception as e:
            pytest.fail(f"CRITICAL: All components failed and run() raised {type(e).__name__}: {e}")

    @pytest.mark.asyncio
    async def test_run_100_consecutive_requests_no_crash(self, orch, mock_db):
        """
        100 consecutive requests must all return OrchestratorResult.
        Uses read_file and list_directory which are safe for repeated calls.
        Mock ensures tool results are predictable across all 100 calls.
        """
        from tools.base import ToolResult

        # Override T1 to always return list_directory (no filesystem risk)
        orch.ollama.generate = AsyncMock(
            return_value=(
                '{"tool": "list_directory", "parameters": {"path": "."}, '
                '"reasoning": "listing the directory", "explanation": "Here are the files"}'
            )
        )

        # Mock list_directory to always succeed without filesystem access
        success_result = ToolResult(
            success=True,
            output="core/\ntools/\nmemory/\nhermes.md\nmain.py",
            exit_code=0
        )

        crashes = []
        wrong_types = []

        with patch("tools.file_tools.ListDirectoryTool.execute", return_value=success_result):
            for i in range(100):
                try:
                    result = await orch.run(f"list all files request number {i}")
                    if not isinstance(result, OrchestratorResult):
                        wrong_types.append(
                            f"Request {i}: returned {type(result).__name__} "
                            f"instead of OrchestratorResult"
                        )
                except Exception as e:
                    crashes.append(
                        f"Request {i}: raised {type(e).__name__}: {str(e)[:80]}"
                    )

        total_issues = crashes + wrong_types
        if total_issues:
            for issue in total_issues[:5]:
                print(f"  ✗ {issue}")
            pytest.fail(
                f"{len(total_issues)}/100 requests had issues "
                f"({len(crashes)} crashes, {len(wrong_types)} wrong types)"
            )

        print(f"  ✓ 100 consecutive requests all returned OrchestratorResult safely")
