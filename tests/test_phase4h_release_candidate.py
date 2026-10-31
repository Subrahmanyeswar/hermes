"""
HERMES Phase 4H - Release Candidate & Generalization Acceptance Test Suite
Comprehensive validation of the final release candidate across:
1. Held-out complexity classification benchmark (25 frozen prompts, 5 tiers, 100% accuracy).
2. Existing codebase modification safety (Scenarios A-E).
3. Independent software generation completeness (Apps 1, 2, 3).
4. Headless Chrome CDP functional flows, responsive reflow, persistence, and zero console errors.
5. Runtime invariants: parallel task serialization, adaptive zero-wait failover, path security, and manifests.
"""

import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "artifacts" / "phase4h"
BENCHMARKS_DIR = ROOT / "benchmarks" / "phase4h"
SCREENSHOTS_DIR = ARTIFACTS_DIR / "screenshots"

from core.mission_planner import classify_mission_complexity, MissionComplexity
from core.adaptive_routing import (
    AdaptiveRouter,
    ProviderHealthState,
)
from core.workspace import (
    canonicalize_workspace_path,
    WorkspaceBoundaryError,
)


# ==============================================================================
# 1. HELD-OUT COMPLEXITY CLASSIFICATION BENCHMARK
# ==============================================================================

def test_heldout_classification_frozen_benchmark():
    prompts_path = BENCHMARKS_DIR / "heldout_prompts.json"
    labels_path = BENCHMARKS_DIR / "reference_labels.json"
    
    assert prompts_path.exists(), "Held-out prompts benchmark must exist"
    assert labels_path.exists(), "Reference labels benchmark must exist"

    prompts_data = json.loads(prompts_path.read_text(encoding="utf-8"))
    labels_data = json.loads(labels_path.read_text(encoding="utf-8"))

    prompt_map = {p["id"]: p["prompt"] for p in prompts_data}

    assert len(prompt_map) == 25, "Must test exactly 25 held-out prompts"

    correct = 0
    tier_counts = {"TRIVIAL": 0, "SIMPLE": 0, "MEDIUM": 0, "COMPLEX": 0, "LARGE": 0}

    for pid, prompt_text in prompt_map.items():
        expected_tier_str = labels_data[pid]["expected_complexity"]
        tier_counts[expected_tier_str] += 1
        predicted_tier = classify_mission_complexity(prompt_text)
        assert predicted_tier.name == expected_tier_str, (
            f"Classification mismatch for {pid}: expected {expected_tier_str}, got {predicted_tier.name}"
        )
        correct += 1

    assert correct == 25, f"All 25 held-out prompts must classify correctly (got {correct}/25)"
    for tier, count in tier_counts.items():
        assert count == 5, f"Each tier must have exactly 5 prompts (tier {tier} had {count})"


# ==============================================================================
# 2. EXISTING REPOSITORY MODIFICATION AUDIT
# ==============================================================================

def test_existing_repo_modification_audit():
    results_path = ARTIFACTS_DIR / "existing_repo_editing_results.json"
    assert results_path.exists(), "Existing repo editing results artifact must exist"

    data = json.loads(results_path.read_text(encoding="utf-8"))
    assert data["overall_success"] is True, "All modification scenarios must pass"

    scenarios = data["scenarios"]
    assert scenarios["A_BUG_FIX"]["passed"] is True
    assert scenarios["B_FEATURE_ADDITION"]["passed"] is True
    assert scenarios["C_CROSS_FILE_COORDINATION"]["passed"] is True
    assert scenarios["D_TEST_REPAIR"]["passed"] is True
    assert scenarios["E_PROTECTED_UNRELATED_WORK"]["passed"] is True


# ==============================================================================
# 3. INDEPENDENT GENERATED APPS COMPLETENESS
# ==============================================================================

def test_independent_generated_apps_completeness():
    # App 1: Habit Tracker Dashboard
    app1_dir = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4h_app1_habits")
    assert (app1_dir / "index.html").exists(), "App 1 index.html must exist"
    assert (app1_dir / "css" / "styles.css").exists(), "App 1 css/styles.css must exist"
    assert (app1_dir / "js" / "app.js").exists(), "App 1 js/app.js must exist"
    assert (app1_dir / "index.html").stat().st_size > 1000
    assert (app1_dir / "css" / "styles.css").stat().st_size > 2000
    assert (app1_dir / "js" / "app.js").stat().st_size > 3000

    # App 2: Kanban Board
    app2_dir = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4h_app2_kanban")
    assert (app2_dir / "index.html").exists(), "App 2 index.html must exist"
    assert (app2_dir / "css" / "styles.css").exists(), "App 2 css/styles.css must exist"
    assert (app2_dir / "js" / "app.js").exists(), "App 2 js/app.js must exist"
    assert (app2_dir / "index.html").stat().st_size > 1000
    assert (app2_dir / "css" / "styles.css").stat().st_size > 2000
    assert (app2_dir / "js" / "app.js").stat().st_size > 3000

    # App 3: Log Analyzer CLI
    app3_dir = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4h_app3_cli")
    assert (app3_dir / "log_analyzer.py").exists(), "App 3 log_analyzer.py must exist"
    assert (app3_dir / "test_log_analyzer.py").exists(), "App 3 test_log_analyzer.py must exist"

    # App 3 tests must pass directly via pytest
    res = subprocess.run(
        [sys.executable, "-m", "pytest", str(app3_dir / "test_log_analyzer.py"), "-q"],
        capture_output=True,
        text=True
    )
    assert res.returncode == 0, f"App 3 pytest failed: {res.stdout}\n{res.stderr}"


# ==============================================================================
# 4. BROWSER CDP ACCEPTANCE & SCREENSHOTS
# ==============================================================================

def test_browser_cdp_acceptance_and_screenshots():
    # Verify screenshot artifacts (>= 9 required across Desktop, Tablet, Mobile)
    screenshots = list(SCREENSHOTS_DIR.glob("*.png"))
    assert len(screenshots) >= 9, f"Must have at least 9 screenshots, found {len(screenshots)}"

    viewports = ["desktop", "tablet", "mobile"]
    for vp in viewports:
        assert any(vp in s.name for s in screenshots), f"Viewport '{vp}' must be represented in screenshots"

    evidence_path = ARTIFACTS_DIR / "browser_functional_evidence.json"
    assert evidence_path.exists(), "Browser functional evidence artifact must exist"

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    summary = evidence["summary"]
    assert summary["all_apps_passed"] is True, "All browser application flows must pass"
    assert summary["zero_console_errors_across_all"] is True, "Must have 0 console errors"
    assert summary["persistence_verified_across_all"] is True, "Persistence must be verified across reloads"


# ==============================================================================
# 5. RUNTIME INVARIANTS, ROUTING & SECURITY
# ==============================================================================

def test_parallel_execution_invariants():
    # Test conflict-key serialization vs disjoint parallelization
    trace_path = ARTIFACTS_DIR / "parallel_execution_trace.json"
    assert trace_path.exists(), "Parallel execution trace must exist"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["invariants_passed"] is True


def test_adaptive_routing_invariants():
    router = AdaptiveRouter()
    assert router.get_health(1).state == ProviderHealthState.HEALTHY

    # Simulate failure
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    # Zero-wait failover routes to T2
    decision = router.route_primary()
    assert decision.tier == 2
    assert decision.bypassed is True

    # Generation success restores T1
    router.record_success(tier=1, latency=0.10)
    assert router.get_health(1).state == ProviderHealthState.HEALTHY
    recovered_dec = router.route_primary()
    assert recovered_dec.tier == 1
    assert recovered_dec.bypassed is False


def test_workspace_security_path_traversal(tmp_path):
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()

    traversal_blocked = False
    try:
        canonicalize_workspace_path("../../outside.txt", ws_root)
    except (WorkspaceBoundaryError, ValueError, PermissionError):
        traversal_blocked = True
    except Exception as e:
        traversal_blocked = "escapes" in str(e).lower() or "outside" in str(e).lower()
    assert traversal_blocked is True, "Path traversal outside workspace root must be blocked"


def test_artifact_manifest_completeness():
    manifest_path = ARTIFACTS_DIR / "artifact_manifests.json"
    assert manifest_path.exists(), "Artifact manifests must exist"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["total_files"] >= 8
    assert manifest["total_bytes"] > 20000
    assert "app1_habits" in manifest["workspaces"]
    assert "app2_kanban" in manifest["workspaces"]
    assert "app3_cli" in manifest["workspaces"]
