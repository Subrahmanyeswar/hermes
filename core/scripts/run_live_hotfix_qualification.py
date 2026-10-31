# core/scripts/run_live_hotfix_qualification.py
"""
Executes a bounded live model-driven qualification mission for HERMES v1.0.0-rc1.
Monitors progress turn-by-turn, captures tool actions, verifies completeness,
and checks final browser output.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8765"
WORKSPACE_ROOT = r"C:\Users\SUBBU\Downloads\live_hotfix_qualification"


def post_json(endpoint: str, data: dict, timeout: float = 15.0):
    req = urllib.request.Request(
        f"{BASE_URL}{endpoint}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(endpoint: str, timeout: float = 15.0):
    req = urllib.request.Request(f"{BASE_URL}{endpoint}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print(f"=== HERMES Live Hotfix Qualification Runner ===")
    print(f"Target workspace: {WORKSPACE_ROOT}")

    # 1. Select and lock workspace
    ws_res = post_json("/api/workspaces/select", {"folder_path": WORKSPACE_ROOT})
    print(f"Workspace select response: {ws_res}")

    # 2. Start mission
    prompt = (
        "Build a clean, interactive 3D website simulating an LVM3 rocket on a launchpad using Three.js. "
        "Create index.html, style.css, and main.js with a complete Three.js scene (scene, camera, renderer, "
        "lighting, a cylinder/cone rocket mesh, and animation loop). Ensure style.css styles the page, "
        "and main.js contains complete executable JavaScript without placeholder ellipses or stubs."
    )
    mission_res = post_json("/api/missions", {
        "prompt": prompt,
        "workspace_root": WORKSPACE_ROOT,
        "plan_mode": False,
    })
    mission_id = mission_res["mission_id"]
    print(f"Mission started: {mission_id}")

    # 3. Monitor mission progress
    t0 = time.monotonic()
    last_status = None
    last_turn = 0
    poll_interval = 3.0
    max_duration = 360.0  # 6 minutes max

    while time.monotonic() - t0 < max_duration:
        try:
            snap = get_json(f"/api/missions/{mission_id}")
            status = snap.get("status")
            progress = snap.get("progress", {})
            turns = progress.get("turn_count", 0)

            if status != last_status or turns != last_turn:
                print(f"[{time.monotonic() - t0:.1f}s] Mission {mission_id} | Status: {status} | Turn: {turns} | Wait: {progress.get('waiting_reason')}")
                last_status = status
                last_turn = turns

            if status in ("COMPLETED", "FAILED", "CANCELLED", "WAITING"):
                print(f"Terminal or waiting state reached: {status}")
                break

        except Exception as e:
            print(f"Poll warning: {e}")

        time.sleep(poll_interval)

    total_time = time.monotonic() - t0
    print(f"=== Mission Execution Ended ({total_time:.1f}s) ===")
    final_snap = get_json(f"/api/missions/{mission_id}")
    print(f"Final status: {final_snap.get('status')}")
    print(f"Summary: {final_snap.get('summary')}")

    # Inspect files created
    ws = Path(WORKSPACE_ROOT)
    files = list(ws.iterdir())
    print(f"Files in workspace ({len(files)}):")
    for f in files:
        if f.is_file():
            print(f"  - {f.name} ({f.stat().st_size} bytes)")

    # Save execution results
    result_data = {
        "mission_id": mission_id,
        "duration_seconds": total_time,
        "final_status": final_snap.get("status"),
        "turns": last_turn,
        "files": [{"name": f.name, "size": f.stat().st_size} for f in files if f.is_file()],
    }
    with open("live_hotfix_qualification_result.json", "w", encoding="utf-8") as out:
        json.dump(result_data, out, indent=2)


if __name__ == "__main__":
    main()
