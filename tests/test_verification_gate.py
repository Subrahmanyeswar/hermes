"""
Unit and Security Tests for Phase 6.2 Progressive Verification & Intelligent Gating.
Validates Level 0 deterministic checks, Level 1 AST checks, Level 2 semantic escalations,
security guardrails, and rollback feature flag.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import tempfile
import os

from core.verification_gate import VerificationGate, ToolRiskCategory
from core.verifier import Tier2Verifier, VerificationResult


@pytest.mark.asyncio
async def test_read_only_tool_verified_deterministically():
    """READ_ONLY tool (list_directory) must be verified deterministically in <5ms without calling Qwen3."""
    gate = VerificationGate(enabled=True)
    mock_verifier = AsyncMock()

    res, method = await gate.evaluate(
        task_description="List all files in generated_projects",
        tier1_reasoning="I will list the directory.",
        tool_name="list_directory",
        tool_parameters={"path": "."},
        tool_result_output="file1.txt\nfile2.txt",
        tool_exit_code=0,
        tool_success=True,
        verifier=mock_verifier,
        task_complexity=0.2
    )

    assert method == "LOCAL_DETERMINISTIC"
    assert res.agree is True
    assert res.confidence == 1.0
    assert mock_verifier.verify.call_count == 0  # Zero LLM calls!


@pytest.mark.asyncio
async def test_simple_python_write_passes_ast_check():
    """Valid Python write_file must pass Level 1 AST check without calling Qwen3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_py = os.path.join(tmpdir, "calc.py")
        content = "def add(a, b):\n    return a + b\n"
        with open(test_py, "w", encoding="utf-8") as f:
            f.write(content)

        gate = VerificationGate(enabled=True)
        mock_verifier = AsyncMock()

        res, method = await gate.evaluate(
            task_description="Create a simple calculator helper function",
            tier1_reasoning="I will write add function.",
            tool_name="write_file",
            tool_parameters={"path": test_py, "content": content},
            tool_result_output=f"Wrote {len(content)} bytes to {test_py}",
            tool_exit_code=0,
            tool_success=True,
            verifier=mock_verifier,
            task_complexity=0.3
        )

        assert method == "LOCAL_STRUCTURAL"
        assert res.agree is True
        assert res.confidence >= 0.95
        assert mock_verifier.verify.call_count == 0  # Zero LLM calls!


@pytest.mark.asyncio
async def test_syntax_error_in_python_file_triggers_tier2():
    """Invalid Python syntax in write_file must fail AST check and invoke Tier 2 diagnostic."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_py = os.path.join(tmpdir, "broken.py")
        broken_content = "def broken(:\n    return"
        with open(test_py, "w", encoding="utf-8") as f:
            f.write(broken_content)

        gate = VerificationGate(enabled=True)
        mock_verifier = AsyncMock()
        mock_verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=False, confidence=0.2, critical_issues=["Syntax error"], risk_score=0.8
        ))

        res, method = await gate.evaluate(
            task_description="Create a helper",
            tier1_reasoning="Writing code",
            tool_name="write_file",
            tool_parameters={"path": test_py, "content": broken_content},
            tool_result_output="Wrote broken.py",
            tool_exit_code=0,
            tool_success=True,
            verifier=mock_verifier,
            task_complexity=0.3
        )

        assert method == "T2_DIAGNOSTIC_FAILURE"
        assert mock_verifier.verify.call_count == 1
        assert any("syntax error" in issue.lower() for issue in res.critical_issues)


@pytest.mark.asyncio
async def test_security_sensitive_task_escalates_to_tier2():
    """Security keywords in task must force Tier 2 verification even for read-only tools."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "config.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("SECRET=123")

        gate = VerificationGate(enabled=True)
        mock_verifier = AsyncMock()
        mock_verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=True, confidence=0.9, critical_issues=[], risk_score=0.1
        ))

        res, method = await gate.evaluate(
            task_description="Read private credentials and API secret tokens from config",
            tier1_reasoning="Reading config",
            tool_name="read_file",
            tool_parameters={"path": test_file},
            tool_result_output="SECRET=123",
            tool_exit_code=0,
            tool_success=True,
            verifier=mock_verifier,
            task_complexity=0.3
        )

        assert method == "T2_SECURITY_SENSITIVE"
        assert mock_verifier.verify.call_count == 1


@pytest.mark.asyncio
async def test_semantic_reasoning_task_invokes_tier2():
    """Semantic refactoring/debugging tasks must invoke Tier 2 semantic verification."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "auth.py")
        content = "class Auth:\n    def check(self): pass\n"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(content)

        gate = VerificationGate(enabled=True)
        mock_verifier = AsyncMock()
        mock_verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=True, confidence=0.95, critical_issues=[], risk_score=0.1
        ))

        res, method = await gate.evaluate(
            task_description="Refactor the binary search algorithm to handle duplicate elements and optimize loop performance",
            tier1_reasoning="Updating algorithm",
            tool_name="write_file",
            tool_parameters={"path": test_file, "content": content},
            tool_result_output=f"Wrote {test_file}",
            tool_exit_code=0,
            tool_success=True,
            verifier=mock_verifier,
            task_complexity=0.8
        )

        assert method == "T2_SEMANTIC_REASONING"
        assert mock_verifier.verify.call_count == 1


@pytest.mark.asyncio
async def test_unknown_tool_defaults_to_tier2():
    """Unregistered tools must default conservatively to Tier 2."""
    gate = VerificationGate(enabled=True)
    mock_verifier = AsyncMock()
    mock_verifier.verify = AsyncMock(return_value=VerificationResult(
        agree=True, confidence=0.85, critical_issues=[], risk_score=0.2
    ))

    res, method = await gate.evaluate(
        task_description="Execute custom operation",
        tier1_reasoning="Calling unknown tool",
        tool_name="unregistered_custom_tool",
        tool_parameters={"arg": "val"},
        tool_result_output="Done",
        tool_exit_code=0,
        tool_success=True,
        verifier=mock_verifier,
        task_complexity=0.5
    )

    assert method == "T2_SECURITY_SENSITIVE"
    assert mock_verifier.verify.call_count == 1


@pytest.mark.asyncio
async def test_feature_flag_disabled_falls_back_to_tier2():
    """When PROGRESSIVE_VERIFICATION_ENABLED is False, everything invokes Tier 2 (full rollback path)."""
    gate = VerificationGate(enabled=False)
    mock_verifier = AsyncMock()
    mock_verifier.verify = AsyncMock(return_value=VerificationResult(
        agree=True, confidence=0.95, critical_issues=[], risk_score=0.1
    ))

    res, method = await gate.evaluate(
        task_description="List all files in generated_projects",
        tier1_reasoning="Listing files",
        tool_name="list_directory",
        tool_parameters={"path": "."},
        tool_result_output="files",
        tool_exit_code=0,
        tool_success=True,
        verifier=mock_verifier,
        task_complexity=0.1
    )

    assert method == "LEGACY_T2_FULL"
    assert mock_verifier.verify.call_count == 1


@pytest.mark.asyncio
async def test_missing_created_file_fails_deterministic_check():
    """When write_file claims success but file is missing on disk, deterministic check fails."""
    gate = VerificationGate(enabled=True)
    mock_verifier = AsyncMock()
    mock_verifier.verify = AsyncMock(return_value=VerificationResult(
        agree=False, confidence=0.1, critical_issues=["Missing file"], risk_score=0.9
    ))

    res, method = await gate.evaluate(
        task_description="Create non_existent_file.txt",
        tier1_reasoning="Writing",
        tool_name="write_file",
        tool_parameters={"path": "/non/existent/path/never_created.txt", "content": "hello"},
        tool_result_output="Success",
        tool_exit_code=0,
        tool_success=True,
        verifier=mock_verifier,
        task_complexity=0.2
    )

    assert method == "T2_DIAGNOSTIC_FAILURE"
    assert mock_verifier.verify.call_count == 1
    assert any("not found on disk" in issue.lower() for issue in res.critical_issues)
