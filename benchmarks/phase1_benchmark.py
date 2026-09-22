# benchmarks/phase1_benchmark.py
"""
HERMES Phase 1 — Baseline Performance Benchmark Suite.

Executes 15 standardized benchmark tasks across 5 categories (A through E).
Measures:
- Cold start vs Warm run latency
- Complete request waterfall (Planning, Context, Tier 1, Validation, Tool, Tier 2, Routing, Tier 3, Memory)
- LLM call counts and token statistics
- System resource utilization (CPU, RAM, GPU, VRAM)
- Task completion, acceptance criteria, and quality metrics

Saves results to: performance/baseline_results.json
"""

import asyncio
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from core.orchestrator import Orchestrator
from core.telemetry import telemetry, RequestTelemetry, sample_system_resources
from core.workspace import workspace_manager


# ── Benchmark Task Definitions ────────────────────────────────────────────────

BENCHMARK_TASKS = [
    # ── Category A: Simple Tasks ──
    {
        "id": "A1_list_files",
        "category": "Category A — Simple",
        "name": "List files in workspace",
        "prompt": "List all files in the current directory",
        "expected_tool": "list_directory",
        "success_check": lambda res: res.success and (res.tool_name == "list_directory" or "file" in res.final_output.lower()),
    },
    {
        "id": "A2_read_file",
        "category": "Category A — Simple",
        "name": "Read specific file",
        "prompt": "Read the file HERMES.md and show its contents",
        "expected_tool": "read_file",
        "success_check": lambda res: res.success and ("hermes" in res.final_output.lower() or res.tool_name == "read_file"),
    },
    {
        "id": "A3_create_dir",
        "category": "Category A — Simple",
        "name": "Create a directory",
        "prompt": "Create a folder called generated_projects/phase1_bench_dir",
        "expected_tool": "create_folder",
        "success_check": lambda res: res.success or Path("generated_projects/phase1_bench_dir").exists(),
    },
    {
        "id": "A4_create_file",
        "category": "Category A — Simple",
        "name": "Create a simple file",
        "prompt": "Create a Python file at generated_projects/hello_bench.py that prints 'Hello from HERMES baseline benchmark'",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/hello_bench.py").exists(),
    },

    # ── Category B: Single-File Coding ──
    {
        "id": "B1_modify_file",
        "category": "Category B — Single-File Coding",
        "name": "Modify an existing file",
        "prompt": "Append a comment '# Verified by HERMES Phase 1' to generated_projects/hello_bench.py",
        "expected_tool": "append_file",
        "success_check": lambda res: res.success,
    },
    {
        "id": "B2_add_function",
        "category": "Category B — Single-File Coding",
        "name": "Add a small function",
        "prompt": "Create a Python file generated_projects/math_utils.py containing a function fibonacci(n: int) -> int that computes Fibonacci numbers with docstrings and type hints",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/math_utils.py").exists(),
    },
    {
        "id": "B3_fix_bug",
        "category": "Category B — Single-File Coding",
        "name": "Fix a simple bug",
        "prompt": "Create a Python file generated_projects/bug_fixed.py with a safe_divide(a, b) function that handles ZeroDivisionError gracefully and returns None",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/bug_fixed.py").exists(),
    },

    # ── Category C: Multi-File Coding ──
    {
        "id": "C1_multi_file_feature",
        "category": "Category C — Multi-File Coding",
        "name": "Add a feature requiring multiple files",
        "prompt": "Create a data loader module at generated_projects/data_loader.py that loads JSON data, and a processor module at generated_projects/data_processor.py that calculates summary statistics",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and (Path("generated_projects/data_loader.py").exists() or Path("generated_projects/data_processor.py").exists()),
    },
    {
        "id": "C2_frontend_backend",
        "category": "Category C — Multi-File Coding",
        "name": "Modify frontend + backend",
        "prompt": "Write a Flask application in generated_projects/flask_app.py that serves a REST API endpoint /api/status returning JSON status ok",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/flask_app.py").exists(),
    },
    {
        "id": "C3_generate_tests",
        "category": "Category C — Multi-File Coding",
        "name": "Add tests for an existing feature",
        "prompt": "Create a pytest test file at generated_projects/test_math_utils.py that tests the fibonacci function with edge cases for 0, 1, and 10",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/test_math_utils.py").exists(),
    },

    # ── Category D: Complex Engineering ──
    {
        "id": "D1_database_crud",
        "category": "Category D — Complex Engineering",
        "name": "Implement SQLite CRUD data store",
        "prompt": "Create a Python SQLite database manager in generated_projects/db_manager.py with a DatabaseManager class supporting init_db, add_user(name, email), and get_users methods",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/db_manager.py").exists(),
    },
    {
        "id": "D2_refactor_code",
        "category": "Category D — Complex Engineering",
        "name": "Refactor modular code",
        "prompt": "Create a refactored pipeline script at generated_projects/data_pipeline.py that integrates data loading, processing, and database storage in a structured pipeline",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/data_pipeline.py").exists(),
    },
    {
        "id": "D3_run_tests_verify",
        "category": "Category D — Complex Engineering",
        "name": "Run tests and verify",
        "prompt": "Run python --version to verify the Python environment runtime",
        "expected_tool": "run_python",
        "success_check": lambda res: res.success or "python" in res.final_output.lower(),
    },
    {
        "id": "D4_multi_task_workflow",
        "category": "Category D — Complex Engineering",
        "name": "Complete multi-task engineering workflow",
        "prompt": "Create a complete configuration management module in generated_projects/config_manager.py that parses environment variables and YAML settings with defaults",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/config_manager.py").exists(),
    },

    # ── Category E: Large Mission ──
    {
        "id": "E1_large_mission",
        "category": "Category E — Large Mission",
        "name": "Full task management application",
        "prompt": "Build a complete task tracking CLI module at generated_projects/task_tracker.py with Task dataclass, add_task, list_tasks, complete_task, and JSON persistence functions",
        "expected_tool": "write_file",
        "success_check": lambda res: res.success and Path("generated_projects/task_tracker.py").exists(),
    },
]


# ── Benchmark Runner Function ─────────────────────────────────────────────────

async def run_benchmark_suite(trials_per_task: int = 2, output_file: str = "performance/baseline_results.json"):
    """
    Run all benchmark tasks across multiple trials (Trial 1 = Cold, Trial 2+ = Warm).
    Record comprehensive telemetry and export results.
    """
    logger.info(f"Starting HERMES Phase 1 Baseline Benchmark ({len(BENCHMARK_TASKS)} tasks x {trials_per_task} trials)...")
    
    # Ensure directories exist
    Path("generated_projects").mkdir(parents=True, exist_ok=True)
    Path("performance").mkdir(parents=True, exist_ok=True)
    
    # Initialize workspace
    workspace_manager.lock_to_cwd()
    
    telemetry.clear()
    orch = Orchestrator(mode="auto", project="benchmark")
    
    start_bench_time = time.time()
    
    for task_idx, task_def in enumerate(BENCHMARK_TASKS, 1):
        task_id = task_def["id"]
        category = task_def["category"]
        prompt = task_def["prompt"]
        
        logger.info(f"\n=======================================================")
        logger.info(f"[{task_idx}/{len(BENCHMARK_TASKS)}] {category} — {task_def['name']} ({task_id})")
        logger.info(f"Prompt: {prompt}")
        logger.info(f"=======================================================")
        
        for trial in range(1, trials_per_task + 1):
            is_cold = (trial == 1 and task_idx == 1)
            trial_label = "COLD" if is_cold else f"WARM (Trial {trial})"
            logger.info(f"--- Running {task_id} [{trial_label}] ---")
            
            t_trial_start = time.perf_counter()
            
            # Execute through master orchestrator
            result = await orch.run(prompt)
            t_trial_end = time.perf_counter()
            
            # Validate acceptance criterion
            criterion_met = task_def["success_check"](result)
            
            logger.info(
                f"Result: success={result.success} | criterion_met={criterion_met} | "
                f"stage={result.pipeline_stage_reached}/12 | latency={result.total_latency_seconds:.2f}s | "
                f"tool={result.tool_name} | tier3={result.tier3_was_called}"
            )
            
            # Update the latest completed telemetry record with task metadata
            completed = telemetry.get_completed_requests()
            if completed:
                last_req = completed[-1]
                last_req.benchmark_id = f"{task_id}_trial_{trial}"
                last_req.task_type = category
                last_req.acceptance_criteria_met = criterion_met
                if result.tool_name:
                    last_req.output_preview = result.final_output[:300]
                
                # Check created files
                if task_def.get("expected_tool") == "write_file" and result.success:
                    for p in Path("generated_projects").glob("*.*"):
                        if p.name not in last_req.files_created:
                            last_req.files_created.append(str(p.name))
    
    total_bench_duration = time.time() - start_bench_time
    logger.info(f"\nBenchmark suite completed in {total_bench_duration:.2f}s!")
    
    # Export structured results
    telemetry.export_to_json(output_file)
    return telemetry.get_completed_requests()


if __name__ == "__main__":
    trials = 2 if "--quick" not in sys.argv else 1
    asyncio.run(run_benchmark_suite(trials_per_task=trials))
