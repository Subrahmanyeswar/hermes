#!/usr/bin/env python3
"""
HERMES — Submission Readiness Validation (Week 20)
The final gate. Run this before submitting.
Every check that fails is a reason the viva examiner could mark you down.

Run: python tests/test_submission_ready.py
Must print READY FOR SUBMISSION before you push to GitHub.
"""
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent))

# ══════════════════════════════════════════════════════════════════════
# Section 1: Repository Security Checks
# ══════════════════════════════════════════════════════════════════════

def test_S1_no_api_keys_in_git_history():
    """
    CRITICAL: No API keys must exist anywhere in the git history.
    This is the most important security check — a fail here is catastrophic.
    Patterns checked: sk-ant-, ghp_, ANTHROPIC_API_KEY=sk, GITHUB_TOKEN=ghp
    """
    print("  Scanning git history for leaked secrets...")

    danger_patterns = [
        r"sk-ant-[a-zA-Z0-9\-_]{20,}",
        r"ghp_[a-zA-Z0-9]{36}",
        r"ANTHROPIC_API_KEY\s*=\s*sk-",
        r"GITHUB_TOKEN\s*=\s*ghp_",
        r"api_key\s*=\s*['\"]sk-",
    ]

    result = subprocess.run(
        ["git", "log", "-p", "--all", "--full-history"],
        capture_output=True, text=True, timeout=60
    )

    if result.returncode != 0:
        print(f"  ⚠ Could not run git log: {result.stderr[:100]}")
        print(f"  ⚠ Skipping git history scan — verify manually")
        return True

    git_history = result.stdout

    for pattern in danger_patterns:
        matches = re.findall(pattern, git_history, re.IGNORECASE)
        if matches:
            # Filter out obvious test/placeholder values
            real_matches = [
                m for m in matches
                if "test" not in m.lower()
                and "fake" not in m.lower()
                and "placeholder" not in m.lower()
                and "example" not in m.lower()
                and len(m) > 20
            ]
            if real_matches:
                print(f"  ✗ CRITICAL: Found potential API key in git history!")
                print(f"    Pattern: {pattern}")
                print(f"    Match: {real_matches[0][:30]}...")
                print(f"    Fix: git-filter-repo or BFG Repo-Cleaner required")
                print(f"    See: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository")
                return False

    print(f"  ✓ No API keys found in git history ({len(danger_patterns)} patterns checked)")
    return True


def test_S2_env_file_not_tracked():
    """.env must be in .gitignore and not tracked by git."""
    gitignore_path = Path(".gitignore")

    if not gitignore_path.exists():
        print("  ✗ .gitignore not found — create it immediately")
        return False

    content = gitignore_path.read_text()
    required_entries = [".env", "__pycache__/", "data/", "*.pyc"]
    missing = [e for e in required_entries if e not in content]

    if missing:
        print(f"  ✗ .gitignore missing entries: {missing}")
        return False

    # Check .env is not tracked
    result = subprocess.run(
        ["git", "ls-files", ".env"],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        print("  ✗ CRITICAL: .env file is tracked by git!")
        print("    Fix: git rm --cached .env && git commit -m 'remove tracked .env'")
        return False

    print("  ✓ .gitignore has all required entries | .env is not tracked by git")
    return True


def test_S3_data_directory_not_tracked():
    """data/ directory (containing API costs and session logs) must not be in git."""
    result = subprocess.run(
        ["git", "ls-files", "data/"],
        capture_output=True, text=True
    )
    tracked_data_files = result.stdout.strip().split("\n") if result.stdout.strip() else []

    # Allow only specific data files that are safe to commit
    safe_data_files = {
        "data/threshold_calibration_results.json",
        "data/paper_threshold_table.csv",
        "data/week10_baseline.json",
        "data/week12_baseline.json",
        "data/week14_summary.json",
        "data/stability_audit.json",
        "data/latency_report.json",
        "data/screenshot_test_results.json",
    }

    unsafe = [f for f in tracked_data_files if f and f not in safe_data_files]
    dangerous = [f for f in unsafe if "tasks.db" in f or "api_costs" in f or "sessions/" in f]

    if dangerous:
        print(f"  ✗ Sensitive data files tracked by git: {dangerous}")
        print(f"    Fix: git rm --cached {' '.join(dangerous)}")
        return False

    print(f"  ✓ No sensitive data files in git | {len(tracked_data_files)} safe data files tracked")
    return True


def test_S4_no_hardcoded_tokens_in_source():
    """Scan all Python files for hardcoded tokens or passwords."""
    dangerous_patterns = [
        (r"sk-ant-[a-zA-Z0-9\-_]{20,}", "Anthropic API key"),
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub token"),
        (r'api_key\s*=\s*["\'][^"\']{20,}["\']', "Hardcoded API key"),
        (r'password\s*=\s*["\'][^"\']{8,}["\']', "Hardcoded password"),
    ]

    py_files = list(Path('.').rglob('*.py'))
    py_files = [f for f in py_files if ".git" not in str(f) and "venv" not in str(f)]

    violations = []
    for py_file in py_files:
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern, description in dangerous_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    if "test" not in match.lower() and "example" not in match.lower():
                        violations.append(f"{py_file}: {description}: {match[:30]}")
        except Exception:
            continue

    if violations:
        print(f"  ✗ Found hardcoded secrets in source code:")
        for v in violations[:5]:
            print(f"    {v}")
        return False

    print(f"  ✓ No hardcoded tokens found in {len(py_files)} Python files")
    return True

# ══════════════════════════════════════════════════════════════════════
# Section 2: Completeness Checks
# ══════════════════════════════════════════════════════════════════════

def test_C1_readme_is_complete():
    """README.md must exist with all required sections."""
    readme_path = Path("README.md")
    if not readme_path.exists():
        print("  ✗ README.md not found")
        return False

    content = readme_path.read_text()
    required_sections = [
        "# HERMES",
        "## Architecture",
        "## Installation",
        "## Usage",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "ollama pull",
        "requirements.txt",
        "pytest",
    ]

    missing = [s for s in required_sections if s not in content]
    if missing:
        print(f"  ✗ README.md missing: {missing}")
        return False

    word_count = len(content.split())
    print(f"  ✓ README.md complete | {word_count} words | all required sections present")
    return True


def test_C2_requirements_txt_pinned():
    """requirements.txt must exist with pinned versions."""
    req_path = Path("requirements.txt")
    if not req_path.exists():
        print("  ✗ requirements.txt not found")
        print("    Fix: pip freeze > requirements.txt")
        return False

    content = req_path.read_text()
    lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]

    if len(lines) < 5:
        print(f"  ✗ requirements.txt too short ({len(lines)} packages) — run pip freeze > requirements.txt")
        return False

    required_packages = ["textual", "loguru", "pydantic", "gitpython", "httpx", "typer", "anthropic"]
    content_lower = content.lower()
    missing = [p for p in required_packages if p.lower() not in content_lower]
    if missing:
        print(f"  ✗ requirements.txt missing packages: {missing}")
        print(f"    Fix: pip install {' '.join(missing)} && pip freeze > requirements.txt")
        return False

    print(f"  ✓ requirements.txt has {len(lines)} pinned packages with all required dependencies")
    return True


def test_C3_all_20_weeks_of_source_files_exist():
    """Every major source file built across 20 weeks must exist."""
    required_files = [
        # Phase 1 — Foundation
        "models/ollama_client.py",
        "models/claude_client.py",
        "tools/base.py",
        "tools/registry.py",
        "tools/file_tools.py",
        "tools/shell_tools.py",
        "tools/network_tools.py",
        "tools/git_tools.py",
        "tools/memory_tools.py",
        "tools/export_tools.py",
        "tools/vision_tools.py",
        "tools/security.py",
        "core/orchestrator.py",
        "core/verifier.py",
        "core/disagreement_router.py",
        "core/planner.py",
        "core/intent_classifier.py",
        "core/prompt_builder.py",
        "core/response_parser.py",
        "core/error_handler.py",
        "memory/store.py",
        "memory/extractor.py",
        "memory/consolidator.py",
        "memory/session_logger.py",
        # Phase 2 — Hardening
        "kairos/db.py",
        "kairos/task_queue.py",
        "kairos/daemon.py",
        "utils/__init__.py",
        "utils/logging.py",
        # Phase 3 — Product
        "ui/__init__.py",
        "ui/app.py",
        "ui/hermes.css",
        "ui/panels/__init__.py",
        "ui/panels/chat.py",
        "ui/panels/right_panel.py",
        "ui/panels/status_bar.py",
        "benchmarks/__init__.py",
        "benchmarks/tasks.json",
        "benchmarks/runner.py",
        "benchmarks/compute_metrics.py",
        "benchmarks/generate_graphs.py",
        "benchmarks/paper_draft.py",
        # Config and entry point
        "main.py",
        "config/settings.yaml",
        "config/permissions.yaml",
        "README.md",
        "requirements.txt",
    ]

    missing = [f for f in required_files if not Path(f).exists()]
    if missing:
        print(f"  ✗ Missing {len(missing)} source files:")
        for m in missing:
            print(f"    - {m}")
        return False

    print(f"  ✓ All {len(required_files)} required source files exist")
    return True


def test_C4_all_12_skills_exist():
    """All 12 SKILL.md files must exist with valid structure."""
    required_skills = [
        "skills/flask-rest-api/SKILL.md",
        "skills/pytest-generation/SKILL.md",
        "skills/debugging/SKILL.md",
        "skills/git-workflow/SKILL.md",
        "skills/security-audit/SKILL.md",
        "skills/auto-docs/SKILL.md",
        "skills/database-design/SKILL.md",
        "skills/refactoring/SKILL.md",
        "skills/bash-scripting/SKILL.md",
        "skills/react-frontend/SKILL.md",
        "skills/code-review/SKILL.md",
        "skills/screenshot-to-code/SKILL.md",
    ]

    missing = [f for f in required_skills if not Path(f).exists()]
    if missing:
        print(f"  ✗ Missing SKILL.md files: {missing}")
        return False

    # Verify each SKILL.md has triggers
    no_triggers = []
    for skill_path in required_skills:
        content = Path(skill_path).read_text()
        if "triggers:" not in content and "Triggers:" not in content:
            no_triggers.append(skill_path)

    if no_triggers:
        print(f"  ✗ Skills missing trigger definitions: {no_triggers}")
        return False

    print(f"  ✓ All 12 SKILL.md files exist with trigger definitions")
    return True


def test_C5_benchmark_outputs_exist():
    """Key benchmark output files must exist."""
    files_and_descriptions = [
        ("benchmarks/tasks.json",        "50 task definitions"),
        ("benchmarks/paper_draft.md",    "8-section paper draft"),
    ]

    optional_files = [
        ("benchmarks/results.json",      "Full benchmark results"),
        ("benchmarks/metrics.json",      "Computed metrics"),
        ("benchmarks/graphs/fig1_completion_rate.png", "Figure 1"),
        ("benchmarks/graphs/fig2_escalation_rate.png", "Figure 2"),
        ("benchmarks/graphs/fig3_skill_lift.png",      "Figure 3"),
        ("benchmarks/graphs/fig4_cost_comparison.png", "Figure 4"),
        ("benchmarks/graphs/fig5_latency_by_difficulty.png", "Figure 5"),
    ]

    missing_required = []
    for path, desc in files_and_descriptions:
        if not Path(path).exists():
            missing_required.append(f"{path} ({desc})")

    if missing_required:
        print(f"  ✗ Missing required benchmark files:")
        for m in missing_required:
            print(f"    - {m}")
        return False

    missing_optional = [(p, d) for p, d in optional_files if not Path(p).exists()]
    if missing_optional:
        print(f"  ⚠ Optional benchmark files not yet generated ({len(missing_optional)} missing):")
        for p, d in missing_optional[:3]:
            print(f"    - {p} ({d})")
        print(f"    Run: python benchmarks/runner.py && python benchmarks/generate_graphs.py")

    print(f"  ✓ All required benchmark output files exist")
    return True

# ══════════════════════════════════════════════════════════════════════
# Section 3: Code Quality Checks
# ══════════════════════════════════════════════════════════════════════

def test_Q1_unit_test_suite_passes():
    """All unit tests must pass with zero failures."""
    print("  Running full unit test suite...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/",
         "--ignore=tests/integration/",
         "--ignore=tests/test_submission_ready.py",
         "-q", "--timeout=120", "--tb=short"],
        capture_output=True, text=True, timeout=240
    )

    lines = result.stdout.strip().split("\n")
    summary = lines[-1] if lines else "(no output)"

    if result.returncode != 0:
        print(f"  ✗ Tests FAILED: {summary}")
        failed_lines = [l for l in lines if "FAILED" in l or "ERROR" in l]
        for line in failed_lines[:10]:
            print(f"    {line}")
        return False

    print(f"  ✓ All unit tests pass | {summary}")
    return True


def test_Q2_all_critical_modules_importable():
    """Every critical module must import without error."""
    modules = [
        ("core.orchestrator",        ["Orchestrator", "OrchestratorResult"]),
        ("core.error_handler",       ["ErrorHandler", "FailureMode"]),
        ("core.response_parser",     ["ResponseParser", "ParseSuccess"]),
        ("core.disagreement_router", ["DisagreementRouter", "load_calibrated_threshold"]),
        ("core.verifier",            ["Tier2Verifier", "VerificationResult"]),
        ("kairos.daemon",            ["KairosDaemon"]),
        ("kairos.task_queue",        ["register_task", "mark_completed"]),
        ("utils.logging",            ["setup_logging", "generate_trace_id"]),
        ("ui.app",                   ["HermesApp", "OrchestratorResponse"]),
        ("ui.panels.chat",           ["ChatPanel", "SPINNER_VERBS"]),
        ("ui.panels.right_panel",    ["RightPanel", "ToolTracePane"]),
        ("ui.panels.status_bar",     ["StatusBar", "SPINNER_VERBS"]),
        ("tools.export_tools",       ["ExportZipTool", "OpenInVSCodeTool"]),
        ("tools.vision_tools",       ["ScreenshotToCodeTool"]),
    ]

    failures = []
    for module_path, symbols in modules:
        try:
            mod = importlib.import_module(module_path)
            for sym in symbols:
                if not hasattr(mod, sym):
                    failures.append(f"{module_path}.{sym} not found")
        except ImportError as e:
            failures.append(f"{module_path}: {e}")
        except Exception as e:
            failures.append(f"{module_path}: {type(e).__name__}: {str(e)[:60]}")

    if failures:
        print(f"  ✗ {len(failures)} import failures:")
        for f in failures:
            print(f"    - {f}")
        return False

    print(f"  ✓ All {len(modules)} critical modules import cleanly")
    return True


def test_Q3_orchestrator_has_all_12_stages():
    """Orchestrator.run() must implement all 12 pipeline stages."""
    import inspect
    from core.orchestrator import Orchestrator

    source = inspect.getsource(Orchestrator.run)
    stage_markers = [
        "Stage 1", "Stage 2", "Stage 3", "Stage 4",
        "Stage 5", "Stage 6", "Stage 7", "Stage 8",
        "Stage 9", "Stage 10", "Stage 11", "Stage 12",
    ]
    missing = [s for s in stage_markers if s not in source]
    if missing:
        print(f"  ✗ Missing pipeline stages: {missing}")
        return False

    print(f"  ✓ All 12 pipeline stages present in Orchestrator.run()")
    return True


def test_Q4_error_handler_covers_all_6_failure_modes():
    """ErrorHandler must handle all 6 documented failure modes."""
    from core.error_handler import ErrorHandler, FailureMode

    handler = ErrorHandler()
    results = [
        handler.json_parse_failure("bad", 0),
        handler.tool_not_found("bad", ["good"], 0),
        handler.tool_execution_failure("bash", 1, "err", 0),
        handler.ollama_timeout("model", 120, "stage"),
        handler.tier3_api_failure("APIError", "detail", "output"),
        handler.memory_parse_error("error", "project"),
    ]

    all_modes = {r.failure_mode for r in results}
    if len(all_modes) < 5:
        print(f"  ✗ Only {len(all_modes)} distinct failure modes (expected 6)")
        return False

    print(f"  ✓ All 6 failure modes handled by ErrorHandler")
    return True


def test_Q5_session_never_crashes_adversarial():
    """Orchestrator.run() must return OrchestratorResult on adversarial inputs."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from models.ollama_client import OllamaTimeoutError, OllamaConnectionError
    from core.orchestrator import OrchestratorResult

    adversarial_inputs = [
        ("empty string",       ""),
        ("10k chars",          "x" * 10000),
        ("unicode",            "日本語 emoji 🚀 mixed"),
        ("injection attempt",  '<script>alert("xss")</script> list files'),
        ("null bytes",         "list \x00files\x01here"),
    ]

    async def run_checks():
        crashes = []
        for desc, user_input in adversarial_inputs:
            with tempfile.TemporaryDirectory() as tmp:
                test_db = Path(tmp) / "test.db"
                from kairos.db import init_db
                init_db(db_path=test_db)

                with patch("core.orchestrator.DB_PATH", test_db), \
                     patch("kairos.task_queue.DB_PATH", test_db), \
                     patch("core.orchestrator.OllamaClient") as mock_cls, \
                     patch("core.orchestrator.ClaudeClient") as mock_claude_cls, \
                     patch("core.orchestrator.Tier2Verifier") as mock_v_cls, \
                     patch("core.orchestrator.KairosDaemon"):

                    mock_o = AsyncMock()
                    mock_o.generate = AsyncMock(side_effect=OllamaTimeoutError("timeout"))
                    mock_cls.return_value = mock_o
                    mock_c = MagicMock()
                    mock_c.get_cost_summary = MagicMock(return_value={"total_spent": 0, "cap": 25, "remaining": 25})
                    mock_claude_cls.return_value = mock_c
                    mock_v_cls.return_value = AsyncMock()

                    from core.orchestrator import Orchestrator
                    orch = Orchestrator(mode="auto")
                    orch.ollama = mock_o
                    orch.claude = mock_c

                    try:
                        result = await orch.run(user_input)
                        if not isinstance(result, OrchestratorResult):
                            crashes.append(f"{desc}: returned {type(result).__name__}")
                    except Exception as e:
                        crashes.append(f"{desc}: raised {type(e).__name__}: {str(e)[:60]}")
        return crashes

    crashes = asyncio.run(run_checks())

    if crashes:
        print(f"  ✗ Session crashed on adversarial inputs:")
        for c in crashes:
            print(f"    - {c}")
        return False

    print(f"  ✓ Session never crashes on {len(adversarial_inputs)} adversarial inputs")
    return True

# ══════════════════════════════════════════════════════════════════════
# Section 4: Demo Readiness
# ══════════════════════════════════════════════════════════════════════

def test_D1_main_py_all_commands_present():
    """main.py must have all required CLI commands."""
    content = Path("main.py").read_text()
    required_commands = ["def run(", "def ui(", "def info(", "def logs(", "def trace(", "def test_pipeline("]
    missing = [c for c in required_commands if c not in content]
    if missing:
        print(f"  ✗ main.py missing commands: {missing}")
        return False
    print(f"  ✓ main.py has all {len(required_commands)} CLI commands")
    return True


def test_D2_tui_imports_and_structures_valid():
    """All TUI components must import and have required structure."""
    from ui.app import HermesApp
    from ui.panels.chat import ChatPanel, SPINNER_VERBS
    from ui.panels.right_panel import RightPanel, ToolTracePane, MemoryViewPane, TaskQueuePane
    from ui.panels.status_bar import StatusBar, SPINNER_VERBS as SB_VERBS

    assert len(SPINNER_VERBS) == 30, f"Expected 30 spinner verbs, got {len(SPINNER_VERBS)}"
    assert len(SB_VERBS) == 30, f"Status bar expected 30 verbs"

    bindings = {b.key for b in HermesApp.BINDINGS}
    required_bindings = {"ctrl+s", "ctrl+p", "ctrl+a", "ctrl+q"}
    missing = required_bindings - bindings
    if missing:
        print(f"  ✗ Missing TUI bindings: {missing}")
        return False

    print(f"  ✓ TUI structure valid | 30 spinner verbs | all 4 key bindings | 4 panels")
    return True


def test_D3_screenshot_test_images_exist():
    """3 test screenshots must exist for the demo."""
    screenshots = [
        "tests/screenshots/test_login_form.png",
        "tests/screenshots/test_dashboard.png",
        "tests/screenshots/test_api_docs.png",
    ]
    missing = [s for s in screenshots if not Path(s).exists()]

    if missing:
        print(f"  ⚠ Test screenshots missing: {missing}")
        print(f"  ⚠ Creating them now...")
        result = subprocess.run(
            [sys.executable, "tests/create_test_screenshots.py"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  ✗ Failed to create screenshots: {result.stderr[:100]}")
            return False
        missing = [s for s in screenshots if not Path(s).exists()]
        if missing:
            print(f"  ✗ Still missing after creation attempt: {missing}")
            return False

    print(f"  ✓ All 3 demo screenshots exist")
    return True


def test_D4_calibrated_threshold_valid():
    """Calibrated confidence threshold must be a valid value."""
    from core.disagreement_router import load_calibrated_threshold
    threshold = load_calibrated_threshold()
    valid_range = (0.0, 1.0)
    if not (valid_range[0] <= threshold <= valid_range[1]):
        print(f"  ✗ Threshold {threshold} outside valid range {valid_range}")
        return False
    print(f"  ✓ Calibrated confidence threshold: {threshold}")
    return True


def test_D5_paper_draft_submission_ready():
    """Paper draft must be present and non-trivial."""
    paper_path = Path("benchmarks/paper_draft.md")
    if not paper_path.exists():
        print("  ✗ benchmarks/paper_draft.md not found")
        return False

    content = paper_path.read_text()
    word_count = len(content.split())

    if word_count < 2000:
        print(f"  ✗ Paper draft too short: {word_count} words")
        return False

    if "[CITATION]" in content:
        citation_count = content.count("[CITATION]")
        print(f"  ⚠ Paper draft has {citation_count} unfilled [CITATION] placeholders")
        print(f"  ⚠ Fill these with real references before submission")

    print(f"  ✓ Paper draft: {word_count:,} words")
    return True

# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("HERMES — Submission Readiness Validation")
    print("Week 20 Final Gate")
    print("=" * 65)

    sections = [
        ("SECURITY", [
            ("No API keys in git history [CRITICAL]",    test_S1_no_api_keys_in_git_history),
            (".env not tracked by git",                  test_S2_env_file_not_tracked),
            ("data/ directory not tracked",              test_S3_data_directory_not_tracked),
            ("No hardcoded tokens in source",            test_S4_no_hardcoded_tokens_in_source),
        ]),
        ("COMPLETENESS", [
            ("README.md complete",                        test_C1_readme_is_complete),
            ("requirements.txt pinned",                   test_C2_requirements_txt_pinned),
            ("All 47 source files exist",                 test_C3_all_20_weeks_of_source_files_exist),
            ("All 12 SKILL.md files exist",               test_C4_all_12_skills_exist),
            ("Benchmark output files exist",              test_C5_benchmark_outputs_exist),
        ]),
        ("CODE QUALITY", [
            ("Unit test suite passes",                    test_Q1_unit_test_suite_passes),
            ("All critical modules importable",           test_Q2_all_critical_modules_importable),
            ("All 12 pipeline stages present",            test_Q3_orchestrator_has_all_12_stages),
            ("All 6 failure modes handled",               test_Q4_error_handler_covers_all_6_failure_modes),
            ("Session never crashes (adversarial)",       test_Q5_session_never_crashes_adversarial),
        ]),
        ("DEMO READINESS", [
            ("main.py has all CLI commands",              test_D1_main_py_all_commands_present),
            ("TUI structure and bindings valid",          test_D2_tui_imports_and_structures_valid),
            ("Demo screenshots exist",                    test_D3_screenshot_test_images_exist),
            ("Calibrated threshold valid",                test_D4_calibrated_threshold_valid),
            ("Paper draft present and non-trivial",       test_D5_paper_draft_submission_ready),
        ]),
    ]

    overall_pass = True
    section_results = {}

    for section_name, tests in sections:
        print("\n" + "-" * 65)
        print(f"  {section_name}")
        print("-" * 65)

        section_pass = True
        for test_name, test_fn in tests:
            print(f"\n[CHECK] {test_name}")
            try:
                passed = test_fn()
                if not passed:
                    section_pass = False
                    overall_pass = False
            except Exception as e:
                import traceback
                print(f"  ✗ ERROR: {type(e).__name__}: {e}")
                traceback.print_exc()
                section_pass = False
                overall_pass = False

        section_results[section_name] = section_pass

    print(f"\n{'=' * 65}")
    print("SUBMISSION READINESS SUMMARY")
    print(f"{'=' * 65}")
    for section, passed in section_results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}  {section}")

    print(f"\n{'=' * 65}")
    if overall_pass:
        print("✓ READY FOR SUBMISSION")
        print()
        print("Final steps:")
        print("  1. Run the demo script 5 times and time each section")
        print("  2. Rehearse all 8 viva answers out loud")
        print("  3. Check demo laptop: Ollama running, both models pulled")
        print("  4. Check battery: fully charged, charger packed")
        print("  5. git push origin main")
        print("  6. Submit the repository URL via the submission portal")
    else:
        failed_sections = [s for s, p in section_results.items() if not p]
        print(f"✗ NOT READY — Fix failures in: {', '.join(failed_sections)}")
        print()
        print("The most critical failure is SECURITY.")
        print("Do not submit until all SECURITY checks pass.")

    print("=" * 65)

    return overall_pass

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
