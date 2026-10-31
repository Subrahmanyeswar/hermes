import asyncio
import os
import json
import time
from pathlib import Path
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from dotenv import load_dotenv

load_dotenv()

from models.nvidia_client import NvidiaClient
from core.response_parser import ResponseParser, ParseSuccess
from tools.platform.catalog import tool_catalog
from core.workspace import WorkspaceManager
from core.agent_loop.actions import ActionExecutor, ActionEnvelope
from core.event_bus import EventBus

BENCHMARK_WS = Path(os.getenv("TEMP", "C:/Users/SUBBU/AppData/Local/Temp")) / "hermes_benchmark_test_b_ws"
BENCHMARK_WS.mkdir(parents=True, exist_ok=True)

CANDIDATES = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "stepfun-ai/step-5-preview",
    "z-ai/glm-5.3-flash",
]

TARGET_FILE = "orbital_telemetry.json"
EXPECTED_KEYWORDS = ["Aether-X", "420.5"]

TASK_PROMPT = (
    "Create orbital_telemetry.json containing telemetry data for our orbital vehicle: "
    "vehicle 'Aether-X', apogee_km 420.5, inclination_deg 28.5, status 'ORBIT_INSERTION'. "
    "You must call the write_file tool to write orbital_telemetry.json to the workspace."
)
SYSTEM_PROMPT = (
    "You are an expert autonomous software engineer. Always call write_file immediately to save files. "
    "Do NOT output conversational prose or unclosed thought tags."
)

async def test_candidate(model: str):
    print(f"\n=======================================================")
    print(f"Testing Candidate: {model}")
    print(f"=======================================================")

    # Ensure workspace file is clean
    target_path = BENCHMARK_WS / TARGET_FILE
    if target_path.exists():
        target_path.unlink()

    client = NvidiaClient()
    parser = ResponseParser()
    bus = EventBus()
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(BENCHMARK_WS))
    executor = ActionExecutor(event_bus_instance=bus)

    native_tools = tool_catalog.get_openai_tools(core_only=True)

    t0 = time.monotonic()
    ttfb = None
    ttfu = None
    tool_call_latency = None
    parse_success = False
    file_write_success = False
    error = None
    resp = None
    parsed_tool = None
    file_size = 0

    try:
        resp = await client.generate(
            model=model,
            prompt=TASK_PROMPT,
            system=SYSTEM_PROMPT,
            tools=native_tools,
            temperature=0.0,
            max_tokens=2048,
            mission_id="m_bench_test_b",
            turn_id=f"turn_{model.replace('/', '_')}",
        )
        total_gen_time = time.monotonic() - t0
        ttfb = resp.ttfb_ms / 1000.0 if resp.ttfb_ms else None
        ttfu = resp.ttfu_ms / 1000.0 if resp.ttfu_ms else total_gen_time
        print(f"  Model responded in {total_gen_time:.2f}s | TTFB: {ttfb}s | TTFU: {ttfu}s")
        print(f"  Raw tool calls: {len(resp.tool_calls)} | Text len: {len(resp.text)}")

        # Parse response
        t_parse_0 = time.monotonic()
        parse_res = parser.parse(resp)
        parse_dur = (time.monotonic() - t_parse_0) * 1000.0

        if not isinstance(parse_res, ParseSuccess):
            fail_reason = getattr(parse_res, "failure_reason", "unknown")
            error = f"ParseFailure: {fail_reason}"
            print(f"  FAILED: ResponseParser failed ({fail_reason})")
        else:
            parse_success = True
            parsed_tool = parse_res.tool
            params = parse_res.parameters
            print(f"  PARSED TOOL: {parsed_tool} (parser took {parse_dur:.2f}ms) | Target: {params.get('path')}")

            # Execute via ActionExecutor
            t_exec_0 = time.monotonic()
            action_env = ActionEnvelope(
                action_id=f"act_bench_{int(time.time())}",
                tool_name=parsed_tool,
                arguments=params,
                turn_id=f"turn_{model.replace('/', '_')}",
                mission_id="m_bench_test_b",
            )
            obs = await executor.execute_action(action_env, workspace=ws_mgr)
            exec_dur = (time.monotonic() - t_exec_0) * 1000.0
            print(f"  ACTION EXECUTOR: success={obs.success} ({exec_dur:.2f}ms) | summary={obs.summary}")

            # Verify on disk
            if target_path.exists():
                content = target_path.read_text(encoding="utf-8", errors="replace")
                file_size = len(content)
                matches = all(k.lower() in content.lower() for k in EXPECTED_KEYWORDS)
                if matches:
                    file_write_success = True
                    print(f"  VERIFIED ON DISK: {target_path.name} ({file_size} bytes, keywords matched!)")
                else:
                    error = f"Keyword mismatch in {target_path.name}"
                    print(f"  FAILED: Keywords {EXPECTED_KEYWORDS} not all found in file!")
            else:
                error = "Target file not found on disk after execution"
                print(f"  FAILED: {target_path.name} does not exist on disk!")

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"  EXCEPTION: {error}")

    total_wall_time = time.monotonic() - t0
    return {
        "model": model,
        "total_wall_time_s": round(total_wall_time, 3),
        "ttfb_s": round(ttfb, 3) if ttfb else None,
        "ttfu_s": round(ttfu, 3) if ttfu else None,
        "raw_tool_calls_count": len(resp.tool_calls) if resp else 0,
        "parse_success": parse_success,
        "parsed_tool": parsed_tool,
        "file_write_success": file_write_success,
        "file_size_bytes": file_size,
        "error": error,
    }

async def main():
    print("===============================================================")
    print("TEST B: REAL STRUCTURED TOOL CALL & FILE-WRITING BENCHMARK")
    print(f"Workspace: {BENCHMARK_WS}")
    print("===============================================================")

    results = []
    for model in CANDIDATES:
        res = await test_candidate(model)
        results.append(res)
        await asyncio.sleep(2.0)

    print("\n\n===============================================================")
    print("TEST B SUMMARY TABLE:")
    print("===============================================================")
    for r in results:
        status = "PASS" if r["file_write_success"] else "FAIL"
        print(
            f"[{status}] {r['model']:<42} | "
            f"WallTime: {r['total_wall_time_s']}s | TTFB: {r['ttfb_s']}s | "
            f"Parsed: {r['parsed_tool']} | File: {r['file_size_bytes']}B | "
            f"Error: {r['error']}"
        )

    out_file = "benchmark_test_b_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved raw results to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())
