import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import os

with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    # Test layout detection
    # Case 1: static layout
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("<!DOCTYPE html><html><head><script src='app.js'></script></head><body><div id='app'></div></body></html>", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (ws / "static" / "app.js").write_text("console.log('hi');", encoding="utf-8")
    (ws / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    
    print("Static test files created in:", ws)
