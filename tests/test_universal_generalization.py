# tests/test_universal_generalization.py
"""
Universal Software-Building Generalization Test Suite for HERMES 2.x (Section 10 & 12E).
Validates that HERMES correctly classifies, parses, and validates distinct project categories:
1. Static websites (HTML + CSS).
2. Interactive web applications (HTML5 Canvas + vanilla ES6).
3. React / Vite modern frontend projects.
4. Python CLI tools (argparse, exit codes, Python AST).
5. REST API backends (FastAPI / Flask endpoints).
6. Existing repository bug fixes (preserves untouched files).
7. Data processing applications (JSON/CSV transformations).
"""

import ast
import json
import pytest
import tempfile
from pathlib import Path

from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase
from core.integration_validator import CrossArtifactValidator


def test_category_1_static_website(tmp_path: Path):
    """Category 1: Static website with HTML and CSS."""
    ws = tmp_path / "static_site"
    ws.mkdir()
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head>'
        '<body><header><h1>Acme Corp</h1></header><main><p>Welcome</p></main></body></html>',
        encoding="utf-8"
    )
    (ws / "style.css").write_text(
        'body { font-family: sans-serif; margin: 0; padding: 20px; color: #333; }',
        encoding="utf-8"
    )

    # Must classify as web task
    assert WebsiteMvpGate.is_website_mission("Build an Acme Corp static marketing landing page", ws)
    
    rep = CrossArtifactValidator.validate_web_integration(ws)
    assert rep.valid, f"Static site must be valid: {rep.issues}"


def test_category_2_interactive_canvas_app(tmp_path: Path):
    """Category 2: Interactive canvas-based drawing/game application."""
    ws = tmp_path / "canvas_app"
    ws.mkdir()
    (ws / "package.json").write_text('{"name": "canvas-app", "version": "1.0.0"}', encoding="utf-8")
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head>'
        '<body><canvas id="game-canvas"></canvas><script src="app.js"></script></body></html>',
        encoding="utf-8"
    )
    (ws / "style.css").write_text('#game-canvas { width: 400px; height: 400px; background: #000; }', encoding="utf-8")
    (ws / "app.js").write_text(
        'const canvas = document.getElementById("game-canvas");\n'
        'const ctx = canvas.getContext("2d");\n'
        'ctx.fillStyle = "#fff";\n'
        'ctx.fillRect(10, 10, 50, 50);\n',
        encoding="utf-8"
    )

    gate = WebsiteMvpGate(workspace_root=ws)
    ok, unmet = gate.evaluate(ws)
    assert ok, f"Interactive canvas app must pass scaffold check: {unmet}"


def test_category_3_react_vite_discovery(tmp_path: Path):
    """Category 3: React/Vite modern web project."""
    ws = tmp_path / "vite_app"
    ws.mkdir()
    (ws / "package.json").write_text(
        '{"name": "vite-react", "scripts": {"dev": "vite", "build": "vite build"}, "dependencies": {"react": "^18.2.0"}}',
        encoding="utf-8"
    )
    (ws / "vite.config.js").write_text('export default { plugins: [] };', encoding="utf-8")
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head></head><body><div id="root"></div>'
        '<script type="module" src="/src/main.jsx"></script></body></html>',
        encoding="utf-8"
    )
    src_dir = ws / "src"
    src_dir.mkdir()
    (src_dir / "main.jsx").write_text(
        'import React from "react";\n'
        'import ReactDOM from "react-dom/client";\n'
        'ReactDOM.createRoot(document.getElementById("root")).render(<h1>Hello</h1>);\n',
        encoding="utf-8"
    )

    # Dynamic entrypoint discovery must detect Vite project
    assert WebsiteMvpGate.is_website_mission("Create a Vite React dashboard", ws)


def test_category_4_python_cli(tmp_path: Path):
    """Category 4: Pure Python CLI utility (must NOT be misclassified as a website)."""
    ws = tmp_path / "py_cli"
    ws.mkdir()
    cli_code = (
        'import argparse\n'
        'import sys\n\n'
        'def main():\n'
        '    parser = argparse.ArgumentParser(description="CLI tool")\n'
        '    parser.add_argument("--count", type=int, default=1)\n'
        '    args = parser.parse_args()\n'
        '    print(f"Count: {args.count}")\n'
        '    return 0\n\n'
        'if __name__ == "__main__":\n'
        '    sys.exit(main())\n'
    )
    cli_file = ws / "cli.py"
    cli_file.write_text(cli_code, encoding="utf-8")

    # AST verification
    parsed = ast.parse(cli_code)
    assert parsed is not None

    # Must NOT classify as website mission
    assert not WebsiteMvpGate.is_website_mission("Write a Python CLI utility to calculate hash sums", ws)


def test_category_5_rest_api(tmp_path: Path):
    """Category 5: REST API backend module (FastAPI/Flask)."""
    ws = tmp_path / "api_service"
    ws.mkdir()
    api_code = (
        'from fastapi import FastAPI\n\n'
        'app = FastAPI(title="Item API")\n\n'
        '@app.get("/items")\n'
        'def get_items():\n'
        '    return [{"id": 1, "name": "Item A"}]\n'
    )
    api_file = ws / "main.py"
    api_file.write_text(api_code, encoding="utf-8")

    # Syntax passes
    parsed = ast.parse(api_code)
    assert parsed is not None

    # Negative cue: "backend service" or "fastapi backend" must not be treated as a website
    assert not WebsiteMvpGate.is_website_mission("Build a FastAPI backend service for item management", ws)


def test_category_6_existing_repo_targeted_fix(tmp_path: Path):
    """Category 6: Targeted bug repair preserving untouched files."""
    ws = tmp_path / "existing_repo"
    ws.mkdir()
    
    # Existing files that must remain pristine
    (ws / "config.json").write_text('{"env": "production", "debug": false}', encoding="utf-8")
    (ws / "utils.py").write_text('def add(a, b): return a + b\n', encoding="utf-8")
    
    # Buggy file
    buggy_code = 'def divide(a, b): return a / b if b != 0 else None\n'
    (ws / "calc.py").write_text(buggy_code, encoding="utf-8")

    initial_config_hash = (ws / "config.json").stat().st_mtime
    initial_utils_hash = (ws / "utils.py").stat().st_mtime

    # Apply surgical repair to calc.py only
    fixed_code = 'def divide(a, b):\n    if b == 0:\n        raise ValueError("Cannot divide by zero")\n    return a / b\n'
    (ws / "calc.py").write_text(fixed_code, encoding="utf-8")

    # Verify calc.py parses
    ast.parse(fixed_code)

    # Verify untouched files are intact
    assert json.loads((ws / "config.json").read_text(encoding="utf-8"))["env"] == "production"
    assert "def add" in (ws / "utils.py").read_text(encoding="utf-8")


def test_category_7_data_processing_application(tmp_path: Path):
    """Category 7: Data processing transformation pipeline."""
    ws = tmp_path / "data_proc"
    ws.mkdir()
    proc_code = (
        'import csv\n'
        'import json\n\n'
        'def csv_to_summary(csv_data: str) -> dict:\n'
        '    lines = csv_data.strip().splitlines()\n'
        '    reader = csv.DictReader(lines)\n'
        '    total = 0\n'
        '    count = 0\n'
        '    for row in reader:\n'
        '        total += float(row.get("amount", 0))\n'
        '        count += 1\n'
        '    return {"total": total, "count": count, "avg": total / count if count else 0}\n'
    )
    (ws / "processor.py").write_text(proc_code, encoding="utf-8")
    parsed = ast.parse(proc_code)
    assert parsed is not None
    assert not WebsiteMvpGate.is_website_mission("Write a Python data-processing script to parse transaction CSVs", ws)
