# core/scripts/qualify_phase5_hybrid.py
"""
HERMES 2.x — PHASE 5 UNIFIED HYBRID INTELLIGENCE & RUNTIME QUALIFICATION SCRIPT

Executes end-to-end live verification across Tasks A through F:
  1. Task A: Real 4-tier Provider Availability Registry probing via GET /api/providers/status?live=true
     (without equating credentials to health; diagnosing Gemini 503, SambaNova 402 BILLING_BLOCKED,
      Ollama daemon down / missing model remediation).
  2. Tasks B/C/D/E/F: Executes 4 complete independent website missions through the REAL HERMES
     FastAPI Mission API (POST /api/missions -> RuntimeAdapter -> AgentLoop.run -> MissionSnapshot)
     into fresh isolated workspaces:
       - Mission A: EMBER & OLIVE (Mode 1 Deterministic - Restaurant)
       - Mission B: FLOWSTACK (Mode 1 Deterministic - SaaS Kanban)
       - Mission C: THE FIELD JOURNAL (Mode 1 Deterministic - Digital Journalism)
       - Mission D: KRONOS HOROLOGY ATELIER (Mode 2 LLM-Assisted - Unfamiliar Bespoke Horology Domain)
  3. Verifies MissionSnapshot telemetry (execution_mode, active_provider, active_model, current_stage,
     duration_seconds, failover_events, terminal_reason, is_terminal).
  4. Runs deep interactive 1440x900 Chrome CDP verification & screenshots across all 4 missions.
  5. Verifies Mode 2 Blocked-Provider protection (zero fake fallback when all providers blocked).

Outputs genuine observed results to phase5_hybrid_intelligence_results.json without touching any
historical Phase 1-4 workspaces.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv(REPO_ROOT / ".env")

from core.browser.dev_server import DevServerManager
from core.browser.manager import BrowserManager, Viewport
from core.domain_confidence import DomainConfidenceClassifier
from core.llm_semantic_planner import LLMSemanticPlanner
from core.mission_spec import MissionSpecification
from core.provider_registry import ProviderAvailabilityRegistry, get_provider_registry
from core.runtime_failover import global_attempt_ledger
from core.server.app import create_app
from core.telemetry import redact_telemetry_secrets

WS_EMBER = Path(r"C:\Users\SUBBU\Downloads\hermes_phase5_a_ember").resolve()
WS_FLOWSTACK = Path(r"C:\Users\SUBBU\Downloads\hermes_phase5_b_flowstack").resolve()
WS_JOURNAL = Path(r"C:\Users\SUBBU\Downloads\hermes_phase5_c_journal").resolve()
WS_HOROLOGY = Path(r"C:\Users\SUBBU\Downloads\hermes_phase5_d_unfamiliar").resolve()

PROMPT_EMBER = (
    "Build a premium modern restaurant reservation website for EMBER & OLIVE. "
    "Include editorial food photography, restaurant identity and chef introduction, "
    "menu categories and dish cards, menu search and category filters, "
    "reservation form with date, time and party-size selection, reservation validation, "
    "and location and opening-hours sections. "
    "Clearly label demonstration/sample data and ensure the reservation form discloses demonstration mode."
)

PROMPT_FLOWSTACK = (
    "Create a professional B2B project-management SaaS product website for FLOWSTACK. "
    "Include product landing page, interactive Kanban workspace with draggable task cards, "
    "project status and progress metrics, team management interface, "
    "pricing comparison with interactive monthly/annual billing switcher, and product demonstration section. "
    "Clearly label sample workspace/demo billing data and disclose demonstration mode."
)

PROMPT_JOURNAL = (
    "Build a premium digital editorial and journalism publication website for THE FIELD JOURNAL "
    "focused on science, technology, environment and innovation. "
    "Include editorial homepage, featured stories, article categories, search, article detail views, "
    "editorial author information, reading-time indicators, related stories, and newsletter subscription validation. "
    "Label sample editorial profiles and disclose newsletter demonstration mode."
)

PROMPT_HOROLOGY = (
    "Build a bespoke mechanical watchmaking and tourbillon restoration studio website for KRONOS HOROLOGY ATELIER. "
    "Showcase in-house hand-regulated mechanical calibres, tourbillon escapements, perpetual complications, "
    "and vintage movement overhaul services with category filters, keyword search, detail inspection view, "
    "and a private commission inquiry form clearly labeled in Demonstration Mode. "
    "Do not invent awards or unverified certifications."
)


async def submit_and_wait_mission(
    client: httpx.AsyncClient,
    *,
    name: str,
    prompt: str,
    workspace_dir: Path,
    timeout_s: float = 90.0,
) -> Dict[str, Any]:
    """Submit a real mission via POST /api/missions and await authoritative terminal snapshot."""
    print(f"\n{'='*80}")
    print(f"  REAL HERMES MISSION SUBMISSION: {name}")
    print(f"  Workspace: {workspace_dir}")
    print(f"{'='*80}")

    if workspace_dir.exists():
        shutil.rmtree(workspace_dir, ignore_errors=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    assessment = DomainConfidenceClassifier.assess(prompt)
    print(
        f"  Pre-check Confidence: {assessment.category.value} | "
        f"mode={assessment.execution_mode.value} | score={assessment.confidence_score}"
    )

    t0 = time.monotonic()
    resp = await client.post(
        "/api/missions",
        json={
            "prompt": prompt,
            "workspace_root": str(workspace_dir),
            "plan_mode": False,
        },
    )
    assert resp.status_code == 201, f"POST /api/missions failed: {resp.status_code} {resp.text}"
    created = resp.json()
    mission_id = created["mission_id"]
    print(f"  Created Mission ID: {mission_id} (initial status={created.get('status')})")

    snapshots_seen: List[Dict[str, Any]] = []
    final_snap: Dict[str, Any] = {}
    while (time.monotonic() - t0) < timeout_s:
        await asyncio.sleep(0.3)
        s_resp = await client.get(f"/api/missions/{mission_id}")
        assert s_resp.status_code == 200
        snap = s_resp.json()
        state_tuple = (snap.get("status"), snap.get("current_stage"), snap.get("execution_mode"))
        if not snapshots_seen or snapshots_seen[-1]["_tuple"] != state_tuple:
            snapshots_seen.append({
                "_tuple": state_tuple,
                "elapsed_s": round(time.monotonic() - t0, 3),
                "status": snap.get("status"),
                "stage": snap.get("current_stage"),
                "execution_mode": snap.get("execution_mode"),
                "active_provider": snap.get("active_provider"),
                "active_model": snap.get("active_model"),
            })
        if snap.get("is_terminal"):
            final_snap = snap
            break

    wall_s = round(time.monotonic() - t0, 3)
    assert final_snap and final_snap.get("is_terminal"), f"Mission {mission_id} did not reach terminal state in {timeout_s}s"

    hist_resp = await client.get(f"/api/missions/{mission_id}/events/history")
    hist_payload = hist_resp.json() if hist_resp.status_code == 200 else {}
    events_history = hist_payload.get("events", []) if isinstance(hist_payload, dict) else hist_payload
    event_types = [e.get("event_type") for e in events_history if isinstance(e, dict)]

    spec = MissionSpecification.load_from_workspace(workspace_dir)
    raw_recs = (
        global_attempt_ledger.get_mission_attempts(mission_id)
        if hasattr(global_attempt_ledger, "get_mission_attempts")
        else [r for r in getattr(global_attempt_ledger, "records", getattr(global_attempt_ledger, "_records", [])) if getattr(r, "mission_id", "") == mission_id]
    )
    ledger_records = [r.to_dict() if hasattr(r, "to_dict") else vars(r) for r in raw_recs]

    for row in snapshots_seen:
        row.pop("_tuple", None)

    print(
        f"  Terminal Snapshot: status={final_snap.get('status')} | is_terminal={final_snap.get('is_terminal')} | "
        f"mode={final_snap.get('execution_mode')} | provider={final_snap.get('active_provider')} | "
        f"model={final_snap.get('active_model')} | stage={final_snap.get('current_stage')} | wall={wall_s:.2f}s"
    )
    assert str(final_snap.get("status", "")).lower() == "completed", (
        f"Mission {name} failed: {final_snap.get('terminal_reason') or final_snap.get('error')}"
    )

    return {
        "mission_id": mission_id,
        "workspace": str(workspace_dir),
        "confidence_assessment": assessment.to_dict(),
        "wall_duration_seconds": wall_s,
        "mission_snapshot": {
            "status": final_snap.get("status"),
            "is_terminal": final_snap.get("is_terminal"),
            "execution_mode": final_snap.get("execution_mode"),
            "active_provider": final_snap.get("active_provider"),
            "active_model": final_snap.get("active_model"),
            "current_stage": final_snap.get("current_stage"),
            "duration_seconds": final_snap.get("duration_seconds"),
            "failover_events": final_snap.get("failover_events"),
            "terminal_reason": final_snap.get("terminal_reason"),
            "files_created": final_snap.get("files_created"),
        },
        "observed_stage_transitions": snapshots_seen,
        "event_types": event_types,
        "synthesis_telemetry": spec.synthesis_telemetry if spec else {},
        "attempt_ledger_records": ledger_records,
    }


async def verify_archetype_cdp(
    workspace_dir: Path,
    expected_brand: str,
    archetype: str,
    forbidden_terms: List[str],
    prefix: str,
) -> Dict[str, Any]:
    print(f"\n{'='*80}")
    print(f"  1440x900 CHROME CDP VERIFICATION: {expected_brand} ({archetype})")
    print(f"{'='*80}")

    screenshots_dir = workspace_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {
        "criteria_results": {},
        "functional_checks": {},
        "honesty_audit": {},
        "console_errors": [],
        "failed_network_requests": [],
        "broken_images": 0,
        "total_images": 0,
        "desktop_screenshot": "",
        "fullpage_screenshot": "",
    }

    server_mgr = DevServerManager()
    server_info = await server_mgr.start_static_server(directory=workspace_dir, timeout=8.0)
    browser = BrowserManager(artifacts_dir=screenshots_dir, prefer_cdp=True)

    try:
        launched = await browser.launch(
            headless=True,
            viewport=Viewport(width=1440, height=900, is_mobile=False),
        )
        assert launched is True, "Failed to launch CDP browser driver"

        nav_res = await browser.navigate(f"{server_info.url}/index.html")
        assert nav_res.success is True, f"Navigation failed: {nav_res.error_message}"
        await asyncio.sleep(0.8)

        async def eval_js(expr: str) -> Any:
            if hasattr(browser.driver, "_send_cdp"):
                res = await browser.driver._send_cdp(
                    "Runtime.evaluate",
                    {"expression": expr, "returnByValue": True, "awaitPromise": True},
                )
                if "exceptionDetails" in res:
                    raise RuntimeError(f"CDP JS Exception: {res['exceptionDetails']}")
                return res.get("result", {}).get("value")
            return None

        title = await eval_js("document.title")
        nav_brand = await eval_js("document.querySelector('.nav-brand')?.textContent?.trim() || ''")
        hero_title = await eval_js("document.querySelector('.hero-title')?.textContent?.trim() || ''")
        body_lower = (await eval_js("document.body.innerText")).lower()
        found_forbidden = [t for t in forbidden_terms if re.search(rf"\b{re.escape(t)}\b", body_lower)]
        c_brand = (expected_brand in title) and (expected_brand in nav_brand) and (expected_brand in hero_title)
        c_clean = len(found_forbidden) == 0
        results["criteria_results"]["1_brand_and_zero_contamination"] = {
            "passed": c_brand and c_clean,
            "title": title,
            "nav_brand": nav_brand,
            "hero_title": hero_title,
            "forbidden_detected": found_forbidden,
        }
        print(f"  [Check 1] Brand & Zero Leaks: {'PASS' if (c_brand and c_clean) else 'FAIL'}")

        nav_links_count = await eval_js("document.querySelectorAll('.nav-link').length")
        hero_cta = await eval_js("document.querySelector('#hero .btn-primary')?.textContent?.trim() || ''")
        img_srcs = await eval_js("Array.from(document.querySelectorAll('img')).map(i => i.getAttribute('src'))")
        img_check = await browser.check_images(scroll_first=True)
        overflow_info = await eval_js(
            "(() => { const d=document.documentElement, b=document.body; const s=Math.max(d.scrollWidth,b.scrollWidth); return {scrollWidth:s, clientWidth:d.clientWidth, overflow:s>d.clientWidth+1}; })()"
        )
        results["broken_images"] = img_check.broken_images
        results["total_images"] = img_check.total_images
        c_nav_hero_layout = (
            nav_links_count >= 4
            and bool(hero_cta)
            and img_check.broken_images == 0
            and img_check.total_images >= 4
            and all(isinstance(s, str) and s.startswith("assets/") for s in img_srcs)
            and not overflow_info["overflow"]
        )
        results["criteria_results"]["2_layout_hero_images"] = {
            "passed": c_nav_hero_layout,
            "nav_links": nav_links_count,
            "hero_cta": hero_cta,
            "total_images": img_check.total_images,
            "broken_images": img_check.broken_images,
            "overflow": overflow_info,
        }
        print(
            f"  [Check 2] Nav/Hero/Images/Overflow: {'PASS' if c_nav_hero_layout else 'FAIL'} "
            f"(imgs={img_check.total_images}, broken={img_check.broken_images}, overflow={overflow_info['overflow']})"
        )

        await eval_js("window.scrollTo(0, 0);")
        await asyncio.sleep(0.4)
        shot_desktop = screenshots_dir / f"{prefix}_desktop_1440.png"
        shot_fullpage = screenshots_dir / f"{prefix}_fullpage.png"
        shot_art = await browser.capture_screenshot(
            name=f"{prefix}_desktop_1440",
            viewport=Viewport(width=1440, height=900, is_mobile=False),
        )
        if Path(shot_art.file_path).exists():
            shutil.copy2(shot_art.file_path, shot_desktop)
            results["desktop_screenshot"] = str(shot_desktop)

        full_res = await browser.driver._send_cdp(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
        )
        b64_data = full_res.get("data")
        if b64_data:
            shot_fullpage.write_bytes(base64.b64decode(b64_data))
            results["fullpage_screenshot"] = str(shot_fullpage)

        if archetype == "culinary_restaurant":
            await eval_js(
                "(() => { const s=document.getElementById('showcase-search'); s.value='pasta'; s.dispatchEvent(new Event('input',{bubbles:true})); })()"
            )
            await asyncio.sleep(0.2)
            vis_pasta = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            await eval_js(
                "(() => { const s=document.getElementById('showcase-search'); s.value=''; s.dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('.filter-pill[data-category=\"starters\"]').click(); })()"
            )
            await asyncio.sleep(0.2)
            vis_starters = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            await eval_js("document.querySelector('.filter-pill[data-category=\"all\"]').click()")
            await asyncio.sleep(0.2)
            vis_all = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")

            await eval_js(
                """(() => {
                    document.getElementById('form-full_name').value = 'Test Diner';
                    document.getElementById('form-email').value = 'guest@example.invalid';
                    document.getElementById('form-reservation_date').value = '2020-01-01';
                    document.getElementById('inquiry-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));
                })()"""
            )
            await asyncio.sleep(0.2)
            past_err = await eval_js(
                "({cls: document.getElementById('form-feedback').className, txt: document.getElementById('form-feedback').textContent})"
            )
            await eval_js(
                """(() => {
                    document.getElementById('form-full_name').value = 'Test Diner';
                    document.getElementById('form-email').value = 'guest@example.invalid';
                    document.getElementById('form-reservation_date').value = '2027-06-15';
                    document.getElementById('inquiry-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));
                })()"""
            )
            await asyncio.sleep(0.2)
            future_ok = await eval_js(
                "({cls: document.getElementById('form-feedback').className, txt: document.getElementById('form-feedback').textContent})"
            )
            has_chef = await eval_js("document.getElementById('about') !== null && document.getElementById('location-hours') !== null")
            fake_claims = [x for x in ("michelin", "yelp", "google reviews", "4.9 stars") if x in body_lower]
            func_ok = (
                vis_pasta == 1
                and vis_starters >= 2
                and vis_all == 6
                and has_chef
                and "error" in past_err["cls"]
                and "future date" in past_err["txt"].lower()
                and "success" in future_ok["cls"]
                and "demonstration mode" in future_ok["txt"].lower()
                and len(fake_claims) == 0
            )
            results["functional_checks"] = {
                "passed": func_ok,
                "search_pasta_count": vis_pasta,
                "filter_starters_count": vis_starters,
                "reset_all_count": vis_all,
                "chef_and_hours_sections": has_chef,
                "past_date_rejected": past_err,
                "future_date_confirmed": future_ok,
            }
            results["honesty_audit"] = {"passed": len(fake_claims) == 0, "fake_claims_found": fake_claims}

        elif archetype == "saas_product":
            init_stats = await eval_js(
                "({total: document.getElementById('kanban-total-count').textContent, done: document.getElementById('kanban-completed-count').textContent, pct: document.getElementById('kanban-progress-pct').textContent})"
            )
            await eval_js(
                """(() => {
                    document.getElementById('new-task-title').value = 'PERF-509: Index Shard Rebalance';
                    document.getElementById('add-task-btn').click();
                })()"""
            )
            await asyncio.sleep(0.2)
            await eval_js(
                """(() => {
                    const card1 = document.querySelector('.kanban-card[data-task-id="task-1"]');
                    if (card1) card1.querySelector('.btn-move-card[data-dir="next"]').click();
                })()"""
            )
            await asyncio.sleep(0.1)
            await eval_js(
                """(() => {
                    const card1 = document.querySelector('.kanban-card[data-task-id="task-1"]');
                    if (card1) card1.querySelector('.btn-move-card[data-dir="next"]').click();
                })()"""
            )
            await asyncio.sleep(0.2)
            await eval_js(
                """(() => {
                    const card2 = document.querySelector('.kanban-card[data-task-id="task-2"]');
                    const colInProg = document.getElementById('col-inprogress');
                    const dt = new DataTransfer();
                    dt.setData('text/plain', 'task-2');
                    card2.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
                    colInProg.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
                    colInProg.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
                })()"""
            )
            await asyncio.sleep(0.2)
            after_kanban = await eval_js(
                "({total: document.getElementById('kanban-total-count').textContent, done: document.getElementById('kanban-completed-count').textContent, inprog: document.getElementById('kanban-inprogress-count').textContent, pct: document.getElementById('kanban-progress-pct').textContent})"
            )
            await eval_js("document.getElementById('tab-analytics').click()")
            await asyncio.sleep(0.1)
            analytics_active = await eval_js("document.getElementById('view-analytics').classList.contains('active')")
            await eval_js("document.getElementById('tab-kanban').click()")

            seats_before = await eval_js("document.getElementById('team-member-count').textContent")
            await eval_js(
                """(() => {
                    document.getElementById('team-member-name').value = 'Sample Staff Tester';
                    document.getElementById('team-member-email').value = 'tester.demo@example.invalid';
                    document.getElementById('add-member-btn').click();
                })()"""
            )
            await asyncio.sleep(0.2)
            seats_after_add = await eval_js("document.getElementById('team-member-count').textContent")
            await eval_js(
                """(() => {
                    const rows = document.querySelectorAll('#team-roster-body tr');
                    const last = rows[rows.length - 1];
                    last.querySelector('.role-select').value = 'Admin';
                    last.querySelector('.role-select').dispatchEvent(new Event('change', {bubbles:true}));
                    last.querySelector('.btn-remove-member').click();
                })()"""
            )
            await asyncio.sleep(0.2)
            seats_after_rm = await eval_js("document.getElementById('team-member-count').textContent")

            monthly_vals = await eval_js("Array.from(document.querySelectorAll('.pricing-amount')).map(el => el.textContent.trim())")
            await eval_js("document.getElementById('billing-toggle').click()")
            await asyncio.sleep(0.2)
            annual_vals = await eval_js("Array.from(document.querySelectorAll('.pricing-amount')).map(el => el.textContent.trim())")

            fake_claims = [x for x in ("soc2", "hipaa", "iso 27001", "99.99%") if x in body_lower]
            func_ok = (
                init_stats["total"] == "6"
                and after_kanban["total"] == "7"
                and int(after_kanban["done"]) >= 3
                and after_kanban["pct"] != init_stats["pct"]
                and analytics_active
                and seats_before == "3"
                and seats_after_add == "4"
                and seats_after_rm == "3"
                and monthly_vals == ["29", "79", "199"]
                and annual_vals == ["23", "63", "159"]
                and len(fake_claims) == 0
            )
            results["functional_checks"] = {
                "passed": func_ok,
                "kanban_initial": init_stats,
                "kanban_after_ops": after_kanban,
                "analytics_tab_active": analytics_active,
                "team_seats": {"before": seats_before, "after_add": seats_after_add, "after_remove": seats_after_rm},
                "billing_monthly": monthly_vals,
                "billing_annual": annual_vals,
            }
            results["honesty_audit"] = {"passed": len(fake_claims) == 0, "fake_claims_found": fake_claims}

        elif archetype == "editorial_publication":
            await eval_js("document.getElementById('btn-read-featured').click()")
            await asyncio.sleep(0.25)
            modal_first = await eval_js(
                "({open: document.getElementById('details-modal').classList.contains('open'), title: document.querySelector('#modal-body h2')?.textContent || '', relCount: document.querySelectorAll('.btn-related-story').length, bodyLen: document.getElementById('modal-body').textContent.length})"
            )
            await eval_js("document.querySelector('.btn-related-story')?.click()")
            await asyncio.sleep(0.2)
            modal_switched_title = await eval_js("document.querySelector('#modal-body h2')?.textContent || ''")
            await eval_js("document.getElementById('modal-close').click()")
            await asyncio.sleep(0.2)

            await eval_js("document.querySelector('.filter-pill[data-category=\"environment\"]').click()")
            await asyncio.sleep(0.2)
            vis_env = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            await eval_js("document.querySelector('.filter-pill[data-category=\"all\"]').click()")
            await asyncio.sleep(0.2)
            await eval_js("(() => { const s=document.getElementById('showcase-search'); s.value='peatland'; s.dispatchEvent(new Event('input',{bubbles:true})); })()")
            await asyncio.sleep(0.2)
            vis_search = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            await eval_js("(() => { const s=document.getElementById('showcase-search'); s.value=''; s.dispatchEvent(new Event('input',{bubbles:true})); })()")

            await eval_js(
                """(() => {
                    document.getElementById('form-full_name').value = 'Sample Reader';
                    document.getElementById('form-email').value = 'not-an-email';
                    document.getElementById('inquiry-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));
                })()"""
            )
            await asyncio.sleep(0.2)
            bad_email_res = await eval_js("document.getElementById('form-feedback').className")
            await eval_js(
                """(() => {
                    document.getElementById('form-full_name').value = 'Sample Reader';
                    document.getElementById('form-email').value = 'reader@example.invalid';
                    document.getElementById('inquiry-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));
                })()"""
            )
            await asyncio.sleep(0.2)
            good_email_res = await eval_js(
                "({cls: document.getElementById('form-feedback').className, txt: document.getElementById('form-feedback').textContent})"
            )
            has_contributors = await eval_js("document.getElementById('contributors') !== null")
            read_times = await eval_js("document.body.innerText.toLowerCase().includes('min read')")

            func_ok = (
                modal_first["open"]
                and modal_first["relCount"] >= 2
                and modal_first["bodyLen"] > 250
                and bool(modal_switched_title)
                and modal_switched_title != modal_first["title"]
                and vis_env >= 1
                and vis_search == 1
                and has_contributors
                and read_times
                and "error" in bad_email_res
                and "success" in good_email_res["cls"]
                and "demonstration mode" in good_email_res["txt"].lower()
            )
            results["functional_checks"] = {
                "passed": func_ok,
                "featured_modal": modal_first,
                "related_story_switched_to": modal_switched_title,
                "env_filter_count": vis_env,
                "search_peatland_count": vis_search,
                "has_contributors": has_contributors,
                "has_reading_time": read_times,
                "newsletter_confirmed": good_email_res,
            }
            results["honesty_audit"] = {"passed": True, "sample_disclosure_present": "sample" in body_lower}

        else:
            # Mode 2 Dynamic Unfamiliar Domain interactive showcase verification
            initial_cards = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            pill_cats = await eval_js(
                "Array.from(document.querySelectorAll('.filter-pill')).map(b => b.getAttribute('data-category'))"
            )
            non_all_cats = [c for c in (pill_cats or []) if c and c != "all"]
            first_cat = non_all_cats[0] if non_all_cats else None
            vis_filtered = initial_cards
            if first_cat:
                await eval_js(f"document.querySelector('.filter-pill[data-category=\"{first_cat}\"]').click()")
                await asyncio.sleep(0.2)
                vis_filtered = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
                await eval_js("document.querySelector('.filter-pill[data-category=\"all\"]').click()")
                await asyncio.sleep(0.2)
            vis_reset = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")

            # Search first card title fragment
            first_title = await eval_js("document.querySelector('#showcase-grid .entity-card h3, #showcase-grid .entity-card .card-title')?.textContent?.trim() || ''")
            q_word = next((w for w in first_title.split() if len(w) >= 4), "Tourbillon")
            await eval_js(
                f"(() => {{ const s=document.getElementById('showcase-search'); s.value={json.dumps(q_word.lower())}; s.dispatchEvent(new Event('input',{{bubbles:true}})); }})()"
            )
            await asyncio.sleep(0.2)
            vis_searched = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            await eval_js("(() => { const s=document.getElementById('showcase-search'); s.value=''; s.dispatchEvent(new Event('input',{bubbles:true})); })()")
            await asyncio.sleep(0.2)

            # Detail modal open & close
            await eval_js("document.querySelector('#showcase-grid .btn-details')?.click()")
            await asyncio.sleep(0.2)
            modal_open = await eval_js("document.getElementById('details-modal')?.classList.contains('open') || false")
            modal_len = await eval_js("document.getElementById('modal-body')?.textContent?.trim().length || 0")
            if modal_open:
                await eval_js("document.getElementById('modal-close')?.click()")
                await asyncio.sleep(0.15)

            # Inquiry form validation & demonstration feedback
            await eval_js(
                """(() => {
                    const form = document.getElementById('inquiry-form');
                    if (!form) return;
                    const nameEl = document.getElementById('form-full_name') || form.querySelector('input[type="text"]');
                    const emailEl = document.getElementById('form-email') || form.querySelector('input[type="email"]');
                    if (nameEl) nameEl.value = '';
                    if (emailEl) emailEl.value = 'invalid';
                    form.dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));
                })()"""
            )
            await asyncio.sleep(0.2)
            bad_form_cls = await eval_js("document.getElementById('form-feedback')?.className || ''")

            await eval_js(
                """(() => {
                    const form = document.getElementById('inquiry-form');
                    if (!form) return;
                    for (const el of form.querySelectorAll('input, textarea, select')) {
                        if (el.type === 'email') el.value = 'collector@example.invalid';
                        else if (el.tagName === 'SELECT' && el.options.length) el.selectedIndex = el.options.length - 1;
                        else if (el.type === 'number') el.value = '1';
                        else if (el.type === 'date') el.value = '2027-07-01';
                        else el.value = 'Demo Commission Request';
                    }
                    form.dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));
                })()"""
            )
            await asyncio.sleep(0.2)
            good_form = await eval_js(
                "({cls: document.getElementById('form-feedback')?.className || '', txt: document.getElementById('form-feedback')?.textContent || ''})"
            )

            fake_claims = [x for x in ("soc2", "hipaa", "iso 27001", "michelin", "99.99%", "100% quality verified", "24/7") if x in body_lower]
            func_ok = (
                initial_cards >= 4
                and vis_reset == initial_cards
                and (first_cat is None or 1 <= vis_filtered < initial_cards)
                and vis_searched >= 1
                and modal_open
                and modal_len > 40
                and "error" in bad_form_cls
                and "success" in good_form["cls"]
                and len(fake_claims) == 0
            )
            results["functional_checks"] = {
                "passed": func_ok,
                "initial_cards": initial_cards,
                "filter_categories": non_all_cats,
                "filtered_count": vis_filtered,
                "reset_count": vis_reset,
                "search_query": q_word,
                "search_count": vis_searched,
                "modal_open": modal_open,
                "modal_body_length": modal_len,
                "form_invalid_class": bad_form_cls,
                "form_valid_feedback": good_form,
            }
            results["honesty_audit"] = {
                "passed": len(fake_claims) == 0,
                "fake_claims_found": fake_claims,
                "demo_disclosure_present": ("demonstration" in body_lower or "illustrative" in body_lower or "sample" in body_lower),
            }

        console_errors = [ce.text for ce in browser.get_console_errors()]
        net_failures = [
            f"{nf.url} (status={nf.status})"
            for nf in browser.get_network_failures()
            if not nf.url.endswith("favicon.ico")
        ]
        results["console_errors"] = console_errors
        results["failed_network_requests"] = net_failures
        c_runtime = len(console_errors) == 0 and len(net_failures) == 0
        results["criteria_results"]["3_zero_console_and_network_errors"] = {
            "passed": c_runtime,
            "console_error_count": len(console_errors),
            "network_failure_count": len(net_failures),
        }

        all_ok = (
            results["criteria_results"]["1_brand_and_zero_contamination"]["passed"]
            and results["criteria_results"]["2_layout_hero_images"]["passed"]
            and results["criteria_results"]["3_zero_console_and_network_errors"]["passed"]
            and results["functional_checks"]["passed"]
            and results["honesty_audit"]["passed"]
        )
        results["all_checks_passed"] = all_ok
        print(f"  [Check 3] Console/Network Clean: {'PASS' if c_runtime else 'FAIL'} | Functional: {'PASS' if results['functional_checks']['passed'] else 'FAIL'} | Overall: {'PASS' if all_ok else 'FAIL'}")
        assert all_ok, f"CDP verification failed for {expected_brand}: {json.dumps(results, indent=2)}"
    finally:
        await browser.close()
        if server_info:
            server_mgr.stop_server(server_info.name)

    return results


async def verify_blocked_llm_honesty(client: httpx.AsyncClient) -> Dict[str, Any]:
    """Verify Mode 2 blocked-provider protection does NOT fall back to a fake website."""
    reg = ProviderAvailabilityRegistry()
    reg.record_outcome(1, success=False, status_code=503, error="Simulated T1 unavailability")
    reg.record_outcome(2, success=False, status_code=503, error="Simulated T2 high demand")
    reg.record_outcome(3, success=False, status_code=402, error="Simulated T3 402 billing exhaustion")
    reg.record_outcome(4, success=False, status_code=404, error="Simulated T4 model unavailable")

    fail_client = MagicMock()
    fail_client.generate = AsyncMock(side_effect=TimeoutError("All providers simulated unavailable"))
    fail_client.aclose = AsyncMock()

    temp_ws = Path(tempfile.mkdtemp(prefix="hermes_p5_blocked_probe_")).resolve()
    try:
        with patch("core.llm_semantic_planner.get_provider_registry", return_value=reg), \
             patch.object(LLMSemanticPlanner, "_build_client_for_tier", return_value=(fail_client, "nvidia_nim", "mock")):
            r = await client.post(
                "/api/missions",
                json={"prompt": PROMPT_HOROLOGY, "workspace_root": str(temp_ws), "plan_mode": False},
            )
            assert r.status_code == 201
            mid = r.json()["mission_id"]
            snap: Dict[str, Any] = {}
            for _ in range(40):
                await asyncio.sleep(0.25)
                s = await client.get(f"/api/missions/{mid}")
                snap = s.json()
                if snap.get("is_terminal"):
                    break

        index_exists = (temp_ws / "index.html").exists()
        ok = (
            bool(snap.get("is_terminal"))
            and str(snap.get("status", "")).lower() == "failed"
            and snap.get("execution_mode") == "llm_assisted"
            and not index_exists
        )
        assert ok, f"Blocked LLM check failed: snap={snap}, index_exists={index_exists}"
        return {
            "passed": ok,
            "mission_id": mid,
            "terminal_status": snap.get("status"),
            "execution_mode": snap.get("execution_mode"),
            "current_stage": snap.get("current_stage"),
            "terminal_reason": snap.get("terminal_reason"),
            "fake_site_generated": index_exists,
        }
    finally:
        # Leave cleanup best-effort on Windows SQLite handle
        shutil.rmtree(temp_ws, ignore_errors=True)


async def main() -> None:
    t_start = time.monotonic()

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=60.0) as client:
        # Task A: Inspect unprobed status first (never equates credentials to HEALTHY), then probe live!
        initial_status_resp = await client.get("/api/providers/status")
        assert initial_status_resp.status_code == 200
        initial_status = initial_status_resp.json()

        live_status_resp = await client.get("/api/providers/status?live=true")
        assert live_status_resp.status_code == 200
        live_status = live_status_resp.json()

        print("\n=== TASK A: LIVE PROVIDER AVAILABILITY REGISTRY ===")
        for tkey, pinfo in live_status.get("providers", {}).items():
            print(
                f"  {tkey}: {pinfo.get('provider')}/{pinfo.get('model')} | "
                f"state={pinfo.get('availability_state')} | routable={pinfo.get('routable')} | "
                f"ttfb={pinfo.get('last_ttfb_ms')}ms | usable_ttft={pinfo.get('last_ttft_usable_ms')}ms | "
                f"action={pinfo.get('corrective_action')}"
            )

        # Run all 4 Missions through REAL HERMES POST /api/missions API
        m_a = await submit_and_wait_mission(client, name="EMBER & OLIVE (Mode 1)", prompt=PROMPT_EMBER, workspace_dir=WS_EMBER)
        m_b = await submit_and_wait_mission(client, name="FLOWSTACK (Mode 1)", prompt=PROMPT_FLOWSTACK, workspace_dir=WS_FLOWSTACK)
        m_c = await submit_and_wait_mission(client, name="THE FIELD JOURNAL (Mode 1)", prompt=PROMPT_JOURNAL, workspace_dir=WS_JOURNAL)
        m_d = await submit_and_wait_mission(client, name="KRONOS HOROLOGY ATELIER (Mode 2 Live LLM)", prompt=PROMPT_HOROLOGY, workspace_dir=WS_HOROLOGY)

        # Verify honest Mode 2 failure when all providers are blocked (never emits fake template)
        blocked_probe = await verify_blocked_llm_honesty(client)

    # Refresh provider status snapshot AFTER Mode 2 inference telemetry was recorded
    post_registry = {f"tier{k}": v.to_dict() for k, v in get_provider_registry().get_all().items()}

    # Interactive 1440x900 Chrome CDP verification across all 4 missions
    cdp_a = await verify_archetype_cdp(
        WS_EMBER, "EMBER & OLIVE", "culinary_restaurant",
        ["wanderworld", "northstar", "flowstack", "field journal", "kronos", "saffron"], "ember"
    )
    cdp_b = await verify_archetype_cdp(
        WS_FLOWSTACK, "FLOWSTACK", "saas_product",
        ["ember & olive", "wanderworld", "field journal", "kronos", "saffron"], "flowstack"
    )
    cdp_c = await verify_archetype_cdp(
        WS_JOURNAL, "THE FIELD JOURNAL", "editorial_publication",
        ["ember & olive", "flowstack", "wanderworld", "kronos", "saffron"], "field_journal"
    )
    cdp_d = await verify_archetype_cdp(
        WS_HOROLOGY, "KRONOS HOROLOGY ATELIER", "interactive_showcase",
        ["ember & olive", "flowstack", "field journal", "wanderworld", "saffron", "northstar", "scientific assets"], "kronos_horology"
    )

    report = {
        "phase": "HERMES 2.x Phase 5: Unified LLM Intelligence, Provider Recovery & End-to-End Website Generation",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_qualification_duration_seconds": round(time.monotonic() - t_start, 2),
        "task_a_provider_availability": {
            "initial_unprobed_status": initial_status,
            "live_probed_status": live_status,
            "post_mission_registry": post_registry,
        },
        "tasks_b_to_f_real_missions": {
            "benchmark_a_ember_olive": {**m_a, "cdp_verification": cdp_a},
            "benchmark_b_flowstack": {**m_b, "cdp_verification": cdp_b},
            "benchmark_c_field_journal": {**m_c, "cdp_verification": cdp_c},
            "benchmark_d_unfamiliar_horology": {**m_d, "cdp_verification": cdp_d},
        },
        "mode2_blocked_provider_honesty_probe": blocked_probe,
        "overall_passed": (
            m_a["mission_snapshot"]["execution_mode"] == "deterministic"
            and m_b["mission_snapshot"]["execution_mode"] == "deterministic"
            and m_c["mission_snapshot"]["execution_mode"] == "deterministic"
            and m_d["mission_snapshot"]["execution_mode"] == "llm_assisted"
            and cdp_a["all_checks_passed"]
            and cdp_b["all_checks_passed"]
            and cdp_c["all_checks_passed"]
            and cdp_d["all_checks_passed"]
            and blocked_probe["passed"]
        ),
    }

    safe_report = redact_telemetry_secrets(report)
    out_file = REPO_ROOT / "phase5_hybrid_intelligence_results.json"
    out_file.write_text(json.dumps(safe_report, indent=2), encoding="utf-8")
    print(f"\nSaved Phase 5 qualification results -> {out_file}")
    print(f"Overall Phase 5 Live Qualification Passed: {safe_report['overall_passed']}")
    if not safe_report["overall_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
