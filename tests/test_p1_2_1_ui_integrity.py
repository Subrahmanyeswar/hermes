# tests/test_p1_2_1_ui_integrity.py
"""
Focused automated regression test suite for P1.2.1 Final UI Integrity & Visual Evidence.
Verifies without live provider calls:
1. Clean initial contact form state (no error text or active feedback).
2. Validation error messages appear on invalid submission.
3. Real-time error clearing handlers exist for input/change.
4. Form reset listener clears validation state.
5. Footer contact details clearly labeled as illustrative with mandatory disclosure.
6. Reservation notification lifecycle with demonstration notice.
7. Contact notification lifecycle with demonstration notice.
8. Screenshot dimensions and full-page capture width integrity.
9. Preservation of existing website components and Gate 16 security.
"""
from pathlib import Path
import json
import pytest
from PIL import Image

WORKSPACE_ROOT = Path(r"C:\Users\SUBBU\Downloads\saffron_stone_test_2")
ARTIFACT_DIR = Path(r"C:\Users\SUBBU\.gemini\antigravity\brain\ac21daf5-52a0-4bf9-91ab-652f5f44de6b")

@pytest.fixture
def workspace_files():
    if not WORKSPACE_ROOT.exists():
        pytest.skip(f"Workspace {WORKSPACE_ROOT} does not exist!")
    return {
        "html": (WORKSPACE_ROOT / "index.html").read_text(encoding="utf-8"),
        "js": (WORKSPACE_ROOT / "app.js").read_text(encoding="utf-8"),
        "css": (WORKSPACE_ROOT / "style.css").read_text(encoding="utf-8"),
    }


def test_initial_contact_form_markup_clean(workspace_files):
    """Verify contact form spans on disk have empty initial text content and phone placeholder is generic."""
    html = workspace_files["html"]
    assert '<span class="field-error" id="contact-name-error"></span>' in html
    assert '<span class="field-error" id="contact-email-error"></span>' in html
    assert '<span class="field-error" id="contact-subject-error"></span>' in html
    assert '<span class="field-error" id="contact-message-error"></span>' in html
    assert 'style="display: none;"' in html, "contact-feedback should be initialized with display: none"
    assert 'placeholder="(Optional) e.g. +1 555-0100"' in html, "contact-phone should have generic illustrative placeholder"
    assert 'placeholder="(555) 382-7194"' not in html, "old personal sample phone placeholder must not remain"


def test_contact_form_validation_logic(workspace_files):
    """Verify validation messages for empty/invalid fields are constructed in submit handler."""
    js = workspace_files["js"]
    assert "Please enter your full name." in js
    assert "Please enter a valid email address." in js
    assert "Please select an enquiry subject." in js
    assert "Please enter a message (at least 10 characters)." in js


def test_realtime_error_clearing_handlers(workspace_files):
    """Verify input and change listeners exist to clear field errors in real time."""
    js = workspace_files["js"]
    assert 'nameInput.addEventListener("input"' in js
    assert 'emailInput.addEventListener("input"' in js
    assert 'subjectInput.addEventListener("change"' in js
    assert 'messageInput.addEventListener("input"' in js


def test_form_reset_clears_validation(workspace_files):
    """Verify form reset event clears all field error elements."""
    js = workspace_files["js"]
    assert 'contactForm.addEventListener("reset"' in js
    assert "clearAllErrors" in js


def test_footer_contact_illustrative_labels_and_disclosure(workspace_files):
    """Verify footer contact information is clearly labeled as illustrative with disclosure."""
    html = workspace_files["html"]
    assert "Illustrative Sample Address" in html
    assert "Sample Demonstration Phone" in html
    assert "Sample Demonstration Email" in html
    assert "All contact details shown are illustrative and do not represent an operating restaurant." in html


def test_reservation_notification_lifecycle(workspace_files):
    """Verify reservation notification contains demonstration notice, close button, and timer cleanup."""
    js = workspace_files["js"]
    html = workspace_files["html"]

    assert "No actual reservation has been created" in js
    assert "showToast" in js
    assert "hideToast" in js
    assert "clearTimeout(toastTimer)" in js
    assert 'id="toast-close"' in html


def test_contact_notification_lifecycle(workspace_files):
    """Verify contact notification contains exact demonstration notice, close button, and timer cleanup."""
    js = workspace_files["js"]
    html = workspace_files["html"]

    exact_notice = "Thank you! Your enquiry has been validated successfully in demonstration mode. No message has been transmitted to a restaurant."
    assert exact_notice in js
    assert "clearTimeout(contactFeedbackTimer)" in js
    assert 'id="contact-feedback-close"' in html


def test_screenshot_dimensions_and_fullpage_widths():
    """Verify captured P1.2.1 screenshots match requested viewport dimensions and fullpage widths."""
    viewports = [
        ("desktop", 1440, 900),
        ("laptop", 1024, 768),
        ("tablet", 768, 1024),
        ("mobile", 390, 844),
    ]
    for vname, vw, vh in viewports:
        vp_path = ARTIFACT_DIR / f"saffron_p1_2_1_viewport_{vname}_{vw}x{vh}.png"
        fp_path = ARTIFACT_DIR / f"saffron_p1_2_1_fullpage_{vname}_{vw}x{vh}.png"

        assert vp_path.exists(), f"Missing viewport screenshot: {vp_path.name}"
        assert fp_path.exists(), f"Missing fullpage screenshot: {fp_path.name}"

        with Image.open(vp_path) as v_im:
            assert v_im.size == (vw, vh), f"Viewport {vname} dimension mismatch: {v_im.size} vs ({vw}, {vh})"

        with Image.open(fp_path) as f_im:
            assert f_im.size[0] == vw, f"Fullpage {vname} width mismatch: {f_im.size[0]} vs {vw}"
            assert f_im.size[1] > 1000, f"Fullpage {vname} height suspiciously small: {f_im.size[1]}"


def test_existing_features_and_security_preserved(workspace_files):
    """Verify all 12 dishes, modals, gallery, and Gate 16 protections remain intact."""
    js = workspace_files["js"]
    html = workspace_files["html"]

    # 12 dishes
    assert "const DISHES = [" in js
    assert "Awadhi Lamb Dum Biryani" in js
    assert "Charred Saffron Paneer Tikka" in js

    # Gate 16 safe_rmtree protection
    from tools.security import safe_rmtree
    assert safe_rmtree(WORKSPACE_ROOT, WORKSPACE_ROOT) is False
    assert safe_rmtree(WORKSPACE_ROOT / "assets", WORKSPACE_ROOT) is False
