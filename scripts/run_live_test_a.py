# scripts/run_live_test_a.py
import json
import time
import urllib.request
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8765"
WS_PATH = Path("generated_projects/live_qual_a_website").resolve()
WS_PATH.mkdir(parents=True, exist_ok=True)

# Clean out any old files
for f in WS_PATH.glob("*"):
    if f.is_file():
        f.unlink()

prompt = "Build a clean responsive countdown timer landing page with index.html, style.css, and main.js. Include styled timer display and start, pause, and reset buttons."

payload = {
    "prompt": prompt,
    "workspace_root": str(WS_PATH),
    "plan_mode": False
}

req = urllib.request.Request(
    f"{BACKEND_URL}/api/missions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)

with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read().decode())
    mission_id = data.get("mission_id")
    print(f"Started Test A Mission: {mission_id}")

start_t = time.monotonic()
while time.monotonic() - start_t < 240:
    time.sleep(3.0)
    try:
        r = urllib.request.Request(f"{BACKEND_URL}/api/missions/{mission_id}")
        with urllib.request.urlopen(r, timeout=5) as resp:
            snap = json.loads(resp.read().decode())
            status = snap.get("status")
            turns = snap.get("turns_completed", 0)
            elapsed = time.monotonic() - start_t
            print(f"[{elapsed:5.1f}s] Status: {status} | Turns: {turns} | Task: {snap.get('active_task')}")
            if status in ("COMPLETED", "FAILED", "CANCELLED"):
                print("Final snapshot:", json.dumps(snap, indent=2))
                break
    except Exception as e:
        print(f"Poll error: {e}")
