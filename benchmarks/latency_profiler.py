#!/usr/bin/env python3
"""
HERMES Latency Profiler — Week 14 Performance Measurement
Measures average latency for every pipeline stage across task difficulty levels.
Requires: Ollama running with both models pulled.

Measurements taken:
  - T1 generation latency (qwen2.5-coder:7b)
  - T2 verification latency (mistral:7b-instruct-q4_K_M)
  - Tool execution time (per tool type)
  - Memory injection overhead (read + format MEMORY.md)
  - Response parse time (ResponseParser)
  - KAIROS consolidation time (if triggered)
  - Full end-to-end pipeline latency

Run: python benchmarks/latency_profiler.py
Output: data/latency_report.json + printed table
"""
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


# ----------------------------------------------------------------------
# Task definitions by difficulty
# ----------------------------------------------------------------------

TASKS_BY_DIFFICULTY = {
    "L1_trivial": [
        "List all files in the current directory",
        "Show me what is in the tests folder",
        "Read the file HERMES.md",
        "List files in the core directory",
        "Show me the config directory",
    ],
    "L2_simple": [
        "Create a Python file at generated_projects/latency_test.py that prints hello",
        "Write a requirements.txt with flask and pydantic listed",
        "Run python --version and show the output",
        "Create a folder called generated_projects/latency_output",
        "Append a line to generated_projects/latency_test.py",
    ],
    "L3_medium": [
        "Create a Python calculator module with add subtract multiply divide functions",
        "Write a Flask hello world app at generated_projects/latency_flask.py",
        "Create a SQLite helper class with connect query and close methods",
        "Generate a pytest test file for a calculator with edge case tests",
        "Write a Python script that reads a JSON file and prints each key value pair",
    ],
}


# ----------------------------------------------------------------------
# Measurement data structures
# ----------------------------------------------------------------------

@dataclass
class StageMeasurement:
    """Latency measurement for one pipeline stage in one run."""
    task_id: str
    difficulty: str
    stage: str
    latency_seconds: float
    success: bool
    notes: str = ""


@dataclass
class LatencyReport:
    """Aggregated latency report across all measurements."""
    measurements: list[StageMeasurement] = field(default_factory=list)

    def add(self, measurement: StageMeasurement):
        self.measurements.append(measurement)

    def get_stage_stats(self, stage: str, difficulty: Optional[str] = None) -> dict:
        """Get statistics for a specific stage, optionally filtered by difficulty."""
        filtered = [
            m for m in self.measurements
            if m.stage == stage
            and m.success
            and (difficulty is None or m.difficulty == difficulty)
        ]
        if not filtered:
            return {"count": 0, "mean": None, "median": None, "min": None, "max": None, "p95": None}

        latencies = [m.latency_seconds for m in filtered]
        latencies_sorted = sorted(latencies)
        p95_idx = int(len(latencies_sorted) * 0.95)

        return {
            "count": len(latencies),
            "mean": round(statistics.mean(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "min": round(min(latencies), 3),
            "max": round(max(latencies), 3),
            "p95": round(latencies_sorted[min(p95_idx, len(latencies_sorted)-1)], 3),
        }

    def to_dict(self) -> dict:
        stages = [
            "t1_generation",
            "t2_verification",
            "tool_execution",
            "memory_injection",
            "response_parsing",
            "full_pipeline",
        ]
        difficulties = list(TASKS_BY_DIFFICULTY.keys())

        report = {
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "total_measurements": len(self.measurements),
            "overall_by_stage": {},
            "by_difficulty_by_stage": {},
            "raw_measurements": [
                {
                    "task_id": m.task_id,
                    "difficulty": m.difficulty,
                    "stage": m.stage,
                    "latency_seconds": m.latency_seconds,
                    "success": m.success,
                    "notes": m.notes
                }
                for m in self.measurements
            ]
        }

        # Overall stats per stage
        for stage in stages:
            report["overall_by_stage"][stage] = self.get_stage_stats(stage)

        # Per-difficulty stats per stage
        for difficulty in difficulties:
            report["by_difficulty_by_stage"][difficulty] = {}
            for stage in stages:
                report["by_difficulty_by_stage"][difficulty][stage] = \
                    self.get_stage_stats(stage, difficulty)

        return report


# ----------------------------------------------------------------------
# Individual stage measurers
# ----------------------------------------------------------------------

async def measure_memory_injection(report: LatencyReport, task_id: str, difficulty: str):
    """Measure time to read MEMORY.md and format it for injection."""
    from memory.store import read_context_for_prompt

    # Write some test facts to measure real read+format time
    test_memory = Path("MEMORY.md")
    had_existing = test_memory.exists()
    existing_content = test_memory.read_text() if had_existing else ""

    # Write 20 test facts (realistic load)
    test_facts = "\n".join([
        f"[FACT]: Test fact {i} about the project being built — relevant detail here" 
        for i in range(20)
    ])
    test_memory.write_text(
        "# HERMES MEMORY INDEX\n## Project: latency_test\n\n" + test_facts + "\n"
    )

    try:
        start = time.monotonic()
        context = read_context_for_prompt(project="latency_test")
        elapsed = time.monotonic() - start

        report.add(StageMeasurement(
            task_id=task_id,
            difficulty=difficulty,
            stage="memory_injection",
            latency_seconds=elapsed,
            success=len(context) > 0,
            notes=f"context_chars={len(context)}"
        ))
    finally:
        # Restore original MEMORY.md
        if had_existing:
            test_memory.write_text(existing_content)
        else:
            if test_memory.exists():
                test_memory.unlink()


async def measure_response_parsing(report: LatencyReport, task_id: str, difficulty: str):
    """Measure time for ResponseParser to parse various response formats."""
    from core.response_parser import ResponseParser

    parser = ResponseParser()

    test_responses = [
        # Clean JSON
        '{"tool": "write_file", "parameters": {"path": "test.py", "content": "x"}, "reasoning": "creating file", "explanation": "done"}',
        # Markdown fenced
        '```json\n{"tool": "list_directory", "parameters": {"path": "."}, "reasoning": "listing", "explanation": "done"}\n```',
        # JSON in prose
        'I will do this now:\n{"tool": "read_file", "parameters": {"path": "app.py"}, "reasoning": "reading", "explanation": "showing"}\nDone.',
        # Plain text (parse failure case)
        "I would be happy to help you with that task by listing the files.",
    ]

    latencies = []
    for resp in test_responses:
        start = time.monotonic()
        parser.parse(resp)
        latencies.append(time.monotonic() - start)

    avg_latency = statistics.mean(latencies)
    report.add(StageMeasurement(
        task_id=task_id,
        difficulty=difficulty,
        stage="response_parsing",
        latency_seconds=avg_latency,
        success=True,
        notes=f"avg_of_{len(latencies)}_responses"
    ))


async def measure_t1_generation(
    ollama_client,
    report: LatencyReport,
    task: str,
    task_id: str,
    difficulty: str
):
    """Measure T1 generation latency for a single task."""
    from core.prompt_builder import PromptContext, build_system_prompt, build_user_message
    from tools.registry import tool_schema_for_prompt, list_tools

    ctx = PromptContext(
        user_task=task,
        mode="auto",
        available_tools=list_tools(),
        tool_descriptions=tool_schema_for_prompt(),
        memory_context="",
        skill_context="",
        active_skill_name="none"
    )
    system = build_system_prompt(ctx)
    user_msg = build_user_message(task)

    start = time.monotonic()
    try:
        response = await ollama_client.generate(
            model="qwen2.5-coder:7b",
            prompt=user_msg,
            system=system,
            keep_alive=0
        )
        elapsed = time.monotonic() - start
        success = True
        notes = f"response_chars={len(response)}"
    except Exception as e:
        elapsed = time.monotonic() - start
        success = False
        notes = f"error={type(e).__name__}"
        response = ""

    report.add(StageMeasurement(
        task_id=task_id,
        difficulty=difficulty,
        stage="t1_generation",
        latency_seconds=elapsed,
        success=success,
        notes=notes
    ))
    return response


async def measure_t2_verification(
    ollama_client,
    report: LatencyReport,
    task: str,
    tier1_output: str,
    task_id: str,
    difficulty: str
):
    """Measure T2 verification latency."""
    from core.verifier import Tier2Verifier

    verifier = Tier2Verifier(ollama_client=ollama_client)

    start = time.monotonic()
    try:
        verification = await verifier.verify(
            task=task,
            tier1_reasoning="I will complete this task using the appropriate tool.",
            tool_name="write_file",
            tool_parameters={"path": "test.py", "content": "x"},
            tool_result_output="Written 1 characters to test.py",
            tool_exit_code=0
        )
        elapsed = time.monotonic() - start
        success = True
        notes = f"agree={verification.agree} conf={verification.confidence:.2f}"
    except Exception as e:
        elapsed = time.monotonic() - start
        success = False
        notes = f"error={type(e).__name__}"

    report.add(StageMeasurement(
        task_id=task_id,
        difficulty=difficulty,
        stage="t2_verification",
        latency_seconds=elapsed,
        success=success,
        notes=notes
    ))


async def measure_tool_execution(
    report: LatencyReport,
    tool_name: str,
    task_id: str,
    difficulty: str,
    tmp_path: Path
):
    """Measure tool execution time for common tools."""
    from tools.registry import get_tool

    tool_class = get_tool(tool_name)
    if tool_class is None:
        return

    # Build appropriate input per tool
    try:
        if tool_name == "list_directory":
            inp = tool_class.Input(path=str(tmp_path))
        elif tool_name == "write_file":
            inp = tool_class.Input(
                path=str(tmp_path / "latency_test.py"),
                content='print("HERMES latency test")\n' * 50  # ~1.5KB
            )
        elif tool_name == "read_file":
            # Write a file first
            test_file = tmp_path / "read_test.py"
            test_file.write_text("x = 1\n" * 100)
            inp = tool_class.Input(path=str(test_file))
        elif tool_name == "bash_exec":
            inp = tool_class.Input(command="echo HERMES_LATENCY_TEST", timeout_seconds=5)
        else:
            return
    except Exception:
        return

    tool_instance = tool_class()
    start = time.monotonic()
    try:
        tool_result = tool_instance.execute(inp)
        elapsed = time.monotonic() - start
        success = tool_result.success
        notes = f"exit_code={tool_result.exit_code}"
    except Exception as e:
        elapsed = time.monotonic() - start
        success = False
        notes = f"error={type(e).__name__}"

    report.add(StageMeasurement(
        task_id=task_id,
        difficulty=difficulty,
        stage="tool_execution",
        latency_seconds=elapsed,
        success=success,
        notes=f"{tool_name} {notes}"
    ))


async def measure_full_pipeline(
    report: LatencyReport,
    task: str,
    task_id: str,
    difficulty: str,
    db_path: Path,
    monkeypatch=None
):
    """Measure complete end-to-end pipeline latency."""
    import tempfile
    from unittest.mock import patch
    from kairos.db import init_db
    from core.orchestrator import Orchestrator

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_db = tmp_path / "latency.db"
        init_db(db_path=test_db)

        with patch("core.orchestrator.DB_PATH", test_db), \
             patch("kairos.task_queue.DB_PATH", test_db), \
             patch("core.orchestrator.KairosDaemon"):

            orch = Orchestrator(mode="auto", project="latency_test")

            start = time.monotonic()
            try:
                result = await orch.run(task)
                elapsed = time.monotonic() - start
                success = result.pipeline_stage_reached >= 6
                notes = (
                    f"stage={result.pipeline_stage_reached} "
                    f"tool={result.tool_name} "
                    f"success={result.success} "
                    f"tier3={result.tier3_was_called}"
                )
            except Exception as e:
                elapsed = time.monotonic() - start
                success = False
                notes = f"error={type(e).__name__}: {str(e)[:80]}"

    report.add(StageMeasurement(
        task_id=task_id,
        difficulty=difficulty,
        stage="full_pipeline",
        latency_seconds=elapsed,
        success=success,
        notes=notes
    ))


# ----------------------------------------------------------------------
# Main profiler
# ----------------------------------------------------------------------

async def run_profiler() -> LatencyReport:
    """Run the complete latency profiler across all difficulty levels."""
    from models.ollama_client import OllamaClient
    import tempfile

    client = OllamaClient()
    if not await client.is_running():
        print("ERROR: Ollama is not running. Start it with: ollama serve")
        sys.exit(1)

    models = await client.list_models()
    if not any("qwen2.5-coder" in m for m in models):
        print("ERROR: qwen2.5-coder:7b not found")
        sys.exit(1)

    report = LatencyReport()

    print("=" * 70)
    print("HERMES Latency Profiler — Week 14")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # -- Phase 1: Individual stage measurements (5 reps each) -----
        print("\nPhase 1: Individual stage measurements (5 iterations each)")
        print("-" * 70)

        for i in range(5):
            task_id = f"STAGE_{i+1:02d}"

            print(f"  Iteration {i+1}/5: memory injection...", end=" ", flush=True)
            await measure_memory_injection(report, task_id, "L1_trivial")
            print(f"response parsing...", end=" ", flush=True)
            await measure_response_parsing(report, task_id, "L1_trivial")
            print(f"tool execution...", end=" ", flush=True)
            for tool in ["list_directory", "write_file", "read_file", "bash_exec"]:
                await measure_tool_execution(report, tool, f"{task_id}_{tool}", "L1_trivial", tmp_path)
            print("done")

        # -- Phase 2: T1 latency across all difficulties --------------
        print("\nPhase 2: T1 generation latency by difficulty")
        print("-" * 70)

        for difficulty, tasks in TASKS_BY_DIFFICULTY.items():
            print(f"  {difficulty}: ", end="", flush=True)
            for j, task in enumerate(tasks):
                task_id = f"T1_{difficulty}_{j+1:02d}"
                response = await measure_t1_generation(client, report, task, task_id, difficulty)
                print(".", end="", flush=True)
                await asyncio.sleep(0.5)  # Brief pause between T1 calls
            print()

        # -- Phase 3: T2 latency (5 calls) ----------------------------
        print("\nPhase 3: T2 verification latency (5 calls)")
        print("-" * 70)

        sample_task = "Create a Flask REST API with user authentication"
        sample_t1_output = '{"tool": "write_file", "parameters": {"path": "app.py"}}'
        for i in range(5):
            print(f"  T2 call {i+1}/5...", end=" ", flush=True)
            await measure_t2_verification(
                client, report, sample_task, sample_t1_output,
                f"T2_{i+1:02d}", "L3_medium"
            )
            print("done")
            await asyncio.sleep(0.5)

        # -- Phase 4: Full pipeline by difficulty (2 tasks each) -------
        print("\nPhase 4: Full end-to-end pipeline latency by difficulty")
        print("-" * 70)

        from kairos.db import init_db
        pipeline_db = tmp_path / "pipeline_test.db"
        init_db(db_path=pipeline_db)

        for difficulty, tasks in TASKS_BY_DIFFICULTY.items():
            print(f"  {difficulty}: ", end="", flush=True)
            # Run only 2 tasks per difficulty to keep time reasonable
            for j, task in enumerate(tasks[:2]):
                task_id = f"PIPELINE_{difficulty}_{j+1:02d}"
                await measure_full_pipeline(
                    report, task, task_id, difficulty, pipeline_db
                )
                print(".", end="", flush=True)
                await asyncio.sleep(1)
            print()

    return report


def print_report(report: LatencyReport, data: dict):
    """Print a formatted latency report."""
    print("\n" + "=" * 70)
    print("LATENCY REPORT")
    print("=" * 70)

    stages = {
        "memory_injection":  "Memory injection (read+format)",
        "response_parsing":  "Response parsing (ResponseParser)",
        "t1_generation":     "T1 generation (qwen2.5-coder:7b)",
        "t2_verification":   "T2 verification (mistral:7b)",
        "tool_execution":    "Tool execution (avg all tools)",
        "full_pipeline":     "Full pipeline (end-to-end)",
    }

    print(f"\n{'Stage':<40} | {'Mean':>7} | {'Median':>7} | {'P95':>7} | {'Count':>5}")
    print("-" * 75)

    overall = data.get("overall_by_stage", {})
    for stage_key, stage_name in stages.items():
        stats = overall.get(stage_key, {})
        mean = f"{stats['mean']:.3f}s" if stats.get("mean") is not None else "N/A"
        median = f"{stats['median']:.3f}s" if stats.get("median") is not None else "N/A"
        p95 = f"{stats['p95']:.3f}s" if stats.get("p95") is not None else "N/A"
        count = stats.get("count", 0)
        print(f"{stage_name:<40} | {mean:>7} | {median:>7} | {p95:>7} | {count:>5}")

    print("\n" + "-" * 70)
    print("T1 Generation by Difficulty Level:")
    print(f"  {'Difficulty':<20} | {'Mean':>7} | {'Median':>7} | {'P95':>7}")
    print("  " + "-" * 55)

    by_difficulty = data.get("by_difficulty_by_stage", {})
    for difficulty in ["L1_trivial", "L2_simple", "L3_medium"]:
        stats = by_difficulty.get(difficulty, {}).get("t1_generation", {})
        mean = f"{stats['mean']:.3f}s" if stats.get("mean") is not None else "N/A"
        median = f"{stats['median']:.3f}s" if stats.get("median") is not None else "N/A"
        p95 = f"{stats['p95']:.3f}s" if stats.get("p95") is not None else "N/A"
        print(f"  {difficulty:<20} | {mean:>7} | {median:>7} | {p95:>7}")

    print("\n" + "-" * 70)
    print("Full Pipeline by Difficulty Level:")
    print(f"  {'Difficulty':<20} | {'Mean':>7} | {'Median':>7} | Count")
    print("  " + "-" * 55)

    for difficulty in ["L1_trivial", "L2_simple", "L3_medium"]:
        stats = by_difficulty.get(difficulty, {}).get("full_pipeline", {})
        mean = f"{stats['mean']:.3f}s" if stats.get("mean") is not None else "N/A"
        median = f"{stats['median']:.3f}s" if stats.get("median") is not None else "N/A"
        count = stats.get("count", 0)
        print(f"  {difficulty:<20} | {mean:>7} | {median:>7} | {count}")

    # -- Performance assessment ----------------------------------------
    print("\n" + "-" * 70)
    print("Performance Assessment:")

    t1_mean = overall.get("t1_generation", {}).get("mean")
    t2_mean = overall.get("t2_verification", {}).get("mean")
    mem_mean = overall.get("memory_injection", {}).get("mean")
    tool_mean = overall.get("tool_execution", {}).get("mean")
    pipeline_mean = overall.get("full_pipeline", {}).get("mean")

    assessments = []
    if t1_mean and t1_mean > 15.0:
        assessments.append(f"  [WARN] T1 generation slow ({t1_mean:.1f}s avg) — consider Q2_K fallback")
    elif t1_mean:
        assessments.append(f"  [OK] T1 generation acceptable ({t1_mean:.1f}s avg)")

    if t2_mean and t2_mean > 12.0:
        assessments.append(f"  [WARN] T2 verification slow ({t2_mean:.1f}s avg)")
    elif t2_mean:
        assessments.append(f"  [OK] T2 verification acceptable ({t2_mean:.1f}s avg)")

    if mem_mean and mem_mean > 0.1:
        assessments.append(f"  [WARN] Memory injection overhead high ({mem_mean*1000:.1f}ms) — check MEMORY.md size")
    elif mem_mean:
        assessments.append(f"  [OK] Memory injection fast ({mem_mean*1000:.1f}ms)")

    if pipeline_mean:
        assessments.append(f"  [INFO] End-to-end pipeline: {pipeline_mean:.1f}s avg (T1+T2+tool+overhead)")

    for assessment in assessments:
        print(assessment)


async def main():
    report = await run_profiler()
    data = report.to_dict()

    # Save report
    report_path = Path("data/latency_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(data, f, indent=2)

    print_report(report, data)

    print(f"\n{'=' * 70}")
    print(f"Full report saved to: {report_path}")
    print(f"Total measurements taken: {len(report.measurements)}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
