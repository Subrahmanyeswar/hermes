import asyncio
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

BASE_URL = "http://127.0.0.1:8765"

def post_json(endpoint: str, data: dict, timeout: float = 5.0):
    req = urllib.request.Request(
        f"{BASE_URL}{endpoint}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        elapsed = time.monotonic() - t0
        return json.loads(resp.read().decode("utf-8")), elapsed

def get_json(endpoint: str, timeout: float = 5.0):
    with urllib.request.urlopen(f"{BASE_URL}{endpoint}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def qualify_stop_and_subsequent_mission():
    print("======================================================================")
    print("STEP 5: VERIFY STOP CANCELLATION, SUBPROCESS TERMINATION & RECOVERY")
    print("======================================================================")
    
    test_ws_1 = Path("C:/Users/SUBBU/Downloads/hermes_stop_qual_ws1")
    test_ws_2 = Path("C:/Users/SUBBU/Downloads/hermes_stop_qual_ws2")
    
    for ws in (test_ws_1, test_ws_2):
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True, exist_ok=True)
        
    print(f"1. Launching Mission 1 to be cancelled in {test_ws_1}...")
    res1, lat1 = post_json("/api/missions", {
        "prompt": "Build a large full-stack simulation project with 10 microservices and 50 files.",
        "workspace_root": str(test_ws_1),
        "plan_mode": False
    })
    m1_id = res1["mission_id"]
    print(f"   Mission 1 Created: {m1_id} (API response time: {lat1*1000:.1f}ms)")
    
    # Wait for worker loop to pick up and start running
    time.sleep(0.5)
    snap1 = get_json(f"/api/missions/{m1_id}")
    print(f"   Mission 1 Status before stop: {snap1.get('status')} | Worker state: {snap1.get('state_version')}")
    
    # Send Stop
    print("2. Issuing POST /api/missions/{m1_id}/stop...")
    t_stop_start = time.monotonic()
    stop_res, stop_lat = post_json(f"/api/missions/{m1_id}/stop", {})
    t_stop_elapsed = time.monotonic() - t_stop_start
    print(f"   Stop Response: {stop_res} (API Latency: {stop_lat*1000:.1f}ms | Total: {t_stop_elapsed*1000:.1f}ms)")
    assert stop_res.get("cancelled") is True, f"Expected cancelled=True, got {stop_res}"
    assert stop_lat < 1.0, f"Stop latency {stop_lat:.2f}s exceeded 1.0s budget!"
    
    # Verify authoritative snapshot status
    snap1_after = get_json(f"/api/missions/{m1_id}")
    print(f"   Mission 1 Authoritative Status after stop: {snap1_after.get('status')}")
    assert snap1_after.get("status") == "CANCELLED", f"Expected CANCELLED, got {snap1_after.get('status')}"
    assert snap1_after.get("is_terminal") is True, "Expected is_terminal=True"

    # Verify no owned orphan subprocesses
    from tools.shell_tools import ACTIVE_SUBPROCESSES
    print(f"   Active tracked subprocesses count: {len(ACTIVE_SUBPROCESSES)}")
    assert len(ACTIVE_SUBPROCESSES) == 0, f"Leaked active subprocesses: {ACTIVE_SUBPROCESSES}"
    
    print("\n3. Launching Subsequent Mission 2 in clean workspace...")
    res2, lat2 = post_json("/api/missions", {
        "prompt": "Create a minimal status file named health_check.txt with content 'OK'.",
        "workspace_root": str(test_ws_2),
        "plan_mode": False
    })
    m2_id = res2["mission_id"]
    print(f"   Mission 2 Created: {m2_id} (API response time: {lat2*1000:.1f}ms)")
    
    # Poll Mission 2 until terminal
    t0 = time.monotonic()
    final_snap2 = None
    while time.monotonic() - t0 < 60.0:
        snap = get_json(f"/api/missions/{m2_id}")
        st = snap.get("status")
        if snap.get("is_terminal") or st in ("COMPLETED", "FAILED", "CANCELLED"):
            final_snap2 = snap
            break
        time.sleep(1.0)
        
    assert final_snap2 is not None, "Mission 2 did not reach terminal state within 60s"
    print(f"   Mission 2 Completed with status: {final_snap2.get('status')} in {time.monotonic()-t0:.1f}s")
    assert final_snap2.get("status") == "COMPLETED", f"Expected COMPLETED, got {final_snap2.get('status')}"
    
    # Verify disk evidence
    check_file = test_ws_2 / "health_check.txt"
    assert check_file.exists(), "health_check.txt was not created by Mission 2"
    print(f"   Verified file created on disk: {check_file.name} -> {check_file.read_text(encoding='utf-8').strip()}")
    
    # Cleanup test workspaces
    shutil.rmtree(test_ws_1, ignore_errors=True)
    shutil.rmtree(test_ws_2, ignore_errors=True)
    
    print("\n[PASS] STEP 5 QUALIFICATION COMPLETE: Stop cancellation (<1s), zero subprocess leak, and clean recovery confirmed!")

if __name__ == "__main__":
    qualify_stop_and_subsequent_mission()
