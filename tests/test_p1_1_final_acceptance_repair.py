# tests/test_p1_1_final_acceptance_repair.py
"""
Regression test suite for HERMES 2.x P1.1 and P1.2 UI Integrity & Demonstration-State.
Verifies all focused acceptance criteria without live provider calls:
1. Physical existence and decodability of all 12 dish images.
2. Complete dish-to-image mapping without nonexistent Mediterranean references.
3. Dish-specific modal content across multiple distinct dishes.
4. #modal-ingredients and #modal-pairing semantic DOM hooks.
5. Global Escape-key modal dismissal integration.
6. Interactive gallery lightbox structure and lifecycle.
7. Gallery previous/next navigation and arrow key handlers.
8. Dedicated contact form and demonstration validation feedback.
9. Demonstration-state reservation notice and notification lifecycle.
10. Preservation of Gate 16 and workspace security protections.
11. Clean illustrative testimonials without fabricated customer claims.
"""
from pathlib import Path
import json
import pytest
from PIL import Image

WORKSPACE_ROOT = Path(r"C:\Users\SUBBU\Downloads\saffron_stone_test_2")

@pytest.fixture
def workspace_files():
    if not WORKSPACE_ROOT.exists():
        pytest.skip(f"Workspace {WORKSPACE_ROOT} does not exist!")
    return {
        "html": (WORKSPACE_ROOT / "index.html").read_text(encoding="utf-8"),
        "js": (WORKSPACE_ROOT / "app.js").read_text(encoding="utf-8"),
        "css": (WORKSPACE_ROOT / "style.css").read_text(encoding="utf-8"),
        "manifest": json.loads((WORKSPACE_ROOT / ".hermes" / "generated_manifest.json").read_text(encoding="utf-8")),
        "asset_manifest": json.loads((WORKSPACE_ROOT / ".hermes" / "asset_manifest.json").read_text(encoding="utf-8")),
    }


def test_all_12_dish_images_physically_exist_and_decode(workspace_files):
    """Verify every dish image physically exists, decodes with PIL, and has positive dimensions."""
    menu_dir = WORKSPACE_ROOT / "assets" / "images" / "menu"
    assert menu_dir.exists(), "assets/images/menu directory missing!"

    expected_menu_files = [
        "paneer-tikka.jpg",
        "dahi-puri.jpg",
        "tandoori-salmon.jpg",
        "tandoori-chops.jpg",
        "lamb-dum-biryani.jpg",
        "butter-chicken.jpg",
        "dal-makhani.jpg",
        "morel-pulao.jpg",
        "truffle-kulcha.jpg",
        "garlic-naan.jpg",
        "kesar-kulfi.jpg",
        "gulab-jamun.jpg",
    ]
    for fname in expected_menu_files:
        fpath = menu_dir / fname
        assert fpath.exists(), f"Missing menu image file: {fname}"
        assert fpath.stat().st_size > 5000, f"File {fname} too small: {fpath.stat().st_size} bytes"
        with Image.open(fpath) as im:
            assert im.format == "JPEG", f"File {fname} is not JPEG: {im.format}"
            assert im.size[0] >= 600, f"Width {im.size[0]} < 600 for {fname}"
            assert im.size[1] >= 400, f"Height {im.size[1]} < 400 for {fname}"


def test_dish_to_image_mapping_in_app_js(workspace_files):
    """Verify app.js DISHES array maps only to existing Indian food images and zero nonexistent Mediterranean paths."""
    js = workspace_files["js"]
    
    # Zero nonexistent Mediterranean paths
    forbidden = [
        "saffron-lamb-tagine.jpg",
        "mezze-platter.jpg",
        "wild-sea-bass.jpg",
        "prime-ribeye.jpg",
        "pistachio-baklava.jpg",
    ]
    for bad in forbidden:
        assert bad not in js, f"Stale Mediterranean file '{bad}' found in app.js!"

    # Verify each dish references an existing local file
    import re
    images = re.findall(r'image:\s*"([^"]+)"', js)
    assert len(images) == 12, f"Expected 12 dish image references in app.js, found {len(images)}"
    for rel_path in images:
        full_path = WORKSPACE_ROOT / rel_path
        assert full_path.exists(), f"Image path '{rel_path}' referenced in app.js does not exist on disk!"


def test_dish_modal_semantic_dom_hooks(workspace_files):
    """Verify semantic DOM hooks #modal-ingredients and #modal-pairing are constructed in openDishDetail."""
    js = workspace_files["js"]
    assert 'id="modal-ingredients"' in js, "Semantic hook #modal-ingredients missing from modal markup!"
    assert 'id="modal-pairing"' in js, "Semantic hook #modal-pairing missing from modal markup!"
    assert 'id="modal-prep"' in js, "Semantic hook #modal-prep missing from modal markup!"


def test_dish_specific_modal_content_distinctness(workspace_files):
    """Verify DISHES array provides distinct, dish-specific ingredients, preparations, and pairings."""
    js = workspace_files["js"]
    
    # Check that Paneer Tikka, Biryani, and Kulfi have distinct data
    assert "Charred Saffron Paneer Tikka" in js
    assert "Gewürztraminer" in js
    assert "Awadhi Lamb Dum Biryani" in js
    assert "Rioja" in js
    assert "Kashmiri Saffron & Pistachio Kulfi" in js
    assert "Sauternes" in js


def test_global_escape_key_modal_dismissal(workspace_files):
    """Verify global Escape key handler closes all modals and cleans up scroll locking."""
    js = workspace_files["js"]
    assert 'e.key === "Escape"' in js or "e.key === 'Escape'" in js, "Escape key handler missing from app.js!"
    assert "closeAllModals" in js or "closeLightbox" in js, "Modal close logic missing!"
    assert 'document.body.style.overflow = ""' in js, "Body overflow restoration missing from modal dismissal!"


def test_gallery_lightbox_markup_and_lifecycle(workspace_files):
    """Verify lightbox modal container exists in index.html and app.js initializes lightbox."""
    html = workspace_files["html"]
    js = workspace_files["js"]

    assert 'id="lightbox-modal"' in html, "Lightbox modal container #lightbox-modal missing from index.html!"
    assert 'id="lightbox-img"' in html, "Lightbox image element #lightbox-img missing!"
    assert 'id="lightbox-close-btn"' in html, "Lightbox close button #lightbox-close-btn missing!"
    assert 'id="lightbox-prev-btn"' in html, "Lightbox prev button #lightbox-prev-btn missing!"
    assert 'id="lightbox-next-btn"' in html, "Lightbox next button #lightbox-next-btn missing!"

    assert "initGalleryLightbox" in js, "initGalleryLightbox function missing from app.js!"


def test_gallery_lightbox_prev_next_and_keyboard_nav(workspace_files):
    """Verify previous/next and arrow key navigation logic is implemented for gallery lightbox."""
    js = workspace_files["js"]
    assert "ArrowLeft" in js, "ArrowLeft keyboard navigation missing from gallery lightbox!"
    assert "ArrowRight" in js, "ArrowRight keyboard navigation missing from gallery lightbox!"
    assert "showImage" in js, "showImage navigation helper missing from app.js!"


def test_dedicated_contact_form(workspace_files):
    """Verify dedicated standalone contact form is present in index.html with required fields and demo feedback."""
    html = workspace_files["html"]
    js = workspace_files["js"]

    assert 'id="contact"' in html, "Dedicated contact section #contact missing from index.html!"
    assert 'id="contact-form"' in html, "Dedicated contact form #contact-form missing from index.html!"
    assert 'id="contact-name"' in html, "Contact name field missing!"
    assert 'id="contact-email"' in html, "Contact email field missing!"
    assert 'id="contact-phone"' in html, "Contact phone field missing!"
    assert 'id="contact-subject"' in html, "Contact subject field missing!"
    assert 'id="contact-message"' in html, "Contact message field missing!"
    assert 'id="contact-feedback"' in html, "Contact feedback element missing!"

    assert "initContactForm" in js, "initContactForm function missing from app.js!"
    assert "demonstration mode" in js.lower(), "demonstration mode notice missing from contact feedback!"
    assert "No message has been transmitted to a restaurant" in js, "Accurate demo notice text missing!"


def test_existing_reservation_functionality_preserved_with_demo_notice(workspace_files):
    """Verify reservation modal, required fields, and booking confirmation remain intact with demonstration notice."""
    html = workspace_files["html"]
    js = workspace_files["js"]

    assert 'id="reservation-modal"' in html, "Reservation modal #reservation-modal missing!"
    assert 'id="reservation-form"' in html, "Reservation form #reservation-form missing!"
    assert 'id="res-name"' in html, "Reservation name field missing!"
    assert 'id="res-email"' in html, "Reservation email field missing!"
    assert 'id="res-date"' in html, "Reservation date field missing!"
    assert 'id="res-time"' in html, "Reservation time field missing!"
    assert 'id="res-guests"' in html, "Reservation guests field missing!"

    assert "initReservationForm" in js, "initReservationForm missing from app.js!"
    assert "No actual reservation has been created" in js, "Demonstration reservation notice missing!"
    assert "Reservation confirmed" not in js, "Misleading confirmed reservation string present!"


def test_clean_illustrative_testimonials(workspace_files):
    """Verify testimonials do not contain fabricated awards or verified claims."""
    html = workspace_files["html"].lower()
    assert "verified dining guests" not in html
    assert "critical acclaim" not in html
    assert "food & hospitality columnist" not in html
    assert "demonstration impressions" in html
    assert "illustrative patron review" in html


def test_workspace_security_manifest_and_safe_rmtree_preservation():
    """Verify Gate 16 protections and generated manifest integrity."""
    from tools.security import safe_rmtree
    if not WORKSPACE_ROOT.exists():
        pytest.skip(f"Workspace {WORKSPACE_ROOT} does not exist!")

    # Verify root deletion is blocked and returns False
    blocked_root = safe_rmtree(WORKSPACE_ROOT, WORKSPACE_ROOT)
    assert blocked_root is False, "safe_rmtree should block deletion of workspace root!"

    # Verify assets deletion is blocked and returns False
    blocked_assets = safe_rmtree(WORKSPACE_ROOT / "assets", WORKSPACE_ROOT)
    assert blocked_assets is False, "safe_rmtree should block deletion of protected assets directory!"

    # Verify generated_manifest.json contains all deliverables
    manifest_path = WORKSPACE_ROOT / ".hermes" / "generated_manifest.json"
    assert manifest_path.exists()
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = m.get("generated_files", {})
    assert "index.html" in files
    assert "style.css" in files
    assert "app.js" in files
    assert "package.json" in files
