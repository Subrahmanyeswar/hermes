# scripts/run_live_test_c.py
import json
import time
import urllib.request
import subprocess
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8765"
WS_PATH = Path("generated_projects/live_qual_c_bugfix").resolve()

prompt = "Fix the bug in stats.py so that all unit tests in test_stats.py pass. Do not introduce any new regressions or delete existing functions."

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
    print(f"Started Test C Mission: {mission_id}")

start_t = time.monotonic()
while time.monotonic() - start_t < 180:
    time.sleep(3.0)
    try:
        r = urllib.request.Request(f"{BACKEND_URL}/api/missions/{mission_id}")
        with urllib.request.urlopen(r, timeout=5) as resp:
            snap = json.loads(resp.read().decode())
            status = snap.get("status")
            elapsed = time.monotonic() - start_t
            wait_reason = snap.get("wait_reason")
            print(f"[{elapsed:5.1f}s] Status: {status} | WaitReason: {wait_reason}")
            if status in ("COMPLETED", "FAILED", "CANCELLED"):
                print("Final snapshot:", json.dumps(snap, indent=2))
                break
    except Exception as e:
        print(f"Poll error: {e}")

# Verify pytest post-fix
res = subprocess.run(
    ["C:\\Users\\SUBBU\\Downloads\\hermes\\venv\\Scripts\\python.exe", "-m", "pytest", str(WS_PATH / "test_stats.py"), "-v"],
    capture_output=True,
    text=True
)
print("Pytest exit code post-fix:", res.returncode)
print("Pytest stdout post-fix:\n", res.stdout)
