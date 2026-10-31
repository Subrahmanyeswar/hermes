import sys
import urllib.request
import json
import time

base_url = "http://127.0.0.1:8765"

def post(endpoint, data):
    req = urllib.request.Request(
        f"{base_url}{endpoint}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get(endpoint):
    with urllib.request.urlopen(f"{base_url}{endpoint}") as resp:
        return json.loads(resp.read().decode("utf-8"))

# 1. Check health
health = get("/api/health")
print("Health status:", health.get("status"))

# 2. Check stop on a mission
import tempfile
import os

temp_ws = tempfile.mkdtemp(prefix="hermes_stop_test_")
m_data = {
    "prompt": "Test controlled cancellation mission",
    "workspace_root": temp_ws,
    "execution_mode": "auto"
}
try:
    sub_res = post("/api/missions", m_data)
    m_id = sub_res.get("mission_id")
    print("Created test mission:", m_id)

    # Poll snapshot
    snap_before = get(f"/api/missions/{m_id}")
    print("Snapshot before stop:", snap_before.get("status"), "state_version:", snap_before.get("state_version"))

    # Stop mission
    stop_res = post(f"/api/missions/{m_id}/stop", {})
    print("Stop response:", stop_res)

    # Poll snapshot after stop
    snap_after = get(f"/api/missions/{m_id}")
    print("Snapshot after stop:", snap_after.get("status"), "state_version:", snap_after.get("state_version"), "is_terminal:", snap_after.get("is_terminal"))

    assert snap_after.get("status") == "CANCELLED"
    assert snap_after.get("state_version") > snap_before.get("state_version") or snap_after.get("is_terminal") is True
    print("\nAPI STOP & SNAPSHOT VERIFICATION: SUCCESSFUL ✓")
except Exception as e:
    print("API test error:", e)
    sys.exit(1)
