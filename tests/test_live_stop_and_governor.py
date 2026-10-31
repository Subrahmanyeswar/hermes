import json
import os
import shutil
import time
import urllib.request
from pathlib import Path
import pytest

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


def test_live_api_stop_cancellation():
    test_ws = Path("C:/Users/SUBBU/Downloads/hermes_stop_eval_ws")
    if test_ws.exists():
        shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    # 1. Create mission
    create_res, create_time = post_json(
        "/api/missions",
        {
            "prompt": "Create a simple test page for cancellation evaluation",
            "workspace_root": str(test_ws),
            "plan_mode": False,
        },
    )
    mission_id = create_res["mission_id"]
    assert mission_id.startswith("m_")
    print(f"\n[PASS] Mission created: {mission_id} (latency: {create_time*1000:.1f}ms)")

    # 2. Allow turn setup
    time.sleep(0.4)

    # 3. Trigger Stop
    stop_res, stop_time = post_json(f"/api/missions/{mission_id}/stop", {})
    print(f"[PASS] Stop response: {stop_res} (latency: {stop_time*1000:.1f}ms)")
    assert stop_res.get("cancelled") is True
    assert stop_time < 1.0, f"Stop latency was {stop_time*1000:.1f}ms, expected <1000ms"

    # 4. Verify snapshot terminal state
    snap = get_json(f"/api/missions/{mission_id}")
    status = snap.get("status")
    print(f"[PASS] Authoritative snapshot status: {status} (state_version: {snap.get('state_version')})")
    assert status == "CANCELLED"

    # Clean up workspace
    shutil.rmtree(test_ws, ignore_errors=True)


def test_live_autonomous_generation():
    gen_ws = Path("C:/Users/SUBBU/Downloads/hermes_controlled_generation_ws")
    if gen_ws.exists():
        shutil.rmtree(gen_ws, ignore_errors=True)
    gen_ws.mkdir(parents=True, exist_ok=True)

    prompt = (
        "Create an interactive counter web application with index.html, styles.css, and app.js. "
        "Include buttons to increment, decrement, and reset the counter, with smooth animations and responsive layout."
    )

    create_res, create_time = post_json(
        "/api/missions",
        {
            "prompt": prompt,
            "workspace_root": str(gen_ws),
            "plan_mode": False,
        },
    )
    mission_id = create_res["mission_id"]
    print(f"\n[PASS] Generation Mission created: {mission_id} (latency: {create_time*1000:.1f}ms)")

    start_time = time.monotonic()
    last_status = None
    terminal_snapshot = None

    while time.monotonic() - start_time < 90.0:
        snap = get_json(f"/api/missions/{mission_id}")
        st = snap.get("status")
        if st != last_status:
            print(f"[STATUS] {mission_id} -> {st} (state_version: {snap.get('state_version')})")
            last_status = st
        if snap.get("is_terminal") or st in ("COMPLETED", "FAILED", "CANCELLED"):
            terminal_snapshot = snap
            break
        time.sleep(1.0)

    total_time = time.monotonic() - start_time
    assert terminal_snapshot is not None, f"Mission did not finish within 90s, last status: {last_status}"
    print(f"\n[RESULT] Mission finished with status {terminal_snapshot.get('status')} in {total_time:.1f}s")
    assert terminal_snapshot.get("status") == "COMPLETED", f"Expected COMPLETED, got {terminal_snapshot.get('status')} - error: {terminal_snapshot.get('error')}"

    # Check files created
    index_file = gen_ws / "index.html"
    assert index_file.exists(), f"index.html was not created in {gen_ws}"
    index_content = index_file.read_text(encoding="utf-8")
    assert len(index_content) > 50, "index.html is unexpectedly small"
    print(f"[VERIFIED] index.html created successfully ({len(index_content)} bytes)")

    # Clean up workspace
    shutil.rmtree(gen_ws, ignore_errors=True)


if __name__ == "__main__":
    test_live_api_stop_cancellation()
    test_live_autonomous_generation()
    print("ALL LIVE TESTS PASSED!")
