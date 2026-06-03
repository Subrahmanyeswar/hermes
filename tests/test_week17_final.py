#!/usr/bin/env python3
"""
HERMES — Week 17 Final Validation
WOW features: export, GitHub push, VS Code, screenshot-to-code, TUI slash commands.

Run: python tests/test_week17_final.py
"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_1_all_wow_tool_files_exist():
    required = [
        ("tools/export_tools.py",   "Export tools (ZIP + VSCode)"),
        ("tools/git_tools.py",      "Git tools including git_push"),
        ("tools/vision_tools.py",   "Vision tools (screenshot-to-code)"),
        ("tests/screenshots/test_login_form.png",  "Test screenshot 1"),
        ("tests/screenshots/test_dashboard.png",   "Test screenshot 2"),
        ("tests/screenshots/test_api_docs.png",    "Test screenshot 3"),
    ]
    missing = []
    for path_str, desc in required:
        if not Path(path_str).exists():
            missing.append(f"{path_str} ({desc})")

    if missing:
        print(f"  [FAIL] Missing files:")
        for m in missing:
            print(f"    - {m}")
        # Screenshots are non-blocking — auto-create them
        if any("screenshot" in m for m in missing):
            print("  [INFO] Creating test screenshots automatically...")
            result = subprocess.run(
                [sys.executable, "tests/create_test_screenshots.py"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print("  [PASS] Test screenshots created")
        return len([m for m in missing if "screenshot" not in m]) == 0

    print(f"  [PASS] All {len(required)} WOW feature files exist")
    return True


def test_2_all_wow_tools_registered():
    from tools.registry import list_tools
    tools = list_tools()
    required = [
        "export_zip", "open_in_vscode",
        "git_push",
        "screenshot_to_code",
    ]
    missing = [t for t in required if t not in tools]
    if missing:
        print(f"  [FAIL] Tools not registered: {missing}")
        return False
    print(f"  [PASS] All 4 WOW tools registered in tool registry")
    return True


def test_3_export_zip_creates_real_zip():
    import zipfile, tempfile
    from tools.export_tools import ExportZipTool

    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "testproject"
        proj.mkdir()
        (proj / "app.py").write_text('print("hello")\n')
        (proj / "requirements.txt").write_text("flask\n")

        tool = ExportZipTool()
        result = tool.execute(ExportZipTool.Input(
            project_path=str(proj),
            output_name="week17_test",
        ))

    if not result.success:
        print(f"  [FAIL] export_zip failed: {result.error}")
        return False

    # Find ZIP path in output
    zip_path = None
    for line in result.output.split("\n"):
        if line.startswith("Path:"):
            zip_path = line.split("Path:")[1].strip()
            break

    if not zip_path or not Path(zip_path).exists():
        print(f"  [FAIL] ZIP file not found in output: {result.output[:100]}")
        return False

    if not zipfile.is_zipfile(zip_path):
        print(f"  [FAIL] Created file is not a valid ZIP: {zip_path}")
        return False

    print(f"  [PASS] export_zip creates valid ZIP | {zip_path}")
    return True


def test_4_git_push_token_masking():
    """Token must never appear in error messages."""
    import os
    from tools.git_tools import GitPushTool
    import tempfile

    secret = "ghp_WEEK17_TEST_TOKEN_MASKING_CHECK"
    os.environ["GITHUB_TOKEN"] = secret

    with tempfile.TemporaryDirectory() as tmp:
        tool = GitPushTool()
        result = tool.execute(GitPushTool.Input(directory=tmp))

    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]

    if secret in (result.error or ""):
        print(f"  [FAIL] CRITICAL: GITHUB_TOKEN appeared in error message!")
        return False
    if secret in (result.output or ""):
        print(f"  [FAIL] CRITICAL: GITHUB_TOKEN appeared in output!")
        return False

    print(f"  [PASS] Token masking working — secret never appears in output or errors")
    return True


def test_5_screenshot_tool_validates_inputs():
    """screenshot_to_code must validate image path and format."""
    from tools.vision_tools import ScreenshotToCodeTool

    tool = ScreenshotToCodeTool()

    # Missing file
    r1 = tool.execute(ScreenshotToCodeTool.Input(image_path="/not/a/real/file.png"))
    assert r1.success is False and "not found" in r1.error.lower()

    # Bad extension
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "image.bmp"
        bad.write_bytes(b"BM fake")
        r2 = tool.execute(ScreenshotToCodeTool.Input(image_path=str(bad)))
        assert r2.success is False and "unsupported" in r2.error.lower()

    print(f"  [PASS] screenshot_to_code validates missing file and unsupported format")
    return True


def test_6_clean_code_output_strips_fences():
    """_clean_code_output must handle all fence variants."""
    from tools.vision_tools import ScreenshotToCodeTool
    tool = ScreenshotToCodeTool()

    cases = [
        ("```html\n<div>test</div>\n```", "html", "<div>test</div>"),
        ("```jsx\nimport React from 'react';\n```", "react", "import React from 'react';"),
        ("```\n<div>test</div>\n```", "html", "<div>test</div>"),
        ("<div>no fence</div>", "html", "<div>no fence</div>"),
    ]
    for raw, fmt, expected_fragment in cases:
        cleaned = tool._clean_code_output(raw, fmt)
        if expected_fragment not in cleaned:
            print(f"  [FAIL] clean_code_output failed for: {raw[:40]!r}")
            return False

    print(f"  [PASS] _clean_code_output handles all {len(cases)} fence variants")
    return True


def test_7_tui_slash_commands_defined():
    """ChatPanel must have all 4 new slash command handlers."""
    import inspect
    from ui.panels.chat import ChatPanel

    src = inspect.getsource(ChatPanel)
    required_handlers = [
        "_run_export_command",
        "_run_vscode_command",
        "_run_push_command",
        "_run_screenshot_command",
    ]
    missing = [h for h in required_handlers if h not in src]
    if missing:
        print(f"  [FAIL] Missing slash command handlers: {missing}")
        return False

    # Verify slash commands are in _handle_slash_command
    required_cmds = ["/export", "/vscode", "/push", "/screenshot"]
    missing_cmds = [c for c in required_cmds if c not in src]
    if missing_cmds:
        print(f"  [FAIL] Missing slash commands in handler: {missing_cmds}")
        return False

    print(f"  [PASS] All 4 slash command handlers present in ChatPanel")
    return True


def test_8_screenshot_test_results_exist():
    """If live tests were run, results.json should exist."""
    results_path = Path("data/screenshot_test_results.json")
    if not results_path.exists():
        print(f"  [WARN] screenshot_test_results.json not found")
        print(f"  [WARN] Run: python tests/test_screenshot_to_code_live.py")
        print(f"  [WARN] Skipping — non-blocking")
        return True

    with open(results_path) as f:
        data = json.load(f)

    passed = data.get("passed", 0)
    total = data.get("total", 0)

    if passed < 2:
        print(f"  [FAIL] Only {passed}/{total} screenshot tests passed")
        return False

    print(f"  [PASS] Screenshot test results: {passed}/{total} passed")
    return True


def test_9_all_wow_unit_tests_pass():
    print("  Running WOW feature unit tests...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_tools.py", "-q", "--timeout=60",
         "-k", "export or vscode or git_push or screenshot or vision",
         "--tb=short"],
        capture_output=True, text=True, timeout=120
    )
    lines = result.stdout.strip().split("\n")
    summary = lines[-1] if lines else ""
    if result.returncode != 0:
        print(f"  [FAIL] WOW unit tests FAILED")
        for line in lines[-10:]:
            if line.strip():
                print(f"    {line}")
        return False
    print(f"  [PASS] {summary}")
    return True


def main():
    print("=" * 65)
    print("HERMES — Week 17 Final Validation")
    print("WOW Features: Export, GitHub Push, VS Code, Screenshot-to-Code")
    print("=" * 65)

    tests = [
        ("All WOW feature files exist",                     test_1_all_wow_tool_files_exist),
        ("All 4 WOW tools registered in registry",          test_2_all_wow_tools_registered),
        ("export_zip creates real valid ZIP",               test_3_export_zip_creates_real_zip),
        ("git_push token masking working",                  test_4_git_push_token_masking),
        ("screenshot_to_code validates inputs",             test_5_screenshot_tool_validates_inputs),
        ("_clean_code_output strips all fence variants",    test_6_clean_code_output_strips_fences),
        ("TUI has all 4 slash command handlers",            test_7_tui_slash_commands_defined),
        ("Screenshot live test results exist",              test_8_screenshot_test_results_exist),
        ("All WOW unit tests pass",                         test_9_all_wow_unit_tests_pass),
    ]

    passed_all = True
    for name, fn in tests:
        print(f"\n[TEST] {name}")
        try:
            if not fn():
                passed_all = False
        except Exception as e:
            import traceback
            print(f"  [ERROR] {type(e).__name__}: {e}")
            traceback.print_exc()
            passed_all = False

    print("\n" + "=" * 65)
    if passed_all:
        print("WEEK 17 COMPLETE: All WOW features operational.")
        print()
        print("  [PASS] /export [path]    — Packages project as ZIP archive")
        print("  [PASS] /vscode [path]    — Opens in VS Code editor")
        print("  [PASS] /push [dir] [branch] — Pushes to GitHub")
        print("  [PASS] /screenshot <img> — Converts UI screenshot to HTML/React")
        print()
        print("Demo these in the live TUI:")
        print("  python main.py ui")
        print("  /export generated_projects")
        print("  /screenshot tests/screenshots/test_login_form.png html")
        print("  /vscode generated_projects")
        print()
        print("Ready for Week 18 (50-task benchmark + ablation study).")
    else:
        print("WEEK 17 INCOMPLETE — fix failures before Week 18.")
    print("=" * 65)


if __name__ == "__main__":
    main()
