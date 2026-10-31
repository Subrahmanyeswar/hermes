# core/scripts/live_qualification_monitor.py
"""
Live Production Qualification Runner & Telemetry Monitor for HERMES.
Submits the cinematic LVM3 rocket website mission to the live running backend,
streams authoritative events, records turn-by-turn model and tool executions,
and executes end-to-end browser qualification upon completion.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx
from core.browser.manager import BrowserManager
from core.browser.models import Viewport
from core.browser.security import BrowserSecurityManager, BrowserSecurityViolation
from core.verification_profiles import VerificationProfile, VerificationProfileEvaluator

BACKEND_URL = "http://127.0.0.1:8765"
WORKSPACE_DIR = r"C:\Users\SUBBU\Downloads\lvm3_rocket_live_qualification"

MISSION_PROMPT = """Create a premium, cinematic, interactive Three.js website simulating an LVM3 rocket launch.
Build a visually impressive, responsive LVM3-inspired launch simulation with a professional aerospace mission-control experience.
Visual direction:
Use a cinematic dark navy and near-black space environment, luminous telemetry, precise technical typography, restrained glass panels, atmospheric lighting, and carefully composed animation.
The main viewport must feature a recognizable, vertically oriented multistage rocket standing on a launch platform, with an Earth-horizon or deep space backdrop. The rocket and interface must remain responsive and visible across desktop and mobile layouts.
Required core functionality:
- A properly initialized Three.js scene, renderer, camera, lighting, and responsive canvas.
- A recognizable multistage rocket (L110 core stage with orange/rust texture, twin S200 solid strap-on boosters with white/metallic casing, C25 cryogenic upper stage, and ogive payload fairing) assembled from procedural geometry.
- A launch countdown controller with Start, Pause, and Reset controls.
- An animated ignition and liftoff sequence with a visible exhaust plume and procedural smoke/flame particle effect.
- A mission-status HUD panel displaying: countdown / elapsed flight time, current mission phase (Pre-launch, Ignition, Liftoff, Booster Separation, Orbital Insertion), simulated altitude (km), and simulated velocity (km/s).
- A visible sequence of flight events: ignition flames, smooth vertical ascent, and booster stage-separation where the two strap-on boosters visibly detach and jettison outwards.
- Responsive CSS layout with glassmorphic HUD styling.
- Clear error and WebGL capability fallback handling.
Follow a clean Vite / Three.js project structure with index.html, style.css, package.json, and main.js."""


async def run_live_qualification():
    print(f"=== HERMES LIVE PRODUCTION QUALIFICATION ===")
    print(f"Target workspace: {WORKSPACE_DIR}")
    print(f"Backend URL: {BACKEND_URL}")

    ws_path = Path(WORKSPACE_DIR)
    ws_path.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Health & Sync Check
        health_resp = await client.get(f"{BACKEND_URL}/api/health")
        health = health_resp.json()
        print(f"Backend Status: {health.get('status')} | Runtime: {health.get('runtime_status')} | PID: {health.get('pid')}")
        print(f"Active Model Stack: {json.dumps(health.get('model_stack'), indent=2)}")
        assert health.get("code_match") is True, "Backend code mismatch detected!"
        assert health.get("runtime_status") == "SYNCED", "Backend runtime status is not SYNCED!"

        # 2. Workspace Selection
        sel_resp = await client.post(
            f"{BACKEND_URL}/api/workspaces/select",
            json={"folder_path": WORKSPACE_DIR},
        )
        assert sel_resp.status_code == 200, f"Workspace selection failed: {sel_resp.text}"
        print(f"Workspace locked & verified: {WORKSPACE_DIR}")

        # 3. Create Mission
        print("\nSubmitting Live Mission to HERMES Production Dispatcher...")
        t_start = time.time()
        create_resp = await client.post(
            f"{BACKEND_URL}/api/missions",
            json={
                "prompt": MISSION_PROMPT,
                "workspace_root": WORKSPACE_DIR,
                "plan_mode": False,
            },
        )
        assert create_resp.status_code == 201, f"Mission creation failed: {create_resp.text}"
        create_data = create_resp.json()
        mission_id = create_data["mission_id"]
        print(f"Mission Created: {mission_id}")

        # 4. Stream / Poll Events and Track Execution
        seen_events = set()
        model_calls = 0
        tool_calls = 0
        turns = 0
        terminal_status = None
        termination_reason = None
        last_logged_time = time.time()

        print("\nStreaming Live Production Telemetry...")
        while True:
            await asyncio.sleep(2.0)
            elapsed = time.time() - t_start

            # Fetch event history
            try:
                hist_resp = await client.get(f"{BACKEND_URL}/api/missions/{mission_id}/events/history")
                if hist_resp.status_code == 200:
                    events = hist_resp.json().get("events", [])
                    for ev in events:
                        ev_id = ev.get("event_id") or f"{ev.get('sequence')}_{ev.get('event_type')}"
                        if ev_id in seen_events:
                            continue
                        seen_events.add(ev_id)
                        ev_type = ev.get("event_type")
                        payload = ev.get("payload", {})

                        if ev_type == "AGENT_TURN_STARTED":
                            turns += 1
                            print(f"[{elapsed:.1f}s] Turn {turns} Started")
                        elif ev_type == "MODEL_REQUESTED":
                            model_calls += 1
                            print(f"[{elapsed:.1f}s] Model Requested: {payload.get('model')} ({payload.get('provider')})")
                        elif ev_type == "MODEL_COMPLETED":
                            lat = payload.get("latency", 0)
                            print(f"[{elapsed:.1f}s] Model Responded (Latency: {lat:.2f}s)")
                        elif ev_type == "TOOL_EXECUTION_COMPLETED":
                            tool_calls += 1
                            t_name = payload.get("tool_name")
                            succ = payload.get("success")
                            summary = payload.get("summary", "")[:80]
                            print(f"[{elapsed:.1f}s] Tool Executed: {t_name} | Success: {succ} | {summary}")
                        elif ev_type == "VERIFICATION_COMPLETED":
                            print(f"[{elapsed:.1f}s] Verification Result: {payload.get('verdict')} | Reason: {payload.get('reason')}")
                        elif ev_type in ("MISSION_COMPLETED", "MISSION_FAILED", "MISSION_CANCELLED"):
                            terminal_status = ev_type
                            termination_reason = payload.get("reason") or payload.get("error")
                            print(f"\n[{elapsed:.1f}s] Terminal Event: {ev_type} | Reason: {termination_reason}")
                            break
            except Exception as hist_err:
                print(f"Telemetry polling notice: {hist_err}")

            # Check mission snapshot
            try:
                snap_resp = await client.get(f"{BACKEND_URL}/api/missions/{mission_id}")
                if snap_resp.status_code == 200:
                    snap = snap_resp.json()
                    status = snap.get("status")
                    if status in ("COMPLETED", "FAILED", "CANCELLED"):
                        terminal_status = terminal_status or f"MISSION_{status}"
                        termination_reason = termination_reason or snap.get("error") or "Concluded"
                        break
            except Exception:
                pass

            if terminal_status:
                break

            if time.time() - last_logged_time > 15.0:
                last_logged_time = time.time()
                print(f"[{elapsed:.1f}s] Mission executing... (Turns: {turns}, Model calls: {model_calls}, Tool calls: {tool_calls})")

            # Timeout safety
            if elapsed > 360.0:
                print("Max monitoring timeout (360s) reached.")
                break

        total_wall_time = time.time() - t_start

        # 5. Inspect Workspace Artifacts
        ws_files = [f.name for f in ws_path.iterdir() if f.is_file()]
        print(f"\nGenerated Workspace Deliverables ({len(ws_files)} files): {ws_files}")

        # 6. Real HTTP Browser Verification
        print("\nExecuting Autonomous Browser Verification over HTTP...")
        browser = BrowserManager(prefer_cdp=True)
        preview_data = {}
        screenshot_path = None
        canvas_found = False
        console_errors = []

        try:
            preview_res = await browser.open_preview(workspace_dir=ws_path)
            preview_data = preview_res
            print(f"HTTP Preview URL: {preview_res.get('url')} | Port: {preview_res.get('port')}")

            # Allow scripts and WebGL scene to mount
            await asyncio.sleep(2.0)

            # Inspect DOM
            inspect_res = await browser.inspect()
            dom_tags = [
                (e.get("tag") or e.get("tag_name") if isinstance(e, dict) else getattr(e, "tag_name", getattr(e, "tag", ""))).lower()
                for e in inspect_res.elements
            ]
            canvas_found = "canvas" in dom_tags
            print(f"DOM Elements Inspected: {len(dom_tags)} | Canvas Present: {canvas_found}")

            # Measure canvas dimensions and HUD if CDP available
            canvas_metrics = {}
            if hasattr(browser.driver, "_send_cdp"):
                try:
                    eval_res = await browser.driver._send_cdp(
                        "Runtime.evaluate",
                        {
                            "expression": "JSON.stringify({canvasWidth: document.querySelector('canvas')?.clientWidth || 0, canvasHeight: document.querySelector('canvas')?.clientHeight || 0, title: document.title, hudPresent: document.querySelectorAll('[id*=\"hud\"], [class*=\"hud\"], [id*=\"telemetry\"], [class*=\"telemetry\"], [id*=\"controls\"], [class*=\"controls\"]').length > 0})"
                        },
                    )
                    val = eval_res.get("result", {}).get("value")
                    if val:
                        canvas_metrics = json.loads(val)
                        print(f"Canvas Runtime Metrics: {canvas_metrics}")
                        if canvas_metrics.get("canvasWidth", 0) > 0:
                            canvas_found = True
                except Exception as cdpe:
                    print(f"CDP eval notice: {cdpe}")

            # Capture console logs
            console_msgs = browser.get_console_messages()
            console_errors = [m.text for m in console_msgs if getattr(m, "level", "").lower() == "error"]
            print(f"Captured Console Messages: {len(console_msgs)} | Errors: {len(console_errors)}")

            # Capture High-Resolution Screenshot
            screenshot_artifact = await browser.capture_screenshot(name="live_lvm3_rocket_qualification")
            screenshot_path = screenshot_artifact.file_path
            print(f"Saved Browser Screenshot: {screenshot_path}")

        except Exception as b_err:
            print(f"Browser verification notice: {b_err}")
        finally:
            try:
                await browser.close()
            except Exception:
                pass

        # 7. Evaluate Verification Profile C
        prof_res = VerificationProfileEvaluator.evaluate(
            VerificationProfile.PROFILE_C,
            ws_path,
            MISSION_PROMPT,
            written_files=ws_files,
        )

        qualification_report = {
            "mission_id": mission_id,
            "workspace": WORKSPACE_DIR,
            "terminal_status": terminal_status or "UNKNOWN",
            "termination_reason": termination_reason,
            "turns_count": turns,
            "model_calls_count": model_calls,
            "tool_calls_count": tool_calls,
            "wall_clock_seconds": round(total_wall_time, 2),
            "deliverable_files": ws_files,
            "http_url": preview_data.get("url"),
            "canvas_present": canvas_found,
            "canvas_metrics": canvas_metrics,
            "console_error_count": len(console_errors),
            "screenshot_artifact": screenshot_path,
            "profile_c_passed": prof_res.passed,
            "profile_c_issues": prof_res.issues,
            "profile_c_summary": prof_res.summary,
        }

        print("\n=== LIVE QUALIFICATION COMPLETE ===")
        print(json.dumps(qualification_report, indent=2))
        return qualification_report


if __name__ == "__main__":
    asyncio.run(run_live_qualification())
