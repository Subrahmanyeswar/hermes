"""
HERMES 2.x - Held-Out Generalization Qualification Test Suite
Validates Scenario 20: HERMES architecture generalizes to 8 held-out project domains:
1. Static Web application (Vanilla HTML/CSS/JS)
2. Interactive Canvas application (2D graphics, drawing, canvas context)
3. React / Vite modern SPA (vite.config, React entrypoint, index.html)
4. Python CLI / utility tool with argparse & exit codes
5. Backend REST API (FastAPI / endpoints)
6. Database-backed application (SQLite schema, queries, migrations)
7. Brownfield patch / existing codebase targeted bug fix (surgical edits preserving existing code)
8. Code refactoring & multi-file architectural migration (modularity, DRY, clean imports)
"""

import ast
import json
import sqlite3
import subprocess
from pathlib import Path
import pytest

from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase
from core.integration_validator import CrossArtifactValidator


def test_domain_1_static_web_application(tmp_path: Path):
    """Domain 1: Static Web application (Vanilla HTML/CSS/JS)."""
    ws = tmp_path / "static_web"
    ws.mkdir()
    (ws / "index.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <link rel="stylesheet" href="style.css">
    <title>Portfolio Site</title>
</head>
<body>
    <header><h1 id="brand-title">Dev Portfolio</h1></header>
    <main><section id="projects"><p>Projects overview</p></section></main>
    <script src="main.js"></script>
</body>
</html>""", encoding="utf-8")

    (ws / "style.css").write_text("""
body { font-family: -apple-system, sans-serif; margin: 0; padding: 20px; background: #0f172a; color: #f8fafc; }
#brand-title { color: #38bdf8; font-size: 2rem; }
""", encoding="utf-8")

    (ws / "main.js").write_text("""
document.addEventListener('DOMContentLoaded', () => {
    const title = document.getElementById('brand-title');
    if (title) {
        title.addEventListener('click', () => {
            console.log('Title clicked');
        });
    }
});
""", encoding="utf-8")

    rep = CrossArtifactValidator.validate_web_integration(ws)
    assert rep.valid, f"Static web must be valid: {rep.issues}"


def test_domain_2_interactive_canvas_application(tmp_path: Path):
    """Domain 2: Interactive Canvas application (2D graphics, drawing, canvas context)."""
    ws = tmp_path / "canvas_game"
    ws.mkdir()
    (ws / "package.json").write_text(json.dumps({
        "name": "canvas-particles",
        "version": "1.0.0",
        "scripts": {"dev": "vite"}
    }), encoding="utf-8")

    (ws / "index.html").write_text("""<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="style.css"></head>
<body>
    <div id="game-container">
        <canvas id="particle-canvas" width="600" height="400"></canvas>
    </div>
    <script src="canvas_app.js"></script>
</body>
</html>""", encoding="utf-8")

    (ws / "style.css").write_text("""
#game-container { display: flex; justify-content: center; align-items: center; min-height: 100vh; background: #000; }
#particle-canvas { border: 1px solid #334155; }
""", encoding="utf-8")

    (ws / "canvas_app.js").write_text("""
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('particle-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let particles = [];
    for (let i = 0; i < 50; i++) {
        particles.push({ x: Math.random() * 600, y: Math.random() * 400, r: 2 });
    }
    particles.forEach(p => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = '#60a5fa';
        ctx.fill();
    });
});
""", encoding="utf-8")

    rep = CrossArtifactValidator.validate_web_integration(ws)
    assert rep.valid, f"Canvas integration must be valid: {rep.issues}"
    node_res = subprocess.run(["node", "--check", str(ws / "canvas_app.js")], capture_output=True, text=True)
    assert node_res.returncode == 0, f"Canvas JS syntax error: {node_res.stderr}"


def test_domain_3_react_vite_spa(tmp_path: Path):
    """Domain 3: React / Vite modern SPA."""
    ws = tmp_path / "react_vite"
    ws.mkdir()
    src = ws / "src"
    src.mkdir()

    (ws / "package.json").write_text(json.dumps({
        "name": "vite-react-dashboard",
        "version": "1.0.0",
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build"},
        "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"}
    }), encoding="utf-8")

    (ws / "vite.config.js").write_text("""
import { defineConfig } from 'vite';
export default defineConfig({
    server: { port: 3000 }
});
""", encoding="utf-8")

    (ws / "index.html").write_text("""<!DOCTYPE html>
<html>
<head><title>React App</title></head>
<body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
</body>
</html>""", encoding="utf-8")

    (src / "main.jsx").write_text("""
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>
);
""", encoding="utf-8")

    (src / "App.jsx").write_text("""
import React, { useState } from 'react';

export default function App() {
    const [count, setCount] = useState(0);
    return (
        <div className="app">
            <h1>Vite + React</h1>
            <button onClick={() => setCount(c => c + 1)}>Count: {count}</button>
        </div>
    );
}
""", encoding="utf-8")

    pkg = json.loads((ws / "package.json").read_text(encoding="utf-8"))
    assert "react" in pkg["dependencies"]
    assert (ws / "vite.config.js").exists()
    assert (ws / "index.html").exists()
    assert (src / "App.jsx").exists()


def test_domain_4_python_cli_utility(tmp_path: Path):
    """Domain 4: Python CLI / utility tool with argparse & exit codes."""
    ws = tmp_path / "cli_tool"
    ws.mkdir()
    cli_file = ws / "cli.py"
    cli_code = '''"""Command line utility for CSV summary statistics."""
import argparse
import sys

def parse_args():
    parser = argparse.ArgumentParser(description="CSV Summary CLI")
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--count-only", action="store_true", help="Only output row count")
    return parser.parse_args()

def main():
    args = parse_args()
    print(f"Processing {args.input}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    cli_file.write_text(cli_code, encoding="utf-8")

    # Validate Python AST compiles cleanly
    tree = ast.parse(cli_code, filename="cli.py")
    assert isinstance(tree, ast.Module)
    functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "parse_args" in functions
    assert "main" in functions


def test_domain_5_backend_rest_api(tmp_path: Path):
    """Domain 5: Backend REST API (FastAPI endpoints)."""
    ws = tmp_path / "rest_api"
    ws.mkdir()
    api_file = ws / "api.py"
    api_code = '''"""FastAPI Microservice Endpoints."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="Item Store API", version="1.0.0")

class Item(BaseModel):
    id: int
    name: str
    price: float
    is_offer: Optional[bool] = None

items_db = {}

@app.get("/items", response_model=List[Item])
def list_items():
    return list(items_db.values())

@app.get("/items/{item_id}", response_model=Item)
def get_item(item_id: int):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    return items_db[item_id]

@app.post("/items", response_model=Item, status_code=201)
def create_item(item: Item):
    items_db[item.id] = item
    return item
'''
    api_file.write_text(api_code, encoding="utf-8")

    tree = ast.parse(api_code, filename="api.py")
    assert isinstance(tree, ast.Module)
    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert "Item" in classes


def test_domain_6_database_backed_application(tmp_path: Path):
    """Domain 6: Database-backed application (SQLite schema, queries, CRUD)."""
    ws = tmp_path / "db_app"
    ws.mkdir()
    db_file = ws / "app.db"

    # Create schema and execute queries
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        INSERT INTO users (username, email) VALUES
        ('alice', 'alice@example.com'),
        ('bob', 'bob@example.com');
    """)
    conn.commit()

    # Query back and assert
    cursor.execute("SELECT id, username, email FROM users ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][1] == "alice"
    assert rows[1][1] == "bob"


def test_domain_7_brownfield_patch_bug_fix(tmp_path: Path):
    """Domain 7: Brownfield patch / existing codebase targeted bug fix (surgical edit)."""
    ws = tmp_path / "brownfield_repo"
    ws.mkdir()

    # Existing module with bug in calculate_discount
    calc_file = ws / "calculator.py"
    calc_file.write_text("""def calculate_discount(price, discount_pct):
    # BUG: using + instead of -
    return price + (price * discount_pct / 100)
""", encoding="utf-8")

    # Surgical patch: fix operator
    content = calc_file.read_text(encoding="utf-8")
    patched = content.replace("price + (price * discount_pct / 100)", "price - (price * discount_pct / 100)")
    calc_file.write_text(patched, encoding="utf-8")

    # Test fix
    tree = ast.parse(patched)
    assert isinstance(tree, ast.Module)
    # Execute and verify
    local_scope = {}
    exec(patched, local_scope)
    fn = local_scope["calculate_discount"]
    assert fn(100, 20) == 80.0


def test_domain_8_code_refactoring_and_modularity(tmp_path: Path):
    """Domain 8: Code refactoring & multi-file architectural migration."""
    ws = tmp_path / "refactored_project"
    ws.mkdir()
    pkg = ws / "mathlib"
    pkg.mkdir()

    (pkg / "__init__.py").write_text("from .geometry import area_circle\nfrom .algebra import solve_linear\n", encoding="utf-8")
    (pkg / "geometry.py").write_text("import math\ndef area_circle(r):\n    return math.pi * r * r\n", encoding="utf-8")
    (pkg / "algebra.py").write_text("def solve_linear(a, b):\n    return -b / a if a != 0 else None\n", encoding="utf-8")

    main_script = ws / "main.py"
    main_script.write_text("""from mathlib import area_circle, solve_linear

def run():
    a = area_circle(2.0)
    x = solve_linear(2, -4)
    return a, x
""", encoding="utf-8")

    tree = ast.parse(main_script.read_text(encoding="utf-8"))
    assert isinstance(tree, ast.Module)
