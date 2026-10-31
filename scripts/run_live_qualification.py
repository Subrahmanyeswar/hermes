# scripts/run_live_qualification.py
"""
Executes and monitors live model-driven missions against the running production HERMES backend.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8765"


def check_backend():
    req = urllib.request.Request(f"{BACKEND_URL}/api/health")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
        print(f"Backend Status: {data.get('runtime_status')} | PID: {data.get('pid')} | Code Match: {data.get('code_match')}")
        return data


def start_mission(prompt: str, workspace_path: str):
    ws = Path(workspace_path).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    payload = {
        "prompt": prompt,
        "workspace_root": str(ws),
        "plan_mode": False
    }
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/missions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode())
        print(f"Started Mission: {res.get('mission_id')} in {res.get('workspace_root')}")
        return res.get("mission_id")


def monitor_mission(mission_id: str, timeout_seconds: float = 300.0):
    start_t = time.monotonic()
    last_status = ""
    last_turn = -1
    print(f"Monitoring mission {mission_id}...")

    while time.monotonic() - start_t < timeout_seconds:
        try:
            req = urllib.request.Request(f"{BACKEND_URL}/api/missions/{mission_id}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                snap = json.loads(resp.read().decode())
                status = snap.get("status")
                current_turn = snap.get("turns_completed", 0)

                if status != last_status or current_turn != last_turn:
                    elapsed = time.monotonic() - start_t
                    print(f"[{elapsed:5.1f}s] Status: {status} | Turns: {current_turn} | Active Task: {snap.get('active_task')}")
                    last_status = status
                    last_turn = current_turn

                if status in ("COMPLETED", "FAILED", "CANCELLED"):
                    return snap
        except Exception as e:
            print(f"Polling notice: {e}")

        time.sleep(2.0)

    print(f"Mission {mission_id} timed out after {timeout_seconds}s")
    return None


if __name__ == "__main__":
    test_type = sys.argv[1] if len(sys.argv) > 1 else "check"
    check_backend()
