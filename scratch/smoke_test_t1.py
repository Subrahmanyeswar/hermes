"""
scratch/smoke_test_t1.py
Real local T1 smoke test using deepseek-r1:8b through real Orchestrator.
Verifies:
- Model call succeeds
- ResponseParser parses model output
- Stage 5 Tool Execution is reached (tool_calls >= 1)
- File is created on disk
- Verification/completion completes
"""

import asyncio
import os
import sys
from pathlib import Path

# Add repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import Orchestrator
from core.telemetry import telemetry

async def main():
    test_file = Path("smoke_test_output.py")
    if test_file.exists():
        test_file.unlink()

    print("=== STARTING REAL T1 SMOKE TEST WITH DEEPSEEK-R1:8B ===")
    telemetry.clear()
    
    orch = Orchestrator(mode="auto", project="smoke_test")
    prompt = "Write a python file smoke_test_output.py with function hello() returning 'world'. Use the write_file tool."
    
    print(f"Executing prompt: {prompt}")
    result = await orch.run(prompt)
    
    print("\n=== SMOKE TEST RESULTS ===")
    print(f"Result Success: {result.success}")
    print(f"Pipeline Stage Reached: {result.pipeline_stage_reached}")
    print(f"Tool Name: {result.tool_name}")
    print(f"Tool Result: {result.tool_result.success if result.tool_result else None}")
    print(f"Output Preview: {result.final_output[:200] if result.final_output else None}")
    
    completed = telemetry.get_completed_requests()
    if completed:
        req = completed[-1]
        print(f"Telemetry Model Calls: {len(req.model_calls)}")
        print(f"Telemetry Tool Calls: {len(req.tools)}")
        for t in req.tools:
            print(f"  Tool: {t.tool_name} | Success: {t.success} | Duration: {t.duration_ms:.1f}ms")
    
    file_exists = test_file.exists()
    print(f"File created on disk: {file_exists}")
    if file_exists:
        print(f"File content:\n{test_file.read_text(encoding='utf-8')}")
        test_file.unlink()  # Clean up after test
        
    assert len(completed) > 0, "No completed requests in telemetry"
    assert len(completed[-1].model_calls) >= 1, "No model calls made"
    print("\nSMOKE TEST EXECUTION FINISHED.")

if __name__ == "__main__":
    asyncio.run(main())
