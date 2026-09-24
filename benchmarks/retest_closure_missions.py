"""
Targeted Live Cloud Qualification for Failure Closure Missions (5, 8, 10).
Uses 100% LIVE cloud models:
  T1: NVIDIA NIM / z-ai/glm-5.3-flash
  T2: Ollama Cloud / gpt-oss:120b-cloud
  T3: Ollama Cloud / nemotron-3-ultra:cloud

Zero mocks. Zero synthetics. Zero cached responses.
"""

import ast
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

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
from benchmarks.run_live_cloud_qualification import LiveCloudQualificationHarness


async def main():
    print("=" * 80)
    print("HERMES LIVE CLOUD FAILURE CLOSURE — DEDICATED RE-TEST")
    print(f"LOCKED T1: {TIER1_PROVIDER} / {TIER1_MODEL}")
    print(f"LOCKED T2: {TIER2_PROVIDER} / {TIER2_MODEL}")
    print(f"LOCKED T3: {TIER3_PROVIDER} / {TIER3_MODEL}")
    print("Zero Mocks. Zero Synthetics. Real Cloud HTTP Streams.")
    print("=" * 80)

    # 1. Clean previous artifacts for missions 5, 8, 10
    m5_file = WORKSPACE / "generated_projects" / "live_web" / "index.html"
    m8_file = WORKSPACE / "generated_projects" / "test_live_calc.py"
    m10_file = WORKSPACE / "generated_projects" / "secure_vault.py"

    for f in [m5_file, m8_file, m10_file]:
        if f.exists():
            f.unlink()
            print(f"Cleaned previous artifact: {f.relative_to(WORKSPACE)}")

    # Ensure parent directories exist
    m5_file.parent.mkdir(parents=True, exist_ok=True)
    m8_file.parent.mkdir(parents=True, exist_ok=True)
    m10_file.parent.mkdir(parents=True, exist_ok=True)

    from models.nvidia_client import close_shared_nvidia_client
    await close_shared_nvidia_client()

    harness = LiveCloudQualificationHarness()

    closure_missions = [
        # Mission 5: Large HTML Tool-Call Resilience
        {
            "index": 5,
            "id": "LIVE_05_HTML_SITE",
            "name": "Single-Page HTML/CSS Interactive Dashboard",
            "prompt": "Create generated_projects/live_web/index.html with an interactive, modern dashboard layout and inline CSS.",
            "expected_file": "generated_projects/live_web/index.html",
            "verify_ast": False,
        },
        # Mission 8: Unit Test Suite & API Contract Verification
        {
            "index": 8,
            "id": "LIVE_08_ADD_TESTS",
            "name": "Unit Test Suite for Calculator",
            "prompt": "Create generated_projects/test_live_calc.py with pytest test functions for addition, division by zero, and negative numbers.",
            "expected_file": "generated_projects/test_live_calc.py",
            "verify_ast": True,
        },
        # Mission 10: Escalation + Execution Contract
        {
            "index": 10,
            "id": "LIVE_10_ESCALATION",
            "name": "Complex Architecture Disagreement and Escalation",
            "prompt": "Perform security review and implement generated_projects/secure_vault.py with token encryption. High risk security architecture decision.",
            "expected_file": "generated_projects/secure_vault.py",
            "verify_ast": True,
            "expect_t2_semantic": True,
            "expect_t3_escalation": True,
        },
    ]

    new_records = {}
    for item in closure_missions:
        rec = await harness.run_live_mission(
            index=item["index"],
            mission_id=item["id"],
            name=item["name"],
            prompt=item["prompt"],
            expected_file=item.get("expected_file"),
            verify_ast=item.get("verify_ast", False),
            expect_t2_semantic=item.get("expect_t2_semantic", False),
            expect_t3_escalation=item.get("expect_t3_escalation", False),
        )
        new_records[item["index"]] = rec

    # Run pytest verification on Mission 8 test_live_calc.py
    if m8_file.exists():
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(WORKSPACE), str(m8_file.parent), env.get("PYTHONPATH", "")])
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(m8_file), "-q", "--tb=short"],
            cwd=str(WORKSPACE),
            env=env,
            capture_output=True,
            text=True
        )
        print(f"\n[MISSION 8 VERIFICATION] pytest exit_code={proc.returncode}")
        print(f"Output: {proc.stdout.strip()}")
        if proc.returncode != 0:
            print(f"Stderr: {proc.stderr.strip()}")

    # Verify physical file existence and AST for Mission 10
    if m10_file.exists():
        content = m10_file.read_text(encoding="utf-8")
        try:
            ast.parse(content)
            print(f"[MISSION 10 VERIFICATION] secure_vault.py AST syntax valid ({len(content)} bytes)")
        except Exception as e:
            print(f"[MISSION 10 VERIFICATION] secure_vault.py AST syntax ERROR: {e}")

    # Verify physical file existence for Mission 5
    if m5_file.exists():
        c5 = m5_file.read_text(encoding="utf-8")
        print(f"[MISSION 5 VERIFICATION] index.html created successfully ({len(c5)} bytes, contains html tags: {'<html' in c5 or '<!DOCTYPE' in c5})")

    # Load existing live qualification results and update with closed records
    results_path = WORKSPACE / "artifacts" / "live_cloud_qualification_results.json"
    if results_path.exists():
        with open(results_path, "r", encoding="utf-8") as f:
            all_results = json.load(f)

        updated_missions = []
        for m in all_results.get("missions", []):
            idx = m.get("mission_index")
            if idx in new_records:
                updated_missions.append(new_records[idx])
            else:
                updated_missions.append(m)

        all_results["missions"] = updated_missions
        passed = sum(1 for m in updated_missions if m.get("success"))
        total = len(updated_missions)
        all_results["passed_missions"] = passed
        all_results["failed_missions"] = total - passed
        all_results["success_rate_pct"] = (passed / total) * 100.0

        all_results["total_real_t1_calls"] = sum(m.get("t1_calls_count", 0) for m in updated_missions)
        all_results["total_real_t2_calls"] = sum(m.get("t2_calls_count", 0) for m in updated_missions)
        all_results["total_real_t3_calls"] = sum(m.get("t3_calls_count", 0) for m in updated_missions)
        all_results["total_real_model_calls"] = (
            all_results["total_real_t1_calls"] + all_results["total_real_t2_calls"] + all_results["total_real_t3_calls"]
        )
        all_results["avg_model_calls_per_mission"] = round(all_results["total_real_model_calls"] / total, 2)
        all_results["timestamp_closure"] = datetime.now(timezone.utc).isoformat()

        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)
        print(f"\n[UPDATED MATRIX] Saved to {results_path}")
        print(f"Overall Result: {passed}/{total} Passed ({all_results['success_rate_pct']:.1f}%)")

    harness.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
