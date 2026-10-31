import asyncio
import time
import os
import json
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

TEMP_WS = Path(os.getenv("TEMP", "C:/Users/SUBBU/AppData/Local/Temp")) / "nemotron_qualification_ws"
TEMP_WS.mkdir(parents=True, exist_ok=True)

PROBES = [
    {
        "id": "probe_1_html",
        "task": "Create index.html for a 3D rocket website named Aether Orbital with a hero section and canvas.",
        "expected_file": "index.html",
        "expected_keyword": "Aether Orbital",
    },
    {
        "id": "probe_2_css",
        "task": "Create styles.css with modern dark-theme styles, flexbox layout, and rocket simulation styling.",
        "expected_file": "styles.css",
        "expected_keyword": "body",
    },
    {
        "id": "probe_3_js",
        "task": "Create app.js containing Three.js initialization, animation loop, and rocket rendering setup.",
        "expected_file": "app.js",
        "expected_keyword": "function",
    },
    {
        "id": "probe_4_readme",
        "task": "Create README.md documenting the Aether Orbital launch vehicle specifications and simulation controls.",
        "expected_file": "README.md",
        "expected_keyword": "Aether Orbital",
    },
    {
        "id": "probe_5_config",
        "task": "Create config.json containing project metadata: name 'aether-orbital', version '1.0.0', and launch_pad 'LC-39A'.",
        "expected_file": "config.json",
        "expected_keyword": "aether-orbital",
    },
]

async def run_qualification():
    print("=================================================================")
    print("PHASE 1: NEMOTRON 3.5 LIGHTNING 30B END-TO-END QUALIFICATION")
    print(f"Workspace: {TEMP_WS}")
    print("=================================================================\n")

    client = NvidiaClient()
    parser = ResponseParser()
    bus = EventBus()
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(TEMP_WS))
    executor = ActionExecutor(event_bus_instance=bus)

    native_tools = tool_catalog.get_openai_tools(core_only=True)
    results = []

    # Clean temp workspace before test
    for f in TEMP_WS.glob("*"):
        if f.is_file():
            try:
                f.unlink()
            except Exception:
                pass

    for i, probe in enumerate(PROBES, 1):
        print(f"--- Probe {i}/5: {probe['id']} ---")
        prompt = (
            f"You are the autonomous software engineer. Complete this task:\n{probe['task']}\n\n"
            f"Call write_file immediately to write {probe['expected_file']} to the workspace."
        )
        system = "You are an expert autonomous software engineer. Always call the appropriate tool immediately to save files. Do NOT output conversational text or think tags."

        t0 = time.monotonic()
        try:
            resp = await client.generate(
                model="nvidia/nemotron-3.5-lightning-30b-a3b",
                prompt=prompt,
                system=system,
                tools=native_tools,
                temperature=0.0,
                max_tokens=2048,
                mission_id="m_qual_nemotron",
                turn_id=f"turn_{i}",
            )
            total_dur = time.monotonic() - t0
            ttfb = resp.ttfb_ms / 1000.0 if resp.ttfb_ms else 0.0
            ttfu = resp.ttfu_ms / 1000.0 if resp.ttfu_ms else total_dur

            print(f"  Model Response in {total_dur:.2f}s | TTFB: {ttfb:.2f}s | TTFU: {ttfu:.2f}s")
            print(f"  Raw tool calls count: {len(resp.tool_calls)} | Text len: {len(resp.text)}")

            # Parse
            parse_res = parser.parse(resp)
            if not isinstance(parse_res, ParseSuccess):
                print(f"  FAILED: Parser failed to extract tool call: {getattr(parse_res, 'failure_reason', 'unknown')}")
                results.append({"probe": probe["id"], "success": False, "error": "parse_failure"})
                continue

            tool_name = parse_res.tool
            params = parse_res.parameters
            print(f"  Parsed Tool: {tool_name} | Target: {params.get('path') or params.get('file_path')}")

            # Dispatch via ActionExecutor
            action_env = ActionEnvelope(
                action_id=f"act_{i}_{int(time.time())}",
                tool_name=tool_name,
                arguments=params,
                turn_id=f"turn_{i}",
                mission_id="m_qual_nemotron",
            )
            obs = await executor.execute_action(action_env, workspace=ws_mgr)
            print(f"  Execution: success={obs.success} | summary={obs.summary}")

            # Verify on disk
            target_path = TEMP_WS / probe["expected_file"]
            if not target_path.exists():
                print(f"  FAILED: Expected file {target_path} not found on disk!")
                results.append({"probe": probe["id"], "success": False, "error": "file_not_found"})
                continue

            disk_content = target_path.read_text(encoding="utf-8", errors="replace")
            if probe["expected_keyword"].lower() not in disk_content.lower():
                print(f"  FAILED: Keyword '{probe['expected_keyword']}' not in {target_path}!")
                results.append({"probe": probe["id"], "success": False, "error": "content_mismatch"})
                continue

            print(f"  VERIFIED ON DISK: {target_path.name} ({len(disk_content)} bytes)")
            results.append({
                "probe": probe["id"],
                "file": probe["expected_file"],
                "size_bytes": len(disk_content),
                "total_duration_s": round(total_dur, 2),
                "ttfb_s": round(ttfb, 2),
                "ttfu_s": round(ttfu, 2),
                "success": True,
            })

        except Exception as exc:
            print(f"  EXCEPTION: {exc}")
            results.append({"probe": probe["id"], "success": False, "error": str(exc)})

    print("\n=================================================================")
    print("QUALIFICATION SUMMARY TABLE:")
    print("=================================================================")
    for r in results:
        status_str = "PASS" if r.get("success") else "FAIL"
        print(f"[{status_str}] {r['probe']} -> file: {r.get('file', 'N/A')} | {r.get('size_bytes', 0)}B | latency: {r.get('total_duration_s', 0)}s (TTFB: {r.get('ttfb_s', 0)}s)")

    passed_count = sum(1 for r in results if r.get("success"))
    print(f"\nTotal: {passed_count}/{len(PROBES)} PASSED")

if __name__ == "__main__":
    asyncio.run(run_qualification())
