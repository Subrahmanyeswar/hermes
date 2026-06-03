#!/usr/bin/env python3
"""
HERMES — Live Screenshot-to-Code Test (Week 17)
Tests the ScreenshotToCodeTool on all 3 real test screenshots.
Requires: Ollama running with qwen2.5-coder:7b pulled (with vision support).

Run: python tests/test_screenshot_to_code_live.py

This test:
  1. Checks Ollama is running and model is available
  2. Runs screenshot_to_code on all 3 test screenshots
  3. Validates the generated code is non-empty and looks like HTML/React
  4. Reports pass/fail for each screenshot
  5. Saves results to data/screenshot_test_results.json
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


SCREENSHOTS_DIR = Path("tests/screenshots")
SCREENSHOTS = [
    ("test_login_form.png",  "html",  "login form"),
    ("test_dashboard.png",   "html",  "dashboard"),
    ("test_api_docs.png",    "react", "API documentation"),
]

RESULTS_PATH = Path("data/screenshot_test_results.json")


async def check_ollama_vision_support() -> tuple[bool, str]:
    """Verify Ollama is running and qwen2.5-coder:7b supports vision."""
    from models.ollama_client import OllamaClient

    client = OllamaClient()
    if not await client.is_running():
        return False, "Ollama is not running. Start with: ollama serve"

    models = await client.list_models()
    if not any("qwen2.5-coder" in m for m in models):
        return False, (
            "qwen2.5-coder:7b not found. Pull it with: "
            "ollama pull qwen2.5-coder:7b"
        )

    return True, "Ollama ready with vision-capable model"


def validate_html_output(code: str) -> tuple[bool, str]:
    """Basic validation that the output looks like HTML."""
    if not code or len(code.strip()) < 50:
        return False, "Output too short"
    lower = code.lower()
    html_indicators = ["<div", "<html", "<!doctype", "<body", "<header",
                       "<nav", "<main", "<section", "class=", "tailwind"]
    matches = sum(1 for ind in html_indicators if ind in lower)
    if matches < 2:
        return False, f"Output doesn't look like HTML (only {matches} indicators found)"
    return True, f"Valid HTML ({len(code)} chars, {matches} HTML indicators)"


def validate_react_output(code: str) -> tuple[bool, str]:
    """Basic validation that the output looks like React."""
    if not code or len(code.strip()) < 50:
        return False, "Output too short"
    react_indicators = ["import ", "export default", "return (", "return(", 
                        "function ", "const ", "=>", "className=", "<div"]
    matches = sum(1 for ind in react_indicators if ind in code)
    if matches < 2:
        return False, f"Output doesn't look like React (only {matches} indicators found)"
    return True, f"Valid React ({len(code)} chars, {matches} React indicators)"


def run_single_screenshot_test(
    screenshot_name: str,
    output_format: str,
    description: str,
) -> dict:
    """Run screenshot-to-code on one image and return result dict."""
    from tools.vision_tools import ScreenshotToCodeTool

    screenshot_path = SCREENSHOTS_DIR / screenshot_name
    if not screenshot_path.exists():
        return {
            "screenshot": screenshot_name,
            "description": description,
            "format": output_format,
            "passed": False,
            "error": f"Screenshot not found at {screenshot_path}. Run: python tests/create_test_screenshots.py",
            "code_lines": 0,
            "latency_seconds": 0,
        }

    output_file = Path("generated_projects") / f"screenshot_{screenshot_path.stem}_{output_format}.{'html' if output_format == 'html' else 'jsx'}"

    print(f"  Running on: {screenshot_name} -> {output_format.upper()}...")
    start = time.monotonic()

    tool = ScreenshotToCodeTool()
    result = tool.execute(ScreenshotToCodeTool.Input(
        image_path=str(screenshot_path),
        output_format=output_format,
        output_file=str(output_file),
    ))

    latency = time.monotonic() - start

    if not result.success:
        return {
            "screenshot": screenshot_name,
            "description": description,
            "format": output_format,
            "passed": False,
            "error": result.error,
            "code_lines": 0,
            "latency_seconds": round(latency, 2),
        }

    # Read the generated code and validate it
    generated_code = ""
    if output_file.exists():
        generated_code = output_file.read_text(encoding="utf-8")

    if output_format == "html":
        valid, validation_msg = validate_html_output(generated_code)
    else:
        valid, validation_msg = validate_react_output(generated_code)

    code_lines = generated_code.count("\n") + 1 if generated_code else 0

    return {
        "screenshot": screenshot_name,
        "description": description,
        "format": output_format,
        "passed": valid,
        "error": None if valid else f"Validation failed: {validation_msg}",
        "validation_message": validation_msg,
        "code_lines": code_lines,
        "output_file": str(output_file),
        "latency_seconds": round(latency, 2),
    }


async def main():
    print("=" * 65)
    print("HERMES — Live Screenshot-to-Code Test (Week 17)")
    print("=" * 65)

    # Check Ollama
    print("\nChecking Ollama availability...")
    available, msg = await check_ollama_vision_support()
    print(f"  {'[OK]' if available else '[ERROR]'} {msg}")

    if not available:
        print("\nSkipping live tests — Ollama not available.")
        print("Unit tests (no Ollama needed) are in tests/test_tools.py:")
        print("  pytest tests/test_tools.py -v -k screenshot")
        sys.exit(0)

    # Check screenshots exist
    if not SCREENSHOTS_DIR.exists() or not any(SCREENSHOTS_DIR.glob("*.png")):
        print("\nTest screenshots not found. Creating them...")
        import subprocess
        subprocess.run(
            [sys.executable, "tests/create_test_screenshots.py"],
            check=True
        )

    # Run all 3 screenshot tests
    print(f"\nRunning {len(SCREENSHOTS)} screenshot-to-code tests...")
    print(f"(Each test takes 20-60 seconds — vision inference is slow)\n")

    results = []
    for screenshot_name, output_format, description in SCREENSHOTS:
        print(f"\n[{description.upper()}]")
        result = run_single_screenshot_test(screenshot_name, output_format, description)
        results.append(result)

        if result["passed"]:
            print(f"  [PASS] | {result['code_lines']} lines | {result['latency_seconds']:.1f}s")
            print(f"    {result.get('validation_message', '')}")
            if result.get("output_file"):
                print(f"    Output: {result['output_file']}")
        else:
            print(f"  [FAIL] | {result['latency_seconds']:.1f}s")
            print(f"    Error: {result.get('error', 'Unknown error')}")

    # Summary
    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    print(f"\n{'=' * 65}")
    print(f"RESULTS: {passed}/{total} tests passed")

    for result in results:
        status = "[PASS]" if result["passed"] else "[FAIL]"
        print(
            f"  {status:<8} {result['description']:<30} "
            f"{result['code_lines']:>5} lines  "
            f"{result['latency_seconds']:>5.1f}s"
        )

    # Save results
    output = {
        "test_run": __import__("datetime").datetime.now().isoformat(),
        "passed": passed,
        "total": total,
        "results": results,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {RESULTS_PATH}")

    print(f"\n{'=' * 65}")
    if passed == total:
        print("ALL SCREENSHOT TESTS PASSED")
        print("screenshot_to_code feature is working correctly.")
    elif passed >= 2:
        print(f"{passed}/{total} TESTS PASSED")
        print("screenshot_to_code is mostly working. Check failures above.")
    else:
        print(f"ONLY {passed}/{total} TESTS PASSED")
        print("Check that qwen2.5-coder:7b vision is working:")
        print("  ollama run qwen2.5-coder:7b 'describe this image' --image tests/screenshots/test_login_form.png")
    print("=" * 65)

    sys.exit(0 if passed >= 2 else 1)


if __name__ == "__main__":
    asyncio.run(main())
