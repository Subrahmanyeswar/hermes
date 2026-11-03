import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
from core.project_contract import ProjectContract, CanonicalPathResolver

with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    
    # 1. Path resolver tests
    # Safe relative path
    safe = CanonicalPathResolver.resolve_workspace_path(ws, "static/index.html")
    assert safe == (ws / "static" / "index.html").resolve()
    
    # Traversal rejection
    try:
        CanonicalPathResolver.resolve_workspace_path(ws, "../outside.txt")
        assert False, "Should have rejected traversal"
    except ValueError as e:
        assert "traversal" in str(e).lower() or "outside" in str(e).lower()
        print("Test 1 (Traversal rejection): PASSED")
        
    # Absolute escape rejection
    outside = Path(tempfile.gettempdir()) / "outside_file.txt"
    try:
        CanonicalPathResolver.resolve_workspace_path(ws, outside)
        assert False, "Should have rejected external absolute path"
    except ValueError as e:
        assert "outside" in str(e).lower()
        print("Test 2 (Outside escape rejection): PASSED")
        
    # 2. Layout detection: static vs root
    # Create static files
    (ws / "static").mkdir()
    (ws / "static" / "index.html").write_text("<!DOCTYPE html><html><body><div id='root'></div></body></html>", encoding="utf-8")
    (ws / "static" / "style.css").write_text("body {}", encoding="utf-8")
    (ws / "static" / "app.js").write_text("console.log(1);", encoding="utf-8")
    (ws / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    
    layout, paths = ProjectContract.detect_project_layout(ws)
    assert layout == "static"
    assert paths["canonical_html"] == "static/index.html"
    assert paths["canonical_js"] == "static/app.js"
    print("Test 3 (Static layout detection): PASSED")
    
    # 3. Create contract
    contract = ProjectContract.create_or_load(ws, mission_id="m_first", prompt="Build TaskForge")
    assert contract.canonical_html == "static/index.html"
    assert contract.mission_id == "m_first"
    print("Test 4 (Contract creation): PASSED")
    
    # 4. Canonical alias resolution
    aliased_html = CanonicalPathResolver.resolve_canonical_alias(ws, "index.html", contract)
    assert aliased_html == "static/index.html"
    # Nested file should NOT be aliased
    nested_admin = CanonicalPathResolver.resolve_canonical_alias(ws, "admin/index.html", contract)
    assert nested_admin == "admin/index.html"
    print("Test 5 (Canonical alias resolution): PASSED")
    
    # 5. Stale contract reconciliation across missions
    # Simulate a new mission starting in same workspace
    new_contract = ProjectContract.create_or_load(ws, mission_id="m_second", prompt="Continue TaskForge")
    assert new_contract.mission_id == "m_second"
    # Ensure previous contract was archived
    archive_dir = ws / ".hermes" / "contracts"
    assert archive_dir.exists()
    archived_files = list(archive_dir.glob("archive_m_first_*.json"))
    assert len(archived_files) >= 1
    print("Test 6 (Stale contract archiving and reconciliation): PASSED")

print("ALL PHASE B PRELIMINARY CHECKS PASSED!")
