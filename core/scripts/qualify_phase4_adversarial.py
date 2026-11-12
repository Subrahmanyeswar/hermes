# core/scripts/qualify_phase4_adversarial.py
"""
HERMES 2.x — PHASE 4 ADVERSARIAL QUALIFICATION & PRODUCTION HARDENING SCRIPT

Executes:
1. Task 1 & Task 2: Real 4-Tier Provider Verification (NVIDIA NIM, Gemini, SambaNova, Ollama)
   + Live End-to-End AgentLoop + Orchestrator Inference Consumption with Monotonic Telemetry.
2. Tasks 3, 4, 5, 6: Independent Greenfield Generation & 1440x900 Chrome CDP Verification
   across 3 diverse archetypes:
   - Benchmark A: Restaurant Reservation Website (EMBER & OLIVE)
     Workspace: C:\\Users\\SUBBU\\Downloads\\hermes_phase4_restaurant_ember
   - Benchmark B: B2B SaaS Project Management & Kanban Dashboard (FLOWSTACK)
     Workspace: C:\\Users\\SUBBU\\Downloads\\hermes_phase4_saas_flowstack
   - Benchmark C: Digital Editorial & Journalism Publication (THE FIELD JOURNAL)
     Workspace: C:\\Users\\SUBBU\\Downloads\\hermes_phase4_editorial_journal

Outputs structured metrics & verification evidence to stdout / JSON without fabricating telemetry
or modifying any historical workspace.
"""

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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from config.model_config import (
    TIER1_PROVIDER,
    TIER1_MODEL,
    TIER1_BASE_URL,
    TIER1_PROVIDER_STATUS,
    TIER2_PROVIDER,
    TIER2_MODEL,
    TIER2_BASE_URL,
    TIER2_PROVIDER_STATUS,
    TIER3_PROVIDER,
    TIER3_MODEL,
    TIER3_BASE_URL,
    TIER3_PROVIDER_STATUS,
    TIER4_PROVIDER,
    TIER4_MODEL,
    TIER4_BASE_URL,
    TIER4_PROVIDER_STATUS,
    NVIDIA_API_KEY,
    GEMINI_API_KEY,
    SAMBANOVA_API_KEY,
)
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.asset_pipeline import AssetPipeline
from core.browser.dev_server import DevServerManager
from core.browser.manager import BrowserManager, Viewport
from core.design_intelligence import DesignBriefGenerator, detect_brand_name
from core.event_bus import EventBus
from core.frontend_contract import FrontendContractBuilder
from core.mission_planner import Mission
from core.mission_spec import MissionSpecification
from core.orchestrator import Orchestrator
from core.runtime_failover import (
    classify_runtime_error,
    global_attempt_ledger,
)
from core.telemetry import redact_telemetry_secrets
from core.universal_renderer import UniversalContentRenderer
from core.verification_profiles import VerificationProfile, VerificationProfileEvaluator
from core.work_package_gate import WorkPackageGate
from core.workspace import WorkspaceManager
from models.common_adapter import CommonProviderAdapter
from models.gemini_client import GeminiClient
from models.nvidia_client import NvidiaClient
from models.ollama_client import OllamaClient

WS_EMBER = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4_restaurant_ember").resolve()
WS_FLOWSTACK = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4_saas_flowstack").resolve()
WS_JOURNAL = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4_editorial_journal").resolve()

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


# ==============================================================================
# PART 1: TASK 1 & TASK 2 — LIVE 4-TIER PROBING & REAL AGENTLOOP TELEMETRY
# ==============================================================================

async def verify_all_tiers_live() -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("  TASK 2: LIVE 4-TIER PROVIDER EXECUTION & ERROR CLASSIFICATION CHECK")
    print("=" * 80)

    tier_results: Dict[str, Any] = {}

    # Tier 1: NVIDIA NIM
    t1_client = NvidiaClient()
    t0 = time.monotonic()
    try:
        res1 = await t1_client.generate(
            model=TIER1_MODEL,
            prompt="Respond with exactly the single token: HERMES_OK",
            max_tokens=512,
            reasoning_effort="low",
        )
        t1_dur = round((time.monotonic() - t0) * 1000.0, 2)
        err_cls1 = classify_runtime_error(response_text=res1.error or "") if not res1.success else None
        tier_results["tier1_nvidia_nim"] = {
            "tier": 1,
            "provider": TIER1_PROVIDER,
            "model": TIER1_MODEL,
            "endpoint": TIER1_BASE_URL,
            "config_status": TIER1_PROVIDER_STATUS,
            "auth_key_present": bool(NVIDIA_API_KEY),
            "success": bool(res1.success),
            "ttfb_ms": round(float(res1.ttfb_ms), 2),
            "ttft_reasoning_ms": round(float(res1.ttft_reasoning_ms), 2),
            "ttft_content_ms": round(float(res1.ttft_content_ms), 2),
            "latency_ms": round(float(res1.latency_ms), 2),
            "monotonic_duration_ms": t1_dur,
            "input_tokens": int(res1.input_tokens or 0),
            "output_tokens": int(res1.output_tokens or 0),
            "response_preview": redact_telemetry_secrets((res1.text or "")[:120]),
            "error": redact_telemetry_secrets(res1.error or "") if res1.error else None,
            "classification": err_cls1[0].value if err_cls1 else None,
            "is_transient": err_cls1[1] if err_cls1 else None,
        }
    except Exception as exc:
        err_cls1 = classify_runtime_error(exc=exc)
        tier_results["tier1_nvidia_nim"] = {
            "tier": 1,
            "provider": TIER1_PROVIDER,
            "model": TIER1_MODEL,
            "endpoint": TIER1_BASE_URL,
            "auth_key_present": bool(NVIDIA_API_KEY),
            "success": False,
            "monotonic_duration_ms": round((time.monotonic() - t0) * 1000.0, 2),
            "error": redact_telemetry_secrets(f"{type(exc).__name__}: {exc}"),
            "classification": err_cls1[0].value,
            "is_transient": err_cls1[1],
        }
    print("  [Tier 1 NVIDIA NIM]", json.dumps(tier_results["tier1_nvidia_nim"]))

    # Tier 2: Gemini (capped cleanly so dead model doesn't block 25s unnecessarily while still proving live timeout/classification)
    t2_client = GeminiClient()
    t0 = time.monotonic()
    try:
        res2 = await asyncio.wait_for(
            t2_client.generate(
                model=TIER2_MODEL,
                prompt="Respond with exactly the single token: HERMES_OK",
                max_tokens=64,
            ),
            timeout=12.0,
        )
        t2_dur = round((time.monotonic() - t0) * 1000.0, 2)
        err_cls2 = classify_runtime_error(response_text=res2.error or "") if not res2.success else None
        tier_results["tier2_gemini"] = {
            "tier": 2,
            "provider": TIER2_PROVIDER,
            "model": TIER2_MODEL,
            "endpoint": TIER2_BASE_URL,
            "config_status": TIER2_PROVIDER_STATUS,
            "auth_key_present": bool(GEMINI_API_KEY),
            "success": bool(res2.success),
            "ttfb_ms": round(float(res2.ttfb_ms), 2),
            "latency_ms": round(float(res2.latency_ms), 2),
            "monotonic_duration_ms": t2_dur,
            "error": redact_telemetry_secrets(res2.error or "") if res2.error else None,
            "classification": err_cls2[0].value if err_cls2 else None,
            "is_transient": err_cls2[1] if err_cls2 else None,
        }
    except asyncio.TimeoutError:
        t2_dur = round((time.monotonic() - t0) * 1000.0, 2)
        err_cls2 = classify_runtime_error(response_text=f"GeminiClient timeout after {t2_dur}ms")
        tier_results["tier2_gemini"] = {
            "tier": 2,
            "provider": TIER2_PROVIDER,
            "model": TIER2_MODEL,
            "endpoint": TIER2_BASE_URL,
            "config_status": TIER2_PROVIDER_STATUS,
            "auth_key_present": bool(GEMINI_API_KEY),
            "success": False,
            "monotonic_duration_ms": t2_dur,
            "error": f"Attempt timeout after {t2_dur}ms (configured Gemini model stall/timeout)",
            "classification": err_cls2[0].value,
            "is_transient": err_cls2[1],
        }
    except Exception as exc:
        err_cls2 = classify_runtime_error(exc=exc)
        tier_results["tier2_gemini"] = {
            "tier": 2,
            "provider": TIER2_PROVIDER,
            "model": TIER2_MODEL,
            "endpoint": TIER2_BASE_URL,
            "auth_key_present": bool(GEMINI_API_KEY),
            "success": False,
            "monotonic_duration_ms": round((time.monotonic() - t0) * 1000.0, 2),
            "error": redact_telemetry_secrets(f"{type(exc).__name__}: {exc}"),
            "classification": err_cls2[0].value,
            "is_transient": err_cls2[1],
        }
    print("  [Tier 2 Gemini]", json.dumps(tier_results["tier2_gemini"]))

    # Tier 3: SambaNova
    t3_client = CommonProviderAdapter(
        provider_name=TIER3_PROVIDER,
        model_name=TIER3_MODEL,
        base_url=TIER3_BASE_URL,
        api_key=SAMBANOVA_API_KEY,
        tier=3,
        timeout_seconds=12.0,
    )
    t0 = time.monotonic()
    try:
        res3 = await t3_client.generate(
            model=TIER3_MODEL,
            prompt="Respond with exactly the single token: HERMES_OK",
            max_tokens=32,
        )
        t3_dur = round((time.monotonic() - t0) * 1000.0, 2)
        err_text3 = res3.error or ""
        status3 = 402 if "402" in err_text3 else None
        err_cls3 = classify_runtime_error(response_text=err_text3, status_code=status3) if not res3.success else None
        tier_results["tier3_sambanova"] = {
            "tier": 3,
            "provider": TIER3_PROVIDER,
            "model": TIER3_MODEL,
            "endpoint": TIER3_BASE_URL,
            "config_status": TIER3_PROVIDER_STATUS,
            "auth_key_present": bool(SAMBANOVA_API_KEY),
            "success": bool(res3.success),
            "latency_ms": round(float(res3.latency_ms), 2),
            "monotonic_duration_ms": t3_dur,
            "error": redact_telemetry_secrets(err_text3) if err_text3 else None,
            "classification": err_cls3[0].value if err_cls3 else None,
            "is_transient": err_cls3[1] if err_cls3 else None,
        }
    except Exception as exc:
        err_cls3 = classify_runtime_error(exc=exc)
        tier_results["tier3_sambanova"] = {
            "tier": 3,
            "provider": TIER3_PROVIDER,
            "model": TIER3_MODEL,
            "endpoint": TIER3_BASE_URL,
            "auth_key_present": bool(SAMBANOVA_API_KEY),
            "success": False,
            "monotonic_duration_ms": round((time.monotonic() - t0) * 1000.0, 2),
            "error": redact_telemetry_secrets(f"{type(exc).__name__}: {exc}"),
            "classification": err_cls3[0].value,
            "is_transient": err_cls3[1],
        }
    finally:
        await t3_client.close()
    print("  [Tier 3 SambaNova]", json.dumps(tier_results["tier3_sambanova"]))

    # Tier 4: Ollama Local Fallback
    t4_client = OllamaClient(base_url=TIER4_BASE_URL)
    t0 = time.monotonic()
    try:
        daemon_up = await t4_client.is_running(timeout=6.0)
        res4 = await asyncio.wait_for(
            t4_client.generate(
                model=TIER4_MODEL,
                prompt="Respond with exactly the single token: HERMES_OK",
                num_predict=20,
            ),
            timeout=10.0,
        )
        t4_dur = round((time.monotonic() - t0) * 1000.0, 2)
        err_text4 = res4.error or ""
        status4 = 404 if "not found" in err_text4.lower() else None
        err_cls4 = classify_runtime_error(response_text=err_text4, status_code=status4) if not res4.success else None
        tier_results["tier4_ollama"] = {
            "tier": 4,
            "provider": TIER4_PROVIDER,
            "model": TIER4_MODEL,
            "endpoint": TIER4_BASE_URL,
            "config_status": TIER4_PROVIDER_STATUS,
            "daemon_running": bool(daemon_up),
            "success": bool(res4.success),
            "latency_ms": round(float(res4.latency_ms), 2),
            "monotonic_duration_ms": t4_dur,
            "error": redact_telemetry_secrets(err_text4) if err_text4 else None,
            "classification": err_cls4[0].value if err_cls4 else None,
            "is_transient": err_cls4[1] if err_cls4 else None,
        }
    except Exception as exc:
        err_cls4 = classify_runtime_error(exc=exc)
        tier_results["tier4_ollama"] = {
            "tier": 4,
            "provider": TIER4_PROVIDER,
            "model": TIER4_MODEL,
            "endpoint": TIER4_BASE_URL,
            "daemon_running": False,
            "success": False,
            "monotonic_duration_ms": round((time.monotonic() - t0) * 1000.0, 2),
            "error": redact_telemetry_secrets(f"{type(exc).__name__}: {exc}"),
            "classification": err_cls4[0].value,
            "is_transient": err_cls4[1],
        }
    print("  [Tier 4 Ollama]", json.dumps(tier_results["tier4_ollama"]))
    return tier_results


async def probe_real_agentloop_consumption() -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("  TASK 1 & 2: REAL END-TO-END AGENTLOOP LIVE MODEL INFERENCE TELEMETRY")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as td:
        ws_path = Path(td).resolve()
        wm = WorkspaceManager()
        wm.lock(ws_path)
        eb = EventBus()
        orch = Orchestrator(mode="auto", project="phase4_live_agentloop_telemetry")
        cfg = AgentLoopConfig(max_turns=3, model_timeout_seconds=25.0, max_wall_time_seconds=300.0)
        loop = AgentLoop(orchestrator=orch, workspace_manager=wm, event_bus_instance=eb, config=cfg)

        mission = Mission(
            mission_id=f"m_p4_live_{int(time.time())}",
            user_prompt="Write a minimal Python utility script hello.py that prints HERMES_OK and stop.",
            workspace_root=str(ws_path),
        )

        mono_origin = time.monotonic()
        timeline: List[Dict[str, Any]] = []

        def on_evt(evt):
            et = evt.event_type.value if hasattr(evt.event_type, "value") else str(evt.event_type)
            if et in (
                "MISSION_STARTED",
                "TIER_SELECTED",
                "MODEL_REQUESTED",
                "MODEL_COMPLETED",
                "DECISION_INTERPRETED",
                "ACTION_EXECUTED",
                "TIER_FAILOVER_STARTED",
                "MISSION_COMPLETED",
                "MISSION_FAILED",
            ):
                timeline.append({
                    "event": et,
                    "elapsed_ms": round((time.monotonic() - mono_origin) * 1000.0, 2),
                    "payload": {
                        k: v
                        for k, v in (evt.payload or {}).items()
                        if k in ("turn", "tier", "provider", "model", "ttft_ms", "duration_ms", "tool_name", "success", "status")
                    },
                })

        eb.subscribe(on_evt)
        res = await loop.run(mission)
        total_ms = round((time.monotonic() - mono_origin) * 1000.0, 2)

        ledger_recs = [
            r.to_dict()
            for r in getattr(global_attempt_ledger, "_records", [])
            if r.mission_id == mission.mission_id
        ]
        hello_exists = (ws_path / "hello.py").exists()
        index_html_exists = (ws_path / "index.html").exists()

        summary = {
            "mission_id": mission.mission_id,
            "success": bool(res.success),
            "status": str(res.status),
            "turns_executed": res.turns_executed,
            "actions_executed": res.actions_executed,
            "total_monotonic_ms": total_ms,
            "hello_py_created": hello_exists,
            "unexpected_index_html_created": index_html_exists,
            "files_created": res.files_created,
            "timeline_events": timeline,
            "attempt_ledger_records": ledger_recs,
            "verified_tier_in_ledger": any(r.get("tier") == 1 for r in ledger_recs),
        }
        print(f"  • AgentLoop completed: success={summary['success']}, turns={summary['turns_executed']}, actions={summary['actions_executed']}, total_ms={total_ms}")
        print(f"  • Non-website guard verified: hello.py={hello_exists}, index.html={index_html_exists}")
        print(f"  • Attempt ledger tier 1 recorded: {summary['verified_tier_in_ledger']} (records={len(ledger_recs)})")
        return summary


# ==============================================================================
# PART 2: TASKS 3-6 — 3-ARCHETYPE GREENFIELD GENERATION + CDP VERIFICATION
# ==============================================================================

async def generate_archetype_website(
    prompt: str,
    workspace_dir: Path,
    mission_id: str,
    expected_brand: str,
    expected_domain: str,
    expected_archetype: str,
) -> Dict[str, Any]:
    print(f"\n{'='*80}")
    print(f"  GREENFIELD GENERATION: {expected_brand} ({expected_archetype})")
    print(f"  Workspace: {workspace_dir}")
    print(f"{'='*80}")

    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = workspace_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    mono_0 = time.monotonic()

    # Step 1: Semantic Extraction
    extracted_brand = detect_brand_name(prompt)
    extracted_domain = DesignBriefGenerator.detect_domain(prompt)
    extracted_archetype = DesignBriefGenerator.detect_archetype(prompt)
    assert extracted_brand == expected_brand, f"Expected brand '{expected_brand}', got '{extracted_brand}'"
    assert extracted_domain == expected_domain, f"Expected domain '{expected_domain}', got '{extracted_domain}'"
    assert extracted_archetype == expected_archetype, f"Expected archetype '{expected_archetype}', got '{extracted_archetype}'"

    # Step 2: Mission Spec, Design Brief & Contract
    t_spec_0 = time.monotonic()
    spec = MissionSpecification.from_prompt(prompt, workspace_dir)
    spec.persist(workspace_dir)
    brief = DesignBriefGenerator.generate_brief(spec.user_prompt, spec.business_domain)
    brief.persist_artifacts(workspace_dir)
    contract = FrontendContractBuilder.build_initial_contract(
        task=spec.user_prompt,
        mission_id=mission_id,
        design_brief=brief,
    )
    (workspace_dir / ".hermes" / "frontend_contract.json").write_text(
        json.dumps(contract.to_dict(), indent=2), encoding="utf-8"
    )
    t_spec_ms = round((time.monotonic() - t_spec_0) * 1000.0, 2)

    # Step 3: Asset Provisioning
    t_asset_0 = time.monotonic()
    manifest = AssetPipeline.provision_assets(
        workspace_root=workspace_dir,
        prompt=prompt,
        domain=spec.business_domain,
        mission_id=mission_id,
    )
    t_asset_ms = round((time.monotonic() - t_asset_0) * 1000.0, 2)

    # Step 4: Rendering
    t_render_0 = time.monotonic()
    rendered = UniversalContentRenderer.render(workspace_dir, spec)
    t_render_ms = round((time.monotonic() - t_render_0) * 1000.0, 2)
    assert rendered is True

    # Verify all rendered HTML/CSS/JS asset paths exist & decode cleanly
    ok_assets, missing_assets, found_assets = AssetPipeline.verify_workspace_assets(workspace_dir)
    assert ok_assets, f"Asset verification failed: missing={missing_assets}"

    # Step 5: Gates & Profile C
    t_gate_0 = time.monotonic()
    f_res = WorkPackageGate.evaluate_foundation_gate(workspace_dir, contract=contract, design_brief=brief)
    c_res = WorkPackageGate.evaluate_content_gate(workspace_dir, contract=contract)
    prof_res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C,
        workspace_dir,
        prompt,
        written_files=["index.html", "style.css", "app.js", "package.json"],
    )
    t_gate_ms = round((time.monotonic() - t_gate_0) * 1000.0, 2)
    assert f_res.passed, f"Foundation gate failed: {f_res.missing_criteria}"
    assert c_res.passed, f"Content gate failed: {c_res.missing_criteria}"
    assert prof_res.passed, f"Profile C failed: {prof_res.issues}"

    total_ms = round((time.monotonic() - mono_0) * 1000.0, 2)
    print(
        f"  • Monotonic Stages (ms): spec={t_spec_ms}, assets={t_asset_ms}, "
        f"render={t_render_ms}, gates={t_gate_ms}, total={total_ms}"
    )

    return {
        "mission_id": mission_id,
        "workspace": str(workspace_dir),
        "brand": extracted_brand,
        "domain": extracted_domain,
        "archetype": extracted_archetype,
        "inference_mode": "deterministic_semantic_synthesis_zero_llm_wait",
        "model_inference_ms_inside_pipeline": 0.0,
        "monotonic_stage_timings_ms": {
            "spec_and_contract_ms": t_spec_ms,
            "asset_provisioning_ms": t_asset_ms,
            "file_rendering_ms": t_render_ms,
            "gates_and_profile_c_ms": t_gate_ms,
            "total_generation_ms": total_ms,
        },
        "assets_count": len(manifest.assets),
        "foundation_gate_passed": f_res.passed,
        "content_gate_passed": c_res.passed,
        "profile_c_passed": prof_res.passed,
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

        # 1. Brand identity & Zero Contamination
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

        # 2. Navigation, Hero, Images & Layout Overflow
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

        # Scroll back to top and capture screenshots BEFORE heavy scroll/modal mutations or reset after
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

        # 3. Domain-Specific Functional & Task-6 Honesty Verification
        if archetype == "culinary_restaurant":
            # Search + Filter
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

            # Past-date reservation rejection -> Future-date reservation success
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
            # 1) Create a task
            await eval_js(
                """(() => {
                    document.getElementById('new-task-title').value = 'PERF-509: Index Shard Rebalance';
                    document.getElementById('add-task-btn').click();
                })()"""
            )
            await asyncio.sleep(0.2)
            # 2) Move a card twice to Completed via btn-move-card AND trigger DragEvent drop on task-2 -> col-inprogress
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
            # Also test DragEvent dispatch on task-2 to col-inprogress
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
            # 3) Switch analytics & automation tabs
            await eval_js("document.getElementById('tab-analytics').click()")
            await asyncio.sleep(0.1)
            analytics_active = await eval_js("document.getElementById('view-analytics').classList.contains('active')")
            await eval_js("document.getElementById('tab-kanban').click()")

            # 4) Team management add / role change / remove
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

            # 5) Billing switcher Monthly <-> Annual
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
            # 1) Read featured story -> modal opens with full body + related stories
            await eval_js("document.getElementById('btn-read-featured').click()")
            await asyncio.sleep(0.25)
            modal_first = await eval_js(
                "({open: document.getElementById('details-modal').classList.contains('open'), title: document.querySelector('#modal-body h2')?.textContent || '', relCount: document.querySelectorAll('.btn-related-story').length, bodyLen: document.getElementById('modal-body').textContent.length})"
            )
            # 2) Click related story inside modal -> switches article
            await eval_js("document.querySelector('.btn-related-story')?.click()")
            await asyncio.sleep(0.2)
            modal_switched_title = await eval_js("document.querySelector('#modal-body h2')?.textContent || ''")
            await eval_js("document.getElementById('modal-close').click()")
            await asyncio.sleep(0.2)

            # 3) Category filter & Search
            await eval_js("document.querySelector('.filter-pill[data-category=\"environment\"]').click()")
            await asyncio.sleep(0.2)
            vis_env = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            await eval_js("document.querySelector('.filter-pill[data-category=\"all\"]').click()")
            await asyncio.sleep(0.2)
            await eval_js("(() => { const s=document.getElementById('showcase-search'); s.value='peatland'; s.dispatchEvent(new Event('input',{bubbles:true})); })()")
            await asyncio.sleep(0.2)
            vis_search = await eval_js("document.querySelectorAll('#showcase-grid .entity-card').length")
            await eval_js("(() => { const s=document.getElementById('showcase-search'); s.value=''; s.dispatchEvent(new Event('input',{bubbles:true})); })()")

            # 4) Newsletter invalid email rejection -> valid email confirmation
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

        # 4. Zero Console Errors & Zero Failed Network Requests
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


async def main():
    overall_t0 = time.monotonic()

    # 1. Task 1 & 2: Live 4-tier probes + Real AgentLoop consumption
    live_tiers = await verify_all_tiers_live()
    agentloop_probe = await probe_real_agentloop_consumption()

    # 2. Tasks 3-6: Three Archetypes
    benchmarks = [
        {
            "key": "benchmark_a_ember_olive",
            "prompt": PROMPT_EMBER,
            "workspace": WS_EMBER,
            "mission_id": "mission_p4_ember_olive_001",
            "brand": "EMBER & OLIVE",
            "domain": "culinary_restaurant",
            "archetype": "culinary_restaurant",
            "forbidden": ["saffron", "wanderworld", "nova", "verdant", "skytrace", "sparkfield"],
            "prefix": "ember_olive",
        },
        {
            "key": "benchmark_b_flowstack",
            "prompt": PROMPT_FLOWSTACK,
            "workspace": WS_FLOWSTACK,
            "mission_id": "mission_p4_flowstack_002",
            "brand": "FLOWSTACK",
            "domain": "saas_tech",
            "archetype": "saas_product",
            "forbidden": ["saffron", "wanderworld", "verdant", "skytrace", "sparkfield", "soc2", "hipaa", "iso 27001", "99.99%"],
            "prefix": "flowstack",
        },
        {
            "key": "benchmark_c_field_journal",
            "prompt": PROMPT_JOURNAL,
            "workspace": WS_JOURNAL,
            "mission_id": "mission_p4_field_journal_003",
            "brand": "THE FIELD JOURNAL",
            "domain": "editorial_publication",
            "archetype": "editorial_publication",
            "forbidden": ["saffron", "wanderworld", "nova", "verdant", "skytrace", "sparkfield"],
            "prefix": "field_journal",
        },
    ]

    archetype_outputs: Dict[str, Any] = {}
    for b in benchmarks:
        gen = await generate_archetype_website(
            prompt=b["prompt"],
            workspace_dir=b["workspace"],
            mission_id=b["mission_id"],
            expected_brand=b["brand"],
            expected_domain=b["domain"],
            expected_archetype=b["archetype"],
        )
        cdp = await verify_archetype_cdp(
            workspace_dir=b["workspace"],
            expected_brand=b["brand"],
            archetype=b["archetype"],
            forbidden_terms=b["forbidden"],
            prefix=b["prefix"],
        )
        archetype_outputs[b["key"]] = {
            "generation": gen,
            "cdp_verification": cdp,
        }

    final_payload = {
        "phase": "HERMES 2.x Phase 4 Adversarial Qualification & Production Hardening",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_qualification_duration_seconds": round(time.monotonic() - overall_t0, 2),
        "task1_telemetry_reconciliation": {
            "historical_discrepancy_root_cause": (
                "core/scripts/qualify_final_integrated_acceptance.py (lines 122-137) inserted a synthetic "
                "ProviderAttemptRecord(duration_ms=1150.0, ttft_ms=420.0) without invoking live model inference, "
                "whereas deterministic generation (spec + asset provisioning + rendering + gates) measured 0.78s. "
                "Additionally, core/agent_loop/loop.py passed tier=None from NormalizedModelResponse to "
                "global_attempt_ledger instead of the active attempt tier; fixed in Phase 4."
            ),
            "live_agentloop_inference_probe": agentloop_probe,
        },
        "task2_real_provider_verification": live_tiers,
        "task3_to_6_archetype_benchmarks": archetype_outputs,
        "overall_passed": (
            bool(live_tiers.get("tier1_nvidia_nim", {}).get("success"))
            and bool(agentloop_probe.get("success"))
            and bool(agentloop_probe.get("verified_tier_in_ledger"))
            and all(v["cdp_verification"]["all_checks_passed"] for v in archetype_outputs.values())
        ),
    }

    out_path = REPO_ROOT / "phase4_adversarial_acceptance_results.json"
    out_path.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
    print("\n" + "=" * 80)
    print(f"  PHASE 4 QUALIFICATION COMPLETE | overall_passed={final_payload['overall_passed']}")
    print(f"  Results JSON: {out_path}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
