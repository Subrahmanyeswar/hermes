# tests/test_prompt3_benchmark_isolation.py
"""
Automated Behavioral Benchmark Isolation Test Suite (Prompt 3 Closure).

Proves that execution_mode='benchmark' strictly preserves frozen benchmark semantics
and cannot accidentally inherit production/demo optimizations:
1. Reasoning behavior isolation (think=None in benchmark, think=False in production).
2. num_predict budget isolation (1536 frozen budget vs bounded production clamps).
3. Timeout isolation (75s frozen timeout vs production clamps).
4. Mission Planner isolation (Rule 9 preserved in benchmark, think=False not injected).
5. Verification gate isolation (mandatory Tier 2 LLM verification, fast path disabled).
6. Routing isolation (verifier.verify called in benchmark, bypassed in production).
7. Execution mode propagation (end-to-end trace comparison through Orchestrator).
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.reasoning_policy import ReasoningPolicy, TaskComplexity
from core.verification_gate import VerificationGate
from core.mission_planner import MissionPlanner
from core.verifier import Tier2Verifier, VerificationResult
from core.orchestrator import Orchestrator, OrchestratorResult


# ── A. REASONING BEHAVIOR ISOLATION ──────────────────────────────────────────

def test_reasoning_behavior_isolation():
    """Assert benchmark mode does NOT receive production reasoning overrides."""
    task_desc = "Create index.html with welcome heading"

    # Benchmark mode resolution
    bench_policy = ReasoningPolicy.resolve(
        task_description=task_desc,
        model="deepseek-r1:8b",
        execution_mode="benchmark"
    )
    assert bench_policy.think is None, f"Benchmark must have think=None, got {bench_policy.think}"
    assert bench_policy.execution_mode == "benchmark"

    # Production mode resolution
    prod_policy = ReasoningPolicy.resolve(
        task_description=task_desc,
        model="deepseek-r1:8b",
        execution_mode="production"
    )
    assert prod_policy.think is False, f"Production must have think=False, got {prod_policy.think}"
    assert prod_policy.execution_mode == "production"


# ── B. NUM_PREDICT BUDGET ISOLATION ──────────────────────────────────────────

def test_num_predict_budget_isolation():
    """Assert benchmark mode retains frozen 1536 budget and is not clamped."""
    task_desc = "Write a simple python helper function"

    bench_policy = ReasoningPolicy.resolve(
        task_description=task_desc,
        model="deepseek-r1:8b",
        execution_mode="benchmark"
    )
    # Frozen benchmark L1 budget is 1536
    assert bench_policy.num_predict == 1536, f"Expected 1536, got {bench_policy.num_predict}"

    # Production clamp for simple task is 512
    prod_policy = ReasoningPolicy.resolve(
        task_description=task_desc,
        model="deepseek-r1:8b",
        execution_mode="production"
    )
    assert prod_policy.num_predict in (512, 1024)
    assert bench_policy.num_predict != prod_policy.num_predict


# ── C. TIMEOUT ISOLATION ─────────────────────────────────────────────────────

def test_timeout_isolation():
    """Assert benchmark mode retains 75s frozen timeout, not production bounds."""
    task_desc = "Write a simple helper"

    bench_policy = ReasoningPolicy.resolve(
        task_description=task_desc,
        model="deepseek-r1:8b",
        execution_mode="benchmark"
    )
    assert bench_policy.timeout_seconds == 75

    prod_policy = ReasoningPolicy.resolve(
        task_description=task_desc,
        model="deepseek-r1:8b",
        execution_mode="production"
    )
    assert prod_policy.timeout_seconds <= 60


# ── D. PLANNER ISOLATION ─────────────────────────────────────────────────────

def test_planner_isolation_rule_9_and_parameters():
    """Assert benchmark planning preserves Rule 9 and does not inject think=False."""
    planner = MissionPlanner()

    # Capture OllamaClient.generate call inside _llm_decompose
    with patch("models.ollama_client.OllamaClient.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = MagicMock(text='["task 1", "task 2"]')

        # 1. Benchmark mode call
        planner._llm_decompose("Build a web page", execution_mode="benchmark")
        assert mock_gen.called
        bench_kwargs = mock_gen.call_args[1]

        # In benchmark mode, think should NOT be explicitly False
        assert "think" not in bench_kwargs or bench_kwargs["think"] is None
        assert bench_kwargs.get("num_predict") is None or bench_kwargs.get("num_predict") != 512
        assert "Minimum 8 tasks. Maximum 25 tasks." in bench_kwargs["system"]
        assert "Output ONLY the necessary tasks" not in bench_kwargs["system"]

        mock_gen.reset_mock()

        # 2. Production mode call
        planner._llm_decompose("Build a web page", execution_mode="production")
        assert mock_gen.called
        prod_kwargs = mock_gen.call_args[1]

        # In production mode, think=False and num_predict=512 are injected
        assert prod_kwargs.get("think") is False
        assert prod_kwargs.get("num_predict") == 512
        assert "Output ONLY the necessary tasks" in prod_kwargs["system"]
        assert "Minimum 8 tasks. Maximum 25 tasks." not in prod_kwargs["system"]


# ── E. VERIFICATION ISOLATION ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verification_gate_benchmark_isolation():
    """Assert benchmark mode ALWAYS enforces Tier 2 LLM verification, bypassing fast-path."""
    gate = VerificationGate(enabled=True)

    mock_verifier = MagicMock(spec=Tier2Verifier)
    mock_verifier.verify = AsyncMock(return_value=VerificationResult(
        agree=True,
        confidence=0.95,
        critical_issues=[],
        risk_score=0.1,
        reasoning="Tier 2 LLM verified"
    ))

    task_desc = "Create hello.py containing print('hello')"
    tool_params = {"path": "hello.py", "content": "print('hello')"}

    # 1. Benchmark mode execution
    result_bench, method_bench = await gate.evaluate(
        task_description=task_desc,
        tier1_reasoning="Create file",
        tool_name="write_file",
        tool_parameters=tool_params,
        tool_result_output="File written successfully",
        tool_exit_code=0,
        tool_success=True,
        verifier=mock_verifier,
        execution_mode="benchmark"
    )

    assert method_bench == "BENCHMARK_FROZEN_T2"
    assert mock_verifier.verify.called, "Tier 2 Verifier MUST be called in benchmark mode!"
    assert mock_verifier.verify.call_count == 1

    mock_verifier.verify.reset_mock()

    # 2. Production mode execution with existing file stub
    with patch.object(gate, "run_deterministic_checks", return_value=(True, ["check_written_file_exists_and_non_empty"], [])):
        with patch.object(gate, "run_structural_checks", return_value=(True, ["python_ast_parse"], [])):
            result_prod, method_prod = await gate.evaluate(
                task_description=task_desc,
                tier1_reasoning="Create file",
                tool_name="write_file",
                tool_parameters=tool_params,
                tool_result_output="File written successfully",
                tool_exit_code=0,
                tool_success=True,
                verifier=mock_verifier,
                execution_mode="production"
            )

            assert method_prod == "LOCAL_STRUCTURAL"
            assert not mock_verifier.verify.called, "Tier 2 Verifier should be bypassed in production fast-path!"


# ── F. ROUTING ISOLATION (READ-ONLY OPERATIONS) ──────────────────────────────

@pytest.mark.asyncio
async def test_read_only_tool_benchmark_isolation():
    """Assert read-only tools also invoke Tier 2 verifier in benchmark mode."""
    gate = VerificationGate(enabled=True)

    mock_verifier = MagicMock(spec=Tier2Verifier)
    mock_verifier.verify = AsyncMock(return_value=VerificationResult(
        agree=True,
        confidence=0.99,
        critical_issues=[],
        risk_score=0.0,
        reasoning="OK"
    ))

    # Benchmark mode on list_directory
    res, method = await gate.evaluate(
        task_description="List files in current directory",
        tier1_reasoning="Inspect workspace",
        tool_name="list_directory",
        tool_parameters={"path": "."},
        tool_result_output="file1.txt\nfile2.txt",
        tool_exit_code=0,
        tool_success=True,
        verifier=mock_verifier,
        execution_mode="benchmark"
    )

    assert method == "BENCHMARK_FROZEN_T2"
    assert mock_verifier.verify.called


# ── G. EXECUTION MODE PROPAGATION & E2E COMPARISON TRACE ─────────────────────

@pytest.mark.asyncio
async def test_orchestrator_execution_mode_propagation_and_trace_comparison():
    """
    End-to-end trace verification:
    Run mock pipeline under execution_mode='production' vs execution_mode='benchmark'
    and assert exact behavioral divergence across reasoning, budget, and verification.
    """
    dummy_model_response = '{"tool": "write_file", "parameters": {"path": "test.py", "content": "def test(): return 1"}, "reasoning": "writing", "explanation": "done"}'

    traces = {}

    for mode in ["production", "benchmark"]:
        orch = Orchestrator(mode="auto", execution_mode=mode)

        captured_calls = []

        async def fake_generate(**kwargs):
            captured_calls.append(kwargs)
            return MagicMock(text=dummy_model_response, output_tokens=50)

        orch.ollama.generate = AsyncMock(side_effect=fake_generate)
        orch.verifier.verify = AsyncMock(return_value=VerificationResult(
            agree=True, confidence=0.9, critical_issues=[], risk_score=0.1, reasoning="ok"
        ))

        from tools.file_tools import WriteFileTool
        from tools.base import ToolResult

        with patch.object(WriteFileTool, "execute", return_value=ToolResult(success=True, exit_code=0, output="OK")):
            with patch.object(orch.verification_gate, "run_deterministic_checks", return_value=(True, ["check"], [])):
                with patch.object(orch.verification_gate, "run_structural_checks", return_value=(True, ["ast"], [])):
                    res = await orch.run("Create a python file test.py")

        assert isinstance(res, OrchestratorResult)

        assert len(captured_calls) >= 1
        t1_call = captured_calls[0]

        traces[mode] = {
            "execution_mode": mode,
            "think": t1_call.get("think"),
            "num_predict": t1_call.get("num_predict"),
            "temperature": t1_call.get("temperature"),
            "t2_called": orch.verifier.verify.called
        }

    # Assert behavioral differences between the two modes
    assert traces["benchmark"]["think"] is None, "Benchmark think must be None!"
    assert traces["production"]["think"] is False, "Production think must be False!"

    assert traces["benchmark"]["num_predict"] == 1536, "Benchmark num_predict must be 1536!"
    assert traces["production"]["num_predict"] in (512, 1024), "Production num_predict must be bounded!"

    assert traces["benchmark"]["t2_called"] is True, "Benchmark must call Tier 2 LLM!"
    assert traces["production"]["t2_called"] is False, "Production must bypass Tier 2 LLM via fast path!"
