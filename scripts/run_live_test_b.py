# scripts/run_live_test_b.py
import json
import time
import urllib.request
import subprocess
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8765"
WS_PATH = Path("generated_projects/live_qual_b_python").resolve()
WS_PATH.mkdir(parents=True, exist_ok=True)

# Clean out any old files completely
for f in WS_PATH.glob("*"):
    if f.is_file():
        f.unlink()

prompt = "Create a Python program orbit_calc.py that computes Keplerian orbital velocity for a given semi-major axis, and provide a pytest unit test file test_orbit_calc.py."

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
    print(f"Started Test B Mission: {mission_id}")

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

# Check files produced
files = list(WS_PATH.glob("*.py"))
print(f"Python files in workspace: {[f.name for f in files]}")
if (WS_PATH / "test_orbit_calc.py").exists():
    res = subprocess.run(
        ["C:\\Users\\SUBBU\\Downloads\\hermes\\venv\\Scripts\\python.exe", "-m", "pytest", str(WS_PATH / "test_orbit_calc.py"), "-v"],
        capture_output=True,
        text=True
    )
    print("Pytest exit code:", res.returncode)
    print("Pytest stdout:\n", res.stdout)
