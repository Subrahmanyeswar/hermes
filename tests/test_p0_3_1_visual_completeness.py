import pytest
from pathlib import Path
from core.foundation_scaffolder import seed_initial_foundation_files
from core.frontend_contract import build_initial_contract
from tools.security import WorkspaceOwnershipManifest

def test_p0_3_1_scaffolder_includes_all_nine_sections(tmp_path: Path):
    ws = tmp_path / "test_nova_ws"
    ws.mkdir()
    
    prompt = "Create a premium consumer electronics e-commerce store called NOVA"
    contract = build_initial_contract(prompt)
    
    ok = seed_initial_foundation_files(workspace_root=ws, prompt=prompt, contract=contract)
    assert ok is True
    
    index_html = (ws / "index.html").read_text(encoding="utf-8")
    style_css = (ws / "style.css").read_text(encoding="utf-8")
    
    # 1. Verify all 9 section IDs are seeded in HTML
    expected_ids = [
        'id="navbar"', 'id="hero"', 'id="categories"', 'id="products"',
        'id="features"', 'id="about"', 'id="testimonials"', 'id="contact"', 'id="footer"'
    ]
    for sec_id in expected_ids:
        assert sec_id in index_html, f"Expected section {sec_id} missing in seeded HTML"
        
    # 2. Verify reviews link in navigation
    assert 'href="#testimonials"' in index_html
    
    # 3. Verify illustrative disclosure
    assert "Illustrative" in index_html
    
    # 4. Verify favicon tag is present
    assert 'rel="icon"' in index_html
    
    # 5. Verify mobile responsive rules in style.css
    assert ".about-stats { grid-template-columns: 1fr; gap: 1rem; }" in style_css
    assert ".testimonials-grid { grid-template-columns: 1fr; }" in style_css
    
    # 6. Verify Gate 16 ownership registration
    assert WorkspaceOwnershipManifest.is_generated_file(ws / "index.html", ws)
    assert WorkspaceOwnershipManifest.is_generated_file(ws / "style.css", ws)
    assert WorkspaceOwnershipManifest.is_generated_file(ws / "package.json", ws)
    assert WorkspaceOwnershipManifest.is_generated_file(ws / "app.js", ws)
