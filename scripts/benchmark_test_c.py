import asyncio
import os
import json
import time
import shutil
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from dotenv import load_dotenv

load_dotenv()

from core.workspace import WorkspaceManager
from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.mission_planner import Mission
from core.runtime_state.events import EventType
import config.model_config as mc

CANDIDATES = [
    {
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "ws_path": Path(r"C:\Users\SUBBU\Downloads\bench_nemotron_lightning_site"),
    },
    {
        "model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "ws_path": Path(r"C:\Users\SUBBU\Downloads\bench_nemotron_super_vl_site"),
    },
]

TASK_PROMPT = (
    "Build a Lunar Lander telemetry and dashboard website. "
    "Create index.html, styles.css, and app.js. "
    "index.html must link styles.css with <link rel='stylesheet' href='styles.css'> "
    "and include app.js with <script src='app.js'></script>. "
    "app.js must define calculateDescentVelocity(altitude, thrust) and update the DOM. "
    "Use write_file to save index.html, styles.css, and app.js."
)

def verify_site_files(ws_dir: Path) -> dict:
    idx_path = ws_dir / "index.html"
    css_path = ws_dir / "styles.css"
    js_path = ws_dir / "app.js"

    checks = {
        "index_exists": idx_path.exists(),
        "index_size": idx_path.stat().st_size if idx_path.exists() else 0,
        "css_exists": css_path.exists(),
        "css_size": css_path.stat().st_size if css_path.exists() else 0,
        "js_exists": js_path.exists(),
        "js_size": js_path.stat().st_size if js_path.exists() else 0,
        "css_linked": False,
        "js_linked": False,
        "js_valid_syntax": False,
    }

    if idx_path.exists():
        idx_content = idx_path.read_text(encoding="utf-8", errors="replace").lower()
        checks["css_linked"] = "styles.css" in idx_content
        checks["js_linked"] = "app.js" in idx_content

    if js_path.exists():
        js_content = js_path.read_text(encoding="utf-8", errors="replace")
        # Check node --check if node is available, else basic bracket/syntax check
        node_bin = shutil.which("node")
        if node_bin:
            res = subprocess.run([node_bin, "--check", str(js_path)], capture_output=True, text=True)
            checks["js_valid_syntax"] = (res.returncode == 0)
            checks["js_syntax_error"] = res.stderr if res.returncode != 0 else None
        else:
            # Fallback syntax balance check
            b_round = js_content.count("(") == js_content.count(")")
            b_curly = js_content.count("{") == js_content.count("}")
            b_square = js_content.count("[") == js_content.count("]")
            checks["js_valid_syntax"] = b_round and b_curly and b_square

    return checks

async def run_candidate_mission(candidate_info: dict) -> dict:
    model_id = candidate_info["model"]
    ws_dir = candidate_info["ws_path"]
    print(f"\n=======================================================")
    print(f"TEST C: AUTONOMOUS WEBSITE GENERATION MISSION")
    print(f"Model: {model_id}")
    print(f"Workspace: {ws_dir}")
    print(f"=======================================================")

    # Prepare clean workspace
    if ws_dir.exists():
        for item in ws_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
    ws_dir.mkdir(parents=True, exist_ok=True)

    # Set model in config
    mc.TIER1_MODEL = model_id
    os.environ["TIER1_MODEL"] = model_id

    bus = EventBus()
    events_captured = []
    bus.subscribe(lambda ev: events_captured.append(ev))

    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_dir))

    orch = Orchestrator()
    orch.event_bus = bus

    loop = AgentLoop(
        orchestrator=orch,
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=6, max_wall_time_seconds=120.0),
    )

    mission = Mission(
        mission_id=f"m_bench_c_{model_id.split('/')[-1].replace('.', '_')}",
        user_prompt=TASK_PROMPT,
    )

    t0 = time.monotonic()
    result = await loop.run(mission)
    wall_duration = time.monotonic() - t0

    # Collect telemetry events
    turns = [e for e in events_captured if e.event_type == EventType.AGENT_TURN_STARTED]
    model_calls = [e for e in events_captured if e.event_type == EventType.MODEL_COMPLETED]
    tool_calls = [e for e in events_captured if e.event_type == EventType.TOOL_COMPLETED]

    avg_model_lat = (
        sum(e.payload.get("latency", 0.0) for e in model_calls) / len(model_calls)
        if model_calls else 0.0
    )

    checks = verify_site_files(ws_dir)

    print(f"  Mission completed in {wall_duration:.2f}s | Status: {getattr(result, 'status', 'UNKNOWN')}")
    print(f"  Turns: {len(turns)} | Model calls: {len(model_calls)} (avg: {avg_model_lat:.2f}s) | Tools executed: {len(tool_calls)}")
    print(f"  Files created on disk: index.html ({checks['index_size']}B), styles.css ({checks['css_size']}B), app.js ({checks['js_size']}B)")
    print(f"  Links: CSS linked={checks['css_linked']}, JS linked={checks['js_linked']} | JS valid={checks['js_valid_syntax']}")

    all_passed = (
        checks["index_exists"] and checks["index_size"] > 50
        and checks["css_exists"] and checks["css_size"] > 20
        and checks["js_exists"] and checks["js_size"] > 20
        and checks["css_linked"] and checks["js_linked"]
        and checks["js_valid_syntax"]
    )

    return {
        "model": model_id,
        "workspace": str(ws_dir),
        "wall_duration_s": round(wall_duration, 2),
        "turns_count": len(turns),
        "model_calls_count": len(model_calls),
        "avg_model_latency_s": round(avg_model_lat, 2),
        "tool_calls_count": len(tool_calls),
        "mission_status": str(getattr(result, "status", "UNKNOWN")),
        "checks": checks,
        "all_passed": all_passed,
    }

async def main():
    results = []
    for cand in CANDIDATES:
        res = await run_candidate_mission(cand)
        results.append(res)
        await asyncio.sleep(3.0)

    print("\n\n=======================================================")
    print("TEST C FINAL COMPARISON SUMMARY:")
    print("=======================================================")
    for r in results:
        status_label = "PASS" if r["all_passed"] else "FAIL"
        print(
            f"[{status_label}] {r['model']:<42} | "
            f"WallTime: {r['wall_duration_s']}s | Turns: {r['turns_count']} | "
            f"AvgModelLat: {r['avg_model_latency_s']}s | "
            f"Files: index({r['checks']['index_size']}B) css({r['checks']['css_size']}B) js({r['checks']['js_size']}B) | "
            f"Linked: css={r['checks']['css_linked']} js={r['checks']['js_linked']} | "
            f"JSValid: {r['checks']['js_valid_syntax']}"
        )

    out_file = "benchmark_test_c_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved Test C results to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())
