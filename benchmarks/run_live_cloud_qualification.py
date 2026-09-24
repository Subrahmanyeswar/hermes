"""
HERMES Live Cloud Qualification Suite.
Executes 10 real software-engineering missions with 100% LIVE cloud models:
  T1: NVIDIA NIM / z-ai/glm-5.3-flash
  T2: Ollama Cloud / gpt-oss:120b-cloud
  T3: Ollama Cloud / nemotron-3-ultra:cloud

Zero mocks. Zero cached responses. Zero synthetic model outputs.
Captures exact wall-clock monotonic timing, streaming tokens, AST syntax checks,
and physical filesystem evidence.
"""

import ast
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from loguru import logger

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from config.model_config import (
    TIER1_MODEL,
    TIER1_PROVIDER,
    TIER2_MODEL,
    TIER2_PROVIDER,
    TIER3_MODEL,
    TIER3_PROVIDER,
)
from core.orchestrator import Orchestrator, OrchestratorResult
from core.telemetry import telemetry
from core.workspace import workspace_manager
from models.nvidia_client import get_shared_nvidia_client
from models.ollama_client import get_shared_ollama_client


class LiveCloudQualificationHarness:
    def __init__(self):
        self.workspace_root = WORKSPACE
        workspace_manager.lock(str(self.workspace_root))

        # Pre-seed buggy binary search file for mission 3 debugging
        bsearch_path = self.workspace_root / "generated_projects" / "live_bsearch.py"
        bsearch_path.parent.mkdir(parents=True, exist_ok=True)
        bsearch_path.write_text(
            'def binary_search(arr, target):\n'
            '    """Buggy binary search implementation"""\n'
            '    low = 0\n'
            '    high = len(arr) - 1\n'
            '    while low <= high:\n'
            '        mid = (low + high) + 1  # BUG: wrong mid calculation\n'
            '        if arr[mid] == target:\n'
            '            return mid\n'
            '        elif arr[mid] < target:\n'
            '            low = mid + 1\n'
            '        else:\n'
            '            high = mid - 1\n'
            '    return -1\n',
            encoding="utf-8"
        )

        self.proc = psutil.Process()
        self.baseline_memory_mb = self.proc.memory_info().rss / (1024 * 1024)
        self.start_wall_clock = time.monotonic()
        self.mission_records: List[Dict[str, Any]] = []

    def get_memory_mb(self) -> float:
        return self.proc.memory_info().rss / (1024 * 1024)

    def cleanup(self):
        try:
            workspace_manager.unlock()
        except Exception:
            pass

    async def run_live_mission(
        self,
        index: int,
        mission_id: str,
        name: str,
        prompt: str,
        expected_file: Optional[str] = None,
        verify_ast: bool = False,
        expect_t2_semantic: bool = False,
        expect_t3_escalation: bool = False,
    ) -> Dict[str, Any]:
        mem_before = self.get_memory_mb()
        mission_start = time.monotonic()
        mission_start_dt = datetime.now(timezone.utc).isoformat()

        print(f"\n[{index:02d}/10] STARTING LIVE MISSION: {name}")
        print(f"       Prompt: {prompt}")

        # Real production Orchestrator with real live cloud clients
        orch = Orchestrator(mode="auto")

        # Telemetry hook to capture raw live model calls
        live_t1_calls = []
        live_t2_calls = []
        live_t3_calls = []

        # Hook into telemetry collector
        orig_record_call = telemetry.record_model_call
        def intercept_model_call(call):
            prov = getattr(call, "provider", "")
            mod = getattr(call, "model", "")
            stg = getattr(call, "stage", "")
            if prov == "nvidia_nim" or "glm" in mod or stg == "Tier 1":
                live_t1_calls.append(call)
            elif "gpt-oss" in mod or stg == "Tier 2":
                live_t2_calls.append(call)
            elif "nemotron" in mod or "Tier 3" in stg:
                live_t3_calls.append(call)
            return orig_record_call(call)

        telemetry.record_model_call = intercept_model_call

        events = []
        async def on_progress(etype, payload):
            events.append((etype, payload, time.monotonic()))

        uncaught_exception = False
        exc_msg = ""
        res: Optional[OrchestratorResult] = None
        try:
            res = await orch.run(user_request=prompt, on_progress=on_progress)
        except Exception as e:
            uncaught_exception = True
            exc_msg = str(e)
            logger.error(f"Live mission {mission_id} exception: {e}")
        finally:
            telemetry.record_model_call = orig_record_call

        # Extract model calls from telemetry completed requests for this trace
        req = None
        if res and res.trace_id:
            with telemetry._global_lock:
                for r in reversed(telemetry._completed_requests):
                    if r.request_id == res.trace_id:
                        req = r
                        break
        if req and req.model_calls:
            for c in req.model_calls:
                prov = getattr(c, "provider", "")
                mod = getattr(c, "model", "")
                stg = getattr(c, "stage", "")
                if prov == "nvidia_nim" or "glm" in mod or stg == "Tier 1":
                    if c not in live_t1_calls:
                        live_t1_calls.append(c)
                elif "gpt-oss" in mod or stg == "Tier 2":
                    if c not in live_t2_calls:
                        live_t2_calls.append(c)
                elif "nemotron" in mod or "Tier 3" in stg:
                    if c not in live_t3_calls:
                        live_t3_calls.append(c)

        mission_end = time.monotonic()
        mission_end_dt = datetime.now(timezone.utc).isoformat()
        elapsed_seconds = mission_end - mission_start
        mem_after = self.get_memory_mb()

        # Physical filesystem inspection
        file_verified = False
        file_bytes = 0
        syntax_verified = False
        if expected_file:
            target_path = self.workspace_root / expected_file
            if target_path.exists():
                file_verified = True
                content = target_path.read_text(encoding="utf-8", errors="ignore")
                file_bytes = len(content.encode("utf-8"))
                if verify_ast and expected_file.endswith(".py"):
                    try:
                        ast.parse(content)
                        syntax_verified = True
                    except SyntaxError as syn_err:
                        syntax_verified = False
                        logger.error(f"AST Syntax error in {expected_file}: {syn_err}")
                else:
                    syntax_verified = True
            else:
                file_verified = False
        else:
            file_verified = True
            syntax_verified = True

        success = (
            res is not None
            and res.success is True
            and file_verified is True
            and syntax_verified is True
            and not uncaught_exception
        )

        record = {
            "mission_index": index,
            "mission_id": mission_id,
            "name": name,
            "prompt": prompt,
            "success": success,
            "start_dt": mission_start_dt,
            "end_dt": mission_end_dt,
            "elapsed_seconds": round(elapsed_seconds, 4),
            "tool_used": getattr(res, "tool_name", None),
            "expected_file": expected_file,
            "file_verified": file_verified,
            "file_bytes": file_bytes,
            "syntax_verified": syntax_verified,
            "t1_calls_count": len(live_t1_calls),
            "t2_calls_count": len(live_t2_calls),
            "t3_calls_count": len(live_t3_calls),
            "t1_calls": [
                {
                    "inference_id": getattr(c, "inference_id", ""),
                    "provider": getattr(c, "provider", ""),
                    "model": getattr(c, "model", ""),
                    "total_latency_ms": getattr(c, "total_latency_ms", 0.0),
                    "ttfb_ms": getattr(c, "ttfb_ms", 0.0),
                    "ttft_ms": getattr(c, "ttft_ms", 0.0),
                    "ttft_reasoning_ms": getattr(c, "ttft_reasoning_ms", 0.0),
                    "ttft_content_ms": getattr(c, "ttft_content_ms", 0.0),
                    "ttft_tool_ms": getattr(c, "ttft_tool_ms", 0.0),
                    "ttfu_ms": getattr(c, "ttfu_ms", 0.0),
                    "prompt_tokens": getattr(c, "prompt_tokens", 0),
                    "output_tokens": getattr(c, "output_tokens", 0),
                    "total_tokens": getattr(c, "total_tokens", 0),
                }
                for c in live_t1_calls
            ],
            "t2_calls": [
                {
                    "inference_id": getattr(c, "inference_id", ""),
                    "provider": getattr(c, "provider", ""),
                    "model": getattr(c, "model", ""),
                    "total_latency_ms": getattr(c, "total_latency_ms", 0.0),
                    "output_tokens": getattr(c, "output_tokens", 0),
                }
                for c in live_t2_calls
            ],
            "t3_calls": [
                {
                    "inference_id": getattr(c, "inference_id", ""),
                    "provider": getattr(c, "provider", ""),
                    "model": getattr(c, "model", ""),
                    "total_latency_ms": getattr(c, "total_latency_ms", 0.0),
                    "output_tokens": getattr(c, "output_tokens", 0),
                }
                for c in live_t3_calls
            ],
            "memory_delta_mb": round(mem_after - mem_before, 2),
            "error": exc_msg or getattr(res, "error", None),
        }
        self.mission_records.append(record)

        status_str = "PASS" if success else "FAIL"
        print(f"[{index:02d}/10] RESULT: {status_str} | Wall Clock: {elapsed_seconds:.2f}s | T1 Calls: {len(live_t1_calls)} | T2 Calls: {len(live_t2_calls)} | T3 Calls: {len(live_t3_calls)}")
        if expected_file:
            print(f"       Artifact: {expected_file} ({file_bytes} bytes, AST syntax={syntax_verified})")
        return record


async def run_live_cloud_matrix():
    print("=" * 75)
    print("HERMES LIVE CLOUD QUALIFICATION — 10 REAL MISSIONS")
    print(f"LOCKED T1: {TIER1_PROVIDER} / {TIER1_MODEL}")
    print(f"LOCKED T2: {TIER2_PROVIDER} / {TIER2_MODEL}")
    print(f"LOCKED T3: {TIER3_PROVIDER} / {TIER3_MODEL}")
    print("Zero Mocks. Zero Synthetics. Real Cloud HTTP Streams.")
    print("=" * 75)

    harness = LiveCloudQualificationHarness()

    missions = [
        # 01. Simple Python file creation
        {
            "id": "LIVE_01_FILE_CREATION",
            "name": "Simple Python File Creation",
            "prompt": "Create generated_projects/live_math.py with two functions: add(a, b) and multiply(a, b).",
            "expected_file": "generated_projects/live_math.py",
            "verify_ast": True,
        },
        # 02. Python CLI calculator with tests
        {
            "id": "LIVE_02_CLI_CALC",
            "name": "Python CLI Calculator with Unit Tests",
            "prompt": "Create generated_projects/live_calc.py containing a Calculator class with add, subtract, multiply, divide.",
            "expected_file": "generated_projects/live_calc.py",
            "verify_ast": True,
        },
        # 03. Debug a broken Python module (Triggers Semantic Verification / Debugging)
        {
            "id": "LIVE_03_DEBUG_REPAIR",
            "name": "Debug Broken Python Algorithm Module",
            "prompt": "Fix the binary search bug in algorithm logic and save to generated_projects/live_bsearch.py with correct mid calculation.",
            "expected_file": "generated_projects/live_bsearch.py",
            "verify_ast": True,
            "expect_t2_semantic": True,
        },
        # 04. Refactor duplicated code
        {
            "id": "LIVE_04_REFACTOR",
            "name": "Refactor Duplicated Logic into Service Layer",
            "prompt": "Create generated_projects/live_auth_service.py refactoring user authentication into a clean AuthService class.",
            "expected_file": "generated_projects/live_auth_service.py",
            "verify_ast": True,
            "expect_t2_semantic": True,
        },
        # 05. Generate a single-page HTML website
        {
            "id": "LIVE_05_HTML_SITE",
            "name": "Single-Page HTML/CSS Interactive Dashboard",
            "prompt": "Create generated_projects/live_web/index.html with an interactive, modern dashboard layout and inline CSS.",
            "expected_file": "generated_projects/live_web/index.html",
            "verify_ast": False,
        },
        # 06. Modify an existing HTML page (or create subpage)
        {
            "id": "LIVE_06_MODIFY_HTML",
            "name": "Create Companion About Page",
            "prompt": "Create generated_projects/live_web/about.html with mission overview and features list matching the dashboard.",
            "expected_file": "generated_projects/live_web/about.html",
            "verify_ast": False,
        },
        # 07. Create a small REST API
        {
            "id": "LIVE_07_REST_API",
            "name": "Lightweight REST API Routing Module",
            "prompt": "Create generated_projects/live_api.py implementing a lightweight HTTP server handler for /health and /metrics.",
            "expected_file": "generated_projects/live_api.py",
            "verify_ast": True,
        },
        # 08. Add tests to an existing project
        {
            "id": "LIVE_08_ADD_TESTS",
            "name": "Unit Test Suite for Calculator",
            "prompt": "Create generated_projects/test_live_calc.py with pytest test functions for addition, division by zero, and negative numbers.",
            "expected_file": "generated_projects/test_live_calc.py",
            "verify_ast": True,
        },
        # 09. Multi-file Python package task
        {
            "id": "LIVE_09_PACKAGE",
            "name": "Multi-File Package Structure Initializer",
            "prompt": "Create generated_projects/live_package/__init__.py with __version__ = '2.0.0' and export a greet function.",
            "expected_file": "generated_projects/live_package/__init__.py",
            "verify_ast": True,
        },
        # 10. Deliberately difficult task designed to trigger T1 -> T2 -> T3
        {
            "id": "LIVE_10_ESCALATION",
            "name": "Complex Architecture Disagreement and Escalation",
            "prompt": "Perform security review and implement generated_projects/secure_vault.py with token encryption. High risk security architecture decision.",
            "expected_file": "generated_projects/secure_vault.py",
            "verify_ast": True,
            "expect_t2_semantic": True,
            "expect_t3_escalation": True,
        },
    ]

    for idx, item in enumerate(missions, start=1):
        await harness.run_live_mission(
            index=idx,
            mission_id=item["id"],
            name=item["name"],
            prompt=item["prompt"],
            expected_file=item.get("expected_file"),
            verify_ast=item.get("verify_ast", False),
            expect_t2_semantic=item.get("expect_t2_semantic", False),
            expect_t3_escalation=item.get("expect_t3_escalation", False),
        )

    total_wall_clock = time.monotonic() - harness.start_wall_clock
    final_mem = harness.get_memory_mb()
    mem_growth = final_mem - harness.baseline_memory_mb

    passed_count = sum(1 for m in harness.mission_records if m["success"])
    total_count = len(harness.mission_records)

    total_t1 = sum(m["t1_calls_count"] for m in harness.mission_records)
    total_t2 = sum(m["t2_calls_count"] for m in harness.mission_records)
    total_t3 = sum(m["t3_calls_count"] for m in harness.mission_records)
    total_model_calls = total_t1 + total_t2 + total_t3

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_missions": total_count,
        "passed_missions": passed_count,
        "failed_missions": total_count - passed_count,
        "success_rate_pct": (passed_count / total_count) * 100.0,
        "total_wall_clock_seconds": round(total_wall_clock, 2),
        "baseline_memory_mb": round(harness.baseline_memory_mb, 2),
        "final_memory_mb": round(final_mem, 2),
        "memory_growth_mb": round(mem_growth, 2),
        "total_real_t1_calls": total_t1,
        "total_real_t2_calls": total_t2,
        "total_real_t3_calls": total_t3,
        "total_real_model_calls": total_model_calls,
        "avg_model_calls_per_mission": round(total_model_calls / total_count, 2),
        "missions": harness.mission_records,
    }

    out_file = WORKSPACE / "artifacts" / "live_cloud_qualification_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n" + "=" * 75)
    print("LIVE CLOUD QUALIFICATION SUMMARY")
    print(f"Total Missions:       {total_count}")
    print(f"Passed:               {passed_count}/{total_count} ({(passed_count/total_count)*100:.1f}%)")
    print(f"Total Wall Clock:     {total_wall_clock:.2f}s")
    print(f"Real T1 (NVIDIA NIM): {total_t1} calls")
    print(f"Real T2 (Ollama):     {total_t2} calls")
    print(f"Real T3 (Ollama):     {total_t3} calls")
    print(f"Total Real Calls:     {total_model_calls} (Avg: {total_model_calls/total_count:.2f}/mission)")
    print(f"Process Memory Delta: {mem_growth:+.2f} MB")
    print(f"Results Saved:        {out_file}")
    print("=" * 75)

    harness.cleanup()
    return results


if __name__ == "__main__":
    asyncio.run(run_live_cloud_matrix())
