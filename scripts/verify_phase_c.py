import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import sqlite3
from core.cross_file_contract import CrossFileContractValidator, SEV_PASS, SEV_FAIL, SEV_WARNING
from core.project_contract import ProjectContract

with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    
    # 1. Clean setup with fallback CSS vars
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'><script src='app.js'></script></head><body><div id='app'></div></body></html>", encoding="utf-8")
    (ws / "static" / "style.css").write_text(":root { --defined: #fff; }\nbody { color: var(--defined); background: var(--undefined-but-has-fallback, #000); }", encoding="utf-8")
    (ws / "static" / "app.js").write_text("document.getElementById('app').innerText = 'ready';", encoding="utf-8")
    (ws / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n@app.get('/api/health')\ndef health():\n    return {'status': 'ok'}\n", encoding="utf-8")
    
    # SQLite DB
    conn = sqlite3.connect(str(ws / "app.db"))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL);")
    conn.close()
    
    contract = ProjectContract.create_or_load(ws, mission_id="m_test")
    contract.database_tables = {"users": ["id", "username"]}
    contract.save_to_workspace(ws)
    
    rep = CrossFileContractValidator.validate_workspace(ws)
    assert rep.valid, f"Expected valid, got issues: {rep}"
    assert rep.severity == SEV_PASS, f"Expected PASS, got: {rep.severity}"
    assert len(rep.css_mismatches) == 0
    assert len(rep.dom_id_mismatches) == 0
    print("Test 1 (Clean setup + CSS fallback awareness): PASSED")
    
    # 2. Plant DOM ID mismatch
    (ws / "static" / "app.js").write_text("document.getElementById('missing_element').click();", encoding="utf-8")
    rep2 = CrossFileContractValidator.validate_workspace(ws)
    assert not rep2.valid
    assert rep2.severity == SEV_FAIL
    assert any("missing_element" in m for m in rep2.dom_id_mismatches)
    print("Test 2 (Planted DOM ID mismatch detected): PASSED")
    
    # 3. Plant SQLite column mismatch
    contract.database_tables = {"users": ["id", "username", "missing_column"]}
    contract.save_to_workspace(ws)
    (ws / "static" / "app.js").write_text("document.getElementById('app').innerText = 'ready';", encoding="utf-8")
    rep3 = CrossFileContractValidator.validate_workspace(ws)
    assert not rep3.valid
    assert any("missing_column" in m for m in rep3.database_mismatches)
    print("Test 3 (Planted DB column mismatch detected): PASSED")

print("ALL PHASE C PRELIMINARY CHECKS PASSED!")
